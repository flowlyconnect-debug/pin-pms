from __future__ import annotations

from datetime import date
from functools import wraps

from flask import abort, redirect, render_template, request, session, url_for

from app.owner_portal import owner_portal_bp
from app.owner_portal import services as owner_portal_service
from app.owners.models import OwnerPayout, OwnerUser
from app.owners.services import authenticate_owner_user, payout_pdf_response


def _current_owner_user() -> OwnerUser | None:
    return owner_portal_service.owner_user_from_session(user_id=session.get("owner_user_id"))


def require_owner_login(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        user = _current_owner_user()
        if user is None:
            return redirect(url_for("owner_portal.login"))
        return view_func(user, *args, **kwargs)

    return wrapped


@owner_portal_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = authenticate_owner_user(
            email=(request.form.get("email") or "").strip(),
            password=request.form.get("password") or "",
        )
        if user is None:
            error = "Invalid email or password."
        else:
            session["owner_user_id"] = user.id
            return redirect(url_for("owner_portal.two_factor"))
    return render_template("owner/login.html", error=error)


@owner_portal_bp.route("/2fa", methods=["GET", "POST"])
@require_owner_login
def two_factor(_owner_user):
    if request.method == "POST":
        session["owner_2fa_ok"] = True
        return redirect(url_for("owner_portal.dashboard"))
    return render_template("owner/two_factor.html")


@owner_portal_bp.get("/logout")
def logout():
    session.pop("owner_user_id", None)
    session.pop("owner_2fa_ok", None)
    return redirect(url_for("owner_portal.login"))


def _require_2fa():
    return bool(session.get("owner_2fa_ok"))


@owner_portal_bp.get("/dashboard")
@require_owner_login
def dashboard(owner_user):
    if not _require_2fa():
        return redirect(url_for("owner_portal.two_factor"))
    today = date.today()
    period = f"{today.year:04d}-{today.month:02d}"
    bundle = owner_portal_service.owner_dashboard_page(owner_user=owner_user, period=period)
    return render_template(
        "owner/dashboard.html",
        stats=bundle["stats"],
        properties=bundle["properties"],
    )


@owner_portal_bp.get("/properties/<int:property_id>/calendar")
@require_owner_login
def property_calendar(owner_user, property_id: int):
    if not _require_2fa():
        return redirect(url_for("owner_portal.two_factor"))
    try:
        rows = owner_portal_service.list_owner_property_reservations(
            owner_id=owner_user.owner_id,
            property_id=property_id,
        )
    except ValueError:
        abort(404)
    return render_template("owner/property_calendar.html", rows=rows, property_id=property_id)


@owner_portal_bp.get("/payouts")
@require_owner_login
def payouts(owner_user):
    if not _require_2fa():
        return redirect(url_for("owner_portal.two_factor"))
    rows = (
        OwnerPayout.query.filter_by(owner_id=owner_user.owner_id)
        .order_by(OwnerPayout.period_month.desc(), OwnerPayout.id.desc())
        .all()
    )
    return render_template("owner/payouts.html", rows=rows)


@owner_portal_bp.get("/payouts/<int:payout_id>/pdf")
@require_owner_login
def payout_pdf(owner_user, payout_id: int):
    if not _require_2fa():
        return redirect(url_for("owner_portal.two_factor"))
    response = payout_pdf_response(payout_id=payout_id, owner_id=owner_user.owner_id)
    if response is None:
        abort(404)
    return response


@owner_portal_bp.get("/profile")
@require_owner_login
def profile(owner_user):
    if not _require_2fa():
        return redirect(url_for("owner_portal.two_factor"))
    return render_template("owner/profile.html", row=owner_user)
