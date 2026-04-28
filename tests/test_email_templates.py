from __future__ import annotations

import pyotp


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


def _force_superadmin_session(client, superadmin):
    with client.session_transaction() as session:
        session["_user_id"] = str(superadmin.id)
        session["_fresh"] = True
        session["2fa_verified"] = True


def test_render_template_for_succeeds_for_all_seed_templates(app):
    from app.email.seed_data import SEED_TEMPLATES
    from app.email.templates import render_template_for

    _seed_templates()

    sample_context = {
        "user_email": "test@example.com",
        "organization_name": "Test Organization",
        "login_url": "https://example.com/login",
        "reset_url": "https://example.com/reset/abc123",
        "expires_minutes": 30,
        "code": "123 456",
        "backup_name": "test-backup",
        "completed_at": "2026-04-25 10:00:00 UTC",
        "size_human": "12.3 MB",
        "location": "/var/backups/pindora/test-backup.sql.gz",
        "failed_at": "2026-04-25 10:00:00 UTC",
        "error_message": "test error",
        "subject_line": "Test subject",
        "message": "Test message",
        "reservation_id": 123,
        "unit_name": "A-101",
        "start_date": "2026-05-01",
        "end_date": "2026-05-05",
        "invoice_number": "INV-123",
        "amount": "100.00",
        "currency": "EUR",
        "due_date": "2026-05-10",
        "description": "Test invoice row",
    }

    for seed in SEED_TEMPLATES:
        rendered = render_template_for(seed["key"], sample_context)
        assert rendered.subject
        assert rendered.text


def test_validate_context_returns_missing_variables(app):
    from app.email.models import TemplateKey
    from app.email.templates import validate_context

    _seed_templates()

    missing = validate_context(
        TemplateKey.WELCOME_EMAIL,
        {"user_email": "alice@example.com"},
    )

    assert "organization_name" in missing
    assert "login_url" in missing


def test_admin_preview_shows_clear_missing_variable_error(client, superadmin):
    from app.email.models import EmailTemplate, TemplateKey

    _seed_templates()
    _login_superadmin_2fa(client, superadmin)

    template = EmailTemplate.query.filter_by(key=TemplateKey.WELCOME_EMAIL).first()
    assert template is not None

    from app.admin import routes as admin_routes

    original_validate = admin_routes.validate_email_context
    admin_routes.validate_email_context = lambda _key, _context: ["missing_var_for_test"]

    try:
        response = client.post(
            f"/admin/email-templates/{template.key}",
            data={
                "action": "preview",
                "subject": "Welcome {{ organization_name }}",
                "body_text": "Hi {{ user_email }}",
                "body_html": "",
            },
            follow_redirects=True,
        )
    finally:
        admin_routes.validate_email_context = original_validate

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Template context is missing required variables: missing_var_for_test" in body


