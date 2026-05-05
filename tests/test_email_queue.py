from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _ctx() -> dict:
    return {"subject_line": "Queue test", "message": "Hello from queue"}


def _seed_admin_notification_template() -> None:
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
            description="Queue test template",
            available_variables=["subject_line", "message"],
        )
    )
    db.session.commit()


def test_send_template_queues_pending_row(app):
    _seed_admin_notification_template()
    from app.email.models import OutgoingEmail, OutgoingEmailStatus, TemplateKey
    from app.email.services import send_template

    app.config["MAIL_DEV_LOG_ONLY"] = False
    ok = send_template(
        TemplateKey.ADMIN_NOTIFICATION,
        to="queue@test.local",
        context=_ctx(),
    )
    assert ok is True

    row = OutgoingEmail.query.filter_by(to="queue@test.local").first()
    assert row is not None
    assert row.status == OutgoingEmailStatus.PENDING
    assert row.attempts == 0
    assert row.subject_snapshot == "Queue test"


def test_scheduler_cycle_marks_pending_as_sent_with_mocked_mailgun(app, monkeypatch):
    _seed_admin_notification_template()
    from app.email.models import OutgoingEmail, OutgoingEmailStatus, TemplateKey
    from app.email.scheduler import run_email_queue_cycle
    from app.email.services import send_template

    app.config["MAIL_DEV_LOG_ONLY"] = False
    app.config["MAILGUN_API_KEY"] = "test-key"
    app.config["MAILGUN_DOMAIN"] = "mg.example.test"

    class _Resp:
        status_code = 200
        text = "ok"

    def _fake_post(*args, **kwargs):
        return _Resp()

    monkeypatch.setattr("app.email.services.requests.post", _fake_post)

    assert send_template(TemplateKey.ADMIN_NOTIFICATION, to="sent@test.local", context=_ctx())
    assert run_email_queue_cycle() == 1

    row = OutgoingEmail.query.filter_by(to="sent@test.local").first()
    assert row is not None
    assert row.status == OutgoingEmailStatus.SENT
    assert row.sent_at is not None
    assert row.attempts == 0


def test_scheduler_retry_and_max_attempts_failed(app, monkeypatch):
    from app.email.models import OutgoingEmail, OutgoingEmailStatus
    from app.email.scheduler import run_email_queue_cycle
    from app.extensions import db

    app.config["MAIL_DEV_LOG_ONLY"] = False
    app.config["MAILGUN_API_KEY"] = "test-key"
    app.config["MAILGUN_DOMAIN"] = "mg.example.test"
    _seed_admin_notification_template()

    class _Resp:
        status_code = 500
        text = "mailgun error"

    def _fake_post(*args, **kwargs):
        return _Resp()

    monkeypatch.setattr("app.email.services.requests.post", _fake_post)

    row = OutgoingEmail(
        to="retry@test.local",
        template_key="admin_notification",
        context_json=_ctx(),
        subject_snapshot="Queue test",
        status=OutgoingEmailStatus.PENDING,
        attempts=4,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.session.add(row)
    db.session.commit()

    assert run_email_queue_cycle() == 1
    db.session.refresh(row)
    assert row.attempts == 5
    assert row.status == OutgoingEmailStatus.FAILED
    assert row.last_error


def test_scheduler_retry_increments_attempts_and_keeps_pending(app, monkeypatch):
    from app.email.models import OutgoingEmail, OutgoingEmailStatus
    from app.email.scheduler import run_email_queue_cycle
    from app.extensions import db

    app.config["MAIL_DEV_LOG_ONLY"] = False
    app.config["MAILGUN_API_KEY"] = "test-key"
    app.config["MAILGUN_DOMAIN"] = "mg.example.test"
    _seed_admin_notification_template()

    class _Resp:
        status_code = 500
        text = "mailgun error"

    def _fake_post(*args, **kwargs):
        return _Resp()

    monkeypatch.setattr("app.email.services.requests.post", _fake_post)

    row = OutgoingEmail(
        to="retry-pending@test.local",
        template_key="admin_notification",
        context_json=_ctx(),
        subject_snapshot="Queue test",
        status=OutgoingEmailStatus.PENDING,
        attempts=0,
        scheduled_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.session.add(row)
    db.session.commit()

    assert run_email_queue_cycle() == 1
    db.session.refresh(row)
    assert row.attempts == 1
    assert row.status == OutgoingEmailStatus.PENDING
    assert row.last_error
