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
from app.extensions import db, limiter
from app.auth.services import authenticate_user

auth_bp = Blueprint("auth", __name__)


def _login_rate_limit() -> str:
    """Return the configured login rate limit (env-driven, spec section 18)."""

    return current_app.config["LOGIN_RATE_LIMIT"]


def _safe_next_url(target: str | None) -> str | None:
    """Return ``target`` only if it is a safe, same-origin relative path.

    Prevents open-redirect issues by rejecting absolute URLs or protocol-relative
    paths that could send the user to an external host after login.
    """

    if not target:
        return None
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc:
        return None
    if not target.startswith("/"):
        return None
    return target


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
                return redirect(url_for("auth.two_factor_verify"))

            session["2fa_verified"] = True
            next_url = _safe_next_url(request.args.get("next"))
            return redirect(next_url or url_for("core.index"))

        # Record failed login with the attempted email so admins can spot
        # enumeration / brute-force attempts. We do *not* log the password.
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
        code = request.form.get("code")
        code = (code or "").replace(" ", "").strip()
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code, valid_window=1):
            user.is_2fa_enabled = True
            audit_record(
                "auth.2fa.enabled",
                status=AuditStatus.SUCCESS,
                target_type="user",
                target_id=user.id,
            )
            db.session.commit()
            session["2fa_verified"] = False
            return redirect(url_for("auth.two_factor_verify"))
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
    totp_uri = qrcode.make(provisioning_uri, image_factory=qrcode.image.svg.SvgImage).to_string(
        encoding="unicode"
    )

    return render_template("two_factor_setup.html", qr_svg=totp_uri, secret=user.totp_secret, error=error)


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
        code = request.form.get("code")
        code = (code or "").replace(" ", "").strip()

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
            return redirect(url_for("auth.superadmin_test"))

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
    return "OK superadmin access", 200


@auth_bp.route("/logout")
@login_required
def logout():
    # Resolve actor identity *before* ``logout_user`` clears the session so
    # the audit row still reflects who logged out.
    audit_record(
        "auth.logout",
        status=AuditStatus.SUCCESS,
        commit=True,
    )
    session.pop("2fa_verified", None)
    logout_user()
    return redirect(url_for("auth.login"))
