from __future__ import annotations

from datetime import date
from functools import wraps

from flask import abort, redirect, render_template, request, session, url_for

from app.owner_portal import owner_portal_bp
from app.owners.models import OwnerPayout, OwnerUser, PropertyOwnerAssignment
from app.owners.services import (
    authenticate_owner_user,
    monthly_owner_dashboard,
    payout_pdf_response,
)
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


def _current_owner_user() -> OwnerUser | None:
    user_id = session.get("owner_user_id")
    if user_id is None:
        return None
    return OwnerUser.query.filter_by(id=user_id, is_active=True).first()


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
    stats = monthly_owner_dashboard(owner_id=owner_user.owner_id, period_month=period)
    assignment_rows = (
        PropertyOwnerAssignment.query.join(
            Property, PropertyOwnerAssignment.property_id == Property.id
        )
        .filter(PropertyOwnerAssignment.owner_id == owner_user.owner_id)
        .order_by(Property.name.asc())
        .all()
    )
    properties = [Property.query.get(a.property_id) for a in assignment_rows]
    return render_template(
        "owner/dashboard.html", stats=stats, properties=[p for p in properties if p is not None]
    )


@owner_portal_bp.get("/properties/<int:property_id>/calendar")
@require_owner_login
def property_calendar(owner_user, property_id: int):
    if not _require_2fa():
        return redirect(url_for("owner_portal.two_factor"))
    assignment = PropertyOwnerAssignment.query.filter_by(
        owner_id=owner_user.owner_id, property_id=property_id
    ).first()
    if assignment is None:
        abort(404)
    rows = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .filter(Unit.property_id == property_id)
        .order_by(Reservation.start_date.asc(), Reservation.id.asc())
        .all()
    )
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
