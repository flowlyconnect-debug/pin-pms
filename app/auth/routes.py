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
import pyotp
import qrcode
import qrcode.image.svg

from app.auth.forms import ResetPasswordForm
from app.auth.models import PasswordResetToken
from app.auth.services import (
    audit_login_failed_2fa,
    audit_login_success,
    audit_logout,
    authenticate_user_for_login,
    complete_password_reset_after_validation,
    complete_superadmin_two_factor_setup,
    ensure_superadmin_totp_secret_initialized,
    regenerate_superadmin_backup_codes,
    request_password_reset,
    send_email_2fa_code,
    verify_superadmin_two_factor_code,
)
from app.extensions import limiter
from app.users.models import UserRole

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

        user, infra_error, _ = authenticate_user_for_login(email=email, password=password)
        if infra_error:
            return _login_error_response(infra_error)

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

        error = "Invalid email or password."

    return _login_error_response(error)


@auth_bp.route("/2fa/setup", methods=["GET", "POST"])
@login_required
def two_factor_setup():
    user = current_user

    if not user.is_superadmin:
        abort(403)

    error = None

    ensure_superadmin_totp_secret_initialized(user)

    if request.method == "POST":
        code = (request.form.get("code") or "").replace(" ", "").strip()
        ok, plaintext_codes = complete_superadmin_two_factor_setup(user=user, code=code)
        if ok and plaintext_codes is not None:
            session["2fa_backup_codes_once"] = plaintext_codes
            session["2fa_verified"] = False
            return redirect(url_for("auth.two_factor_backup_codes"))
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
        plaintext_codes = regenerate_superadmin_backup_codes(user=user)
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
        outcome = verify_superadmin_two_factor_code(user=user, code=code)
        if outcome in {"totp", "backup", "email"}:
            session["2fa_verified"] = True
            next_url = _safe_next_url(session.pop("post_login_next", None))
            return redirect(next_url or _default_post_login_url_for(user.role))

        audit_login_failed_2fa(user)
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
            request_password_reset(email=email)

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
            complete_password_reset_after_validation(row=row, password=form.password)
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
