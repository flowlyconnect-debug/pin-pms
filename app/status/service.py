from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import requests
from flask import current_app
from sqlalchemy import text

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.backups.models import Backup, BackupStatus
from app.email.models import EmailQueueItem, OutgoingEmailStatus
from app.extensions import db
from app.status.models import StatusCheck, StatusComponent

_MAILGUN_CACHE_TTL_SECONDS = 30
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


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


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
    age = datetime.now(timezone.utc) - _as_utc(latest_success.created_at)
    _record(
        "backups",
        age < timedelta(hours=36),
        0,
        None if age < timedelta(hours=36) else "Last backup too old",
    )


def _check_simple(component_key: str) -> None:
    _record(component_key, True, 0, None)


def readiness_status(app) -> dict[str, object]:
    db_check = _check_db_ready()
    mailgun_check = _check_mailgun_ready(app)
    scheduler_check = _check_scheduler_running(app)
    backup_check = _check_backup_recency()
    email_queue_check = _check_email_queue_ready()
    checks = [db_check, mailgun_check, scheduler_check, backup_check, email_queue_check]
    ok = bool(db_check.get("ok")) and bool(scheduler_check.get("ok")) and bool(email_queue_check.get("ok"))
    if not ok:
        audit_record(
            "monitoring.health_check_failed",
            status=AuditStatus.FAILURE,
            target_type="monitoring",
            target_id=None,
            metadata={"checks": _safe_checks_for_audit(checks)},
        )
    return {"ok": ok, "checks": checks}


def _check_email_queue_ready() -> dict[str, object]:
    now = datetime.now(timezone.utc)
    pending = EmailQueueItem.query.filter(EmailQueueItem.status == OutgoingEmailStatus.PENDING).count()
    failed = EmailQueueItem.query.filter(EmailQueueItem.status == OutgoingEmailStatus.FAILED).count()
    oldest_pending = (
        EmailQueueItem.query.filter(EmailQueueItem.status == OutgoingEmailStatus.PENDING)
        .order_by(EmailQueueItem.created_at.asc())
        .first()
    )
    oldest_pending_age_minutes = 0
    if oldest_pending is not None and oldest_pending.created_at is not None:
        created_at = _as_utc(oldest_pending.created_at)
        oldest_pending_age_minutes = max(
            0,
            int((now - created_at).total_seconds() // 60),
        )
    check: dict[str, object] = {
        "name": "email_queue",
        "ok": True,
        "pending": pending,
        "failed": failed,
        "oldest_pending_age_minutes": oldest_pending_age_minutes,
    }
    if oldest_pending_age_minutes > 30:
        check["warning"] = "Oldest pending email is older than 30 minutes"
    if failed > 10:
        check["ok"] = False
        check["warning"] = "Too many failed emails in queue"
    return check


def _check_db_ready() -> dict[str, object]:
    started = time.perf_counter()
    try:
        db.session.execute(text("SELECT 1"))
        latency_ms = int((time.perf_counter() - started) * 1000)
        if latency_ms > 500:
            return {"name": "db", "ok": False, "latency_ms": latency_ms, "error": "DB latency too high"}
        return {"name": "db", "ok": True, "latency_ms": latency_ms}
    except Exception as exc:  # noqa: BLE001
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {"name": "db", "ok": False, "latency_ms": latency_ms, "error": _truncate_error(exc)}


def _check_mailgun_ready(app) -> dict[str, object]:
    now = time.monotonic()
    checked_at = float(_mailgun_cache.get("checked_at", 0.0) or 0.0)
    if now - checked_at < _MAILGUN_CACHE_TTL_SECONDS:
        check = {"name": "mailgun", "ok": bool(_mailgun_cache["ok"]), "cached": True}
        detail = _mailgun_cache.get("detail")
        if detail:
            check["error"] = detail
        return check

    api_key = (app.config.get("MAILGUN_API_KEY") or "").strip()
    domain = (app.config.get("MAILGUN_DOMAIN") or "").strip()
    if not api_key or not domain:
        return {"name": "mailgun", "ok": True, "disabled": True}
    else:
        try:
            base_url = (app.config.get("MAILGUN_BASE_URL") or "https://api.mailgun.net/v3").rstrip(
                "/"
            )
            resp = requests.get(
                f"{base_url}/{domain}/log",
                auth=("api", api_key),
                params={"limit": 1},
                timeout=2,
            )
            if resp.status_code == 200:
                result = {"ok": True}
            else:
                result = {"ok": False, "detail": f"HTTP {resp.status_code}"}
        except Exception as exc:  # noqa: BLE001
            result = {"ok": False, "detail": _truncate_error(exc)}

    _mailgun_cache.update({"checked_at": now, "ok": result["ok"], "detail": result.get("detail")})
    check = {"name": "mailgun", "ok": bool(result["ok"]), "cached": False}
    if not result["ok"]:
        check["error"] = result.get("detail")
        audit_record(
            "monitoring.mailgun_unreachable",
            status=AuditStatus.FAILURE,
            target_type="mailgun",
            target_id=None,
            metadata={"error": str(result.get("detail") or "unknown")[:200]},
        )
    return check


def _check_backup_recency() -> dict[str, object]:
    latest_success = (
        Backup.query.filter_by(status=BackupStatus.SUCCESS)
        .order_by(Backup.created_at.desc())
        .first()
    )
    if latest_success is None:
        return {"name": "backup", "ok": True, "warning": "No successful backup found"}
    latest_success_at = _as_utc(latest_success.created_at)
    age = datetime.now(timezone.utc) - latest_success_at
    age_hours = round(age.total_seconds() / 3600, 2)
    check: dict[str, object] = {"name": "backup", "ok": True, "age_hours": age_hours}
    if age > timedelta(hours=25):
        check["warning"] = "Last successful backup is older than 25h"
    if age > timedelta(hours=36):
        check["warning"] = "Last successful backup is older than 36h"
        _capture_backup_overdue_sentry()
        audit_record(
            "monitoring.backup_overdue",
            status=AuditStatus.FAILURE,
            target_type="backup",
            target_id=None,
            metadata={"last_success_at": latest_success_at.isoformat()},
        )
    return check


def _check_scheduler_running(app) -> dict[str, object]:
    registry = app.extensions.get("apscheduler_instances", {}) if hasattr(app, "extensions") else {}
    jobs_issues: list[str] = []
    running = []
    for name, scheduler in registry.items():
        if scheduler is None or not getattr(scheduler, "running", False):
            continue
        running.append(name)
        for job in scheduler.get_jobs():
            if job.next_run_time is None:
                jobs_issues.append(f"{name}:{job.id}")
    if running and not jobs_issues:
        return {"name": "scheduler", "ok": True, "running": running}
    scheduler_enabled = any(
        bool(app.config.get(key))
        for key in (
            "EMAIL_SCHEDULER_ENABLED",
            "BACKUP_SCHEDULER_ENABLED",
            "INVOICE_OVERDUE_SCHEDULER_ENABLED",
            "IDEMPOTENCY_PRUNE_SCHEDULER_ENABLED",
            "STATUS_SCHEDULER_ENABLED",
            "WEBHOOK_DELIVERY_SCHEDULER_ENABLED",
            "ICAL_SYNC_ENABLED",
        )
    )
    if not running and not scheduler_enabled:
        return {"name": "scheduler", "ok": True, "disabled": True}
    if jobs_issues:
        return {"name": "scheduler", "ok": False, "error": f"jobs without next_run_time: {jobs_issues}"}
    return {"name": "scheduler", "ok": False, "error": "No running APScheduler instance detected"}


def _safe_checks_for_audit(checks: list[dict[str, object]]) -> list[dict[str, object]]:
    safe_checks: list[dict[str, object]] = []
    for check in checks:
        safe_checks.append(
            {
                "name": check.get("name"),
                "ok": bool(check.get("ok")),
                "latency_ms": check.get("latency_ms"),
                "warning": check.get("warning"),
                "error": str(check.get("error") or "")[:120],
            }
        )
    return safe_checks


def _truncate_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc)[:180]}"


def _capture_backup_overdue_sentry() -> None:
    try:
        import sentry_sdk

        sentry_sdk.capture_message("backup_overdue", level="warning")
    except Exception:
        return
