from __future__ import annotations

import pyotp


def _login_superadmin_2fa(client, superadmin):
    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
        follow_redirects=False,
    )
    code = pyotp.TOTP(superadmin.totp_secret).now()
    client.post("/2fa/verify", data={"code": code}, follow_redirects=False)


def test_settings_list_masks_secret_values(client, superadmin):
    from app.settings import services as settings_service

    settings_service.set_value(
        "mailgun_api_key",
        "super-secret-value",
        type_="string",
        description="Mailgun API key",
        is_secret=True,
        actor_user_id=superadmin.id,
    )
    _login_superadmin_2fa(client, superadmin)

    response = client.get("/admin/settings")
    assert response.status_code == 200
    assert "••••••".encode("utf-8") in response.data
    assert b"super-secret-value" not in response.data


def test_secret_reveal_requires_fresh_2fa_code(client, superadmin):
    from app.settings import services as settings_service

    settings_service.set_value(
        "smtp_password",
        "smtp-super-secret",
        type_="string",
        is_secret=True,
        actor_user_id=superadmin.id,
    )
    _login_superadmin_2fa(client, superadmin)

    denied = client.post(
        "/admin/settings/smtp_password",
        data={"action": "reveal", "reveal_code": "000000"},
        follow_redirects=True,
    )
    assert denied.status_code == 200
    assert b"fresh 2FA code is required" in denied.data
    assert b"smtp-super-secret" not in denied.data

    allowed = client.post(
        "/admin/settings/smtp_password",
        data={"action": "reveal", "reveal_code": pyotp.TOTP(superadmin.totp_secret).now()},
        follow_redirects=True,
    )
    assert allowed.status_code == 200
    assert b"smtp-super-secret" in allowed.data


def test_set_value_persists_updated_by_and_audits(superadmin):
    from app.audit.models import AuditLog
    from app.settings import services as settings_service
    from app.settings.models import Setting

    row = settings_service.set_value(
        "company_name",
        "Pindora Oy",
        type_="string",
        description="Brand name",
        actor_user_id=superadmin.id,
    )
    assert row.updated_by == superadmin.id

    persisted = Setting.query.filter_by(key="company_name").first()
    assert persisted is not None
    assert persisted.updated_by == superadmin.id

    audit = (
        AuditLog.query.filter_by(action="setting.updated")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert audit.target_id == row.id


def test_logging_filter_redacts_secret_context_values():
    from app.core.logging import _redact_secret_context

    payload = {
        "event": "setting.updated",
        "is_secret": True,
        "value": "plain-secret",
        "nested": {"is_secret": True, "raw_value": "nested-secret"},
    }
    redacted = _redact_secret_context(payload)
    assert redacted["value"] == "***"
    assert redacted["nested"]["raw_value"] == "***"
