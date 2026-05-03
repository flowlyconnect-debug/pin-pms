import secrets
from datetime import datetime, timedelta, timezone

from flask import current_app, request

from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.auth.models import EMAIL_2FA_TTL, LoginAttempt, TwoFactorEmailCode
from app.email.models import TemplateKey
from app.email.services import send_template
from app.extensions import db
from app.users.models import User


def _audit_auth_login_failed(
    *,
    reason: str,
    login_identifier: str | None,
    user: User | None = None,
) -> None:
    ident = (login_identifier or "").strip().lower() or None
    audit_record(
        "auth.login_failed",
        status=AuditStatus.FAILURE,
        actor_type=ActorType.ANONYMOUS,
        actor_email=ident,
        target_type="user" if user is not None else "auth",
        target_id=user.id if user is not None else None,
        context={"reason": reason, "login_identifier": ident},
        commit=True,
    )


def authenticate_user(email: str, password: str) -> User | None:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        _audit_auth_login_failed(
            reason="missing_identifier",
            login_identifier=None,
            user=None,
        )
        return None

    if _is_locked_out(normalized_email):
        _record_login_attempt(normalized_email, success=False)
        _audit_auth_login_failed(
            reason="account_locked",
            login_identifier=normalized_email,
            user=None,
        )
        return None

    user = User.query.filter_by(email=normalized_email).first()
    if not user:
        _record_login_attempt(normalized_email, success=False)
        _audit_auth_login_failed(
            reason="user_not_found",
            login_identifier=normalized_email,
            user=None,
        )
        return None

    if not user.is_active:
        _record_login_attempt(normalized_email, success=False)
        _audit_auth_login_failed(
            reason="user_inactive",
            login_identifier=normalized_email,
            user=user,
        )
        return None

    if not user.check_password(password):
        _record_login_attempt(normalized_email, success=False)
        _audit_auth_login_failed(
            reason="invalid_password",
            login_identifier=normalized_email,
            user=user,
        )
        return None

    _record_login_attempt(normalized_email, success=True)
    _reset_failed_attempts(normalized_email)
    return user


def _max_login_attempts() -> int:
    val = current_app.config.get("MAX_LOGIN_ATTEMPTS", 5)
    try:
        return max(1, int(val))
    except (TypeError, ValueError):
        return 5


def _is_locked_out(email: str) -> bool:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(minutes=15)
    failed_count = (
        LoginAttempt.query.filter_by(email=email, success=False)
        .filter(LoginAttempt.created_at >= window_start)
        .count()
    )
    return failed_count > _max_login_attempts()


def _record_login_attempt(email: str, *, success: bool) -> None:
    ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not ip:
        ip = request.remote_addr
    db.session.add(LoginAttempt(email=email, ip=ip, success=success))
    db.session.commit()


def _reset_failed_attempts(email: str) -> None:
    LoginAttempt.query.filter_by(email=email, success=False).delete(synchronize_session=False)
    db.session.commit()


def audit_login_success(user: User) -> None:
    audit_record(
        "login",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=user.id,
        actor_email=user.email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        context={},
        commit=True,
    )


def audit_login_failed_2fa(user: User) -> None:
    """Record a failed second-factor check during login (superadmin flow)."""

    _audit_auth_login_failed(
        reason="invalid_2fa_code",
        login_identifier=user.email,
        user=user,
    )


def audit_logout(user: User) -> None:
    audit_record(
        "auth.logout",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=user.id,
        actor_email=user.email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        context={},
        commit=True,
    )


def enable_2fa(user: User, *, backup_codes_issued: int = 0) -> None:
    audit_record(
        "2fa_enabled",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=user.id,
        actor_email=user.email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        context={"backup_codes_issued": int(backup_codes_issued)},
    )


def disable_2fa(user: User, *, reason: str = "manual") -> None:
    user.is_2fa_enabled = False
    user.totp_secret = None
    user.backup_codes = []
    audit_record(
        "2fa_disabled",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=user.id,
        actor_email=user.email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        context={"reason": reason},
    )
    db.session.commit()


def send_email_2fa_code(user: User) -> bool:
    code = f"{secrets.randbelow(1_000_000):06d}"
    row = TwoFactorEmailCode.issue(user_id=user.id, code=code)
    db.session.add(row)
    db.session.flush()

    ok = send_template(
        TemplateKey.LOGIN_2FA_CODE,
        to=user.email,
        context={
            "user_email": user.email,
            "code": code,
            "expires_minutes": int(EMAIL_2FA_TTL.total_seconds() // 60),
        },
    )
    if not ok:
        db.session.rollback()
        return False

    audit_record(
        "2fa.email_code_sent",
        status=AuditStatus.SUCCESS,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        context={"expires_minutes": int(EMAIL_2FA_TTL.total_seconds() // 60)},
    )
    db.session.commit()
    return True


def cleanup_expired_tokens(*, now: datetime | None = None) -> dict[str, int]:
    """Delete expired token rows used by auth and portal flows."""
    from app.auth.models import PasswordResetToken

    current = now or datetime.now(timezone.utc)
    deleted_password_reset = PasswordResetToken.query.filter(
        PasswordResetToken.expires_at < current
    ).delete(synchronize_session=False)
    deleted_email_2fa = TwoFactorEmailCode.query.filter(
        TwoFactorEmailCode.expires_at < current
    ).delete(synchronize_session=False)

    deleted_portal_magic = 0
    try:
        from app.portal.models import PortalMagicLinkToken

        deleted_portal_magic = PortalMagicLinkToken.query.filter(
            PortalMagicLinkToken.expires_at < current
        ).delete(synchronize_session=False)
    except Exception:
        deleted_portal_magic = 0

    db.session.commit()
    return {
        "password_reset_tokens": int(deleted_password_reset or 0),
        "two_factor_email_codes": int(deleted_email_2fa or 0),
        "portal_magic_link_tokens": int(deleted_portal_magic or 0),
    }
