"""Admin-only views — audit log browser and email-template editor.

All routes in this blueprint require an authenticated superadmin whose TOTP
2FA session is verified. Reuses the decorator declared in :mod:`app.auth.routes`
so the 2FA gate stays in a single place.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import wraps

from flask import (
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user

from app.admin import admin_bp
from app.admin import services as admin_service
from app.admin.forms import (
    ApiKeyForm,
    EmailTemplateForm,
    EmailTemplateTestSendForm,
    OrganizationForm,
    SettingForm,
    UserCreateForm,
    UserEditForm,
)
from app.api.models import ApiKey, ApiKeyUsage
from app.api.schemas import json_error, json_ok
from app.audit import record as audit_record
from app.audit.models import ActorType, AuditLog, AuditStatus
from app.auth.models import TwoFactorEmailCode
from app.auth.routes import require_superadmin_2fa
from app.billing import services as billing_service
from app.email.models import EmailTemplate
from app.email.services import EmailServiceError
from app.extensions import db
from app.guests import services as guest_service
from app.integrations.ical.models import ImportedCalendarFeed
from app.integrations.ical.service import IcalService, IcalServiceError
from app.maintenance import services as maintenance_service
from app.organizations.models import Organization
from app.owners import services as owners_service
from app.owners.models import PropertyOwner
from app.properties import services as property_service
from app.properties.models import Property, Unit
from app.reports import services as report_service
from app.reservations import services as reservation_service
from app.settings import services as settings_service
from app.settings.models import SettingType
from app.status.models import StatusComponent, StatusIncident
from app.users.models import User, UserRole

PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 200


def _is_admin_or_superadmin() -> bool:
    return current_user.role in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}


def require_admin_pms_access(view_func):
    @wraps(view_func)
    @login_required
    def wrapped(*args, **kwargs):
        if not _is_admin_or_superadmin():
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped


def check_impersonation_blocked(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if session.get("impersonator_user_id"):
            abort(403)
        return view_func(*args, **kwargs)

    return wrapped


def _pms_org_id() -> int:
    # TODO: If a safe, explicit superadmin cross-tenant override is introduced
    # in the future, centralize it here. For now we keep strict tenant scope.
    return current_user.organization_id


def _pms_pagination() -> tuple[int, int]:
    try:
        page = max(int(request.args.get("page", "1")), 1)
    except ValueError:
        page = 1
    try:
        per_page = int(request.args.get("per_page", "25"))
    except ValueError:
        per_page = 25
    per_page = max(1, min(per_page, 100))
    return page, per_page


@admin_bp.get("")
@admin_bp.get("/")
@admin_bp.get("/dashboard")
@require_admin_pms_access
def admin_home():
    selected_range = admin_service.normalize_dashboard_range(request.args.get("range"))
    summary = admin_service.get_dashboard_stats(
        organization_id=_pms_org_id(),
        viewer_is_superadmin=bool(current_user.is_superadmin),
        range_key=selected_range,
    )
    return render_template("admin/dashboard.html", summary=summary)


def _parse_optional_calendar_filter_int(name: str) -> int | None:
    raw = request.args.get(name)
    if raw is None or not str(raw).strip():
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        abort(400)


def _parse_calendar_event_types() -> set[str]:
    raw = (request.args.get("event_types") or request.args.get("event_type") or "").strip()
    if not raw:
        return {"reservations"}
    values = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return values or {"reservations"}


@admin_bp.get("/calendar")
@require_admin_pms_access
def calendar_page():
    properties, units = _reservation_edit_form_context(organization_id=_pms_org_id())
    return render_template(
        "admin/calendar.html",
        properties=properties,
        units=units,
    )


@admin_bp.get("/calendar/events")
@require_admin_pms_access
def calendar_events():
    try:
        start_d = reservation_service.parse_calendar_iso_bound(request.args.get("start"))
        end_d = reservation_service.parse_calendar_iso_bound(request.args.get("end"))
    except ValueError:
        abort(400)
    property_id = _parse_optional_calendar_filter_int("property_id")
    unit_id = _parse_optional_calendar_filter_int("unit_id")
    event_types = _parse_calendar_event_types()
    try:
        events = reservation_service.get_calendar_events(
            organization_id=_pms_org_id(),
            start_date=start_d,
            end_date=end_d,
            property_id=property_id,
            unit_id=unit_id,
            include_event_types=event_types,
        )
    except reservation_service.ReservationServiceError as exc:
        return json_error(exc.code, exc.message, status=exc.status)
    return jsonify(events)


def _reservation_form_choices(*, organization_id: int):
    units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .order_by(Property.id.asc(), Unit.id.asc())
        .all()
    )
    guest_rows, _ = guest_service.list_guests(
        organization_id=organization_id,
        page=1,
        per_page=500,
    )
    return units, guest_rows


def _reservation_edit_return_target(raw: str | None) -> str:
    """Where to redirect after a successful reservation edit (allowlist)."""

    value = (raw or "").strip().lower()
    if value in {"calendar", "detail", "list"}:
        return value
    return "calendar"


def _reservation_edit_form_context(*, organization_id: int) -> tuple[list[Property], list[Unit]]:
    properties = (
        Property.query.filter_by(organization_id=organization_id)
        .order_by(Property.name.asc(), Property.id.asc())
        .all()
    )
    units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .order_by(Property.name.asc(), Unit.name.asc(), Unit.id.asc())
        .all()
    )
    return properties, units


@admin_bp.get("/guests")
@require_admin_pms_access
def guests_list():
    page, per_page = _pms_pagination()
    search = (request.args.get("search") or "").strip() or None
    rows, total = guest_service.list_guests(
        organization_id=_pms_org_id(),
        search=search,
        page=page,
        per_page=per_page,
    )
    return render_template(
        "admin/guests/list.html",
        rows=rows,
        total=total,
        page=page,
        per_page=per_page,
        search=search or "",
    )


@admin_bp.route("/guests/new", methods=["GET", "POST"])
@require_admin_pms_access
def guests_new():
    form = {
        "first_name": "",
        "last_name": "",
        "email": "",
        "phone": "",
        "notes": "",
        "preferences": "",
    }
    error: str | None = None
    if request.method == "POST":
        for key in form:
            form[key] = (request.form.get(key) or "").strip()
        try:
            row = guest_service.create_guest(_pms_org_id(), form, current_user)
        except guest_service.GuestServiceError as err:
            error = err.message
        else:
            flash("Guest created.")
            return redirect(url_for("admin.guests_detail", guest_id=row["id"]))
    return render_template("admin/guests/new.html", form=form, error=error)


@admin_bp.get("/guests/<int:guest_id>")
@require_admin_pms_access
def guests_detail(guest_id: int):
    try:
        row = guest_service.get_guest(guest_id, _pms_org_id())
        reservations = guest_service.get_guest_reservations(guest_id, _pms_org_id())
    except guest_service.GuestServiceError:
        abort(404)
    return render_template("admin/guests/detail.html", row=row, reservations=reservations)


@admin_bp.get("/api/guests/search")
@require_admin_pms_access
def api_guests_search():
    """JSON guest lookup for reservation forms (tenant-scoped)."""

    q = (request.args.get("q") or "").strip() or None
    rows, _ = guest_service.list_guests(
        organization_id=_pms_org_id(),
        search=q,
        page=1,
        per_page=20,
    )
    return jsonify(
        [
            {
                "id": r["id"],
                "full_name": r["full_name"],
                "email": r["email"] or "",
            }
            for r in rows
        ]
    )


@admin_bp.route("/guests/<int:guest_id>/edit", methods=["GET", "POST"])
@require_admin_pms_access
def guests_edit(guest_id: int):
    try:
        row = guest_service.get_guest(guest_id, _pms_org_id())
    except guest_service.GuestServiceError:
        abort(404)
    form = {
        "first_name": row["first_name"],
        "last_name": row["last_name"],
        "email": row["email"] or "",
        "phone": row["phone"] or "",
        "notes": row["notes"] or "",
        "preferences": row["preferences"] or "",
    }
    error: str | None = None
    if request.method == "POST":
        for key in form:
            form[key] = (request.form.get(key) or "").strip()
        try:
            row = guest_service.update_guest(guest_id, _pms_org_id(), form, current_user)
        except guest_service.GuestServiceError as err:
            if err.status == 404:
                abort(404)
            error = err.message
        else:
            flash("Guest updated.")
            return redirect(url_for("admin.guests_detail", guest_id=row["id"]))
    return render_template("admin/guests/edit.html", row=row, form=form, error=error)


@admin_bp.get("/properties")
@require_admin_pms_access
def properties_list():
    page, per_page = _pms_pagination()
    rows, total = property_service.list_properties_paginated(
        organization_id=_pms_org_id(),
        page=page,
        per_page=per_page,
    )
    return render_template(
        "admin/properties/list.html",
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
    )


@admin_bp.route("/properties/new", methods=["GET", "POST"])
@require_admin_pms_access
def properties_new():
    form = {"name": "", "address": ""}
    error: str | None = None

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["address"] = (request.form.get("address") or "").strip()
        try:
            row = property_service.create_property(
                organization_id=_pms_org_id(),
                name=form["name"],
                address=form["address"],
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Property created.")
            return redirect(url_for("admin.properties_detail", property_id=row["id"]))

    return render_template("admin/properties/new.html", form=form, error=error)


@admin_bp.get("/properties/<int:property_id>")
@require_admin_pms_access
def properties_detail(property_id: int):
    try:
        row = property_service.get_property(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError:
        abort(404)
    return render_template("admin/properties/detail.html", row=row)


@admin_bp.route("/properties/<int:property_id>/edit", methods=["GET", "POST"])
@require_admin_pms_access
def properties_edit(property_id: int):
    try:
        row = property_service.get_property(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError:
        abort(404)

    form = {
        "name": row["name"],
        "address": row["address"] or "",
    }
    error: str | None = None

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["address"] = (request.form.get("address") or "").strip()
        try:
            row = property_service.update_property(
                organization_id=_pms_org_id(),
                property_id=property_id,
                name=form["name"],
                address=form["address"],
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Property updated.")
            return redirect(url_for("admin.properties_detail", property_id=row["id"]))

    return render_template("admin/properties/edit.html", row=row, form=form, error=error)


@admin_bp.get("/properties/<int:property_id>/units")
@require_admin_pms_access
def units_list(property_id: int):
    try:
        property_row = property_service.get_property(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
        rows = property_service.list_units(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError:
        abort(404)
    return render_template("admin/units/list.html", property_row=property_row, rows=rows)


@admin_bp.route("/properties/<int:property_id>/units/new", methods=["GET", "POST"])
@require_admin_pms_access
def units_new(property_id: int):
    try:
        property_row = property_service.get_property(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError:
        abort(404)

    form = {"name": "", "unit_type": ""}
    error: str | None = None

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["unit_type"] = (request.form.get("unit_type") or "").strip()
        try:
            _ = property_service.create_unit(
                organization_id=_pms_org_id(),
                property_id=property_id,
                name=form["name"],
                unit_type=form["unit_type"],
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Unit created.")
            return redirect(url_for("admin.units_list", property_id=property_id))

    return render_template(
        "admin/units/new.html",
        property_row=property_row,
        form=form,
        error=error,
    )


@admin_bp.route("/units/<int:unit_id>/edit", methods=["GET", "POST"])
@require_admin_pms_access
def units_edit(unit_id: int):
    try:
        row = property_service.get_unit(
            organization_id=_pms_org_id(),
            unit_id=unit_id,
        )
    except property_service.PropertyServiceError:
        abort(404)

    form = {
        "name": row["name"],
        "unit_type": row["unit_type"] or "",
    }
    error: str | None = None

    if request.method == "POST":
        form["name"] = (request.form.get("name") or "").strip()
        form["unit_type"] = (request.form.get("unit_type") or "").strip()
        try:
            row = property_service.update_unit(
                organization_id=_pms_org_id(),
                unit_id=unit_id,
                name=form["name"],
                unit_type=form["unit_type"],
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Unit updated.")
            return redirect(url_for("admin.units_list", property_id=row["property_id"]))

    return render_template("admin/units/edit.html", row=row, form=form, error=error)


@admin_bp.route("/units/<int:unit_id>/calendar-sync", methods=["GET", "POST"])
@require_admin_pms_access
def units_calendar_sync(unit_id: int):
    org_id = _pms_org_id()
    try:
        row = property_service.get_unit(organization_id=org_id, unit_id=unit_id)
    except property_service.PropertyServiceError:
        abort(404)

    service = IcalService()
    token = service.sign_unit_token(unit_id=unit_id)
    ics_url = url_for("api.export_unit_calendar_ics", unit_id=unit_id, token=token, _external=True)
    error: str | None = None

    if request.method == "POST":
        source_url = (request.form.get("source_url") or "").strip()
        name = (request.form.get("name") or "").strip() or None
        if not source_url.lower().startswith(("http://", "https://")):
            error = "Calendar URL must start with http:// or https://."
        else:
            try:
                service.create_feed(
                    organization_id=org_id,
                    unit_id=unit_id,
                    source_url=source_url,
                    name=name,
                )
            except IcalServiceError as err:
                error = err.message
            else:
                flash("Imported calendar source saved.")
                return redirect(url_for("admin.units_calendar_sync", unit_id=unit_id))

    feeds = service.list_unit_feeds(organization_id=org_id, unit_id=unit_id)
    return render_template(
        "admin/units/calendar_sync.html",
        row=row,
        ics_url=ics_url,
        feeds=feeds,
        error=error,
    )


@admin_bp.get("/calendar-sync/conflicts")
@require_admin_pms_access
def calendar_sync_conflicts():
    service = IcalService()
    rows = service.detect_conflicts(organization_id=_pms_org_id())
    return render_template("admin/calendar_sync_conflicts.html", rows=rows)


@admin_bp.post("/calendar-sync/feeds/<int:feed_id>/sync")
@require_admin_pms_access
def calendar_sync_feed_now(feed_id: int):
    row = ImportedCalendarFeed.query.get(feed_id)
    if row is None or row.organization_id != _pms_org_id():
        abort(404)
    IcalService().sync_all_feeds(organization_id=row.organization_id)
    flash("Calendar sync finished.")
    return redirect(url_for("admin.units_calendar_sync", unit_id=row.unit_id))


@admin_bp.get("/reservations")
@require_admin_pms_access
def reservations_list():
    page, per_page = _pms_pagination()
    rows, total = reservation_service.list_reservations_paginated(
        organization_id=_pms_org_id(),
        page=page,
        per_page=per_page,
    )
    return render_template(
        "admin/reservations/list.html",
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
    )


@admin_bp.route("/reservations/new", methods=["GET", "POST"])
@require_admin_pms_access
def reservations_new():
    units, _ = _reservation_form_choices(organization_id=_pms_org_id())
    form = {
        "unit_id": "",
        "guest_id": "",
        "guest_search": "",
        "guest_name": "",
        "start_date": "",
        "end_date": "",
        "amount": "",
        "currency": "EUR",
    }
    error: str | None = None

    if request.method == "POST":
        form["unit_id"] = (request.form.get("unit_id") or "").strip()
        form["guest_id"] = (request.form.get("guest_id") or "").strip()
        form["guest_search"] = (request.form.get("guest_search") or "").strip()
        form["guest_name"] = (request.form.get("guest_name") or "").strip()
        form["start_date"] = (request.form.get("start_date") or "").strip()
        form["end_date"] = (request.form.get("end_date") or "").strip()
        form["amount"] = (request.form.get("amount") or "").strip()
        form["currency"] = (request.form.get("currency") or "").strip().upper() or "EUR"

        if not form["unit_id"] or not form["start_date"] or not form["end_date"]:
            error = "Unit and dates are required."
        else:
            try:
                parsed_guest_id = int(form["guest_id"]) if form["guest_id"] else None
                row = reservation_service.create_reservation(
                    organization_id=_pms_org_id(),
                    unit_id=int(form["unit_id"]),
                    guest_id=parsed_guest_id,
                    guest_name=form["guest_name"] or None,
                    start_date_raw=form["start_date"],
                    end_date_raw=form["end_date"],
                    amount=form["amount"],
                    currency=form["currency"],
                    actor_user_id=current_user.id,
                )
            except (TypeError, ValueError):
                error = "Unit and guest must be valid numeric IDs."
            except reservation_service.ReservationServiceError as err:
                error = err.message
            else:
                flash("Reservation created.")
                return redirect(url_for("admin.reservations_detail", reservation_id=row["id"]))

    return render_template(
        "admin/reservations/new.html",
        units=units,
        form=form,
        error=error,
    )


@admin_bp.get("/reservations/<int:reservation_id>")
@require_admin_pms_access
def reservations_detail(reservation_id: int):
    try:
        row = reservation_service.get_reservation_detail(
            organization_id=_pms_org_id(),
            reservation_id=reservation_id,
        )
    except reservation_service.ReservationServiceError:
        abort(404)
    return render_template("admin/reservations/detail.html", row=row)


@admin_bp.patch("/reservations/<int:reservation_id>/move")
@require_admin_pms_access
def reservations_move(reservation_id: int):
    if not request.is_json:
        return json_error("invalid_request", "JSON body required.", status=400, data=None)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return json_error("invalid_request", "Invalid JSON body.", status=400, data=None)
    try:
        data = reservation_service.move_reservation(
            reservation_id=reservation_id,
            organization_id=_pms_org_id(),
            payload=body,
            actor_user_id=current_user.id,
            actor_role=current_user.role,
        )
    except reservation_service.ReservationServiceError as err:
        return json_error(err.code, err.message, status=err.status, data=None)
    return json_ok(
        {
            "id": data["id"],
            "start_date": data["start_date"],
            "end_date": data["end_date"],
            "unit_id": data["unit_id"],
        }
    )


@admin_bp.patch("/reservations/<int:reservation_id>/resize")
@require_admin_pms_access
def reservations_resize(reservation_id: int):
    if not request.is_json:
        return json_error("invalid_request", "JSON body required.", status=400, data=None)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return json_error("invalid_request", "Invalid JSON body.", status=400, data=None)
    try:
        data = reservation_service.resize_reservation(
            reservation_id=reservation_id,
            organization_id=_pms_org_id(),
            payload=body,
            actor_user_id=current_user.id,
            actor_role=current_user.role,
        )
    except reservation_service.ReservationServiceError as err:
        return json_error(err.code, err.message, status=err.status, data=None)
    return json_ok(
        {
            "id": data["id"],
            "start_date": data["start_date"],
            "end_date": data["end_date"],
            "unit_id": data["unit_id"],
        }
    )


@admin_bp.route("/reservations/<int:reservation_id>/edit", methods=["GET", "POST"])
@require_admin_pms_access
def reservations_edit(reservation_id: int):
    org_id = _pms_org_id()
    properties, units = _reservation_edit_form_context(organization_id=org_id)
    return_to = _reservation_edit_return_target(request.args.get("next"))

    if request.method == "POST":
        return_to = _reservation_edit_return_target(request.form.get("return_to"))

    try:
        row = reservation_service.get_reservation_for_edit(
            organization_id=org_id,
            reservation_id=reservation_id,
        )
    except reservation_service.ReservationServiceError:
        abort(404)

    form = {
        "guest_name": row["guest_name"],
        "guest_id": str(row["guest_id"] or ""),
        "guest_search": "",
        "property_id": str(row["property_id"] or ""),
        "unit_id": str(row["unit_id"]),
        "start_date": row["start_date"],
        "end_date": row["end_date"],
        "status": row["status"],
        "amount": row["amount"] or "",
        "currency": row["currency"] or "EUR",
        "return_to": return_to,
    }
    if form["guest_id"]:
        try:
            g = guest_service.get_guest(int(form["guest_id"]), org_id)
            form["guest_search"] = g["full_name"]
            if g.get("email"):
                form["guest_search"] += f" ({g['email']})"
        except (ValueError, guest_service.GuestServiceError):
            form["guest_search"] = form["guest_name"] or ""
    error: str | None = None

    if request.method == "POST":
        form["guest_name"] = (request.form.get("guest_name") or "").strip()
        form["guest_id"] = (request.form.get("guest_id") or "").strip()
        form["guest_search"] = (request.form.get("guest_search") or "").strip()
        form["property_id"] = (request.form.get("property_id") or "").strip()
        form["unit_id"] = (request.form.get("unit_id") or "").strip()
        form["start_date"] = (request.form.get("start_date") or "").strip()
        form["end_date"] = (request.form.get("end_date") or "").strip()
        form["status"] = (request.form.get("status") or "").strip()
        form["amount"] = (request.form.get("amount") or "").strip()
        form["currency"] = (request.form.get("currency") or "").strip().upper() or "EUR"
        form["return_to"] = return_to

        payload = {
            "guest_name": form["guest_name"],
            "guest_id": form["guest_id"],
            "property_id": form["property_id"],
            "unit_id": form["unit_id"],
            "start_date": form["start_date"],
            "end_date": form["end_date"],
            "status": form["status"],
            "amount": form["amount"],
            "currency": form["currency"],
        }
        try:
            _ = reservation_service.update_reservation(
                reservation_id=reservation_id,
                organization_id=org_id,
                data=payload,
                actor_user_id=current_user.id,
            )
        except reservation_service.ReservationServiceError as err:
            if err.status == 404:
                abort(404)
            error = err.message
        else:
            flash("Reservation updated.")
            if return_to == "calendar":
                return redirect(url_for("admin.calendar_page"))
            if return_to == "list":
                return redirect(url_for("admin.reservations_list"))
            return redirect(url_for("admin.reservations_detail", reservation_id=reservation_id))

    return render_template(
        "admin/reservations/edit.html",
        row=row,
        form=form,
        properties=properties,
        units=units,
        error=error,
    )


@admin_bp.post("/reservations/<int:reservation_id>/cancel")
@require_admin_pms_access
def reservations_cancel(reservation_id: int):
    if (request.form.get("confirm_cancel") or "").strip().lower() != "yes":
        flash("Please confirm cancellation.")
        return redirect(url_for("admin.reservations_detail", reservation_id=reservation_id))

    try:
        _ = reservation_service.cancel_reservation(
            organization_id=_pms_org_id(),
            reservation_id=reservation_id,
            actor_user_id=current_user.id,
        )
    except reservation_service.ReservationServiceError:
        abort(404)

    flash("Reservation cancelled.")
    return redirect(url_for("admin.reservations_detail", reservation_id=reservation_id))


@admin_bp.post("/reservations/<int:reservation_id>/mark-paid")
@require_admin_pms_access
def reservations_mark_paid(reservation_id: int):
    try:
        _ = reservation_service.mark_reservation_paid(
            reservation_id=reservation_id,
            organization_id=_pms_org_id(),
            actor_user=current_user,
        )
    except reservation_service.ReservationServiceError as err:
        if err.status == 404:
            abort(404)
        if err.status == 403:
            abort(403)
        flash(err.message)
        return redirect(url_for("admin.reservations_detail", reservation_id=reservation_id))
    flash("Reservation marked as paid.")
    return redirect(url_for("admin.reservations_detail", reservation_id=reservation_id))


@admin_bp.get("/reservations/<int:reservation_id>/invoice.pdf")
@require_admin_pms_access
def reservations_invoice_pdf(reservation_id: int):
    try:
        return reservation_service.generate_invoice(
            reservation_id=reservation_id,
            organization_id=_pms_org_id(),
            actor_user=current_user,
        )
    except reservation_service.ReservationServiceError as err:
        if err.status == 404:
            abort(404)
        if err.status == 403:
            abort(403)
        abort(400)


@admin_bp.get("/reports")
@require_admin_pms_access
def reports_index():
    return render_template("admin/reports/index.html")


@admin_bp.get("/reports/occupancy")
@require_admin_pms_access
def reports_occupancy():
    data = None
    error: str | None = None
    start_date_raw = (request.args.get("start_date") or "").strip()
    end_date_raw = (request.args.get("end_date") or "").strip()

    if start_date_raw or end_date_raw:
        if not start_date_raw or not end_date_raw:
            error = "Both start date and end date are required."
        else:
            from datetime import date

            try:
                start_date = date.fromisoformat(start_date_raw)
                end_date = date.fromisoformat(end_date_raw)
            except ValueError:
                error = "Dates must be valid ISO dates (YYYY-MM-DD)."
            else:
                if start_date >= end_date:
                    error = "Start date must be before end date."
                else:
                    data = report_service.occupancy_report(
                        organization_id=_pms_org_id(),
                        start_date=start_date,
                        end_date=end_date,
                    )

    return render_template(
        "admin/reports/occupancy.html",
        data=data,
        error=error,
        start_date=start_date_raw,
        end_date=end_date_raw,
    )


@admin_bp.get("/reports/reservations")
@require_admin_pms_access
def reports_reservations():
    data = report_service.reservation_report(organization_id=_pms_org_id())
    return render_template("admin/reports/reservations.html", data=data)


# --- Leases & invoices (billing) -------------------------------------------


@admin_bp.get("/leases")
@require_admin_pms_access
def leases_list():
    page, per_page = _pms_pagination()
    rows, total = billing_service.list_leases_paginated(
        organization_id=_pms_org_id(),
        page=page,
        per_page=per_page,
    )
    return render_template(
        "admin/leases/list.html",
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
    )


@admin_bp.route("/leases/new", methods=["GET", "POST"])
@require_admin_pms_access
def leases_new():
    org_id = _pms_org_id()
    units, guest_rows = _reservation_form_choices(organization_id=org_id)
    form = {
        "unit_id": "",
        "guest_id": "",
        "guest_search": "",
        "reservation_id": "",
        "start_date": "",
        "end_date": "",
        "rent_amount": "",
        "deposit_amount": "0",
        "billing_cycle": "monthly",
        "notes": "",
    }
    error: str | None = None

    if request.method == "POST":
        form["unit_id"] = (request.form.get("unit_id") or "").strip()
        form["guest_id"] = (request.form.get("guest_id") or "").strip()
        form["guest_search"] = (request.form.get("guest_search") or "").strip()
        form["reservation_id"] = (request.form.get("reservation_id") or "").strip()
        form["start_date"] = (request.form.get("start_date") or "").strip()
        form["end_date"] = (request.form.get("end_date") or "").strip()
        form["rent_amount"] = (request.form.get("rent_amount") or "").strip()
        form["deposit_amount"] = (request.form.get("deposit_amount") or "").strip()
        form["billing_cycle"] = (request.form.get("billing_cycle") or "").strip().lower()
        form["notes"] = (request.form.get("notes") or "").strip()

        if (
            not form["unit_id"]
            or not form["guest_id"]
            or not form["start_date"]
            or not form["rent_amount"]
        ):
            error = "Unit, guest, start date, and rent are required."
        else:
            try:
                res_id = int(form["reservation_id"]) if form["reservation_id"] else None
                row = billing_service.create_lease(
                    organization_id=org_id,
                    unit_id=int(form["unit_id"]),
                    guest_id=int(form["guest_id"]),
                    reservation_id=res_id,
                    start_date_raw=form["start_date"],
                    end_date_raw=form["end_date"] or None,
                    rent_amount_raw=form["rent_amount"],
                    deposit_amount_raw=form["deposit_amount"],
                    billing_cycle=form["billing_cycle"],
                    notes=form["notes"] or None,
                    actor_user_id=current_user.id,
                )
            except (TypeError, ValueError):
                error = "Unit, guest, and reservation must be valid numeric IDs."
            except billing_service.LeaseServiceError as err:
                error = err.message
            else:
                flash("Lease created.")
                return redirect(url_for("admin.leases_detail", lease_id=row["id"]))

    return render_template(
        "admin/leases/new.html",
        units=units,
        guest_rows=guest_rows,
        form=form,
        error=error,
    )


@admin_bp.get("/leases/<int:lease_id>")
@require_admin_pms_access
def leases_detail(lease_id: int):
    try:
        row = billing_service.get_lease_for_org(
            organization_id=_pms_org_id(),
            lease_id=lease_id,
        )
    except billing_service.LeaseServiceError:
        abort(404)
    return render_template("admin/leases/detail.html", row=row)


@admin_bp.route("/leases/<int:lease_id>/edit", methods=["GET", "POST"])
@require_admin_pms_access
def leases_edit(lease_id: int):
    org_id = _pms_org_id()
    units, guest_rows = _reservation_form_choices(organization_id=org_id)
    try:
        row = billing_service.get_lease_for_org(organization_id=org_id, lease_id=lease_id)
    except billing_service.LeaseServiceError:
        abort(404)

    form = {
        "unit_id": str(row["unit_id"]),
        "guest_id": str(row["guest_id"]),
        "guest_search": "",
        "reservation_id": str(row["reservation_id"] or ""),
        "start_date": row["start_date"],
        "end_date": row["end_date"] or "",
        "rent_amount": row["rent_amount"],
        "deposit_amount": row["deposit_amount"],
        "billing_cycle": row["billing_cycle"],
        "notes": row["notes"] or "",
    }
    if form["guest_id"]:
        try:
            g = guest_service.get_guest(int(form["guest_id"]), org_id)
            form["guest_search"] = g["full_name"]
            if g.get("email"):
                form["guest_search"] += f" ({g['email']})"
        except (ValueError, guest_service.GuestServiceError):
            form["guest_search"] = ""

    error: str | None = None
    if request.method == "POST":
        form["unit_id"] = (request.form.get("unit_id") or "").strip()
        form["guest_id"] = (request.form.get("guest_id") or "").strip()
        form["guest_search"] = (request.form.get("guest_search") or "").strip()
        form["reservation_id"] = (request.form.get("reservation_id") or "").strip()
        form["start_date"] = (request.form.get("start_date") or "").strip()
        form["end_date"] = (request.form.get("end_date") or "").strip()
        form["rent_amount"] = (request.form.get("rent_amount") or "").strip()
        form["deposit_amount"] = (request.form.get("deposit_amount") or "").strip()
        form["billing_cycle"] = (request.form.get("billing_cycle") or "").strip().lower()
        form["notes"] = (request.form.get("notes") or "").strip()

        try:
            row_now = billing_service.get_lease_for_org(organization_id=org_id, lease_id=lease_id)
        except billing_service.LeaseServiceError:
            abort(404)

        payload: dict = {}
        st = row_now["status"]
        if st == "draft":
            payload = {
                "unit_id": int(form["unit_id"]) if form["unit_id"] else None,
                "guest_id": int(form["guest_id"]) if form["guest_id"] else None,
                "reservation_id": int(form["reservation_id"]) if form["reservation_id"] else None,
                "start_date": form["start_date"],
                "end_date": form["end_date"] or None,
                "rent_amount": form["rent_amount"],
                "deposit_amount": form["deposit_amount"],
                "billing_cycle": form["billing_cycle"],
                "notes": form["notes"] or None,
            }
            if payload["unit_id"] is None or payload["guest_id"] is None:
                raise billing_service.LeaseServiceError(
                    code="validation_error",
                    message="Unit and guest are required.",
                    status=400,
                )
        elif st == "active":
            payload = {
                "end_date": form["end_date"] or None,
                "rent_amount": form["rent_amount"],
                "deposit_amount": form["deposit_amount"],
                "notes": form["notes"] or None,
            }
        else:
            payload = {"notes": form["notes"] or None}

        try:
            _ = billing_service.update_lease(
                organization_id=org_id,
                lease_id=lease_id,
                data=payload,
                actor_user_id=current_user.id,
            )
        except (TypeError, ValueError):
            error = "Unit, guest, and reservation must be valid numeric IDs."
        except billing_service.LeaseServiceError as err:
            if err.status == 404:
                abort(404)
            error = err.message
        else:
            flash("Lease updated.")
            return redirect(url_for("admin.leases_detail", lease_id=lease_id))

    return render_template(
        "admin/leases/edit.html",
        row=row,
        units=units,
        guest_rows=guest_rows,
        form=form,
        error=error,
    )


@admin_bp.post("/leases/<int:lease_id>/activate")
@require_admin_pms_access
def leases_activate(lease_id: int):
    try:
        _ = billing_service.activate_lease(
            organization_id=_pms_org_id(),
            lease_id=lease_id,
            actor_user_id=current_user.id,
        )
    except billing_service.LeaseServiceError as err:
        if err.status == 404:
            abort(404)
        flash(err.message)
        return redirect(url_for("admin.leases_detail", lease_id=lease_id))
    flash("Lease activated.")
    return redirect(url_for("admin.leases_detail", lease_id=lease_id))


@admin_bp.post("/leases/<int:lease_id>/end")
@require_admin_pms_access
def leases_end(lease_id: int):
    if (request.form.get("confirm_end") or "").strip().lower() != "yes":
        flash("Please confirm ending the lease.")
        return redirect(url_for("admin.leases_detail", lease_id=lease_id))
    end_raw = (request.form.get("end_date") or "").strip() or None
    try:
        _ = billing_service.end_lease(
            organization_id=_pms_org_id(),
            lease_id=lease_id,
            end_date_raw=end_raw,
            actor_user_id=current_user.id,
        )
    except billing_service.LeaseServiceError as err:
        if err.status == 404:
            abort(404)
        flash(err.message)
        return redirect(url_for("admin.leases_detail", lease_id=lease_id))
    flash("Lease ended.")
    return redirect(url_for("admin.leases_detail", lease_id=lease_id))


@admin_bp.post("/leases/<int:lease_id>/cancel")
@require_admin_pms_access
def leases_cancel(lease_id: int):
    if (request.form.get("confirm_cancel") or "").strip().lower() != "yes":
        flash("Please confirm cancellation.")
        return redirect(url_for("admin.leases_detail", lease_id=lease_id))
    try:
        _ = billing_service.cancel_lease(
            organization_id=_pms_org_id(),
            lease_id=lease_id,
            actor_user_id=current_user.id,
        )
    except billing_service.LeaseServiceError as err:
        if err.status == 404:
            abort(404)
        flash(err.message)
        return redirect(url_for("admin.leases_detail", lease_id=lease_id))
    flash("Lease cancelled.")
    return redirect(url_for("admin.leases_detail", lease_id=lease_id))


@admin_bp.get("/invoices")
@require_admin_pms_access
def invoices_list():
    page, per_page = _pms_pagination()
    rows, total = billing_service.list_invoices_paginated(
        organization_id=_pms_org_id(),
        page=page,
        per_page=per_page,
    )
    return render_template(
        "admin/invoices/list.html",
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
    )


@admin_bp.route("/invoices/new", methods=["GET", "POST"])
@require_admin_pms_access
def invoices_new():
    org_id = _pms_org_id()
    lease_rows = billing_service.list_leases_for_org(organization_id=org_id)
    form = {
        "lease_id": "",
        "amount": "",
        "currency": "EUR",
        "due_date": "",
        "description": "",
        "status": "open",
        "guest_id": "",
        "reservation_id": "",
    }
    error: str | None = None

    if request.method == "POST":
        form["lease_id"] = (request.form.get("lease_id") or "").strip()
        form["amount"] = (request.form.get("amount") or "").strip()
        form["currency"] = (request.form.get("currency") or "").strip().upper() or "EUR"
        form["due_date"] = (request.form.get("due_date") or "").strip()
        form["description"] = (request.form.get("description") or "").strip()
        form["status"] = (request.form.get("status") or "").strip().lower() or "open"
        form["guest_id"] = (request.form.get("guest_id") or "").strip()
        form["reservation_id"] = (request.form.get("reservation_id") or "").strip()

        if not form["due_date"]:
            error = "Due date is required."
        elif form["lease_id"]:
            try:
                row = billing_service.create_invoice_for_lease(
                    organization_id=org_id,
                    lease_id=int(form["lease_id"]),
                    amount_raw=form["amount"] or None,
                    due_date_raw=form["due_date"],
                    currency=form["currency"],
                    description=form["description"] or None,
                    status=form["status"],
                    actor_user_id=current_user.id,
                )
            except (TypeError, ValueError):
                error = "Lease id must be a valid number."
            except billing_service.InvoiceServiceError as err:
                error = err.message
            else:
                flash("Invoice created.")
                return redirect(url_for("admin.invoices_detail", invoice_id=row["id"]))
        else:
            if not form["amount"]:
                error = "Amount is required when no lease is selected."
            else:
                try:
                    res_id = int(form["reservation_id"]) if form["reservation_id"] else None
                    guest_id = int(form["guest_id"]) if form["guest_id"] else None
                    row = billing_service.create_invoice(
                        organization_id=org_id,
                        amount_raw=form["amount"],
                        due_date_raw=form["due_date"],
                        currency=form["currency"],
                        description=form["description"] or None,
                        lease_id=None,
                        reservation_id=res_id,
                        guest_id=guest_id,
                        status=form["status"],
                        metadata_json=None,
                        actor_user_id=current_user.id,
                    )
                except (TypeError, ValueError):
                    error = "Guest and reservation must be valid numeric IDs when provided."
                except billing_service.InvoiceServiceError as err:
                    error = err.message
                else:
                    flash("Invoice created.")
                    return redirect(url_for("admin.invoices_detail", invoice_id=row["id"]))

    return render_template(
        "admin/invoices/new.html",
        lease_rows=lease_rows,
        form=form,
        error=error,
    )


@admin_bp.get("/invoices/<int:invoice_id>")
@require_admin_pms_access
def invoices_detail(invoice_id: int):
    try:
        row = billing_service.get_invoice_for_org(
            organization_id=_pms_org_id(),
            invoice_id=invoice_id,
        )
    except billing_service.InvoiceServiceError:
        abort(404)
    return render_template("admin/invoices/detail.html", row=row)


@admin_bp.post("/invoices/<int:invoice_id>/mark-paid")
@require_admin_pms_access
def invoices_mark_paid(invoice_id: int):
    try:
        _ = billing_service.mark_invoice_paid(
            organization_id=_pms_org_id(),
            invoice_id=invoice_id,
            actor_user_id=current_user.id,
        )
    except billing_service.InvoiceServiceError as err:
        if err.status == 404:
            abort(404)
        flash(err.message)
        return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))
    flash("Invoice marked as paid.")
    return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))


@admin_bp.post("/invoices/<int:invoice_id>/cancel")
@require_admin_pms_access
def invoices_cancel(invoice_id: int):
    if (request.form.get("confirm_cancel") or "").strip().lower() != "yes":
        flash("Please confirm cancellation.")
        return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))
    try:
        _ = billing_service.cancel_invoice(
            organization_id=_pms_org_id(),
            invoice_id=invoice_id,
            actor_user_id=current_user.id,
        )
    except billing_service.InvoiceServiceError as err:
        if err.status == 404:
            abort(404)
        flash(err.message)
        return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))
    flash("Invoice cancelled.")
    return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))


@admin_bp.post("/invoices/mark-overdue")
@require_admin_pms_access
def invoices_mark_overdue():
    n = billing_service.mark_overdue_invoices(organization_id=_pms_org_id())
    flash(f"Marked {n} invoice(s) as overdue.")
    return redirect(url_for("admin.invoices_list"))


# --- Maintenance requests ---------------------------------------------------


def _org_users_for_assign(organization_id: int) -> list[User]:
    return (
        User.query.filter_by(organization_id=organization_id, is_active=True)
        .order_by(User.email.asc())
        .all()
    )


@admin_bp.get("/maintenance-requests")
@require_admin_pms_access
def maintenance_requests_list():
    page, per_page = _pms_pagination()
    status = (request.args.get("status") or "").strip() or None
    priority = (request.args.get("priority") or "").strip() or None
    try:
        prop_raw = request.args.get("property_id")
        unit_raw = request.args.get("unit_id")
        sel_property_id = int(prop_raw) if prop_raw not in (None, "") else None
        sel_unit_id = int(unit_raw) if unit_raw not in (None, "") else None
    except ValueError:
        abort(400)
    rows, total = maintenance_service.list_maintenance_requests_paginated(
        organization_id=_pms_org_id(),
        page=page,
        per_page=per_page,
        status=status,
        priority=priority,
        property_id=sel_property_id,
        unit_id=sel_unit_id,
    )
    org_id = _pms_org_id()
    properties = (
        Property.query.filter_by(organization_id=org_id)
        .order_by(Property.name.asc(), Property.id.asc())
        .all()
    )
    units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == org_id)
        .order_by(Property.name.asc(), Unit.name.asc(), Unit.id.asc())
        .all()
    )
    return render_template(
        "admin/maintenance/list.html",
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
        status_filter=status or "",
        priority_filter=priority or "",
        sel_property_id=sel_property_id,
        sel_unit_id=sel_unit_id,
        properties=properties,
        units=units,
    )


@admin_bp.route("/maintenance-requests/new", methods=["GET", "POST"])
@require_admin_pms_access
def maintenance_requests_new():
    org_id = _pms_org_id()
    properties, units = _reservation_edit_form_context(organization_id=org_id)
    assignees = _org_users_for_assign(org_id)
    form = {
        "property_id": "",
        "unit_id": "",
        "guest_id": "",
        "reservation_id": "",
        "title": "",
        "description": "",
        "priority": "normal",
        "status": "new",
        "due_date": "",
        "assigned_to_id": "",
    }
    error: str | None = None
    if request.method == "POST":
        for key in form:
            form[key] = (request.form.get(key) or "").strip()
        if not form["property_id"] or not form["title"]:
            error = "Property and title are required."
        else:
            try:
                row = maintenance_service.create_maintenance_request(
                    organization_id=org_id,
                    property_id=int(form["property_id"]),
                    unit_id=int(form["unit_id"]) if form["unit_id"] else None,
                    guest_id=int(form["guest_id"]) if form["guest_id"] else None,
                    reservation_id=int(form["reservation_id"]) if form["reservation_id"] else None,
                    title=form["title"],
                    description=form["description"] or None,
                    priority=form["priority"] or "normal",
                    status=form["status"] or "new",
                    due_date_raw=form["due_date"] or None,
                    assigned_to_id=int(form["assigned_to_id"]) if form["assigned_to_id"] else None,
                    actor_user_id=current_user.id,
                )
            except (TypeError, ValueError):
                error = "IDs must be valid numbers."
            except maintenance_service.MaintenanceServiceError as err:
                error = err.message
            else:
                flash("Maintenance request created.")
                return redirect(url_for("admin.maintenance_requests_detail", request_id=row["id"]))

    return render_template(
        "admin/maintenance/new.html",
        properties=properties,
        units=units,
        assignees=assignees,
        form=form,
        error=error,
    )


@admin_bp.get("/maintenance-requests/<int:request_id>")
@require_admin_pms_access
def maintenance_requests_detail(request_id: int):
    org_id = _pms_org_id()
    try:
        row = maintenance_service.get_maintenance_request(
            organization_id=org_id,
            request_id=request_id,
        )
    except maintenance_service.MaintenanceServiceError:
        abort(404)
    assignees = _org_users_for_assign(org_id)
    return render_template(
        "admin/maintenance/detail.html",
        row=row,
        assignees=assignees,
    )


@admin_bp.route("/maintenance-requests/<int:request_id>/edit", methods=["GET", "POST"])
@require_admin_pms_access
def maintenance_requests_edit(request_id: int):
    org_id = _pms_org_id()
    properties, units = _reservation_edit_form_context(organization_id=org_id)
    assignees = _org_users_for_assign(org_id)
    try:
        row = maintenance_service.get_maintenance_request(
            organization_id=org_id, request_id=request_id
        )
    except maintenance_service.MaintenanceServiceError:
        abort(404)
    if row["status"] in {"resolved", "cancelled"}:
        flash("This request cannot be edited.")
        return redirect(url_for("admin.maintenance_requests_detail", request_id=request_id))

    form = {
        "property_id": str(row["property_id"]),
        "unit_id": str(row["unit_id"] or ""),
        "guest_id": str(row["guest_id"] or ""),
        "reservation_id": str(row["reservation_id"] or ""),
        "title": row["title"],
        "description": row["description"] or "",
        "priority": row["priority"],
        "due_date": row["due_date"] or "",
        "assigned_to_id": str(row["assigned_to_id"] or ""),
    }
    error: str | None = None
    if request.method == "POST":
        for key in form:
            form[key] = (request.form.get(key) or "").strip()
        if not form["property_id"] or not form["title"]:
            error = "Property and title are required."
        else:
            payload = {
                "property_id": int(form["property_id"]),
                "unit_id": int(form["unit_id"]) if form["unit_id"] else None,
                "guest_id": int(form["guest_id"]) if form["guest_id"] else None,
                "reservation_id": int(form["reservation_id"]) if form["reservation_id"] else None,
                "title": form["title"],
                "description": form["description"] or None,
                "priority": form["priority"],
                "due_date": form["due_date"] or None,
                "assigned_to_id": int(form["assigned_to_id"]) if form["assigned_to_id"] else None,
            }
            try:
                _ = maintenance_service.update_maintenance_request(
                    organization_id=org_id,
                    request_id=request_id,
                    data=payload,
                    actor_user_id=current_user.id,
                )
            except (TypeError, ValueError):
                error = "IDs must be valid numbers."
            except maintenance_service.MaintenanceServiceError as err:
                if err.status == 404:
                    abort(404)
                error = err.message
            else:
                flash("Maintenance request updated.")
                return redirect(url_for("admin.maintenance_requests_detail", request_id=request_id))

    return render_template(
        "admin/maintenance/edit.html",
        row=row,
        properties=properties,
        units=units,
        assignees=assignees,
        form=form,
        error=error,
    )


@admin_bp.post("/maintenance-requests/<int:request_id>/status")
@require_admin_pms_access
def maintenance_requests_set_status(request_id: int):
    st = (request.form.get("status") or "").strip().lower()
    try:
        _ = maintenance_service.update_maintenance_request(
            organization_id=_pms_org_id(),
            request_id=request_id,
            data={"status": st},
            actor_user_id=current_user.id,
        )
    except maintenance_service.MaintenanceServiceError as err:
        if err.status == 404:
            abort(404)
        flash(err.message)
    else:
        flash("Status updated.")
    return redirect(url_for("admin.maintenance_requests_detail", request_id=request_id))


@admin_bp.post("/maintenance-requests/<int:request_id>/assign")
@require_admin_pms_access
def maintenance_requests_assign(request_id: int):
    raw = (request.form.get("assigned_to_id") or "").strip()
    try:
        _ = maintenance_service.update_maintenance_request(
            organization_id=_pms_org_id(),
            request_id=request_id,
            data={"assigned_to_id": int(raw) if raw else None},
            actor_user_id=current_user.id,
        )
    except (TypeError, ValueError):
        flash("Invalid assignee.")
    except maintenance_service.MaintenanceServiceError as err:
        if err.status == 404:
            abort(404)
        flash(err.message)
    else:
        flash("Assignment updated.")
    return redirect(url_for("admin.maintenance_requests_detail", request_id=request_id))


@admin_bp.post("/maintenance-requests/<int:request_id>/resolve")
@require_admin_pms_access
def maintenance_requests_resolve(request_id: int):
    try:
        _ = maintenance_service.resolve_maintenance_request(
            organization_id=_pms_org_id(),
            request_id=request_id,
            actor_user_id=current_user.id,
        )
    except maintenance_service.MaintenanceServiceError as err:
        if err.status == 404:
            abort(404)
        flash(err.message)
    else:
        flash("Request marked resolved.")
    return redirect(url_for("admin.maintenance_requests_detail", request_id=request_id))


@admin_bp.post("/maintenance-requests/<int:request_id>/cancel")
@require_admin_pms_access
def maintenance_requests_cancel(request_id: int):
    if (request.form.get("confirm_cancel") or "").strip().lower() != "yes":
        flash("Please confirm cancellation.")
        return redirect(url_for("admin.maintenance_requests_detail", request_id=request_id))
    try:
        _ = maintenance_service.cancel_maintenance_request(
            organization_id=_pms_org_id(),
            request_id=request_id,
            actor_user_id=current_user.id,
        )
    except maintenance_service.MaintenanceServiceError as err:
        if err.status == 404:
            abort(404)
        flash(err.message)
    else:
        flash("Request cancelled.")
    return redirect(url_for("admin.maintenance_requests_detail", request_id=request_id))


@admin_bp.get("/audit")
@require_superadmin_2fa
def audit():
    """List audit events, newest first, with basic filtering and pagination."""

    try:
        page = max(int(request.args.get("page", "1")), 1)
    except ValueError:
        page = 1

    try:
        page_size = int(request.args.get("page_size", str(PAGE_SIZE_DEFAULT)))
    except ValueError:
        page_size = PAGE_SIZE_DEFAULT
    page_size = max(1, min(page_size, PAGE_SIZE_MAX))

    action_filter = (request.args.get("action") or "").strip()
    email_filter = (request.args.get("email") or "").strip().lower()

    query = AuditLog.query
    if action_filter:
        query = query.filter(AuditLog.action.ilike(f"{action_filter}%"))
    if email_filter:
        query = query.filter(AuditLog.actor_email.ilike(f"%{email_filter}%"))

    total = query.count()

    offset = (page - 1) * page_size
    rows = query.order_by(AuditLog.created_at.desc()).offset(offset).limit(page_size).all()

    has_next = offset + len(rows) < total
    has_prev = page > 1

    return render_template(
        "admin_audit.html",
        rows=rows,
        page=page,
        page_size=page_size,
        total=total,
        has_next=has_next,
        has_prev=has_prev,
        action_filter=action_filter,
        email_filter=email_filter,
    )


# ---------------------------------------------------------------------------
# Email templates — list + edit. Project brief, section 7.
# ---------------------------------------------------------------------------


@admin_bp.get("/email-templates")
@require_superadmin_2fa
def email_templates_list():
    """List every editable email template, alphabetised by key."""

    rows = EmailTemplate.query.order_by(EmailTemplate.key.asc()).all()
    return render_template("admin_email_templates.html", templates=rows)


def _load_template_or_404(key: str) -> EmailTemplate:
    template = EmailTemplate.query.filter_by(key=key).first()
    if template is None:
        abort(404)
    return template


@admin_bp.get("/email-templates/<key>/preview")
@require_superadmin_2fa
def email_template_preview(key: str):
    template = _load_template_or_404(key)
    rendered = None
    error = None
    try:
        rendered = admin_service.build_email_template_preview(template_key=template.key)
        audit_record(
            "email_template.previewed",
            status=AuditStatus.SUCCESS,
            target_type="email_template",
            target_id=template.id,
            context={"key": template.key},
            commit=True,
        )
    except EmailServiceError as err:
        error = err.public_message
        audit_record(
            "email_template.previewed",
            status=AuditStatus.FAILURE,
            target_type="email_template",
            target_id=template.id,
            context={"key": template.key, "error": err.public_message},
            commit=True,
        )
    return render_template(
        "admin_email_template_preview.html",
        template=template,
        rendered=rendered,
        used_variables=template.available_variables or [],
        error=error,
    )


@admin_bp.route("/email-templates/<key>/test-send", methods=["GET", "POST"])
@require_superadmin_2fa
def email_template_test_send(key: str):
    template = _load_template_or_404(key)
    form = EmailTemplateTestSendForm()
    if request.method == "GET":
        form.to.data = current_user.email
    if form.validate_on_submit():
        to = form.to.data.strip().lower()
        if "@" not in to or "." not in to.split("@")[-1]:
            flash("Anna kelvollinen vastaanottajan sahkopostiosoite.")
            return render_template(
                "admin_email_template_test_send.html", template=template, form=form
            )
        try:
            admin_service.send_email_template_test(
                template_key=template.key,
                to=to,
                actor_user=current_user,
            )
            audit_record(
                "email_template.test_sent",
                status=AuditStatus.SUCCESS,
                target_type="email_template",
                target_id=template.id,
                context={"key": template.key, "to": to},
                commit=True,
            )
            flash("Testiviesti lahetetty onnistuneesti.")
            return redirect(url_for("admin.email_templates_list"))
        except EmailServiceError as err:
            audit_record(
                "email_template.test_failed",
                status=AuditStatus.FAILURE,
                target_type="email_template",
                target_id=template.id,
                context={"key": template.key, "to": to, "error": err.public_message},
                commit=True,
            )
            flash(f"Testiviestin lahetys epaonnistui: {err.public_message}")
    elif request.method == "POST":
        flash("Anna kelvollinen vastaanottajan sahkopostiosoite.")

    return render_template("admin_email_template_test_send.html", template=template, form=form)


@admin_bp.route("/email-templates/<key>", methods=["GET", "POST"])
@require_superadmin_2fa
def email_template_edit(key: str):
    """Edit one email template's subject / text body / HTML body."""

    template = _load_template_or_404(key)
    error: str | None = None

    form = EmailTemplateForm(obj=template)
    if request.method == "GET":
        form.subject.data = template.subject
        form.body_text.data = template.effective_text_content
        form.body_html.data = template.effective_html_content or ""
    if request.method == "POST":
        if form.validate():
            normalized_html: str | None = (form.body_html.data or "").strip() or None
            template.subject = form.subject.data.strip()
            template.body_text = form.body_text.data
            template.body_html = normalized_html
            template.text_content = form.body_text.data
            template.html_content = normalized_html
            template.updated_by_id = current_user.id
            db.session.commit()
            audit_record(
                "email_template.updated",
                status=AuditStatus.SUCCESS,
                target_type="email_template",
                target_id=template.id,
                context={"key": template.key},
                commit=True,
            )
            flash("Pohja tallennettu.")
            return redirect(url_for("admin.email_template_edit", key=key))
        else:
            error = "Tarkista lomakkeen kentat."

    return render_template(
        "admin_email_template_edit.html",
        template=template,
        form=form,
        error=error,
    )


# ---------------------------------------------------------------------------
# Settings — list + edit + create. Project brief, section 9.
# ---------------------------------------------------------------------------


@admin_bp.get("/settings")
@require_superadmin_2fa
def settings_list():
    """Show every application setting, alphabetical, secrets masked."""

    rows = settings_service.get_all()
    return render_template(
        "admin_settings.html",
        rows=rows,
        mask=settings_service.mask_for_display,
    )


@admin_bp.route("/settings/new", methods=["GET", "POST"])
@require_superadmin_2fa
@check_impersonation_blocked
def settings_new():
    """Create a new setting row (key + type are required and immutable later)."""

    error: str | None = None
    form = SettingForm()
    form.type.data = form.type.data or SettingType.STRING

    if form.validate_on_submit():
        setting_key = form.key.data.strip()
        setting_type = form.type.data
        if settings_service.find(setting_key) is not None:
            error = f"A setting with key {setting_key!r} already exists."
        else:
            try:
                settings_service.set_value(
                    setting_key,
                    _coerce_form_value(form.value.data or "", setting_type),
                    type_=setting_type,
                    description=(form.description.data or "").strip(),
                    is_secret=bool(form.is_secret.data),
                    actor_user_id=current_user.id,
                )
            except settings_service.SettingValueError as err:
                error = f"Invalid value for type {setting_type!r}: {err}"
            else:
                flash(f"Setting {setting_key!r} created.")
                return redirect(url_for("admin.settings_edit", key=setting_key))
    elif request.method == "POST":
        error = "Please correct the highlighted fields."

    return render_template(
        "admin_settings_new.html",
        form=form,
        error=error,
    )


@admin_bp.route("/settings/<key>", methods=["GET", "POST"])
@require_superadmin_2fa
@check_impersonation_blocked
def settings_edit(key: str):
    """Edit one setting -- value, description, is_secret. Key + type are stable."""

    row = settings_service.find(key)
    if row is None:
        abort(404)

    error: str | None = None
    form = SettingForm(obj=row)
    form.key.data = row.key
    form.type.data = row.type
    reveal_value = None
    if request.method == "GET":
        form.value.data = "" if row.is_secret else settings_service.mask_for_display(row)
        form.description.data = row.description
        form.is_secret.data = row.is_secret

    if request.method == "POST":
        post_action = (request.form.get("action") or "save").strip().lower()
        if post_action == "reveal":
            code = (request.form.get("reveal_code") or "").replace(" ", "").strip()
            if not _verify_fresh_2fa_code(code):
                error = "A valid fresh 2FA code is required to reveal this secret."
                form.value.data = ""
            else:
                reveal_value = settings_service.get(row.key, default="")
                form.value.data = reveal_value if reveal_value is not None else ""
        if post_action == "reveal":
            pass
        elif form.validate():
            submitted_value = form.value.data or ""
            if row.is_secret and submitted_value == "":
                new_value = settings_service.get(row.key)
            else:
                try:
                    new_value = _coerce_form_value(submitted_value, row.type)
                except (ValueError, settings_service.SettingValueError) as err:
                    error = f"Invalid value for type {row.type!r}: {err}"
                    new_value = None

            if error is None:
                try:
                    settings_service.set_value(
                        row.key,
                        new_value,
                        description=(form.description.data or "").strip(),
                        is_secret=bool(form.is_secret.data),
                        actor_user_id=current_user.id,
                    )
                except settings_service.SettingValueError as err:
                    error = str(err)
                else:
                    flash("Setting saved.")
                    return redirect(url_for("admin.settings_edit", key=row.key))
        else:
            error = "Please correct the highlighted fields."

    return render_template(
        "admin_settings_edit.html",
        setting=row,
        form=form,
        error=error,
        reveal_value=reveal_value,
    )


def _coerce_form_value(raw: str, type_: str):
    if type_ == SettingType.STRING:
        return raw
    if type_ == SettingType.INT:
        if raw.strip() == "":
            return 0
        return int(raw)
    if type_ == SettingType.BOOL:
        return raw.strip().lower() in {"true", "1", "yes", "on"}
    if type_ == SettingType.JSON:
        import json as _json

        return _json.loads(raw) if raw.strip() else None
    return raw


def _verify_fresh_2fa_code(code: str) -> bool:
    if not code:
        return False
    if current_user.verify_totp(code):
        return True
    if current_user.consume_backup_code(code):
        db.session.commit()
        return True
    if TwoFactorEmailCode.consume_active_code(user_id=current_user.id, raw_code=code):
        db.session.commit()
        return True
    return False


# ---------------------------------------------------------------------------
# Users -- superadmin CRUD. Project brief section 3.
# ---------------------------------------------------------------------------


@admin_bp.get("/users")
@require_superadmin_2fa
def users_list():
    rows = User.query.order_by(User.email.asc()).all()
    return render_template("admin_users.html", rows=rows, roles=list(UserRole))


@admin_bp.post("/superadmin/impersonate/<int:user_id>")
@require_superadmin_2fa
def superadmin_impersonate(user_id: int):
    if not current_user.is_superadmin:
        abort(403)
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("Impersonoinnin syy on pakollinen.")
        return redirect(url_for("admin.users_list"))
    target_user = User.query.get_or_404(user_id)
    if target_user.id == current_user.id:
        flash("Et voi impersonoida itseäsi.")
        return redirect(url_for("admin.users_list"))
    admin_service.start_impersonation(
        actor_user=current_user,
        target_user=target_user,
        reason=reason,
    )
    session["impersonator_user_id"] = current_user.id
    session["impersonation_started_at"] = datetime.now(timezone.utc).isoformat()
    login_user(target_user)
    flash(f"Esiinnyt nyt käyttäjänä {target_user.email}.")
    return redirect(url_for("admin.admin_home"))


@admin_bp.post("/exit-impersonation")
@login_required
def exit_impersonation():
    impersonator_user_id = session.get("impersonator_user_id")
    if not impersonator_user_id:
        abort(400)
    impersonator = User.query.get_or_404(int(impersonator_user_id))
    started_raw = session.get("impersonation_started_at")
    duration = 0
    if started_raw:
        try:
            started_at = datetime.fromisoformat(started_raw)
            duration = int((datetime.now(timezone.utc) - started_at).total_seconds())
        except Exception:
            duration = 0
    admin_service.end_impersonation(
        actor_user=current_user,
        impersonator_user=impersonator,
        duration_seconds=duration,
    )
    session.pop("impersonator_user_id", None)
    session.pop("impersonation_started_at", None)
    login_user(impersonator)
    flash("Impersonointi lopetettu.")
    return redirect(url_for("admin.users_list"))


@admin_bp.route("/users/new", methods=["GET", "POST"])
@require_superadmin_2fa
def users_new():
    organizations = Organization.query.order_by(Organization.name.asc()).all()
    form = UserCreateForm()
    form.role.data = form.role.data or UserRole.USER.value
    form.organization_id.choices = [(o.id, o.name) for o in organizations]
    error: str | None = None

    if form.validate_on_submit():
        normalized_email = form.email.data.strip().lower()
        if User.query.filter_by(email=normalized_email).first() is not None:
            error = f"User '{normalized_email}' already exists."
        else:
            try:
                user = admin_service.create_user(
                    email=normalized_email,
                    password=form.password.data,
                    role=form.role.data,
                    organization_id=form.organization_id.data,
                    actor_type=ActorType.USER,
                    actor_id=current_user.id,
                    actor_email=current_user.email,
                )
            except admin_service.UserServiceError as err:
                error = str(err)
            else:
                flash(f"User {user.email} created.")
                return redirect(url_for("admin.users_list"))
    elif request.method == "POST":
        error = "Please correct the highlighted fields."

    return render_template(
        "admin_user_form.html",
        form=form,
        organizations=organizations,
        roles=list(UserRole),
        error=error,
        is_new=True,
        target_user=None,
    )


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@require_superadmin_2fa
@check_impersonation_blocked
def users_edit(user_id: int):
    target_user = User.query.get_or_404(user_id)
    organizations = Organization.query.order_by(Organization.name.asc()).all()
    form = UserEditForm(obj=target_user)
    form.organization_id.choices = [(o.id, o.name) for o in organizations]
    if request.method == "GET":
        form.organization_id.data = target_user.organization_id
        form.role.data = target_user.role
        form.is_active.data = target_user.is_active
    error: str | None = None

    if form.validate_on_submit():
        old_role = target_user.role
        old_org_id = target_user.organization_id
        old_is_active = target_user.is_active
        try:
            target_user.organization_id = form.organization_id.data
            if form.password.data:
                admin_service.change_password(
                    user_id=target_user.id,
                    new_password=form.password.data,
                    actor_type=ActorType.USER,
                    actor_id=current_user.id,
                    actor_email=current_user.email,
                    commit=False,
                )
            if old_role != form.role.data:
                admin_service.update_user_role(
                    user_id=target_user.id,
                    new_role=form.role.data,
                    actor_type=ActorType.USER,
                    actor_id=current_user.id,
                    actor_email=current_user.email,
                    commit=False,
                )
            if old_is_active != form.is_active.data:
                if form.is_active.data:
                    admin_service.reactivate_user(
                        user_id=target_user.id,
                        actor_type=ActorType.USER,
                        actor_id=current_user.id,
                        actor_email=current_user.email,
                        commit=False,
                    )
                else:
                    admin_service.deactivate_user(
                        user_id=target_user.id,
                        actor_type=ActorType.USER,
                        actor_id=current_user.id,
                        actor_email=current_user.email,
                        commit=False,
                    )
        except admin_service.UserServiceError as err:
            db.session.rollback()
            error = str(err)
        else:
            audit_record(
                "user.updated",
                status=AuditStatus.SUCCESS,
                actor_type=ActorType.USER,
                actor_id=current_user.id,
                actor_email=current_user.email,
                target_type="user",
                target_id=target_user.id,
                context={
                    "old_organization_id": old_org_id,
                    "new_organization_id": target_user.organization_id,
                },
                commit=True,
            )
            flash("User updated.")
            return redirect(url_for("admin.users_list"))
    elif request.method == "POST":
        error = "Please correct the highlighted fields."

    return render_template(
        "admin_user_form.html",
        form=form,
        organizations=organizations,
        roles=list(UserRole),
        error=error,
        is_new=False,
        target_user=target_user,
    )


@admin_bp.post("/users/<int:user_id>/toggle-active")
@require_superadmin_2fa
@check_impersonation_blocked
def users_toggle_active(user_id: int):
    target_user = User.query.get_or_404(user_id)
    try:
        if target_user.is_active:
            admin_service.deactivate_user(
                user_id=target_user.id,
                actor_type=ActorType.USER,
                actor_id=current_user.id,
                actor_email=current_user.email,
                commit=True,
            )
        else:
            admin_service.reactivate_user(
                user_id=target_user.id,
                actor_type=ActorType.USER,
                actor_id=current_user.id,
                actor_email=current_user.email,
                commit=True,
            )
    except admin_service.UserServiceError as err:
        flash(str(err))
        return redirect(url_for("admin.users_list"))
    db.session.refresh(target_user)
    flash(
        f"User {target_user.email} is now " f"{'active' if target_user.is_active else 'inactive'}."
    )
    return redirect(url_for("admin.users_list"))


# ---------------------------------------------------------------------------
# Organizations -- superadmin CRUD. Project brief section 3 + 12.
# ---------------------------------------------------------------------------


@admin_bp.get("/organizations")
@require_superadmin_2fa
def organizations_list():
    rows = Organization.query.order_by(Organization.name.asc()).all()
    return render_template("admin_organizations.html", rows=rows)


@admin_bp.route("/organizations/new", methods=["GET", "POST"])
@require_superadmin_2fa
def organizations_new():
    form = OrganizationForm()
    error: str | None = None

    if form.validate_on_submit():
        org_name = form.name.data.strip()
        if Organization.query.filter_by(name=org_name).first() is not None:
            error = f"Organization '{org_name}' already exists."
        else:
            org = Organization(name=org_name)
            db.session.add(org)
            db.session.flush()
            audit_record(
                "organization.created",
                status=AuditStatus.SUCCESS,
                actor_type=ActorType.USER,
                actor_id=current_user.id,
                actor_email=current_user.email,
                target_type="organization",
                target_id=org.id,
                context={"name": org.name},
                commit=True,
            )
            flash(f"Organization '{org.name}' created.")
            return redirect(url_for("admin.organizations_list"))
    elif request.method == "POST":
        error = "Please correct the highlighted fields."

    return render_template(
        "admin_organization_form.html",
        form=form,
        error=error,
        is_new=True,
        target_org=None,
    )


@admin_bp.route("/organizations/<int:org_id>/edit", methods=["GET", "POST"])
@require_superadmin_2fa
def organizations_edit(org_id: int):
    org = Organization.query.get_or_404(org_id)
    form = OrganizationForm(obj=org)
    error: str | None = None

    if form.validate_on_submit():
        old_name = org.name
        org.name = form.name.data.strip()
        audit_record(
            "organization.updated",
            status=AuditStatus.SUCCESS,
            actor_type=ActorType.USER,
            actor_id=current_user.id,
            actor_email=current_user.email,
            target_type="organization",
            target_id=org.id,
            context={"old_name": old_name, "new_name": org.name},
            commit=True,
        )
        flash("Organization updated.")
        return redirect(url_for("admin.organizations_list"))
    elif request.method == "POST":
        error = "Please correct the highlighted fields."

    return render_template(
        "admin_organization_form.html",
        form=form,
        error=error,
        is_new=False,
        target_org=org,
    )


# ---------------------------------------------------------------------------
# API keys -- superadmin CRUD. Project brief section 6.
# ---------------------------------------------------------------------------


@admin_bp.get("/owners")
@require_superadmin_2fa
def owners_list():
    rows = (
        PropertyOwner.query.filter_by(organization_id=current_user.organization_id)
        .order_by(PropertyOwner.name.asc(), PropertyOwner.id.asc())
        .all()
    )
    properties = (
        Property.query.filter_by(organization_id=current_user.organization_id)
        .order_by(Property.name.asc())
        .all()
    )
    return render_template("admin/owners_list.html", rows=rows, properties=properties)


@admin_bp.route("/owners/new", methods=["GET", "POST"])
@require_superadmin_2fa
def owners_new():
    error: str | None = None
    if request.method == "POST":
        try:
            row = owners_service.create_owner(
                organization_id=current_user.organization_id,
                name=(request.form.get("name") or "").strip(),
                email=(request.form.get("email") or "").strip(),
                phone=(request.form.get("phone") or "").strip() or None,
                payout_iban=(request.form.get("payout_iban") or "").strip() or None,
            )
            password = (request.form.get("password") or "").strip()
            if password:
                owners_service.create_owner_user(
                    owner_id=row.id,
                    email=row.email,
                    password=password,
                )
            db.session.commit()
            flash("Owner created.")
            return redirect(url_for("admin.owners_list"))
        except Exception as exc:
            db.session.rollback()
            error = str(exc)
    return render_template("admin/owners_new.html", error=error)


@admin_bp.post("/owners/<int:owner_id>/assign-property")
@require_superadmin_2fa
def owners_assign_property(owner_id: int):
    from datetime import date
    from decimal import Decimal

    try:
        valid_from = date.fromisoformat((request.form.get("valid_from") or "").strip())
        valid_to_raw = (request.form.get("valid_to") or "").strip()
        owners_service.assign_property(
            owner_id=owner_id,
            organization_id=current_user.organization_id,
            property_id=int(request.form.get("property_id")),
            ownership_pct=Decimal((request.form.get("ownership_pct") or "1").strip()),
            management_fee_pct=Decimal((request.form.get("management_fee_pct") or "0").strip()),
            valid_from=valid_from,
            valid_to=date.fromisoformat(valid_to_raw) if valid_to_raw else None,
        )
        db.session.commit()
        flash("Property linked to owner.")
    except Exception as exc:
        db.session.rollback()
        flash(f"Could not assign property: {exc}")
    return redirect(url_for("admin.owners_list"))


@admin_bp.get("/api-keys")
@require_superadmin_2fa
def api_keys_list():
    rows = ApiKey.query.order_by(ApiKey.created_at.desc()).all()
    raw_key = request.args.get("show_raw")
    return render_template("admin_api_keys.html", rows=rows, raw_key=raw_key)


@admin_bp.route("/api-keys/new", methods=["GET", "POST"])
@require_superadmin_2fa
def api_keys_new():
    organizations = Organization.query.order_by(Organization.name.asc()).all()
    users = User.query.filter_by(is_active=True).order_by(User.email.asc()).all()
    form = ApiKeyForm()
    form.organization_id.choices = [(o.id, o.name) for o in organizations]
    form.user_id.choices = [(0, "-- none (org-scoped) --")] + [(u.id, u.email) for u in users]
    error: str | None = None

    if form.validate_on_submit():
        selected_user_id = (
            form.user_id.data if form.user_id.data and form.user_id.data > 0 else None
        )
        expires_at = form.expires_at.data
        if selected_user_id is not None:
            selected_user = User.query.get(selected_user_id)
            if selected_user is None:
                error = "Selected user does not exist."
            elif selected_user.organization_id != form.organization_id.data:
                error = "Selected user must belong to the selected organization."
        selected_scopes = list(form.scopes.data or [])
        if "admin:*" in selected_scopes and not current_user.is_superadmin:
            error = "Only superadmin can create API keys with admin:* scope."
        if error is None:
            api_key, raw_key = ApiKey.issue(
                name=form.name.data.strip(),
                organization_id=form.organization_id.data,
                user_id=selected_user_id,
                scopes=",".join(selected_scopes),
                expires_at=expires_at,
            )
            db.session.add(api_key)
            db.session.flush()
            audit_record(
                "apikey.created",
                status=AuditStatus.SUCCESS,
                actor_type=ActorType.USER,
                actor_id=current_user.id,
                actor_email=current_user.email,
                target_type="api_key",
                target_id=api_key.id,
                context={
                    "name": api_key.name,
                    "prefix": api_key.key_prefix,
                    "scopes": api_key.scope_list,
                },
                commit=True,
            )
            flash("API key issued. The plaintext is shown once below -- copy it now.")
            return redirect(url_for("admin.api_keys_list", show_raw=raw_key))
    elif request.method == "POST":
        error = "Please correct the highlighted fields."

    return render_template(
        "admin_api_key_form.html",
        form=form,
        organizations=organizations,
        users=users,
        error=error,
    )


@admin_bp.post("/api-keys/<int:key_id>/toggle-active")
@require_superadmin_2fa
def api_keys_toggle_active(key_id: int):
    api_key = ApiKey.query.get_or_404(key_id)
    api_key.is_active = not api_key.is_active
    audit_record(
        "apikey.active_toggled",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        actor_email=current_user.email,
        target_type="api_key",
        target_id=api_key.id,
        context={"is_active": api_key.is_active, "prefix": api_key.key_prefix},
        commit=True,
    )
    flash(
        f"API key {api_key.key_prefix} is now " f"{'active' if api_key.is_active else 'inactive'}."
    )
    return redirect(url_for("admin.api_keys_list"))


@admin_bp.post("/api-keys/<int:key_id>/delete")
@require_superadmin_2fa
def api_keys_delete(key_id: int):
    api_key = ApiKey.query.get_or_404(key_id)
    prefix = api_key.key_prefix
    db.session.delete(api_key)
    audit_record(
        "apikey.deleted",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=current_user.id,
        actor_email=current_user.email,
        target_type="api_key",
        target_id=key_id,
        context={"prefix": prefix},
        commit=True,
    )
    flash(f"API key {prefix} deleted.")
    return redirect(url_for("admin.api_keys_list"))


@admin_bp.get("/api-keys/<int:key_id>/usage")
@require_superadmin_2fa
def api_keys_usage(key_id: int):
    api_key = ApiKey.query.get_or_404(key_id)
    rows = (
        ApiKeyUsage.query.filter_by(api_key_id=api_key.id)
        .order_by(ApiKeyUsage.created_at.desc())
        .limit(100)
        .all()
    )
    return render_template("admin/api_key_usage.html", api_key=api_key, rows=rows)


@admin_bp.get("/superadmin/tenants/<int:org_id>/debug")
@require_superadmin_2fa
def tenant_debug(org_id: int):
    try:
        payload = admin_service.build_tenant_debug_view(organization_id=org_id)
    except ValueError:
        abort(404)
    sentry_url = f"https://sentry.io/issues/?query=organization_id%3A{org_id}"
    return render_template(
        "admin/superadmin_tenant_debug.html", data=payload, org_id=org_id, sentry_url=sentry_url
    )


@admin_bp.route("/superadmin/status", methods=["GET", "POST"])
@require_superadmin_2fa
def superadmin_status():
    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "component_state":
            comp = StatusComponent.query.filter_by(
                key=(request.form.get("component_key") or "").strip()
            ).first_or_404()
            comp.current_state = (request.form.get("current_state") or "operational").strip()
            comp.scheduled_maintenance = bool(request.form.get("scheduled_maintenance"))
            db.session.commit()
            flash("Komponentin tila paivitetty.")
        elif action == "incident_create":
            incident = StatusIncident(
                title=(request.form.get("title") or "").strip() or "Untitled incident",
                body=(request.form.get("body") or "").strip(),
                severity=(request.form.get("severity") or "minor").strip(),
                component_keys=[
                    x.strip()
                    for x in (request.form.get("component_keys") or "").split(",")
                    if x.strip()
                ],
                status="open",
            )
            db.session.add(incident)
            db.session.commit()
            flash("Incident luotu.")
        elif action == "incident_close":
            incident = StatusIncident.query.get_or_404(int(request.form.get("incident_id")))
            incident.status = "resolved"
            incident.resolved_at = datetime.now(timezone.utc)
            db.session.commit()
            flash("Incident suljettu.")
    payload = admin_service.public_status_payload(window_days=90)
    return render_template("admin/superadmin_status.html", payload=payload)
