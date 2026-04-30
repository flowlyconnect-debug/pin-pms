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
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.auth.forms import ResetPasswordForm
from app.auth.models import PASSWORD_RESET_TTL, PasswordResetToken, TwoFactorEmailCode
from app.auth.services import (
    audit_login_failed,
    audit_login_success,
    audit_logout,
    authenticate_user,
    enable_2fa,
    send_email_2fa_code,
)
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


def _login_error_response(error_text):
    """Render the login page with an error, trying both template paths."""
    try:
        return render_template(
            "auth/login.html",
            error=error_text,
            is_authenticated=current_user.is_authenticated,
        )
    except Exception:
        return render_template(
            "login.html",
            error=error_text,
            is_authenticated=current_user.is_authenticated,
        )


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

        try:
            user = authenticate_user(email, password)
        except SQLAlchemyError as exc:
            log_payload = {
                "error_type": type(exc).__name__,
                "email": email,
                "path": request.path,
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
            # Never leak hostnames, usernames, or other connection-string
            # internals to the page — they may identify the production
            # database. Operators can find the full traceback in the logs.
            if current_app.debug:
                detail = (
                    f"Kirjautumispalvelu ei ole käytettävissä "
                    f"(DB-virhe: {type(exc).__name__}). Katso lokit."
                )
            else:
                detail = "Kirjautumispalvelu ei ole hetkellisesti käytettävissä. Yritä hetken kuluttua uudelleen."
            return _login_error_response(detail)
        except Exception as exc:  # noqa: BLE001
            current_app.logger.exception("Unexpected error during /login authentication.")
            if current_app.debug:
                detail = (
                    f"Odottamaton virhe ({type(exc).__name__}). Katso lokit."
                )
            else:
                detail = "Kirjautumispalvelu ei ole hetkellisesti käytettävissä. Yritä hetken kuluttua uudelleen."
            return _login_error_response(detail)

        if user:
            login_user(user)
            session.permanent = True
            audit_login_success(user)
            if user.is_superadmin:
                session["2fa_verified"] = False
                session["post_login_next"] = _safe_next_url(request.args.get("next"))
                return redirect(url_for("auth.two_factor_verify"))

            session["2fa_verified"] = True
            next_url = _safe_next_url(request.args.get("next"))
            return redirect(next_url or _default_post_login_url_for(user.role))

        audit_login_failed(email)
        error = "Invalid email or password."

    return _login_error_response(error)


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
            enable_2fa(user, backup_codes_issued=len(plaintext_codes))
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
        flash("Virheellinen vahvistuskoodi.")

    provisioning_uri = pyotp.TOTP(user.totp_secret).provisioning_uri(
        name=user.email,
        issuer_name="Pin PMS",
    )
    totp_uri = qrcode.make(provisioning_uri, image_factory=qrcode.image.svg.SvgImage).to_string(
        encoding="unicode"
    )

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

        if TwoFactorEmailCode.consume_active_code(user_id=user.id, raw_code=code):
            session["2fa_verified"] = True
            audit_record(
                "2fa.email_code_used",
                status=AuditStatus.SUCCESS,
                organization_id=user.organization_id,
                target_type="user",
                target_id=user.id,
            )
            db.session.commit()
            next_url = _safe_next_url(session.pop("post_login_next", None))
            return redirect(next_url or _default_post_login_url_for(user.role))

        audit_record(
            "auth.2fa.failed",
            status=AuditStatus.FAILURE,
            target_type="user",
            target_id=user.id,
            commit=True,
        )
        flash("Virheellinen vahvistuskoodi.")

    return render_template("two_factor_verify.html")


@auth_bp.route("/2fa/email-code", methods=["GET", "POST"])
@login_required
def two_factor_email_code():
    user = current_user

    if not user.is_superadmin:
        abort(403)
    if not user.is_2fa_enabled:
        return redirect(url_for("auth.two_factor_setup"))

    if request.method == "POST":
        sent = send_email_2fa_code(user)
        if sent:
            flash("2FA-koodi lähetetty sähköpostiisi.")
            return redirect(url_for("auth.two_factor_verify"))
        flash("Sähköpostikoodin lähetys ei onnistunut juuri nyt. Yritä uudelleen.")

    return render_template("two_factor_email_code.html")


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

        flash("Jos osoitteelle löytyy käyttäjätili, palautuslinkki on lähetetty sähköpostiin.")
        return redirect(url_for("auth.login"))

    return render_template("forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    row = PasswordResetToken.find_active_by_raw(token)
    if row is None:
        return render_template("reset_password.html", error="invalid_token")

    error = None

    if request.method == "POST":
        form = ResetPasswordForm.from_request(request)
        ok, error = form.validate()
        if ok:
            user = row.user
            user.set_password(form.password)
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
            flash("Salasana päivitetty. Voit nyt kirjautua sisään.")
            return redirect(url_for("auth.login"))

    return render_template("reset_password.html", error=error)


@auth_bp.route("/logout")
@login_required
def logout():
    audit_logout(current_user)
    session.pop("2fa_verified", None)
    logout_user()
    return redirect(url_for("auth.login"))
