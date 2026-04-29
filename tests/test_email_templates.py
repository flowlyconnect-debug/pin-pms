from __future__ import annotations

import pyotp
import pytest


def _seed_templates():
    from app.email.services import ensure_seed_templates

    ensure_seed_templates()


def _login_superadmin_2fa(client, superadmin):
    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
        follow_redirects=True,
    )
    code = pyotp.TOTP(superadmin.totp_secret).now()
    client.post("/2fa/verify", data={"code": code}, follow_redirects=True)


def test_superadmin_can_open_preview(client, superadmin):
    _seed_templates()
    _login_superadmin_2fa(client, superadmin)
    response = client.get("/admin/email-templates/welcome_email/preview")
    assert response.status_code == 200
    assert "Esikatselu".encode() in response.data


def test_user_without_permission_cannot_open_preview(client, regular_user):
    client.post(
        "/login",
        data={"email": regular_user.email, "password": regular_user.password_plain},
    )
    response = client.get("/admin/email-templates/welcome_email/preview")
    assert response.status_code == 403


def test_superadmin_without_active_2fa_cannot_send_test(client, superadmin):
    from app.extensions import db

    _seed_templates()
    superadmin.is_2fa_enabled = False
    db.session.commit()
    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
    )
    response = client.post(
        "/admin/email-templates/welcome_email/test-send",
        data={"to": "test@example.com"},
    )
    assert response.status_code == 302
    assert "/2fa/setup" in response.headers["Location"]


def test_test_send_validates_email(client, superadmin):
    _seed_templates()
    _login_superadmin_2fa(client, superadmin)
    response = client.post(
        "/admin/email-templates/welcome_email/test-send",
        data={"to": "bad-email"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert "kelvollinen".encode() in response.data


def test_template_renders_with_variables(app):
    from app.email.services import render_template

    _seed_templates()
    rendered = render_template(
        "welcome_email",
        {
            "user_email": "alice@example.com",
            "organization_name": "Pindora",
            "login_url": "https://example.com/login",
            "from_name": "Pin PMS",
        },
    )
    assert "Pindora" in rendered.subject
    assert "alice@example.com" in rendered.text


def test_missing_variable_returns_controlled_error(app):
    from app.email.services import EmailServiceError, render_template

    _seed_templates()
    with pytest.raises(EmailServiceError) as err_info:
        render_template("welcome_email", {"user_email": "alice@example.com"})
    assert "puuttuvia muuttujia" in err_info.value.public_message.lower()


def test_mailgun_service_called_on_test_send(client, superadmin, monkeypatch):
    _seed_templates()
    _login_superadmin_2fa(client, superadmin)
    called = {"value": False}

    def _fake_send(*, template_key: str, to: str, actor_user):
        _ = template_key, to, actor_user
        called["value"] = True

    monkeypatch.setattr("app.admin.services.send_email_template_test", _fake_send)
    response = client.post(
        "/admin/email-templates/welcome_email/test-send",
        data={"to": "qa@example.com"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert called["value"] is True


def test_audit_log_successful_test_send(client, superadmin, monkeypatch):
    from app.audit.models import AuditLog

    _seed_templates()
    _login_superadmin_2fa(client, superadmin)
    monkeypatch.setattr("app.admin.services.send_email_template_test", lambda **kwargs: None)
    client.post(
        "/admin/email-templates/welcome_email/test-send",
        data={"to": "qa@example.com"},
        follow_redirects=False,
    )
    row = (
        AuditLog.query.filter_by(action="email_template.test_sent")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None


def test_audit_log_failed_test_send(client, superadmin, monkeypatch):
    from app.audit.models import AuditLog
    from app.email.services import EmailServiceError

    _seed_templates()
    _login_superadmin_2fa(client, superadmin)

    def _boom(**kwargs):
        _ = kwargs
        raise EmailServiceError("Sahkopalvelu ei vastaa")

    monkeypatch.setattr("app.admin.services.send_email_template_test", _boom)
    client.post(
        "/admin/email-templates/welcome_email/test-send",
        data={"to": "qa@example.com"},
        follow_redirects=False,
    )
    row = (
        AuditLog.query.filter_by(action="email_template.test_failed")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None
