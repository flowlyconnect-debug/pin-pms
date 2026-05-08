from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.audit.models import AuditLog
from app.backups.models import Backup, BackupStatus, BackupTrigger
from app.extensions import db


def _health_ready(client, api_key):
    return client.get(
        "/api/v1/health/ready",
        headers={"X-API-Key": api_key.raw},
    )


def test_health_includes_db_check(client, api_key):
    response = _health_ready(client, api_key)
    assert response.status_code in {200, 503}
    payload = response.get_json()
    checks = payload["data"]["checks"]
    assert any(check.get("name") == "db" for check in checks)


def test_health_includes_mailgun_check_when_configured(app, client, api_key, monkeypatch):
    app.config["MAILGUN_API_KEY"] = "mg-key"
    app.config["MAILGUN_DOMAIN"] = "mg.example.com"

    class _Response:
        status_code = 200

    from app.status import service as status_service

    status_service._mailgun_cache.update(
        {"checked_at": 0.0, "ok": False, "detail": "uninitialized"}
    )
    monkeypatch.setattr(status_service.requests, "get", lambda *args, **kwargs: _Response())
    response = _health_ready(client, api_key)
    checks = response.get_json()["data"]["checks"]
    assert any(check.get("name") == "mailgun" for check in checks)


def test_health_returns_503_when_db_slow_or_down(app, client, api_key, monkeypatch):
    from app.status import service as status_service

    monkeypatch.setattr(
        status_service,
        "_check_db_ready",
        lambda: {"name": "db", "ok": False, "latency_ms": 900, "error": "DB latency too high"},
    )
    response = _health_ready(client, api_key)
    assert response.status_code == 503
    audit = AuditLog.query.filter_by(action="monitoring.health_check_failed").first()
    assert audit is not None


def test_health_warns_when_backup_overdue(app, client, api_key, monkeypatch):
    from app.status import service as status_service

    app.config["MAILGUN_API_KEY"] = ""
    app.config["MAILGUN_DOMAIN"] = ""
    overdue_time = datetime.now(timezone.utc) - timedelta(hours=40)
    db.session.add(
        Backup(
            filename="old-backup.sql.gz",
            location="/tmp/old-backup.sql.gz",
            status=BackupStatus.SUCCESS,
            trigger=BackupTrigger.SCHEDULED,
            created_at=overdue_time,
            completed_at=overdue_time,
        )
    )
    db.session.commit()
    sentry_messages: list[str] = []
    monkeypatch.setitem(
        __import__("sys").modules,
        "sentry_sdk",
        type(
            "FakeSentry",
            (),
            {"capture_message": staticmethod(lambda msg, level=None: sentry_messages.append(msg))},
        ),
    )
    response = _health_ready(client, api_key)
    checks = response.get_json()["data"]["checks"]
    backup_check = next(check for check in checks if check.get("name") == "backup")
    assert "warning" in backup_check
    assert "backup_overdue" in sentry_messages
    audit = AuditLog.query.filter_by(action="monitoring.backup_overdue").first()
    assert audit is not None
    status_service._mailgun_cache.update(
        {"checked_at": 0.0, "ok": False, "detail": "uninitialized"}
    )


def test_health_audits_mailgun_unreachable(app, client, api_key, monkeypatch):
    from app.status import service as status_service

    app.config["MAILGUN_API_KEY"] = "mg-key"
    app.config["MAILGUN_DOMAIN"] = "mg.example.com"
    status_service._mailgun_cache.update(
        {"checked_at": 0.0, "ok": False, "detail": "uninitialized"}
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("mailgun down")

    monkeypatch.setattr(status_service.requests, "get", _boom)
    response = _health_ready(client, api_key)
    assert response.status_code in {200, 503}
    audit = AuditLog.query.filter_by(action="monitoring.mailgun_unreachable").first()
    assert audit is not None
