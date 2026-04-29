from __future__ import annotations


def _login_superadmin(client, superadmin):
    return client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
        follow_redirects=False,
    )


def test_seed_templates_include_required_init_keys():
    from app.email.seed_data import SEED_TEMPLATES

    required = {
        "welcome_email",
        "password_reset",
        "login_2fa_code",
        "backup_completed",
        "backup_failed",
        "admin_notification",
    }
    by_key = {item["key"]: item for item in SEED_TEMPLATES}
    assert required.issubset(by_key.keys())
    for key in required:
        template = by_key[key]
        assert isinstance(template.get("subject"), str) and template["subject"].strip()
        assert isinstance(template.get("body_text"), str) and template["body_text"].strip()
        assert isinstance(template.get("body_html"), str) and template["body_html"].strip()
        assert isinstance(template.get("available_variables"), list)
        assert template["available_variables"]


def test_send_email_2fa_code_creates_hashed_token_and_audit(superadmin, monkeypatch):
    from app.audit.models import AuditLog
    from app.auth.models import TwoFactorEmailCode
    from app.auth.services import send_email_2fa_code

    sent_payload = {}

    def _fake_send_template(key, *, to, context):
        sent_payload["key"] = key
        sent_payload["to"] = to
        sent_payload["context"] = dict(context)
        return True

    monkeypatch.setattr("app.auth.services.send_template", _fake_send_template)
    monkeypatch.setattr("app.auth.services.secrets.randbelow", lambda _n: 123456)

    assert send_email_2fa_code(superadmin) is True

    row = TwoFactorEmailCode.query.filter_by(user_id=superadmin.id).first()
    assert row is not None
    assert row.code_hash != "123456"
    assert row.used_at is None
    assert sent_payload["to"] == superadmin.email
    assert sent_payload["context"]["code"] == "123456"

    audit = (
        AuditLog.query.filter_by(action="2fa.email_code_sent").order_by(AuditLog.id.desc()).first()
    )
    assert audit is not None
    assert audit.target_id == superadmin.id


def test_2fa_email_code_route_and_verify_accepts_code(client, superadmin, monkeypatch):
    from app.audit.models import AuditLog

    _login_superadmin(client, superadmin)

    monkeypatch.setattr("app.auth.services.send_template", lambda *args, **kwargs: True)
    monkeypatch.setattr("app.auth.services.secrets.randbelow", lambda _n: 424242)

    send_response = client.post("/2fa/email-code", follow_redirects=False)
    assert send_response.status_code == 302
    assert "/2fa/verify" in send_response.headers["Location"]

    verify_response = client.post(
        "/2fa/verify",
        data={"code": "424242"},
        follow_redirects=False,
    )
    assert verify_response.status_code == 302
    assert "/admin" in verify_response.headers["Location"]

    sent_audit = AuditLog.query.filter_by(action="2fa.email_code_sent").first()
    used_audit = AuditLog.query.filter_by(action="2fa.email_code_used").first()
    assert sent_audit is not None
    assert used_audit is not None
