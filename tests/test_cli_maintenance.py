from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_cleanup_expired_tokens_cli_deletes_expired_rows(app, regular_user):
    from app.auth.models import PasswordResetToken, TwoFactorEmailCode
    from app.core.security import hash_token
    from app.extensions import db
    from app.portal.models import PortalMagicLinkToken

    now = datetime.now(timezone.utc)

    expired_reset, _ = PasswordResetToken.issue(user_id=regular_user.id)
    expired_reset.expires_at = now - timedelta(days=1)
    active_reset, _ = PasswordResetToken.issue(user_id=regular_user.id)
    active_reset.expires_at = now + timedelta(days=1)

    expired_2fa = TwoFactorEmailCode.issue(user_id=regular_user.id, code="111111")
    expired_2fa.expires_at = now - timedelta(days=1)
    active_2fa = TwoFactorEmailCode.issue(user_id=regular_user.id, code="222222")
    active_2fa.expires_at = now + timedelta(days=1)

    expired_magic = PortalMagicLinkToken(
        user_id=regular_user.id,
        token_hash=hash_token("expired-magic-token"),
        expires_at=now - timedelta(days=1),
    )
    active_magic = PortalMagicLinkToken(
        user_id=regular_user.id,
        token_hash=hash_token("active-magic-token"),
        expires_at=now + timedelta(days=1),
    )

    db.session.add_all(
        [expired_reset, active_reset, expired_2fa, active_2fa, expired_magic, active_magic]
    )
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["cleanup-expired-tokens"])

    assert result.exit_code == 0, result.output
    assert "Deleted 3 expired token row(s)." in result.output

    assert PasswordResetToken.query.count() == 1
    assert TwoFactorEmailCode.query.count() == 1
    assert PortalMagicLinkToken.query.count() == 1


def test_vacuum_audit_logs_cli_keeps_recent_rows(app):
    from app.audit.models import ActorType, AuditLog, AuditStatus
    from app.extensions import db

    now = datetime.now(timezone.utc)
    old_row = AuditLog(
        actor_type=ActorType.SYSTEM,
        action="tests.old_row",
        status=AuditStatus.SUCCESS,
        created_at=now - timedelta(days=60),
    )
    recent_row = AuditLog(
        actor_type=ActorType.SYSTEM,
        action="tests.recent_row",
        status=AuditStatus.SUCCESS,
        created_at=now - timedelta(days=5),
    )
    db.session.add_all([old_row, recent_row])
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["vacuum-audit-logs", "--keep-days", "30"])

    assert result.exit_code == 0, result.output
    assert "Deleted 1 audit row(s) older than 30 day(s)." in result.output

    actions = {row.action for row in AuditLog.query.all()}
    assert "tests.old_row" not in actions
    assert "tests.recent_row" in actions
    assert "audit.logs.vacuumed" in actions
