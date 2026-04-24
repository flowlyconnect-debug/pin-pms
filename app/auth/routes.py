from flask import Blueprint, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

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
            return redirect(url_for("auth.login"))

        error = "Invalid email or password."

    return render_template("login.html", error=error, is_authenticated=current_user.is_authenticated)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
