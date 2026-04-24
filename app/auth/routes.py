import pyotp
import qrcode
import qrcode.image.svg
from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.extensions import db
from app.auth.services import authenticate_user

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""

        user = authenticate_user(email, password)
        if user:
            login_user(user)
            if user.is_superadmin:
                session["is_2fa_verified"] = False
                return redirect(url_for("auth.two_factor_setup"))

            session["is_2fa_verified"] = True
            return redirect(url_for("auth.login"))

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

    print("SECRET:", user.totp_secret)

    if request.method == "POST":
        code = request.form.get("code")
        code = (code or "").replace(" ", "").strip()
        print("SECRET:", user.totp_secret)
        print("INPUT:", code)
        print("EXPECTED:", pyotp.TOTP(user.totp_secret).now())
        totp = pyotp.TOTP(user.totp_secret)
        if totp.verify(code, valid_window=1):
            user.is_2fa_enabled = True
            db.session.commit()
            session["is_2fa_verified"] = True
            return redirect("/")
        flash("Invalid verification code")

    provisioning_uri = pyotp.TOTP(user.totp_secret).provisioning_uri(
        name=user.email,
        issuer_name="Pindora PMS",
    )
    totp_uri = qrcode.make(provisioning_uri, image_factory=qrcode.image.svg.SvgImage).to_string(
        encoding="unicode"
    )

    return render_template("two_factor_setup.html", qr_svg=totp_uri, secret=user.totp_secret, error=error)


@auth_bp.route("/logout")
@login_required
def logout():
    session.pop("is_2fa_verified", None)
    logout_user()
    return redirect(url_for("auth.login"))
