from functools import wraps
from urllib.parse import urlparse

import pyotp
import qrcode
import qrcode.image.svg
from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user, logout_user

from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.auth.models import PASSWORD_RESET_TTL, PasswordResetToken
from app.auth.services import authenticate_user
from app.email.models import TemplateKey
from app.email.services import EmailTemplateNotFound, send_template
from app.extensions import db, limiter
from app.users.models import User, UserRole

auth_bp = Blueprint("auth", __name__)


def _login_rate_limit():
    return current_app.config["LOGIN_RATE_LIMIT"]


def _safe_next_url(target):
    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    if not target.startswith("/"):
        return None
    return target


def _default_post_login_url_for(role):
    if role in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        return url_for("admin.admin_home")
    return url_for("core.index")


def require_superadmin_2fa(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if not current_user.is_superadmin:
            abort(403)
        if not current_user.is_2fa_enabled:
            return redirect(url_for("auth.two_factor_setup"))
        if not session.get("2fa_verified"):
            return redirect(url_for("auth.two_factor_verify"))
        return view_func(*args, **kwargs)

    return wrapper


@auth_bp.route("/login", methods=["GET", "POST"])
@limiter.limit(
    _login_rate_limit,
    methods=["POST"],
    error_message="Too many login attempts. Please wait and try again.",
)
def login():
    error = None

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = authenticate_user(email, password)
        if user:
            login_user(user)
            audit_record(
                "auth.login.success",
                status=AuditStatus.SUCCESS,
                actor_type=ActorType.USER,
                actor_id=user.id,
                actor_email=user.email,
                organization_id=user.organization_id,
                target_type="user",
                target_id=user.id,
                commit=True,
            )
            if user.is_superadmin:
                session["2fa_verified"] = False
                session["post_login_next"] = _safe_next_url(request.args.get("next"))
                return redirect(url_for("auth.two_factor_verify"))

            session["2fa_verified"] = True
            next_url = _safe_next_url(request.args.get("next"))
            return redirect(next_url or _default_post_login_url_for(user.role))

        audit_record(
            "auth.login.failure",
            status=AuditStatus.FAILURE,
            actor_type=ActorType.ANONYMOUS,
            actor_email=email or None,
            commit=True,
        )
        error = "Invalid email or password."

    return render_template(
        "login.html",
        error=error,
        is_authenticated=current_user.is_authenticated,
    )


@auth_bp.route("/2fa/setup", methods=["GET", "POST"])
@login_required
def two_factor_setup():
    user = current_user

    if not user.is_superadmin:
        abort(403)

    error = None

    if not user.totp_secret:
        user.totp_secret = pyotp.random_base32()
        db.session.commit()

    if request.method == "POST":
        code = (request.form.get("code") or "").replace(" ", "").strip()
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code, valid_window=1):
            user.is_2fa_enabled = True
            plaintext_codes = user.generate_backup_codes()
            session["2fa_backup_codes_once"] = plaintext_codes
            audit_record(
                "auth.2fa.enabled",
                status=AuditStatus.SUCCESS,
                target_type="user",
                target_id=user.id,
                context={"backup_codes_issued": len(plaintext_codes)},
            )
            db.session.commit()
            session["2fa_verified"] = False
            return redirect(url_for("auth.two_factor_backup_codes"))
        audit_record(
            "auth.2fa.setup_failed",
            status=AuditStatus.FAILURE,
            target_type="user",
            target_id=user.id,
            commit=True,
        )
        flash("Invalid verification code")

    provisioning_uri = pyotp.TOTP(user.totp_secret).provisioning_uri(
        name=user.email,
        issuer_name="Pindora PMS",
    )
    totp_uri = qrcode.make(
        provisioning_uri, image_factory=qrcode.image.svg.SvgImage
    ).to_string(encoding="unicode")

    return render_template(
        "two_factor_setup.html",
        qr_svg=totp_uri,
        secret=user.totp_secret,
        error=error,
    )


@auth_bp.route("/2fa/backup-codes", methods=["GET", "POST"])
@login_required
def two_factor_backup_codes():
    user = current_user
    if not user.is_superadmin:
        abort(403)

    if request.method == "POST":
        plaintext_codes = user.generate_backup_codes()
        audit_record(
            "auth.2fa.backup_codes_regenerated",
            status=AuditStatus.SUCCESS,
            target_type="user",
            target_id=user.id,
            context={"count": len(plaintext_codes)},
        )
        db.session.commit()
        session["2fa_backup_codes_once"] = plaintext_codes
        return redirect(url_for("auth.two_factor_backup_codes"))

    plaintext_codes = session.pop("2fa_backup_codes_once", None)
    return render_template(
        "two_factor_backup_codes.html",
        plaintext_codes=plaintext_codes,
        codes_remaining=user.backup_codes_remaining,
    )


@auth_bp.route("/2fa/verify", methods=["GET", "POST"])
@login_required
def two_factor_verify():
    user = current_user

    if not user.is_superadmin:
        abort(403)

    if not user.is_2fa_enabled:
        return redirect(url_for("auth.two_factor_setup"))

    if not user.totp_secret:
        return redirect(url_for("auth.two_factor_setup"))

    if request.method == "POST":
        code = (request.form.get("code") or "").replace(" ", "").strip()

        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code, valid_window=1):
            session["2fa_verified"] = True
            audit_record(
                "auth.2fa.verified",
                status=AuditStatus.SUCCESS,
                target_type="user",
                target_id=user.id,
                commit=True,
            )
            next_url = _safe_next_url(session.pop("post_login_next", None))
            return redirect(next_url or _default_post_login_url_for(user.role))

        if user.consume_backup_code(code):
            session["2fa_verified"] = True
            audit_record(
                "auth.2fa.backup_code_used",
                status=AuditStatus.SUCCESS,
                target_type="user",
                target_id=user.id,
                context={"codes_remaining": user.backup_codes_remaining},
                commit=True,
            )
            next_url = _safe_next_url(session.pop("post_login_next", None))
            return redirect(next_url or _default_post_login_url_for(user.role))

        audit_record(
            "auth.2fa.failed",
            status=AuditStatus.FAILURE,
            target_type="user",
            target_id=user.id,
            commit=True,
        )
        flash("Invalid verification code")

    return render_template("two_factor_verify.html")


@auth_bp.route("/superadmin/test")
@require_superadmin_2fa
def superadmin_test():
    return redirect(_default_post_login_url_for(current_user.role))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit(
    _login_rate_limit,
    methods=["POST"],
    error_message="Too many password-reset attempts. Please wait and try again.",
)
def forgot_password():
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        if email:
            user = User.query.filter_by(email=email).first()
            if user is not None and user.is_active:
                token_row, raw_token = PasswordResetToken.issue(user_id=user.id)
                db.session.add(token_row)
                db.session.commit()

                reset_url = url_for(
                    "auth.reset_password",
                    token=raw_token,
                    _external=True,
                )
                try:
                    send_template(
                        TemplateKey.PASSWORD_RESET,
                        to=user.email,
                        context={
                            "user_email": user.email,
                            "reset_url": reset_url,
                            "expires_minutes": int(
                                PASSWORD_RESET_TTL.total_seconds() // 60
                            ),
                        },
                    )
                except EmailTemplateNotFound:
                    current_app.logger.error(
                        "Password reset email skipped: template %r is not in the database "
                        "(user_id=%s). Token was still created.",
                        TemplateKey.PASSWORD_RESET,
                        user.id,
                    )
                except Exception:  # noqa: BLE001 — never leak 500 on forgot-password
                    current_app.logger.exception(
                        "Password reset email failed (user_id=%s). Token was still created.",
                        user.id,
                    )
                else:
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

        flash(
            "If an account exists for that address, a reset link has been sent."
        )
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    row = PasswordResetToken.find_active_by_raw(token)
    if row is None:
        return render_template("reset_password.html", error="invalid_token")

    error = None

    if request.method == "POST":
        new_password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""

        if len(new_password) < 12:
            error = "Password must be at least 12 characters long."
        elif new_password != confirm:
            error = "Passwords do not match."
        else:
            user = row.user
            user.set_password(new_password)
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
            flash("Password updated. You can now sign in.")
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html", error=error)


@auth_bp.route("/logout")
@login_required
def logout():
    audit_record(
        "auth.logout",
        status=AuditStatus.SUCCESS,
        commit=True,
    )
    session.pop("2fa_verified", None)
    logout_user()
    return redirect(url_for("auth.login"))
