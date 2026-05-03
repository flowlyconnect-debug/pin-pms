"""Project brief section 11 — ``settings.update`` audit context (redaction flags)."""

from __future__ import annotations


def test_create_audit_redaction_flags(superadmin):
    from app.audit.models import AuditLog
    from app.settings import services as settings_service

    settings_service.set_value(
        "company_name",
        "Pindora Oy",
        type_="string",
        actor_user_id=superadmin.id,
    )
    audit = AuditLog.query.filter_by(action="settings.update").order_by(AuditLog.id.desc()).first()
    assert audit is not None
    ctx = audit.context or {}
    assert ctx.get("action") == "create"
    assert ctx.get("old_value_redacted") is False
    assert ctx.get("new_value_redacted") is False
    assert "old_value" not in ctx
    assert "new_value" not in ctx


def test_update_audit_redaction_flags(superadmin):
    from app.audit.models import AuditLog
    from app.settings import services as settings_service

    settings_service.set_value(
        "company_name",
        "Old Co",
        type_="string",
        actor_user_id=superadmin.id,
    )
    settings_service.set_value(
        "company_name",
        "New Co",
        actor_user_id=superadmin.id,
    )

    audit = AuditLog.query.filter_by(action="settings.update").order_by(AuditLog.id.desc()).first()
    assert audit is not None
    ctx = audit.context or {}
    assert ctx.get("action") == "update"
    assert ctx.get("old_value_redacted") is False
    assert ctx.get("new_value_redacted") is False
    assert "old_value" not in ctx
    assert "new_value" not in ctx


def test_secret_audit_omits_raw_values(superadmin):
    from app.audit.models import AuditLog
    from app.settings import services as settings_service

    settings_service.set_value(
        "smtp_password",
        "first-secret",
        type_="string",
        is_secret=True,
        actor_user_id=superadmin.id,
    )
    settings_service.set_value(
        "smtp_password",
        "rotated-secret",
        actor_user_id=superadmin.id,
    )

    audits = AuditLog.query.filter_by(action="settings.update").order_by(AuditLog.id.asc()).all()
    assert len(audits) >= 2
    for audit in audits:
        ctx = audit.context or {}
        assert "old_value" not in ctx
        assert "new_value" not in ctx
        assert b"first-secret".decode() not in str(ctx)
        assert b"rotated-secret".decode() not in str(ctx)
        assert ctx.get("new_value_redacted") is True
        assert ctx.get("old_value_redacted") in (True, False)

    update_ctx = audits[-1].context or {}
    assert update_ctx.get("value_changed") is True


def test_no_op_update_does_not_emit_value_change(superadmin):
    from app.audit.models import AuditLog
    from app.settings import services as settings_service

    settings_service.set_value(
        "company_name",
        "Steady",
        type_="string",
        actor_user_id=superadmin.id,
    )
    settings_service.set_value(
        "company_name",
        "Steady",
        actor_user_id=superadmin.id,
    )

    audit = AuditLog.query.filter_by(action="settings.update").order_by(AuditLog.id.desc()).first()
    ctx = audit.context or {}
    assert "value_changed" not in ctx
    assert "old_value" not in ctx
    assert "new_value" not in ctx
