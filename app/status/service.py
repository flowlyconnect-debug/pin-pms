from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app

from app.backups.models import Backup, BackupStatus
from app.extensions import db
from app.status.models import StatusCheck, StatusComponent

_MAILGUN_CACHE_TTL_SECONDS = 60
_mailgun_cache: dict[str, object] = {"checked_at": 0.0, "ok": False, "detail": "uninitialized"}


DEFAULT_COMPONENTS = [
    ("api", "API"),
    ("web", "Web"),
    ("email", "Email (Mailgun)"),
    ("backups", "Backups"),
    ("channel_manager", "Channel manager"),
    ("booking_com", "Booking.com"),
    ("airbnb", "Airbnb"),
    ("pindora", "Pindora"),
]


def ensure_default_components() -> None:
    changed = False
    for key, name in DEFAULT_COMPONENTS:
        row = StatusComponent.query.filter_by(key=key).first()
        if row is None:
            db.session.add(StatusComponent(key=key, name=name, current_state="operational"))
            changed = True
    if changed:
        db.session.commit()


def _record(
    component_key: str, ok: bool, latency_ms: int | None = None, error_message: str | None = None
) -> None:
    db.session.add(
        StatusCheck(
            component_key=component_key,
            ok=bool(ok),
            latency_ms=latency_ms,
            error_message=(error_message or "")[:1000] or None,
        )
    )


def run_synthetic_checks() -> None:
    ensure_default_components()
    _check_api()
    _check_web()
    _check_email()
    _check_backups()
    _check_simple("channel_manager")
    _check_simple("booking_com")
    _check_simple("airbnb")
    _check_simple("pindora")
    db.session.commit()


def _check_api() -> None:
    base_url = (current_app.config.get("APP_BASE_URL") or "http://127.0.0.1:5000").rstrip("/")
    url = f"{base_url}/api/v1/health"
    started = time.perf_counter()
    try:
        response = requests.get(url, timeout=5)
        latency_ms = int((time.perf_counter() - started) * 1000)
        _record(
            "api", response.ok, latency_ms, None if response.ok else f"HTTP {response.status_code}"
        )
    except Exception as exc:  # noqa: BLE001
        _record("api", False, None, str(exc))


def _check_web() -> None:
    base_url = (current_app.config.get("APP_BASE_URL") or "http://127.0.0.1:5000").rstrip("/")
    started = time.perf_counter()
    try:
        response = requests.get(f"{base_url}/health", timeout=5)
        latency_ms = int((time.perf_counter() - started) * 1000)
        _record(
            "web", response.ok, latency_ms, None if response.ok else f"HTTP {response.status_code}"
        )
    except Exception as exc:  # noqa: BLE001
        _record("web", False, None, str(exc))


def _check_email() -> None:
    has_mailgun = bool(current_app.config.get("MAILGUN_API_KEY")) and bool(
        current_app.config.get("MAILGUN_DOMAIN")
    )
    _record("email", has_mailgun, 0, None if has_mailgun else "Mailgun not configured")


def _check_backups() -> None:
    latest_success = (
        Backup.query.filter_by(status=BackupStatus.SUCCESS)
        .order_by(Backup.created_at.desc())
        .first()
    )
    if latest_success is None:
        _record("backups", False, None, "No successful backup found")
        return
    age = datetime.now(timezone.utc) - latest_success.created_at
    _record(
        "backups",
        age < timedelta(hours=36),
        0,
        None if age < timedelta(hours=36) else "Last backup too old",
    )


def _check_simple(component_key: str) -> None:
    _record(component_key, True, 0, None)


def readiness_status(app) -> dict[str, object]:
    checks = {
        "db": _check_db_ready(),
        "mailgun": _check_mailgun_ready(app),
        "backups": _check_backup_recency(),
        "scheduler": _check_scheduler_running(app),
    }
    ok = all(bool(item["ok"]) for item in checks.values())
    return {"ok": ok, "checks": checks}


def _check_db_ready() -> dict[str, object]:
    try:
        db.session.execute(db.text("SELECT 1"))
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}


def _check_mailgun_ready(app) -> dict[str, object]:
    now = time.monotonic()
    checked_at = float(_mailgun_cache.get("checked_at", 0.0) or 0.0)
    if now - checked_at < _MAILGUN_CACHE_TTL_SECONDS:
        return {
            "ok": bool(_mailgun_cache["ok"]),
            "detail": _mailgun_cache.get("detail"),
            "cached": True,
        }

    api_key = (app.config.get("MAILGUN_API_KEY") or "").strip()
    domain = (app.config.get("MAILGUN_DOMAIN") or "").strip()
    if not api_key or not domain:
        result = {"ok": False, "detail": "MAILGUN_API_KEY or MAILGUN_DOMAIN missing"}
    else:
        try:
            base_url = (app.config.get("MAILGUN_BASE_URL") or "https://api.mailgun.net/v3").rstrip(
                "/"
            )
            resp = requests.get(
                f"{base_url}/domains/{domain}",
                auth=("api", api_key),
                timeout=5,
            )
            result = {"ok": resp.status_code < 300, "detail": f"HTTP {resp.status_code}"}
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "detail": f"{type(exc).__name__}: {exc}"}

    _mailgun_cache.update({"checked_at": now, "ok": result["ok"], "detail": result.get("detail")})
    result["cached"] = False
    return result


def _check_backup_recency() -> dict[str, object]:
    latest_success = (
        Backup.query.filter_by(status=BackupStatus.SUCCESS)
        .order_by(Backup.created_at.desc())
        .first()
    )
    if latest_success is None:
        return {"ok": False, "detail": "No successful backup found"}
    age = datetime.now(timezone.utc) - latest_success.created_at
    return {"ok": age < timedelta(hours=36), "age_hours": round(age.total_seconds() / 3600, 2)}


def _check_scheduler_running(app) -> dict[str, object]:
    registry = app.extensions.get("apscheduler_instances", {}) if hasattr(app, "extensions") else {}
    running = []
    for name, scheduler in registry.items():
        if scheduler is not None and getattr(scheduler, "running", False):
            running.append(name)
    if not running:
        return {"ok": False, "detail": "No running APScheduler instance detected"}
    return {"ok": True, "running": running}
