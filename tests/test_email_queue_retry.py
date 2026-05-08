from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pyotp


def _ctx() -> dict:
    return {"subject_line": "Queue test", "message": "Hello from queue"}


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _seed_template() -> None:
    from app.email.models import EmailTemplate, TemplateKey
    from app.extensions import db

    if EmailTemplate.query.filter_by(key=TemplateKey.ADMIN_NOTIFICATION).first() is not None:
        return
    db.session.add(
        EmailTemplate(
            key=TemplateKey.ADMIN_NOTIFICATION,
            subject="{{ subject_line }}",
            body_text="{{ message }}",
            body_html="<p>{{ message }}</p>",
            description="Queue retry test template",
            available_variables=["subject_line", "message"],
        )
    )
    db.session.commit()


def _login_admin(client, admin_user):
    return client.post(
        "/login", data={"email": admin_user.email, "password": admin_user.password_plain}
    )


def _login_superadmin_2fa(client, superadmin):
    _ = client.post(
        "/login", data={"email": superadmin.email, "password": superadmin.password_plain}
    )
    code = pyotp.TOTP(superadmin.totp_secret).now()
    return client.post("/two-factor/verify", data={"code": code})


def test_email_queue_retries_failed_send(app, monkeypatch):
    from app.email.models import EmailQueueItem, OutgoingEmailStatus, TemplateKey
    from app.email.scheduler import process_email_queue
    from app.email.services import send_template

    _seed_template()
    app.config["MAIL_DEV_LOG_ONLY"] = False
    app.config["MAILGUN_API_KEY"] = "test-key"
    app.config["MAILGUN_DOMAIN"] = "mg.example.test"

    calls = {"n": 0}

    class _Resp:
        def __init__(self, status_code: int):
            self.status_code = status_code
            self.text = "mailgun error" if status_code >= 300 else "ok"

    def _fake_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return _Resp(500)
        return _Resp(200)

    monkeypatch.setattr("app.email.services.requests.post", _fake_post)
    assert send_template(TemplateKey.ADMIN_NOTIFICATION, to="retry@test.local", context=_ctx())

    assert process_email_queue() == 1
    row = EmailQueueItem.query.filter_by(to="retry@test.local").first()
    assert row is not None
    assert row.status == OutgoingEmailStatus.PENDING
    assert row.effective_attempt_count == 1
    assert row.next_attempt_at is not None

    row.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    from app.extensions import db

    db.session.commit()
    assert process_email_queue() == 1
    db.session.refresh(row)
    assert row.status == OutgoingEmailStatus.SENT
    assert row.sent_at is not None


def test_email_queue_max_attempts_marks_failed(app, monkeypatch):
    from app.email.models import EmailQueueItem, OutgoingEmailStatus
    from app.email.scheduler import process_email_queue
    from app.extensions import db

    _seed_template()
    app.config["MAIL_DEV_LOG_ONLY"] = False
    app.config["MAILGUN_API_KEY"] = "test-key"
    app.config["MAILGUN_DOMAIN"] = "mg.example.test"

    class _Resp:
        status_code = 500
        text = "mailgun error"

    monkeypatch.setattr("app.email.services.requests.post", lambda *args, **kwargs: _Resp())

    row = EmailQueueItem(
        to="failed@test.local",
        recipient_email="failed@test.local",
        template_key="admin_notification",
        context_json=_ctx(),
        subject_snapshot="Queue test",
        status=OutgoingEmailStatus.PENDING,
        attempt_count=4,
        attempts=4,
        next_attempt_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.session.add(row)
    db.session.commit()

    assert process_email_queue() == 1
    db.session.refresh(row)
    assert row.status == OutgoingEmailStatus.FAILED
    assert row.effective_attempt_count == 5
    assert row.next_attempt_at is None
    assert row.last_error


def test_email_queue_audit_log_for_each_state(app, monkeypatch):
    from app.audit.models import AuditLog
    from app.email.models import EmailQueueItem, OutgoingEmailStatus, TemplateKey
    from app.email.scheduler import process_email_queue
    from app.email.services import send_template
    from app.extensions import db

    _seed_template()
    app.config["MAIL_DEV_LOG_ONLY"] = False
    app.config["MAILGUN_API_KEY"] = "test-key"
    app.config["MAILGUN_DOMAIN"] = "mg.example.test"

    calls = {"n": 0}

    class _Resp:
        def __init__(self, code: int):
            self.status_code = code
            self.text = "err" if code >= 300 else "ok"

    def _fake_post(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] <= 2:
            return _Resp(500)
        return _Resp(200)

    monkeypatch.setattr("app.email.services.requests.post", _fake_post)
    assert send_template(TemplateKey.ADMIN_NOTIFICATION, to="audit@test.local", context=_ctx())
    first = EmailQueueItem.query.filter_by(to="audit@test.local").first()
    assert first is not None
    assert AuditLog.query.filter_by(action="email.queued", target_id=first.id).first() is not None

    assert process_email_queue() == 1
    db.session.refresh(first)
    assert first.status == OutgoingEmailStatus.PENDING
    assert AuditLog.query.filter_by(action="email.retried", target_id=first.id).first() is not None

    first.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.session.commit()
    assert process_email_queue() == 1
    db.session.refresh(first)
    assert first.status == OutgoingEmailStatus.PENDING

    first.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.session.commit()
    assert process_email_queue() == 1
    assert AuditLog.query.filter_by(action="email.sent", target_id=first.id).first() is not None

    # separate item to force terminal failure
    row = EmailQueueItem(
        to="audit-fail@test.local",
        recipient_email="audit-fail@test.local",
        template_key="admin_notification",
        context_json=_ctx(),
        subject_snapshot="Queue test",
        status=OutgoingEmailStatus.PENDING,
        attempt_count=4,
        attempts=4,
        next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        scheduled_at=datetime.now(timezone.utc) - timedelta(seconds=1),
    )
    db.session.add(row)
    db.session.commit()
    calls["n"] = 0
    monkeypatch.setattr("app.email.services.requests.post", lambda *args, **kwargs: _Resp(500))
    assert process_email_queue() == 1
    assert AuditLog.query.filter_by(action="email.failed", target_id=row.id).first() is not None


def test_email_queue_backoff_schedule():
    from app.email.scheduler import _compute_next_attempt

    now = datetime.now(timezone.utc)
    expected = [1, 5, 30, 120, 720]
    for idx, minutes in enumerate(expected, start=1):
        next_time = _compute_next_attempt(now, idx)
        delta_minutes = int((next_time - now).total_seconds() // 60)
        assert abs(delta_minutes - minutes) <= 1


def test_admin_can_retry_failed_message(app, client, admin_user):
    from app.email.models import EmailQueueItem, OutgoingEmailStatus
    from app.extensions import db

    _login_admin(client, admin_user)
    row = EmailQueueItem(
        organization_id=admin_user.organization_id,
        to="retry-admin@test.local",
        recipient_email="retry-admin@test.local",
        template_key="admin_notification",
        context_json=_ctx(),
        status=OutgoingEmailStatus.FAILED,
        attempt_count=5,
        attempts=5,
    )
    db.session.add(row)
    db.session.commit()

    resp = client.post(f"/admin/email-queue/{row.id}/retry", data={})
    assert resp.status_code == 302
    db.session.refresh(row)
    assert row.status == OutgoingEmailStatus.PENDING
    assert _as_utc(row.next_attempt_at) <= datetime.now(timezone.utc)


def test_admin_can_cancel_pending_message(app, client, admin_user):
    from app.email.models import EmailQueueItem, OutgoingEmailStatus
    from app.extensions import db

    _login_admin(client, admin_user)
    row = EmailQueueItem(
        organization_id=admin_user.organization_id,
        to="cancel-admin@test.local",
        recipient_email="cancel-admin@test.local",
        template_key="admin_notification",
        context_json=_ctx(),
        status=OutgoingEmailStatus.PENDING,
        attempt_count=0,
        attempts=0,
        next_attempt_at=datetime.now(timezone.utc),
    )
    db.session.add(row)
    db.session.commit()

    resp = client.post(f"/admin/email-queue/{row.id}/cancel", data={})
    assert resp.status_code == 302
    db.session.refresh(row)
    assert row.status == OutgoingEmailStatus.CANCELLED


def test_password_reset_uses_sync_path(app, monkeypatch, regular_user):
    from app.auth.services import request_password_reset
    from app.email.models import EmailQueueItem

    called = {"sync": 0}

    def _fake_sync(*args, **kwargs):
        called["sync"] += 1
        return True

    monkeypatch.setattr("app.auth.services.send_template_sync", _fake_sync)
    request_password_reset(email=regular_user.email)
    assert called["sync"] == 1
    assert EmailQueueItem.query.count() == 0


def test_health_reports_queue_status(app):
    from app.email.models import EmailQueueItem, OutgoingEmailStatus
    from app.extensions import db
    from app.status.service import readiness_status

    old = datetime.now(timezone.utc) - timedelta(minutes=40)
    db.session.add(
        EmailQueueItem(
            to="pending@test.local",
            recipient_email="pending@test.local",
            template_key="admin_notification",
            context_json=_ctx(),
            status=OutgoingEmailStatus.PENDING,
            next_attempt_at=old,
            scheduled_at=old,
            created_at=old,
        )
    )
    for idx in range(11):
        db.session.add(
            EmailQueueItem(
                to=f"failed{idx}@test.local",
                recipient_email=f"failed{idx}@test.local",
                template_key="admin_notification",
                context_json=_ctx(),
                status=OutgoingEmailStatus.FAILED,
                attempt_count=5,
                attempts=5,
            )
        )
    db.session.commit()
    payload = readiness_status(app)
    check = [c for c in payload["checks"] if c.get("name") == "email_queue"][0]
    assert check["pending"] >= 1
    assert check["failed"] >= 11
    assert check["oldest_pending_age_minutes"] >= 30
    assert check["ok"] is False
    assert payload["ok"] is False


def test_mail_dev_log_only_does_not_enqueue(app, monkeypatch):
    from app.email.models import EmailQueueItem, TemplateKey
    from app.email.services import send_template

    _seed_template()
    app.config["MAIL_DEV_LOG_ONLY"] = True
    called = {"post": 0}

    def _fake_post(*args, **kwargs):
        called["post"] += 1
        raise AssertionError("Mailgun post must not run in dev log mode")

    monkeypatch.setattr("app.email.services.requests.post", _fake_post)
    assert (
        send_template(TemplateKey.ADMIN_NOTIFICATION, to="dev@test.local", context=_ctx()) is True
    )
    assert EmailQueueItem.query.count() == 0
    assert called["post"] == 0


def test_email_context_does_not_store_secret_token(app):
    from app.email.models import EmailQueueItem, TemplateKey
    from app.email.services import send_template

    _seed_template()
    app.config["MAIL_DEV_LOG_ONLY"] = False
    assert send_template(
        TemplateKey.ADMIN_NOTIFICATION,
        to="safe@test.local",
        context={"subject_line": "s", "message": "m", "reset_token": "raw-secret-token"},
    )
    row = EmailQueueItem.query.filter_by(to="safe@test.local").first()
    assert row is not None
    assert "reset_token" not in (row.context_json or {})
