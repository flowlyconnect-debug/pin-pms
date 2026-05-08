import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal

import pyotp
from flask import current_app
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.auth.models import (
    EMAIL_2FA_TTL,
    PASSWORD_RESET_TTL,
    LoginAttempt,
    PasswordResetToken,
    TwoFactorEmailCode,
)
from app.email.models import TemplateKey
from app.email.services import EmailTemplateNotFound, send_template, send_template_sync
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
    try:
        from flask import has_request_context
        from flask import request as flask_request

        if has_request_context():
            ip = flask_request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            if not ip:
                ip = flask_request.remote_addr
        else:
            ip = None
    except Exception:
        ip = None
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


# --- Route-facing orchestration (keeps ``auth.routes`` thin) ----------------


def authenticate_user_for_login(
    *, email: str, password: str
) -> tuple[User | None, str | None, bool]:
    """Run :func:`authenticate_user` and map SQLAlchemy failures to a safe page message.

    Returns ``(user, error_message, is_infrastructure_error)``.
    """

    try:
        user = authenticate_user(email, password)
        return user, None, False
    except SQLAlchemyError as exc:
        try:
            from flask import has_request_context
            from flask import request as flask_request

            path = flask_request.path if has_request_context() else None
        except Exception:
            path = None
        log_payload = {
            "error_type": type(exc).__name__,
            "email": email,
            "path": path,
        }
        if isinstance(exc, DBAPIError):
            log_payload["dbapi_error"] = str(exc.orig)
            if exc.statement:
                log_payload["statement"] = exc.statement
            if exc.params:
                log_payload["params"] = repr(exc.params)[:500]
        current_app.logger.exception(
            "Database error during /login authentication.",
            extra=log_payload,
        )
        if current_app.debug:
            detail = (
                f"Kirjautumispalvelu ei ole käytettävissä "
                f"(DB-virhe: {type(exc).__name__}). Katso lokit."
            )
        else:
            detail = "Kirjautumispalvelu ei ole hetkellisesti käytettävissä. Yritä hetken kuluttua uudelleen."
        return None, detail, True
    except Exception as exc:  # noqa: BLE001
        current_app.logger.exception("Unexpected error during /login authentication.")
        if current_app.debug:
            detail = f"Odottamaton virhe ({type(exc).__name__}). Katso lokit."
        else:
            detail = "Kirjautumispalvelu ei ole hetkellisesti käytettävissä. Yritä hetken kuluttua uudelleen."
        return None, detail, True


def ensure_superadmin_totp_secret_initialized(user: User) -> None:
    if not user.totp_secret:
        user.totp_secret = pyotp.random_base32()
        db.session.commit()


def complete_superadmin_two_factor_setup(*, user: User, code: str) -> tuple[bool, list[str] | None]:
    """Verify TOTP and enable 2FA; returns ``(success, plaintext_backup_codes)``."""

    normalized = (code or "").replace(" ", "").strip()
    totp = pyotp.TOTP(user.totp_secret)
    if not totp.verify(normalized, valid_window=1):
        audit_record(
            "auth.2fa.setup_failed",
            status=AuditStatus.FAILURE,
            target_type="user",
            target_id=user.id,
            commit=True,
        )
        return False, None

    user.is_2fa_enabled = True
    plaintext_codes = user.generate_backup_codes()
    enable_2fa(user, backup_codes_issued=len(plaintext_codes))
    db.session.commit()
    return True, plaintext_codes


def regenerate_superadmin_backup_codes(*, user: User) -> list[str]:
    plaintext_codes = user.generate_backup_codes()
    audit_record(
        "auth.2fa.backup_codes_regenerated",
        status=AuditStatus.SUCCESS,
        target_type="user",
        target_id=user.id,
        context={"count": len(plaintext_codes)},
    )
    db.session.commit()
    return plaintext_codes


Superadmin2faVerifyResult = Literal["totp", "backup", "email", "failed"]


def verify_superadmin_two_factor_code(*, user: User, code: str) -> Superadmin2faVerifyResult:
    normalized = (code or "").replace(" ", "").strip()
    totp = pyotp.TOTP(user.totp_secret)
    if totp.verify(normalized, valid_window=1):
        audit_record(
            "auth.2fa.verified",
            status=AuditStatus.SUCCESS,
            target_type="user",
            target_id=user.id,
            commit=True,
        )
        return "totp"

    if user.consume_backup_code(normalized):
        audit_record(
            "auth.2fa.backup_code_used",
            status=AuditStatus.SUCCESS,
            target_type="user",
            target_id=user.id,
            context={"codes_remaining": user.backup_codes_remaining},
            commit=True,
        )
        return "backup"

    if TwoFactorEmailCode.consume_active_code(user_id=user.id, raw_code=normalized):
        audit_record(
            "2fa.email_code_used",
            status=AuditStatus.SUCCESS,
            organization_id=user.organization_id,
            target_type="user",
            target_id=user.id,
        )
        db.session.commit()
        return "email"

    return "failed"


def request_password_reset(*, email: str) -> None:
    """Issue reset token when eligible, send email, write audit (same UX for unknown emails)."""

    if not email:
        return
    user = User.query.filter_by(email=email).first()
    if user is not None and user.is_active:
        token_row, raw_token = PasswordResetToken.issue(user_id=user.id)
        db.session.add(token_row)
        db.session.commit()

        from flask import has_request_context, url_for

        if has_request_context():
            reset_url = url_for("auth.reset_password", token=raw_token, _external=True)
        else:
            base_url = (current_app.config.get("APP_BASE_URL") or "http://127.0.0.1:5000").rstrip(
                "/"
            )
            reset_url = f"{base_url}/reset-password/{raw_token}"
        try:
            send_template_sync(
                TemplateKey.PASSWORD_RESET,
                to=user.email,
                context={
                    "user_email": user.email,
                    "reset_url": reset_url,
                    "expires_minutes": int(PASSWORD_RESET_TTL.total_seconds() // 60),
                },
            )
        except EmailTemplateNotFound:
            current_app.logger.warning("password_reset template not seeded")
        audit_record(
            "auth.password.reset_requested",
            status=AuditStatus.SUCCESS,
            actor_type=ActorType.USER,
            actor_id=user.id,
            actor_email=user.email,
            target_type="user",
            target_id=user.id,
            commit=True,
        )
    else:
        audit_record(
            "auth.password.reset_requested",
            status=AuditStatus.FAILURE,
            actor_type=ActorType.ANONYMOUS,
            actor_email=email,
            commit=True,
        )


def complete_password_reset_after_validation(*, row: PasswordResetToken, password: str) -> None:
    user = row.user
    user.set_password(password)
    row.mark_used()
    audit_record(
        "auth.password.changed",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=user.id,
        actor_email=user.email,
        target_type="user",
        target_id=user.id,
        context={"via": "reset_token"},
        commit=False,
    )
    db.session.commit()
