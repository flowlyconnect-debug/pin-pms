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


def authenticate_user(email: str, password: str) -> User | None:
    normalized_email = (email or "").strip().lower()
    if not normalized_email:
        return None

    if _is_locked_out(normalized_email):
        _record_login_attempt(normalized_email, success=False)
        return None

    user = User.query.filter_by(email=normalized_email).first()
    if not user:
        _record_login_attempt(normalized_email, success=False)
        return None

    if not user.is_active:
        _record_login_attempt(normalized_email, success=False)
        return None

    if not user.check_password(password):
        _record_login_attempt(normalized_email, success=False)
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
    LoginAttempt.query.filter_by(email=email, success=False).delete(
        synchronize_session=False
    )
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
        commit=True,
    )


def audit_login_failed(email: str | None = None) -> None:
    normalized_email = (email or "").strip().lower() or None
    audit_record(
        "login_failed",
        status=AuditStatus.FAILURE,
        actor_type=ActorType.ANONYMOUS,
        actor_email=normalized_email,
        commit=True,
    )


def audit_logout(user: User) -> None:
    audit_record(
        "logout",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=user.id,
        actor_email=user.email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
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
