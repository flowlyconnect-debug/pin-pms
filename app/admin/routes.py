"""Admin-only views — audit log browser and email-template editor.

All routes in this blueprint require an authenticated superadmin whose TOTP
2FA session is verified. Reuses the decorator declared in :mod:`app.auth.routes`
so the 2FA gate stays in a single place.
"""

from __future__ import annotations

import csv
import hashlib
import json
import time
from datetime import date, datetime, timedelta, timezone
from functools import wraps
from io import BytesIO, StringIO

from flask import (
    Response,
    abort,
    current_app,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from flask_login import current_user, login_required, login_user
from sqlalchemy import or_

from app.admin import admin_bp
from app.admin import services as admin_service
from app.admin.forms import (
    ApiKeyForm,
    EmailTemplateForm,
    EmailTemplateTestSendForm,
    OrganizationForm,
    PropertyForm,
    SettingForm,
    UnitForm,
    UserCreateForm,
    UserEditForm,
)
from app.api.models import ApiKey, ApiKeyUsage
from app.api.schemas import json_error, json_ok
from app.api.services import (
    ApiKeyAdminError,
    create_api_key_admin,
    delete_api_key_admin,
    toggle_api_key_active_admin,
)
from app.audit import record as audit_record
from app.audit.models import ActorType, AuditLog, AuditStatus
from app.auth.routes import require_superadmin_2fa
from app.billing import services as billing_service
from app.billing.models import Invoice
from app.billing.pdf import generate_invoice_pdf
from app.comments.services import CommentService, CommentServiceError
from app.core.decorators import require_tenant_access
from app.email.models import EmailQueueItem, EmailTemplate, OutgoingEmailStatus, TemplateKey
from app.email.services import EmailServiceError, send_template, update_email_template_admin
from app.expenses import services as expense_service
from app.extensions import db
from app.gdpr.services import (
    GdprPermissionError,
    anonymize_user_data,
    delete_user_data,
    export_json_safe,
    export_user_data,
)
from app.guests import services as guest_service
from app.integrations.ical.service import IcalService, IcalServiceError
from app.maintenance import services as maintenance_service
from app.notifications import routes as notification_routes
from app.notifications import services as notification_service
from app.organizations.models import Organization
from app.owners import services as owners_service
from app.owners.models import PropertyOwner
from app.payments import services as payment_service
from app.payments.models import Payment, PaymentRefund
from app.properties import images as property_image_service
from app.properties import services as property_service
from app.properties.models import Property, Unit
from app.reports import services as report_service
from app.reservations import services as reservation_service
from app.settings import services as settings_service
from app.settings.models import SettingType
from app.tags.services import TagService, TagServiceError
from app.users.models import User, UserRole
from app.users.services import UserServiceError

PAGE_SIZE_DEFAULT = 50
PAGE_SIZE_MAX = 200
_AVAILABILITY_CACHE_TTL_SECONDS = 30
_availability_cache: dict[tuple, tuple[float, dict]] = {}


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
    # Cross-tenant superadmin override is out of scope; track future design at
    # https://github.com/example/pindora-pms/issues/1
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


def _parse_csv_filter_args(key: str) -> list[str]:
    raw_values = request.args.getlist(key)
    values: list[str] = []
    for raw in raw_values:
        for part in raw.split(","):
            cleaned = part.strip()
            if cleaned:
                values.append(cleaned)
    return values


def _normalize_action_type(action: str) -> str:
    lowered = (action or "").lower()
    if any(token in lowered for token in ("delete", "removed", "poist")):
        return "delete"
    if any(token in lowered for token in ("login", "auth.")):
        return "login"
    if any(token in lowered for token in ("send", "retry", "dispatch", "email")):
        return "send"
    if any(token in lowered for token in ("create", "new", "created", "add")):
        return "create"
    return "update"


def _label_from_action_type(action_type: str) -> str:
    labels = {
        "create": "Luotu",
        "update": "Muokattu",
        "delete": "Poistettu",
        "login": "Login",
        "send": "Lahetetty",
    }
    return labels.get(action_type, "Muokattu")


def _label_from_entity(target_type: str | None) -> tuple[str, str]:
    normalized = (target_type or "event").strip().lower()
    labels = {
        "invoice": "Lasku",
        "customer": "Asiakas",
        "guest": "Asiakas",
        "contract": "Sopimus",
        "lease": "Sopimus",
        "property": "Kohde",
        "unit": "Kohde",
        "user": "Kayttaja",
    }
    return normalized, labels.get(normalized, (target_type or "Tapahtuma").capitalize())


def _context_to_diff(context: dict | None) -> list[dict[str, str | None]]:
    if not isinstance(context, dict):
        return []
    before = context.get("before")
    after = context.get("after")
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    fields = sorted(set(before.keys()) | set(after.keys()))
    changes: list[dict[str, str | None]] = []
    for field in fields:
        old_value = before.get(field)
        new_value = after.get(field)
        if old_value == new_value:
            continue
        changes.append(
            {
                "field": str(field),
                "oldValue": None if old_value is None else str(old_value),
                "newValue": None if new_value is None else str(new_value),
            }
        )
    return changes


def _parse_optional_date(name: str) -> date | None:
    raw = (request.args.get(name) or "").strip()
    if not raw:
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _list_filters() -> dict:
    return {
        "status": (request.args.get("status") or "").strip() or None,
        "date_from": _parse_optional_date("from"),
        "date_to": _parse_optional_date("to"),
        "q": (request.args.get("q") or "").strip() or None,
        "sort": (request.args.get("sort") or "created_at").strip(),
        "direction": (request.args.get("dir") or "desc").strip().lower(),
    }


def _sanitize_ui_theme(raw: str | None) -> str:
    value = (raw or "").strip().lower()
    if value in {"light", "dark"}:
        return value
    return "auto"


def _ui_theme_setting_key() -> str:
    return "ui.theme"


def _notification_scope_org_id() -> int:
    requested_org_id = _pms_org_id()
    if current_user.role == UserRole.SUPERADMIN.value:
        return requested_org_id
    return current_user.organization_id


@admin_bp.get("")
@admin_bp.get("/")
@admin_bp.get("/dashboard")
@require_admin_pms_access
def admin_home():
    selected_org_id = current_user.organization_id
    org_options: list[Organization] = []
    if current_user.is_superadmin:
        org_options = Organization.query.order_by(Organization.name.asc(), Organization.id.asc()).all()
        requested_org_id_raw = (request.args.get("organization_id") or "").strip()
        if requested_org_id_raw:
            try:
                requested_org_id = int(requested_org_id_raw)
            except ValueError:
                requested_org_id = None
            if requested_org_id is not None and any(org.id == requested_org_id for org in org_options):
                selected_org_id = requested_org_id
    selected_range = admin_service.normalize_dashboard_range(request.args.get("range"))
    summary = admin_service.get_dashboard_stats(
        organization_id=selected_org_id,
        viewer_is_superadmin=current_user.is_superadmin,
        range_key=selected_range,
    )
    modern_summary = admin_service.dashboard_summary(organization_id=selected_org_id)
    dashboard_chart_data = {
        "trend_revenue_30d": modern_summary.get("trend_revenue_30d", []),
        "trend_occupancy_30d": modern_summary.get("trend_occupancy_30d", []),
        "timezone": (modern_summary.get("meta") or {}).get("timezone", "Europe/Helsinki"),
        "insufficient_chart_data": (modern_summary.get("meta") or {}).get(
            "insufficient_chart_data", False
        ),
        "week_overview": summary.get("week_overview", []),
        "unit_status_overview": summary.get("unit_status_overview", []),
        "range_key": summary.get("range_key", selected_range),
    }
    today = date.today()
    availability_preview = _get_cached_availability_matrix(
        organization_id=selected_org_id,
        start_date=today,
        end_date=today + timedelta(days=6),
        property_id=None,
        include_cancelled=False,
    )
    availability_preview["properties"] = availability_preview["properties"][:3]
    return render_template(
        "admin/dashboard.html",
        summary=summary,
        organization_options=org_options,
        selected_organization_id=selected_org_id,
        dashboard_chart_data=dashboard_chart_data,
        selected_range=selected_range,
        availability_preview=availability_preview,
    )


@admin_bp.get("/api/dashboard/stats")
@require_admin_pms_access
def api_dashboard_stats():
    selected_org_id = _pms_org_id()
    summary = admin_service.get_dashboard_stats(
        organization_id=selected_org_id,
        viewer_is_superadmin=current_user.is_superadmin,
        range_key="30d",
    )
    modern_summary = admin_service.dashboard_summary(organization_id=selected_org_id)
    kpi = modern_summary.get("kpi", {})
    occupancy_trend = modern_summary.get("trend_occupancy_30d", [])
    revenue_trend = modern_summary.get("trend_revenue_30d", [])
    occupancy_sparkline = [float(item.get("pct", 0) or 0) for item in occupancy_trend]
    revenue_sparkline = [float(item.get("value", 0) or 0) for item in revenue_trend]
    expenses_this_month = float((summary.get("cash_flow") or {}).get("expenses_this_month") or 0)
    net_cash_flow_this_month = float((summary.get("cash_flow") or {}).get("net_cash_flow_this_month") or 0)
    revenue_this_month = float(kpi.get("revenue_this_month") or 0)
    revenue_last_month = float(kpi.get("revenue_last_month") or 0)
    occupancy_today = float(kpi.get("occupancy_today_pct") or 0)
    occupancy_7d_avg = float(kpi.get("occupancy_7d_avg_pct") or 0)

    def _trend_pct(current: float, previous: float) -> float:
        if previous == 0:
            return 0.0
        return round(((current - previous) / previous) * 100, 1)

    return jsonify(
        {
            "occupancy": {
                "value": round(occupancy_today, 1),
                "trend": round(occupancy_today - occupancy_7d_avg, 1),
                "sparkline": occupancy_sparkline,
                "intent": "default",
            },
            "revenue": {
                "value": revenue_this_month,
                "trend": _trend_pct(revenue_this_month, revenue_last_month),
                "sparkline": revenue_sparkline,
                "intent": "success",
            },
            "expenses": {
                "value": expenses_this_month,
                "trend": 0.0,
                "sparkline": [],
                "intent": "warning",
            },
            "net_cash_flow": {
                "value": net_cash_flow_this_month,
                "trend": 0.0,
                "sparkline": [],
                "intent": "danger" if net_cash_flow_this_month < 0 else "success",
            },
        }
    )


def _parse_report_range() -> tuple[date, date, str | None]:
    start_date_raw = (request.args.get("start_date") or "").strip()
    end_date_raw = (request.args.get("end_date") or "").strip()
    if not start_date_raw or not end_date_raw:
        today = date.today()
        start_date = date(today.year, today.month, 1)
        return start_date, today, None
    try:
        start_date = date.fromisoformat(start_date_raw)
        end_date = date.fromisoformat(end_date_raw)
    except ValueError:
        return date.today(), date.today(), "Päivämäärien tulee olla muodossa YYYY-MM-DD."
    if start_date > end_date:
        return start_date, end_date, "Alkupäivä ei voi olla loppupäivän jälkeen."
    return start_date, end_date, None


@admin_bp.post("/theme")
@require_admin_pms_access
def set_theme():
    theme = _sanitize_ui_theme(request.form.get("theme"))
    settings_service.set_value(
        _ui_theme_setting_key(),
        theme,
        type_=SettingType.STRING,
        description="Admin UI theme preference (light/dark/auto).",
        actor_user_id=current_user.id,
    )
    response = redirect(request.referrer or url_for("admin.admin_home"))
    response.set_cookie(
        "ui_theme",
        theme,
        max_age=60 * 60 * 24 * 365,
        secure=bool(request.is_secure),
        httponly=True,
        samesite="Lax",
    )
    return response


@admin_bp.get("/notifications")
@require_admin_pms_access
def notifications_list():
    rows = notification_service.list_all_for_user(
        user_id=current_user.id,
        organization_id=_notification_scope_org_id(),
        limit=200,
    )
    return render_template(
        "admin/notifications.html",
        rows=rows,
        grouped_rows=notification_routes.group_by_day(rows),
    )


@admin_bp.post("/notifications/<int:notification_id>/read")
@require_admin_pms_access
def notifications_mark_read(notification_id: int):
    try:
        row = notification_service.mark_read(notification_id=notification_id, user_id=current_user.id)
    except notification_service.NotificationServiceError as err:
        if err.status == 404:
            abort(404)
        if err.status == 403:
            abort(403)
        abort(400)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "notification": notification_routes.to_payload(row)})
    destination = row.link or url_for("admin.notifications_list")
    return redirect(destination)


@admin_bp.post("/notifications/read-all")
@require_admin_pms_access
def notifications_mark_all_read():
    try:
        marked = notification_service.mark_all_read(
            user_id=current_user.id,
            organization_id=_notification_scope_org_id(),
        )
    except notification_service.NotificationServiceError as err:
        if err.status == 403:
            abort(403)
        abort(400)
    db.session.commit()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": True, "count": marked})
    flash("Ilmoitukset merkitty luetuiksi.")
    return redirect(url_for("admin.notifications_list"))


@admin_bp.get("/notifications/unread_count")
@require_admin_pms_access
def notifications_unread_count():
    count = notification_service.unread_count(
        user_id=current_user.id,
        organization_id=_notification_scope_org_id(),
    )
    return jsonify({"count": count})


@admin_bp.get("/notifications/unread")
@require_admin_pms_access
def notifications_unread():
    rows = notification_service.list_unread(
        user_id=current_user.id,
        organization_id=_notification_scope_org_id(),
        limit=20,
    )
    return jsonify({"items": [notification_routes.to_payload(row) for row in rows]})


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


def _parse_availability_from_date() -> date:
    raw = (request.args.get("from") or "").strip()
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        abort(400)


def _parse_availability_days() -> int:
    raw = (request.args.get("days") or "").strip()
    if not raw:
        return 14
    try:
        days = int(raw)
    except ValueError:
        abort(400)
    return max(1, min(days, 31))


def _availability_cache_key(*, organization_id: int, start_date: date, end_date: date, property_id: int | None, include_cancelled: bool) -> tuple:
    return (
        current_user.id,
        organization_id,
        start_date.isoformat(),
        end_date.isoformat(),
        property_id,
        include_cancelled,
    )


def _get_cached_availability_matrix(
    *,
    organization_id: int,
    start_date: date,
    end_date: date,
    property_id: int | None,
    include_cancelled: bool,
) -> dict:
    now = time.time()
    key = _availability_cache_key(
        organization_id=organization_id,
        start_date=start_date,
        end_date=end_date,
        property_id=property_id,
        include_cancelled=include_cancelled,
    )
    hit = _availability_cache.get(key)
    if hit and now - hit[0] <= _AVAILABILITY_CACHE_TTL_SECONDS:
        return hit[1]
    payload = reservation_service.availability_matrix(
        organization_id=organization_id,
        start_date=start_date,
        end_date=end_date,
        property_id=property_id,
        include_cancelled=include_cancelled,
    )
    _availability_cache[key] = (now, payload)
    return payload


@admin_bp.get("/availability")
@require_admin_pms_access
def availability_page():
    org_id = _pms_org_id()
    start_d = _parse_availability_from_date()
    days = _parse_availability_days()
    end_d = start_d + timedelta(days=days - 1)
    property_id = _parse_optional_calendar_filter_int("property_id")
    include_cancelled = (request.args.get("include_cancelled") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    properties, _ = _reservation_edit_form_context(organization_id=org_id)
    try:
        matrix = _get_cached_availability_matrix(
            organization_id=org_id,
            start_date=start_d,
            end_date=end_d,
            property_id=property_id,
            include_cancelled=include_cancelled,
        )
    except reservation_service.ReservationServiceError as exc:
        flash(exc.message, "error")
        return redirect(url_for("admin.calendar_page"))

    return render_template(
        "admin/availability.html",
        matrix=matrix,
        properties=properties,
        selected_property_id=property_id,
        include_cancelled=include_cancelled,
        start_date=start_d,
        end_date=end_d,
        days=days,
        today=date.today(),
        prev_from=(start_d - timedelta(days=7)).isoformat(),
        next_from=(start_d + timedelta(days=7)).isoformat(),
    )


@admin_bp.get("/availability/quick")
@require_admin_pms_access
def quick_availability():
    range_key = (request.args.get("range") or "today").strip().lower()
    try:
        payload = reservation_service.get_quick_availability(
            organization_id=_pms_org_id(),
            range_key=range_key,
            user=current_user,
        )
    except reservation_service.ReservationServiceError as exc:
        return json_error(exc.code, exc.message, status=exc.status)
    return json_ok(payload)


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
    f = _list_filters()
    rows, total = admin_service.list_admin_guests(
        organization_id=_pms_org_id(),
        status=f["status"],
        date_from=f["date_from"],
        date_to=f["date_to"],
        q=f["q"],
        page=page,
        per_page=per_page,
        sort=f["sort"],
        direction=f["direction"],
    )
    return render_template(
        "admin/guests/list.html",
        rows=rows,
        total=total,
        page=page,
        per_page=per_page,
        search=f["q"] or "",
        filters=f,
        saved_filters=admin_service.list_saved_filters(user_id=current_user.id, view_type="guests"),
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
            flash("Asiakas luotu.")
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
    tags = TagService.list_for_target(_pms_org_id(), "guest", guest_id)
    all_tags = TagService.list_for_org(_pms_org_id())
    comments = CommentService.list_for_target(_pms_org_id(), "guest", guest_id, include_internal=True)
    return render_template(
        "admin/guests/detail.html",
        row=row,
        reservations=reservations,
        tags=tags,
        all_tags=all_tags,
        comments=comments,
        target_type="guest",
    )


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


@admin_bp.get("/api/tags")
@require_admin_pms_access
def admin_tags_list():
    rows = TagService.list_for_org(_pms_org_id())
    return json_ok(
        [
            {"id": row.id, "name": row.name, "color": row.color, "organization_id": row.organization_id}
            for row in rows
        ]
    )


@admin_bp.post("/api/tags")
@require_admin_pms_access
def admin_tags_create():
    body = request.get_json(silent=True) or {}
    try:
        row = TagService.create(
            organization_id=_pms_org_id(),
            name=str(body.get("name", "")),
            color=str(body.get("color", "")),
            created_by_user_id=current_user.id,
        )
        db.session.commit()
    except TagServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"id": row.id, "name": row.name, "color": row.color}, status=201)


@admin_bp.post("/api/<string:resource>/<int:resource_id>/tags")
@require_admin_pms_access
def admin_tags_attach(resource: str, resource_id: int):
    target_type = {"guests": "guest", "reservations": "reservation", "properties": "property"}.get(resource)
    if target_type is None:
        return json_error("not_found", "Resource not supported.", status=404)
    body = request.get_json(silent=True) or {}
    try:
        TagService.attach(
            organization_id=_pms_org_id(),
            target_type=target_type,
            target_id=resource_id,
            tag_id=int(body.get("tag_id", 0)),
            actor_user_id=current_user.id,
        )
        db.session.commit()
    except (TypeError, ValueError):
        return json_error("validation_error", "tag_id must be an integer.", status=400)
    except TagServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"ok": True})


@admin_bp.delete("/api/<string:resource>/<int:resource_id>/tags/<int:tag_id>")
@require_admin_pms_access
def admin_tags_detach(resource: str, resource_id: int, tag_id: int):
    target_type = {"guests": "guest", "reservations": "reservation", "properties": "property"}.get(resource)
    if target_type is None:
        return json_error("not_found", "Resource not supported.", status=404)
    try:
        TagService.detach(
            organization_id=_pms_org_id(),
            target_type=target_type,
            target_id=resource_id,
            tag_id=tag_id,
            actor_user_id=current_user.id,
        )
        db.session.commit()
    except TagServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"ok": True})


@admin_bp.get("/api/<string:resource>/<int:resource_id>/comments")
@require_admin_pms_access
def admin_comments_list(resource: str, resource_id: int):
    target_type = {"guests": "guest", "reservations": "reservation", "properties": "property"}.get(resource)
    if target_type is None:
        return json_error("not_found", "Resource not supported.", status=404)
    try:
        rows = CommentService.list_for_target(_pms_org_id(), target_type, resource_id, include_internal=True)
    except CommentServiceError as err:
        return json_error(err.code, err.message, status=err.status)
    return json_ok(
        [
            {
                "id": row.id,
                "target_type": row.target_type,
                "target_id": row.target_id,
                "author_user_id": row.author_user_id,
                "body": row.body,
                "is_internal": row.is_internal,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "edited_at": row.edited_at.isoformat() if row.edited_at else None,
            }
            for row in rows
        ]
    )


@admin_bp.post("/api/<string:resource>/<int:resource_id>/comments")
@require_admin_pms_access
def admin_comments_create(resource: str, resource_id: int):
    target_type = {"guests": "guest", "reservations": "reservation", "properties": "property"}.get(resource)
    if target_type is None:
        return json_error("not_found", "Resource not supported.", status=404)
    body = request.get_json(silent=True) or {}
    try:
        row = CommentService.create(
            organization_id=_pms_org_id(),
            target_type=target_type,
            target_id=resource_id,
            author_user_id=current_user.id,
            body=str(body.get("body", "")),
            is_internal=bool(body.get("is_internal", True)),
        )
        db.session.commit()
    except CommentServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"id": row.id}, status=201)


@admin_bp.patch("/api/comments/<int:comment_id>")
@require_admin_pms_access
def admin_comments_edit(comment_id: int):
    body = request.get_json(silent=True) or {}
    try:
        row = CommentService.edit(comment_id=comment_id, actor_user_id=current_user.id, body=str(body.get("body", "")))
        db.session.commit()
    except CommentServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"id": row.id, "edited_at": row.edited_at.isoformat() if row.edited_at else None})


@admin_bp.delete("/api/comments/<int:comment_id>")
@require_admin_pms_access
def admin_comments_delete(comment_id: int):
    try:
        CommentService.delete(comment_id=comment_id, actor_user_id=current_user.id)
        db.session.commit()
    except CommentServiceError as err:
        db.session.rollback()
        return json_error(err.code, err.message, status=err.status)
    return json_ok({"ok": True})


@admin_bp.get("/search")
@require_admin_pms_access
def admin_search():
    q = (request.args.get("q") or "").strip()
    return json_ok(admin_service.search_all_resources(organization_id=_pms_org_id(), q=q))


@admin_bp.post("/saved-filters")
@require_admin_pms_access
def saved_filter_create():
    view_type = (request.form.get("view_type") or "").strip()
    name = (request.form.get("name") or "").strip()
    params = {
        "status": (request.form.get("status") or "").strip(),
        "from": (request.form.get("from") or "").strip(),
        "to": (request.form.get("to") or "").strip(),
        "q": (request.form.get("q") or "").strip(),
        "sort": (request.form.get("sort") or "").strip(),
        "dir": (request.form.get("dir") or "").strip(),
    }
    admin_service.create_saved_filter(
        user_id=current_user.id,
        name=name,
        view_type=view_type,
        filter_params=params,
    )
    flash("Suodatin tallennettu.")
    return redirect(request.referrer or url_for("admin.admin_home"))


@admin_bp.post("/saved-filters/<int:saved_filter_id>/delete")
@require_admin_pms_access
def saved_filter_delete(saved_filter_id: int):
    try:
        admin_service.delete_saved_filter(user_id=current_user.id, saved_filter_id=saved_filter_id)
    except ValueError:
        abort(404)
    flash("Tallennettu suodatin poistettu.")
    return redirect(request.referrer or url_for("admin.admin_home"))

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
            flash("Asiakkaan tiedot päivitetty.")
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
    form = PropertyForm()
    error: str | None = None

    if form.validate_on_submit():
        try:
            row = property_service.create_property(
                organization_id=_pms_org_id(),
                name=form.name.data,
                address=form.address.data,
                city=form.city.data,
                postal_code=form.postal_code.data,
                street_address=form.street_address.data,
                latitude=form.latitude.data,
                longitude=form.longitude.data,
                year_built=form.year_built.data,
                has_elevator=form.has_elevator.data,
                has_parking=form.has_parking.data,
                has_sauna=form.has_sauna.data,
                has_courtyard=form.has_courtyard.data,
                has_air_conditioning=form.has_air_conditioning.data,
                description=form.description.data,
                url=form.url.data,
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
            flash("Tallennus epäonnistui", "error")
        else:
            flash("Kohde luotu", "success")
            return redirect(url_for("admin.properties_detail", property_id=row["id"]))
    elif request.method == "POST":
        if form.errors:
            error = " ".join(msg for messages in form.errors.values() for msg in messages)
        else:
            error = "Tarkista lomakkeen kentät."

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
    tags = TagService.list_for_target(_pms_org_id(), "property", property_id)
    all_tags = TagService.list_for_org(_pms_org_id())
    comments = CommentService.list_for_target(
        _pms_org_id(), "property", property_id, include_internal=True
    )
    return render_template(
        "admin/properties/detail.html",
        row=row,
        tags=tags,
        all_tags=all_tags,
        comments=comments,
        target_type="property",
    )


@admin_bp.route("/properties/<int:property_id>/images", methods=["GET", "POST"])
@require_admin_pms_access
def properties_images(property_id: int):
    try:
        property_row = property_service.get_property(
            organization_id=_pms_org_id(),
            property_id=property_id,
        )
    except property_service.PropertyServiceError:
        abort(404)
    error = None
    if request.method == "POST":
        image_file = request.files.get("image")
        alt_text = (request.form.get("alt_text") or "").strip()
        if image_file is None or not image_file.filename:
            error = "Valitse ladattava kuva."
        else:
            try:
                property_image_service.upload_property_image(
                    organization_id=_pms_org_id(),
                    property_id=property_id,
                    raw=image_file.read(),
                    content_type=(image_file.mimetype or "").lower(),
                    alt_text=alt_text,
                    uploaded_by=current_user.id,
                )
                flash("Kuva ladattu.")
                return redirect(url_for("admin.properties_images", property_id=property_id))
            except property_image_service.PropertyImageError as err:
                error = err.message
    rows = property_image_service.list_property_images(
        organization_id=_pms_org_id(), property_id=property_id
    )
    return render_template(
        "admin/properties/images.html",
        row=property_row,
        images=rows,
        error=error,
    )


@admin_bp.post("/properties/<int:property_id>/images/<int:image_id>/delete")
@require_admin_pms_access
def properties_images_delete(property_id: int, image_id: int):
    try:
        property_image_service.delete_property_image(
            organization_id=_pms_org_id(),
            property_id=property_id,
            image_id=image_id,
        )
        flash("Kuva poistettu.")
    except property_image_service.PropertyImageError as err:
        flash(err.message)
    return redirect(url_for("admin.properties_images", property_id=property_id))


@admin_bp.post("/properties/<int:property_id>/images/reorder")
@require_admin_pms_access
def properties_images_reorder(property_id: int):
    ids_raw = request.form.getlist("image_ids")
    try:
        ids = [int(x) for x in ids_raw]
        property_image_service.reorder_property_images(
            organization_id=_pms_org_id(),
            property_id=property_id,
            ids=ids,
        )
        flash("Kuvien jarjestys paivitetty.")
    except (ValueError, property_image_service.PropertyImageError):
        flash("Kuvien jarjestyksen paivitys epaonnistui.")
    return redirect(url_for("admin.properties_images", property_id=property_id))


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

    form = PropertyForm(data=row)
    error: str | None = None

    if form.validate_on_submit():
        try:
            row = property_service.update_property(
                organization_id=_pms_org_id(),
                property_id=property_id,
                name=form.name.data,
                address=form.address.data,
                city=form.city.data,
                postal_code=form.postal_code.data,
                street_address=form.street_address.data,
                latitude=form.latitude.data,
                longitude=form.longitude.data,
                year_built=form.year_built.data,
                has_elevator=form.has_elevator.data,
                has_parking=form.has_parking.data,
                has_sauna=form.has_sauna.data,
                has_courtyard=form.has_courtyard.data,
                has_air_conditioning=form.has_air_conditioning.data,
                description=form.description.data,
                url=form.url.data,
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Kohteen tiedot päivitetty.")
            return redirect(url_for("admin.properties_detail", property_id=row["id"]))
    elif request.method == "POST":
        if form.errors:
            error = " ".join(msg for messages in form.errors.values() for msg in messages)
        else:
            error = "Tarkista lomakkeen kentät."

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

    form = UnitForm()
    error: str | None = None

    if form.validate_on_submit():
        try:
            _ = property_service.create_unit(
                organization_id=_pms_org_id(),
                property_id=property_id,
                name=form.name.data,
                unit_type=form.unit_type.data,
                floor=form.floor.data,
                area_sqm=form.area_sqm.data,
                bedrooms=form.bedrooms.data,
                has_kitchen=form.has_kitchen.data,
                has_bathroom=form.has_bathroom.data,
                has_balcony=form.has_balcony.data,
                has_terrace=form.has_terrace.data,
                has_dishwasher=form.has_dishwasher.data,
                has_washing_machine=form.has_washing_machine.data,
                has_tv=form.has_tv.data,
                has_wifi=form.has_wifi.data,
                max_guests=form.max_guests.data,
                description=form.description.data,
                floor_plan_image_id=form.floor_plan_image_id.data,
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Huone luotu.")
            return redirect(url_for("admin.units_list", property_id=property_id))
    elif request.method == "POST":
        if form.errors:
            error = " ".join(msg for messages in form.errors.values() for msg in messages)
        else:
            error = "Tarkista lomakkeen kentät."

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

    form = UnitForm(data=row)
    error: str | None = None

    if form.validate_on_submit():
        try:
            row = property_service.update_unit(
                organization_id=_pms_org_id(),
                unit_id=unit_id,
                name=form.name.data,
                unit_type=form.unit_type.data,
                floor=form.floor.data,
                area_sqm=form.area_sqm.data,
                bedrooms=form.bedrooms.data,
                has_kitchen=form.has_kitchen.data,
                has_bathroom=form.has_bathroom.data,
                has_balcony=form.has_balcony.data,
                has_terrace=form.has_terrace.data,
                has_dishwasher=form.has_dishwasher.data,
                has_washing_machine=form.has_washing_machine.data,
                has_tv=form.has_tv.data,
                has_wifi=form.has_wifi.data,
                max_guests=form.max_guests.data,
                description=form.description.data,
                floor_plan_image_id=form.floor_plan_image_id.data,
                actor_user_id=current_user.id,
            )
        except property_service.PropertyServiceError as err:
            error = err.message
        else:
            flash("Huoneen tiedot päivitetty.")
            return redirect(url_for("admin.units_list", property_id=row["property_id"]))
    elif request.method == "POST":
        if form.errors:
            error = " ".join(msg for messages in form.errors.values() for msg in messages)
        else:
            error = "Tarkista lomakkeen kentät."

    return render_template("admin/units/edit.html", row=row, form=form, error=error)


@admin_bp.get("/units/<int:unit_id>")
@require_admin_pms_access
def units_detail(unit_id: int):
    try:
        row = property_service.get_unit(
            organization_id=_pms_org_id(),
            unit_id=unit_id,
        )
    except property_service.PropertyServiceError:
        abort(404)
    return render_template("admin/units/detail.html", row=row)


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
            error = "Kalenteri-URL:n tulee alkaa osoitteella http:// tai https://."
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
                flash("Tuotu kalenterilähde tallennettu.")
                return redirect(url_for("admin.units_calendar_sync", unit_id=unit_id))

    feeds = service.list_unit_feeds(organization_id=org_id, unit_id=unit_id)
    return render_template(
        "admin/units/calendar_sync.html",
        row=row,
        ics_url=ics_url,
        feeds=feeds,
        error=error,
    )


@admin_bp.get("/konfliktit")
@admin_bp.get("/calendar-sync/conflicts")
@require_admin_pms_access
def conflicts_page():
    service = IcalService()
    try:
        rows = service.detect_conflicts(organization_id=_pms_org_id())
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Konfliktien haku epäonnistui.")
        flash("Kalenteriristiriitojen lataus epäonnistui. Yritä hetken päästä uudelleen.")
        rows = []
    return render_template("admin/calendar_sync_conflicts.html", rows=rows)


@admin_bp.get("/kalenteriristiriidat")
@require_admin_pms_access
def conflicts_legacy_redirect():
    return redirect(url_for("admin.conflicts_page"))


@admin_bp.get("/api/conflicts")
@require_admin_pms_access
def conflicts_api():
    rows = IcalService().detect_conflicts(organization_id=_pms_org_id())
    return json_ok({"count": len(rows), "items": rows})


@admin_bp.post("/calendar-sync/feeds/<int:feed_id>/sync")
@require_admin_pms_access
@require_tenant_access("imported_calendar_feed", id_arg="feed_id")
def calendar_sync_feed_now(feed_id: int):
    row = g.scoped_entity
    IcalService().sync_all_feeds(organization_id=row.organization_id)
    flash("Kalenterin synkronointi valmis.")
    return redirect(url_for("admin.units_calendar_sync", unit_id=row.unit_id))


@admin_bp.get("/reservations")
@require_admin_pms_access
def reservations_list():
    page, per_page = _pms_pagination()
    f = _list_filters()
    rows, total = admin_service.list_admin_reservations(
        organization_id=_pms_org_id(),
        status=f["status"],
        date_from=f["date_from"],
        date_to=f["date_to"],
        q=f["q"],
        page=page,
        per_page=per_page,
        sort=f["sort"],
        direction=f["direction"],
    )
    return render_template(
        "admin/reservations/list.html",
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
        filters=f,
        saved_filters=admin_service.list_saved_filters(
            user_id=current_user.id, view_type="reservations"
        ),
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

    if request.method == "GET":
        allowed_unit_ids = {str(unit.id) for unit in units}
        unit_id = (request.args.get("unit_id") or "").strip()
        if unit_id in allowed_unit_ids:
            form["unit_id"] = unit_id
        for field in ("start_date", "end_date"):
            value = (request.args.get(field) or "").strip()
            try:
                if value:
                    date.fromisoformat(value)
            except ValueError:
                continue
            form[field] = value
    elif request.method == "POST":
        form["unit_id"] = (request.form.get("unit_id") or "").strip()
        form["guest_id"] = (request.form.get("guest_id") or "").strip()
        form["guest_search"] = (request.form.get("guest_search") or "").strip()
        form["guest_name"] = (request.form.get("guest_name") or "").strip()
        form["start_date"] = (request.form.get("start_date") or "").strip()
        form["end_date"] = (request.form.get("end_date") or "").strip()
        form["amount"] = (request.form.get("amount") or "").strip()
        form["currency"] = (request.form.get("currency") or "").strip().upper() or "EUR"

        if not form["unit_id"] or not form["start_date"] or not form["end_date"]:
            error = "Huone ja päivämäärät ovat pakollisia."
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
                error = "Huoneen ja asiakkaan tunnisteiden tulee olla numeroita."
            except reservation_service.ReservationServiceError as err:
                error = err.message
            else:
                flash("Varaus luotu.")
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
    tags = TagService.list_for_target(_pms_org_id(), "reservation", reservation_id)
    all_tags = TagService.list_for_org(_pms_org_id())
    comments = CommentService.list_for_target(
        _pms_org_id(), "reservation", reservation_id, include_internal=True
    )
    return render_template(
        "admin/reservations/detail.html",
        row=row,
        tags=tags,
        all_tags=all_tags,
        comments=comments,
        target_type="reservation",
    )


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
            flash("Tallennus epäonnistui", "error")
        else:
            flash("Varaus muokattu", "success")
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
        flash("Vahvista peruutus.")
        return redirect(url_for("admin.reservations_detail", reservation_id=reservation_id))

    try:
        _ = reservation_service.cancel_reservation(
            organization_id=_pms_org_id(),
            reservation_id=reservation_id,
            actor_user_id=current_user.id,
        )
    except reservation_service.ReservationServiceError:
        abort(404)

    flash("Varaus peruttu.")
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
    flash("Varaus merkitty maksetuksi.")
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
            error = "Sekä alku- että loppupäivä ovat pakollisia."
        else:
            from datetime import date

            try:
                start_date = date.fromisoformat(start_date_raw)
                end_date = date.fromisoformat(end_date_raw)
            except ValueError:
                error = "Päivämäärien tulee olla kelvollisia muodossa YYYY-MM-DD."
            else:
                if start_date >= end_date:
                    error = "Alkupäivän tulee olla ennen loppupäivää."
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


@admin_bp.get("/expenses")
@require_admin_pms_access
def expenses_list():
    org_id = _pms_org_id()
    property_raw = (request.args.get("property_id") or "").strip()
    property_id = int(property_raw) if property_raw.isdigit() else None
    rows = expense_service.list_expenses(organization_id=org_id, property_id=property_id)
    properties = (
        Property.query.filter_by(organization_id=org_id)
        .order_by(Property.name.asc(), Property.id.asc())
        .all()
    )
    return render_template(
        "admin/expenses/list.html",
        rows=rows,
        properties=properties,
        selected_property_id=property_id,
    )


@admin_bp.route("/expenses/new", methods=["GET", "POST"])
@require_admin_pms_access
def expenses_new():
    org_id = _pms_org_id()
    properties = (
        Property.query.filter_by(organization_id=org_id)
        .order_by(Property.name.asc(), Property.id.asc())
        .all()
    )
    form = {
        "property_id": "",
        "category": "other",
        "amount": "",
        "vat": "0.00",
        "date": date.today().isoformat(),
        "description": "",
        "payee": "",
    }
    error = None
    if request.method == "POST":
        form["property_id"] = (request.form.get("property_id") or "").strip()
        form["category"] = (request.form.get("category") or "").strip().lower()
        form["amount"] = (request.form.get("amount") or "").strip()
        form["vat"] = (request.form.get("vat") or "").strip()
        form["date"] = (request.form.get("date") or "").strip()
        form["description"] = (request.form.get("description") or "").strip()
        form["payee"] = (request.form.get("payee") or "").strip()
        property_id = int(form["property_id"]) if form["property_id"].isdigit() else None
        try:
            expense_service.create_expense(
                organization_id=org_id,
                property_id=property_id,
                category=form["category"],
                amount_raw=form["amount"],
                vat_raw=form["vat"],
                date_raw=form["date"],
                description=form["description"],
                payee=form["payee"],
                actor_user_id=current_user.id,
            )
        except expense_service.ExpenseServiceError as err:
            error = err.message
        else:
            flash("Kulu lisätty.")
            return redirect(url_for("admin.expenses_list"))
    return render_template(
        "admin/expenses/new.html",
        properties=properties,
        form=form,
        categories=expense_service.ALLOWED_CATEGORIES,
        error=error,
    )


def _report_xlsx_response(*, filename: str, columns: list[str], rows: list[list]):
    try:
        from openpyxl import Workbook
    except Exception:
        abort(400, description="openpyxl puuttuu, XLSX-vienti ei käytettävissä.")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Report"
    sheet.append(columns)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=filename,
    )


@admin_bp.get("/reports/cash-flow")
@require_admin_pms_access
def reports_cash_flow():
    org_id = _pms_org_id()
    start_date, end_date, error = _parse_report_range()
    property_raw = (request.args.get("property_id") or "").strip()
    property_id = int(property_raw) if property_raw.isdigit() else None
    export_format = (request.args.get("export") or "").strip().lower()
    data = report_service.cash_flow_report(
        organization_id=org_id,
        start_date=start_date,
        end_date=end_date,
        property_id=property_id,
    )
    if export_format in {"csv", "xlsx"}:
        export_rows = [
            [row["label"], str(row["income"]), str(row["expenses"]), str(row["net"])]
            for row in data["groups"]
        ]
        if export_format == "csv":
            sio = StringIO()
            writer = csv.writer(sio)
            writer.writerow(["period", "income", "expenses", "net"])
            writer.writerows(export_rows)
            return Response(
                sio.getvalue(),
                mimetype="text/csv; charset=utf-8",
                headers={"Content-Disposition": 'attachment; filename="cash-flow.csv"'},
            )
        return _report_xlsx_response(
            filename="cash-flow.xlsx",
            columns=["period", "income", "expenses", "net"],
            rows=export_rows,
        )
    properties = (
        Property.query.filter_by(organization_id=org_id)
        .order_by(Property.name.asc(), Property.id.asc())
        .all()
    )
    return render_template(
        "admin/reports/cash_flow.html",
        data=data,
        error=error,
        properties=properties,
        selected_property_id=property_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )


@admin_bp.get("/reports/income-breakdown")
@require_admin_pms_access
def reports_income_breakdown():
    org_id = _pms_org_id()
    start_date, end_date, error = _parse_report_range()
    property_raw = (request.args.get("property_id") or "").strip()
    property_id = int(property_raw) if property_raw.isdigit() else None
    export_format = (request.args.get("export") or "").strip().lower()
    data = report_service.income_breakdown_report(
        organization_id=org_id,
        start_date=start_date,
        end_date=end_date,
        property_id=property_id,
    )
    export_rows = [[row["label"], str(row["amount"])] for row in data["groups"]]
    if export_format == "csv":
        sio = StringIO()
        writer = csv.writer(sio)
        writer.writerow(["type", "amount"])
        writer.writerows(export_rows)
        return Response(
            sio.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="income-breakdown.csv"'},
        )
    if export_format == "xlsx":
        return _report_xlsx_response(
            filename="income-breakdown.xlsx",
            columns=["type", "amount"],
            rows=export_rows,
        )
    properties = (
        Property.query.filter_by(organization_id=org_id)
        .order_by(Property.name.asc(), Property.id.asc())
        .all()
    )
    return render_template(
        "admin/reports/income_breakdown.html",
        data=data,
        error=error,
        properties=properties,
        selected_property_id=property_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )


@admin_bp.get("/reports/expenses-breakdown")
@require_admin_pms_access
def reports_expenses_breakdown():
    org_id = _pms_org_id()
    start_date, end_date, error = _parse_report_range()
    property_raw = (request.args.get("property_id") or "").strip()
    property_id = int(property_raw) if property_raw.isdigit() else None
    export_format = (request.args.get("export") or "").strip().lower()
    data = report_service.expenses_breakdown_report(
        organization_id=org_id,
        start_date=start_date,
        end_date=end_date,
        property_id=property_id,
    )
    export_rows = [[row["label"], str(row["amount"])] for row in data["groups"]]
    if export_format == "csv":
        sio = StringIO()
        writer = csv.writer(sio)
        writer.writerow(["category", "amount"])
        writer.writerows(export_rows)
        return Response(
            sio.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="expenses-breakdown.csv"'},
        )
    if export_format == "xlsx":
        return _report_xlsx_response(
            filename="expenses-breakdown.xlsx",
            columns=["category", "amount"],
            rows=export_rows,
        )
    properties = (
        Property.query.filter_by(organization_id=org_id)
        .order_by(Property.name.asc(), Property.id.asc())
        .all()
    )
    return render_template(
        "admin/reports/expenses_breakdown.html",
        data=data,
        error=error,
        properties=properties,
        selected_property_id=property_id,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
    )


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
            error = "Huone, asiakas, alkupäivä ja vuokra ovat pakollisia."
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
                error = "Huoneen, asiakkaan ja varauksen tunnisteiden tulee olla numeroita."
            except billing_service.LeaseServiceError as err:
                error = err.message
            else:
                flash("Vuokrasopimus luotu.")
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
                    message="Huone ja asiakas ovat pakollisia.",
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
            error = "Huoneen, asiakkaan ja varauksen tunnisteiden tulee olla numeroita."
        except billing_service.LeaseServiceError as err:
            if err.status == 404:
                abort(404)
            error = err.message
        else:
            flash("Vuokrasopimus päivitetty.")
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
    flash("Vuokrasopimus aktivoitu.")
    return redirect(url_for("admin.leases_detail", lease_id=lease_id))


@admin_bp.post("/leases/<int:lease_id>/end")
@require_admin_pms_access
def leases_end(lease_id: int):
    if (request.form.get("confirm_end") or "").strip().lower() != "yes":
        flash("Vahvista vuokrasopimuksen päättäminen.")
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
    flash("Vuokrasopimus päätetty.")
    return redirect(url_for("admin.leases_detail", lease_id=lease_id))


@admin_bp.post("/leases/<int:lease_id>/cancel")
@require_admin_pms_access
def leases_cancel(lease_id: int):
    if (request.form.get("confirm_cancel") or "").strip().lower() != "yes":
        flash("Vahvista peruutus.")
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
    flash("Vuokrasopimus peruttu.")
    return redirect(url_for("admin.leases_detail", lease_id=lease_id))


@admin_bp.get("/invoices")
@require_admin_pms_access
def invoices_list():
    page, per_page = _pms_pagination()
    f = _list_filters()
    rows, total = admin_service.list_admin_invoices(
        organization_id=_pms_org_id(),
        status=f["status"],
        date_from=f["date_from"],
        date_to=f["date_to"],
        q=f["q"],
        page=page,
        per_page=per_page,
        sort=f["sort"],
        direction=f["direction"],
    )
    return render_template(
        "admin/invoices/list.html",
        rows=rows,
        page=page,
        per_page=per_page,
        total=total,
        filters=f,
        saved_filters=admin_service.list_saved_filters(user_id=current_user.id, view_type="invoices"),
    )


@admin_bp.route("/invoices/new", methods=["GET", "POST"])
@require_admin_pms_access
def invoices_new():
    org_id = _pms_org_id()
    lease_rows = billing_service.list_leases_for_org(organization_id=org_id)
    form = {
        "lease_id": "",
        "subtotal_excl_vat": "",
        "vat_rate": "",
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
        form["subtotal_excl_vat"] = (request.form.get("subtotal_excl_vat") or "").strip()
        form["vat_rate"] = (request.form.get("vat_rate") or "").strip()
        form["currency"] = (request.form.get("currency") or "").strip().upper() or "EUR"
        form["due_date"] = (request.form.get("due_date") or "").strip()
        form["description"] = (request.form.get("description") or "").strip()
        form["status"] = (request.form.get("status") or "").strip().lower() or "open"
        form["guest_id"] = (request.form.get("guest_id") or "").strip()
        form["reservation_id"] = (request.form.get("reservation_id") or "").strip()

        if not form["due_date"]:
            error = "Eräpäivä on pakollinen."
        elif form["lease_id"]:
            try:
                row = billing_service.create_invoice_for_lease(
                    organization_id=org_id,
                    lease_id=int(form["lease_id"]),
                    subtotal_excl_vat_raw=form["subtotal_excl_vat"] or None,
                    due_date_raw=form["due_date"],
                    currency=form["currency"],
                    description=form["description"] or None,
                    status=form["status"],
                    actor_user_id=current_user.id,
                    vat_rate_raw=form["vat_rate"] or None,
                )
            except (TypeError, ValueError):
                error = "Vuokrasopimuksen tunnisteen tulee olla numero."
            except billing_service.InvoiceServiceError as err:
                error = err.message
                flash("Tallennus epäonnistui", "error")
            else:
                flash("Lasku tallennettu", "success")
                return redirect(url_for("admin.invoices_detail", invoice_id=row["id"]))
        else:
            if not form["subtotal_excl_vat"]:
                error = "Veroton summa on pakollinen, jos vuokrasopimusta ei ole valittu."
            else:
                try:
                    res_id = int(form["reservation_id"]) if form["reservation_id"] else None
                    guest_id = int(form["guest_id"]) if form["guest_id"] else None
                    row = billing_service.create_invoice(
                        organization_id=org_id,
                        subtotal_excl_vat_raw=form["subtotal_excl_vat"],
                        due_date_raw=form["due_date"],
                        currency=form["currency"],
                        description=form["description"] or None,
                        lease_id=None,
                        reservation_id=res_id,
                        guest_id=guest_id,
                        status=form["status"],
                        metadata_json=None,
                        actor_user_id=current_user.id,
                        vat_rate_raw=form["vat_rate"] or None,
                    )
                except (TypeError, ValueError):
                    error = "Asiakkaan ja varauksen tunnisteiden tulee olla numeroita, jos ne annetaan."
                except billing_service.InvoiceServiceError as err:
                    error = err.message
                    flash("Tallennus epäonnistui", "error")
                else:
                    flash("Lasku tallennettu", "success")
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
    payment_rows = (
        Payment.query.filter_by(organization_id=_pms_org_id(), invoice_id=invoice_id)
        .order_by(Payment.id.desc())
        .limit(20)
        .all()
    )
    from app.payments.services import refundable_outstanding_amount

    payment_outstanding = {p.id: refundable_outstanding_amount(p.id) for p in payment_rows}
    refunds_by_payment_id: dict[int, list] = {
        p.id: PaymentRefund.query.filter_by(payment_id=p.id).order_by(PaymentRefund.id.desc()).all()
        for p in payment_rows
    }
    return render_template(
        "admin/invoices/detail.html",
        row=row,
        payment_rows=payment_rows,
        payment_outstanding=payment_outstanding,
        refunds_by_payment_id=refunds_by_payment_id,
    )


@admin_bp.post("/invoices/<int:invoice_id>/send-payment-link")
@require_admin_pms_access
def invoices_send_payment_link(invoice_id: int):
    provider = (request.form.get("provider") or "stripe").strip().lower()
    configured_return = (current_app.config.get("PAYMENT_RETURN_URL") or "").strip()
    if configured_return:
        base_return = configured_return
        sep = "&" if "?" in base_return else "?"
        return_url = (
            f"{base_return}{sep}payment_id={{payment_id}}"
            if "{payment_id}" not in base_return
            else base_return
        )
    else:
        base_return = url_for("portal.payment_return", _external=True)
        sep = "&" if "?" in base_return else "?"
        return_url = f"{base_return}{sep}payment_id={{payment_id}}"
    try:
        checkout = payment_service.create_checkout(
            invoice_id=invoice_id,
            provider_name=provider,
            return_url=return_url,
            cancel_url=url_for("portal.payment_cancel", invoice_id=invoice_id, _external=True),
            actor_user_id=current_user.id,
            idempotency_key=(request.headers.get("Idempotency-Key") or "").strip() or None,
        )
    except payment_service.PaymentServiceError as err:
        flash(err.message)
        return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))
    flash(f"Maksulinkki luotu: {checkout['redirect_url']}")
    return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))


@admin_bp.post("/invoices/<int:invoice_id>/refunds/<int:refund_id>/retry")
@require_admin_pms_access
def invoices_refund_retry(invoice_id: int, refund_id: int):
    refund_row = PaymentRefund.query.get(refund_id)
    if refund_row is None:
        abort(404)
    payment = Payment.query.get(refund_row.payment_id)
    if (
        payment is None
        or payment.organization_id != _pms_org_id()
        or payment.invoice_id != invoice_id
    ):
        abort(404)
    try:
        _ = payment_service.retry_refund(refund_id, actor_user_id=current_user.id)
    except payment_service.PaymentServiceError as err:
        flash(err.message)
        return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))
    flash("Hyvityksen uudelleenyritys käynnistetty.")
    return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))


@admin_bp.post("/payments/<int:payment_id>/refund")
@require_admin_pms_access
@require_tenant_access("payment", id_arg="payment_id")
def payments_refund(payment_id: int):
    try:
        _ = payment_service.refund(
            payment_id=payment_id,
            amount=request.form.get("amount"),
            reason=request.form.get("reason"),
            actor_user_id=current_user.id,
            idempotency_key=(request.headers.get("Idempotency-Key") or "").strip() or None,
        )
    except payment_service.PaymentServiceError as err:
        flash(err.message)
        return redirect(request.referrer or url_for("admin.payments_list"))
    flash("Hyvitys käynnistetty.")
    return redirect(request.referrer or url_for("admin.payments_list"))


@admin_bp.get("/payments")
@require_admin_pms_access
def payments_list():
    q = Payment.query.filter_by(organization_id=_pms_org_id())
    provider = (request.args.get("provider") or "").strip()
    status = (request.args.get("status") or "").strip()
    date_from = _parse_optional_date("from")
    date_to = _parse_optional_date("to")
    if provider:
        q = q.filter(Payment.provider == provider)
    if status:
        q = q.filter(Payment.status == status)
    if date_from:
        q = q.filter(Payment.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(Payment.created_at <= datetime.combine(date_to, datetime.max.time()))
    rows = q.order_by(Payment.id.desc()).limit(200).all()
    return render_template(
        "admin/payments/list.html",
        rows=rows,
        provider=provider,
        status=status,
        date_from=(request.args.get("from") or ""),
        date_to=(request.args.get("to") or ""),
    )


@admin_bp.get("/payments/export")
@require_admin_pms_access
def payments_export():
    q = Payment.query.filter_by(organization_id=_pms_org_id())
    provider = (request.args.get("provider") or "").strip()
    status = (request.args.get("status") or "").strip()
    date_from = _parse_optional_date("from")
    date_to = _parse_optional_date("to")
    if provider:
        q = q.filter(Payment.provider == provider)
    if status:
        q = q.filter(Payment.status == status)
    if date_from:
        q = q.filter(Payment.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to:
        q = q.filter(Payment.created_at <= datetime.combine(date_to, datetime.max.time()))
    rows = q.order_by(Payment.id.desc()).all()
    sio = StringIO()
    writer = csv.writer(sio)
    writer.writerow(
        ["id", "created_at", "provider", "amount", "currency", "status", "method", "invoice_number", "customer_email"]
    )
    for row in rows:
        inv = Invoice.query.get(row.invoice_id) if row.invoice_id else None
        writer.writerow(
            [
                row.id,
                row.created_at.isoformat() if row.created_at else "",
                row.provider,
                str(row.amount),
                row.currency,
                row.status,
                row.method or "",
                inv.invoice_number if inv else "",
                getattr(getattr(inv, "guest", None), "email", "") if inv else "",
            ]
        )
    audit_record(
        "payment.exported",
        status=AuditStatus.SUCCESS,
        organization_id=_pms_org_id(),
        target_type="payment",
        target_id=None,
        metadata={"format": "csv", "count": len(rows)},
        commit=True,
    )
    return Response(
        sio.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=payments.csv"},
    )


@admin_bp.get("/invoices/<int:invoice_id>/pdf")
@require_admin_pms_access
@require_tenant_access("invoice", id_arg="invoice_id", allow_superadmin_all_tenants=True)
def invoices_pdf(invoice_id: int):
    inv = g.scoped_entity
    try:
        pdf_bytes = generate_invoice_pdf(invoice_id)
    except billing_service.InvoiceServiceError as err:
        if err.status == 404:
            abort(404)
        abort(400)
    billing_service.log_invoice_pdf_downloaded(
        invoice_id=invoice_id,
        organization_id=inv.organization_id,
    )
    safe_name = (inv.invoice_number or f"INV-{inv.id}").replace("/", "-").replace("\\", "-")
    return send_file(
        BytesIO(pdf_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"lasku-{safe_name}.pdf",
    )


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
    flash("Lasku merkitty maksetuksi.")
    return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))


@admin_bp.post("/invoices/<int:invoice_id>/cancel")
@require_admin_pms_access
def invoices_cancel(invoice_id: int):
    if (request.form.get("confirm_cancel") or "").strip().lower() != "yes":
        flash("Vahvista peruutus.")
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
    flash("Lasku peruttu.")
    return redirect(url_for("admin.invoices_detail", invoice_id=invoice_id))


@admin_bp.post("/invoices/mark-overdue")
@require_admin_pms_access
def invoices_mark_overdue():
    n = billing_service.mark_overdue_invoices(organization_id=_pms_org_id())
    flash(f"{n} laskua merkitty erääntyneeksi.")
    return redirect(url_for("admin.invoices_list"))


def _parse_bulk_ids() -> list[int]:
    raw_values = request.form.getlist("ids")
    if not raw_values and request.is_json:
        payload = request.get_json(silent=True) or {}
        raw_values = [str(v) for v in payload.get("ids", [])]
    ids: list[int] = []
    for raw in raw_values:
        try:
            ids.append(int(raw))
        except (TypeError, ValueError):
            continue
    return sorted(set(ids))


@admin_bp.post("/reservations/bulk")
@require_admin_pms_access
def reservations_bulk():
    ids = _parse_bulk_ids()
    action = (request.form.get("action") or "").strip()
    idem_key = (request.headers.get("Idempotency-Key") or request.form.get("idempotency_key") or "").strip()
    if not idem_key:
        return json_error("idempotency_key_required", "Idempotency key required.", status=400)
    if len(ids) > 1000:
        return json_error("too_many_ids", "Too many ids for synchronous processing.", status=422)
    req_hash = hashlib.sha256(json.dumps({"action": action, "ids": ids}, sort_keys=True).encode("utf-8")).hexdigest()
    try:
        idem_row, created = admin_service._apply_idempotency_key(
            key=idem_key,
            endpoint="admin.reservations.bulk",
            organization_id=_pms_org_id(),
            request_hash=req_hash,
        )
    except Exception:
        return json_error("idempotency_key_conflict", "Conflicting idempotency key.", status=409)
    if not created and idem_row.response_body:
        return Response(idem_row.response_body, status=idem_row.response_status, mimetype="application/json")
    if action == "cancel":
        for rid in ids:
            try:
                reservation_service.cancel_reservation(
                    organization_id=_pms_org_id(), reservation_id=rid, actor_user_id=current_user.id
                )
            except reservation_service.ReservationServiceError as err:
                if err.status in {403, 404}:
                    return json_error("forbidden", "One or more ids are outside tenant scope.", status=403)
                raise
            audit_record(
                "reservation.bulk_cancelled",
                status=AuditStatus.SUCCESS,
                organization_id=_pms_org_id(),
                target_type="reservation",
                target_id=rid,
                commit=True,
            )
    body = {"success": True, "data": {"count": len(ids)}, "error": None}
    admin_service.record_response(idem_row, 200, body)
    return json_ok({"count": len(ids)})


@admin_bp.post("/invoices/bulk")
@require_admin_pms_access
def invoices_bulk():
    ids = _parse_bulk_ids()
    if len(ids) > 1000:
        return json_error("too_many_ids", "Too many ids for synchronous processing.", status=422)
    action = (request.form.get("action") or "").strip()
    if action == "mark_paid":
        for iid in ids:
            billing_service.mark_invoice_paid(
                organization_id=_pms_org_id(), invoice_id=iid, actor_user_id=current_user.id
            )
            audit_record(
                "invoice.bulk_marked_paid",
                status=AuditStatus.SUCCESS,
                organization_id=_pms_org_id(),
                target_type="invoice",
                target_id=iid,
                commit=True,
            )
    return json_ok({"count": len(ids)})


@admin_bp.post("/guests/bulk")
@require_admin_pms_access
def guests_bulk():
    ids = _parse_bulk_ids()
    if len(ids) > 1000:
        return json_error("too_many_ids", "Too many ids for synchronous processing.", status=422)
    action = (request.form.get("action") or "").strip()
    if action == "delete" and not current_user.is_superadmin:
        abort(403)
    for gid in ids:
        audit_record(
            "guest.bulk_tagged",
            status=AuditStatus.SUCCESS,
            organization_id=_pms_org_id(),
            target_type="guest",
            target_id=gid,
            commit=True,
        )
    return json_ok({"count": len(ids)})


@admin_bp.get("/<string:resource>/export")
@require_admin_pms_access
def resource_export(resource: str):
    fmt = (request.args.get("format") or "csv").strip().lower()
    if fmt != "csv":
        abort(400)
    f = _list_filters()
    page, per_page = 1, 10000
    org_id = _pms_org_id()
    if resource == "reservations":
        rows, total = admin_service.list_admin_reservations(
            organization_id=org_id,
            status=f["status"],
            date_from=f["date_from"],
            date_to=f["date_to"],
            q=f["q"],
            page=page,
            per_page=per_page,
            sort=f["sort"],
            direction=f["direction"],
        )
        cols = ["id", "guest_name", "start_date", "end_date", "status", "unit_id"]
    elif resource == "invoices":
        rows, total = admin_service.list_admin_invoices(
            organization_id=org_id,
            status=f["status"],
            date_from=f["date_from"],
            date_to=f["date_to"],
            q=f["q"],
            page=page,
            per_page=per_page,
            sort=f["sort"],
            direction=f["direction"],
        )
        cols = ["id", "invoice_number", "status", "due_date", "currency", "total_incl_vat"]
    elif resource == "guests":
        rows, total = admin_service.list_admin_guests(
            organization_id=org_id,
            status=f["status"],
            date_from=f["date_from"],
            date_to=f["date_to"],
            q=f["q"],
            page=page,
            per_page=per_page,
            sort=f["sort"],
            direction=f["direction"],
        )
        cols = ["id", "full_name", "email", "phone", "created_at"]
    else:
        abort(404)
    if total > 10000:
        try:
            send_template(
                TemplateKey.ADMIN_NOTIFICATION,
                to=current_user.email,
                context={
                    "subject_line": f"{resource} export queued",
                    "message": f"{total} rows requested, export queued.",
                    "organization_id": current_user.organization_id,
                },
            )
        except Exception:
            pass
        return json_ok({"queued": True, "count": total})
    csv_text = admin_service._csv_for_rows(rows=rows, columns=cols)
    audit_record(
        f"{resource}.exported",
        status=AuditStatus.SUCCESS,
        organization_id=org_id,
        target_type=resource,
        metadata={"format": "csv", "count": total},
        commit=True,
    )
    return Response(
        csv_text,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{resource}.csv"'},
    )


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
            error = "Kohde ja otsikko ovat pakollisia."
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
                error = "Tunnisteiden tulee olla numeroita."
            except maintenance_service.MaintenanceServiceError as err:
                error = err.message
            else:
                flash("Huoltopyyntö luotu.")
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
        flash("Tätä pyyntöä ei voi muokata.")
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
            error = "Kohde ja otsikko ovat pakollisia."
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
                error = "Tunnisteiden tulee olla numeroita."
            except maintenance_service.MaintenanceServiceError as err:
                if err.status == 404:
                    abort(404)
                error = err.message
            else:
                flash("Huoltopyyntö päivitetty.")
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
        flash("Tila päivitetty.")
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
        flash("Virheellinen vastuuhenkilö.")
    except maintenance_service.MaintenanceServiceError as err:
        if err.status == 404:
            abort(404)
        flash(err.message)
    else:
        flash("Vastuuhenkilö päivitetty.")
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
        flash("Pyyntö merkitty ratkaistuksi.")
    return redirect(url_for("admin.maintenance_requests_detail", request_id=request_id))


@admin_bp.post("/maintenance-requests/<int:request_id>/cancel")
@require_admin_pms_access
def maintenance_requests_cancel(request_id: int):
    if (request.form.get("confirm_cancel") or "").strip().lower() != "yes":
        flash("Vahvista peruutus.")
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
        flash("Pyyntö peruttu.")
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


@admin_bp.get("/api/audit-events")
@require_superadmin_2fa
def audit_events_api():
    from_raw = (request.args.get("from") or "").strip()
    to_raw = (request.args.get("to") or "").strip()
    action_filters = _parse_csv_filter_args("action")
    user_filters = _parse_csv_filter_args("user")
    entity_filters = _parse_csv_filter_args("entity")
    try:
        page = max(int(request.args.get("page", "1") or 1), 1)
    except ValueError:
        page = 1
    page_size = 50

    query = AuditLog.query
    if from_raw:
        try:
            start = datetime.strptime(from_raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            query = query.filter(AuditLog.created_at >= start)
        except ValueError:
            return json_error("invalid_from", "Virheellinen from-parametri.", status=400)
    if to_raw:
        try:
            end = datetime.strptime(to_raw, "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            query = query.filter(AuditLog.created_at < end)
        except ValueError:
            return json_error("invalid_to", "Virheellinen to-parametri.", status=400)
    if user_filters:
        user_ids = [int(value) for value in user_filters if value.isdigit()]
        if user_ids:
            query = query.filter(AuditLog.actor_id.in_(user_ids))
    if action_filters:
        ilike_filters = [AuditLog.action.ilike(f"%{value}%") for value in action_filters]
        query = query.filter(or_(*ilike_filters))
    if entity_filters:
        query = query.filter(AuditLog.target_type.in_(entity_filters))

    ordered = query.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
    offset = (page - 1) * page_size
    rows = ordered.offset(offset).limit(page_size + 1).all()
    has_next = len(rows) > page_size
    rows = rows[:page_size]

    payload = []
    for row in rows:
        action_type = _normalize_action_type(row.action or "")
        entity_key, entity_label = _label_from_entity(row.target_type)
        actor_name = (row.actor_email or "Jarjestelma").split("@")[0].replace(".", " ").strip().title() or "Jarjestelma"
        entity_ref = f"{entity_key[:3].upper()}-{row.target_id}" if row.target_id else None
        action_label = _label_from_action_type(action_type)
        summary = f"{actor_name} {action_label.lower()} {entity_label.lower()}"
        if entity_ref:
            summary = f"{summary} {entity_ref}"
        payload.append(
            {
                "id": row.id,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "action": row.action,
                "action_label": action_label,
                "action_type": action_type,
                "actor_id": row.actor_id,
                "actor_name": actor_name,
                "actor_email": row.actor_email,
                "actor_avatar": None,
                "entity_type": entity_key,
                "entity_label": entity_label,
                "entity_id": row.target_id,
                "entity_ref": entity_ref,
                "entity_url": None,
                "summary": summary,
                "time_label": f"klo {(row.created_at or datetime.now(timezone.utc)).strftime('%H:%M')}",
                "diff": _context_to_diff(row.context),
            }
        )

    if request.args.get("format") == "csv":
        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["id", "created_at", "action", "actor_email", "target_type", "target_id", "status"])
        for row in rows:
            writer.writerow(
                [
                    row.id,
                    row.created_at.isoformat() if row.created_at else "",
                    row.action or "",
                    row.actor_email or "",
                    row.target_type or "",
                    row.target_id or "",
                    row.status or "",
                ]
            )
        csv_data = buffer.getvalue()
        return Response(
            csv_data,
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=audit-events.csv"},
        )

    user_rows = (
        db.session.query(AuditLog.actor_id, AuditLog.actor_email)
        .filter(AuditLog.actor_id.isnot(None))
        .distinct()
        .limit(150)
        .all()
    )
    users = [
        {
            "id": actor_id,
            "name": ((actor_email or f"User {actor_id}").split("@")[0].replace(".", " ").title()),
            "avatar": None,
        }
        for actor_id, actor_email in user_rows
        if actor_id is not None
    ]
    return json_ok(
        {
            "events": payload,
            "page": page,
            "has_next": has_next,
            "users": users,
            "actions": [
                {"key": "create", "label": "Luotu"},
                {"key": "update", "label": "Muokattu"},
                {"key": "delete", "label": "Poistettu"},
                {"key": "login", "label": "Login"},
                {"key": "send", "label": "Lahetetty"},
            ],
            "entities": [
                {"key": "invoice", "label": "Lasku"},
                {"key": "customer", "label": "Asiakas"},
                {"key": "contract", "label": "Sopimus"},
                {"key": "property", "label": "Kohde"},
                {"key": "user", "label": "Kayttaja"},
            ],
        }
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


def _email_queue_query_for_current_user():
    query = EmailQueueItem.query
    if current_user.is_superadmin:
        return query
    return query.filter(EmailQueueItem.organization_id == _pms_org_id())


@admin_bp.get("/email-queue")
@require_admin_pms_access
def email_queue_list():
    rows = _email_queue_query_for_current_user().order_by(EmailQueueItem.created_at.desc()).limit(200).all()
    return render_template("admin_email_queue.html", rows=rows)


@admin_bp.post("/email-queue/<int:item_id>/retry")
@require_admin_pms_access
def email_queue_retry(item_id: int):
    row = _email_queue_query_for_current_user().filter(EmailQueueItem.id == item_id).first()
    if row is None:
        abort(404)
    if row.status != OutgoingEmailStatus.FAILED:
        flash("Vain epäonnistuneen viestin voi yrittää uudelleen.")
        return redirect(url_for("admin.email_queue_list"))
    row.status = OutgoingEmailStatus.PENDING
    row.next_attempt_at = datetime.now(timezone.utc)
    row.sync_compat_fields()
    db.session.add(row)
    db.session.commit()
    audit_record(
        "email.retry_requested",
        status=AuditStatus.SUCCESS,
        organization_id=row.organization_id,
        target_type="email_queue",
        target_id=row.id,
        metadata={"template_key": row.template_key, "status": row.status, "attempt_count": row.effective_attempt_count},
        commit=True,
    )
    flash("Sähköposti asetettu uudelleen jonoon.")
    return redirect(url_for("admin.email_queue_list"))


@admin_bp.post("/email-queue/<int:item_id>/cancel")
@require_admin_pms_access
def email_queue_cancel(item_id: int):
    row = _email_queue_query_for_current_user().filter(EmailQueueItem.id == item_id).first()
    if row is None:
        abort(404)
    if row.status != OutgoingEmailStatus.PENDING:
        flash("Vain jonossa olevan viestin voi perua.")
        return redirect(url_for("admin.email_queue_list"))
    row.status = OutgoingEmailStatus.CANCELLED
    row.next_attempt_at = None
    row.sync_compat_fields()
    db.session.add(row)
    db.session.commit()
    audit_record(
        "email.cancelled",
        status=AuditStatus.SUCCESS,
        organization_id=row.organization_id,
        target_type="email_queue",
        target_id=row.id,
        metadata={"template_key": row.template_key, "status": row.status},
        commit=True,
    )
    flash("Sähköpostin lähetys peruttu.")
    return redirect(url_for("admin.email_queue_list"))


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
            flash("Anna kelvollinen vastaanottajan sähköpostiosoite.")
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
            flash("Testiviesti lähetetty onnistuneesti.")
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
            flash(f"Testiviestin lähetys epäonnistui: {err.public_message}")
    elif request.method == "POST":
        flash("Anna kelvollinen vastaanottajan sähköpostiosoite.")

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
            update_email_template_admin(
                template=template,
                subject=form.subject.data.strip(),
                body_text=form.body_text.data,
                body_html=(form.body_html.data or "").strip() or None,
                actor_id=current_user.id,
            )
            flash("Pohja tallennettu.")
            return redirect(url_for("admin.email_template_edit", key=key))
        else:
            error = "Tarkista lomakkeen kentät."

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
            error = f"Asetus avaimella {setting_key!r} on jo olemassa."
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
                error = f"Virheellinen arvo tyypille {setting_type!r}: {err}"
            else:
                flash(f"Asetus {setting_key!r} luotu.")
                return redirect(url_for("admin.settings_edit", key=setting_key))
    elif request.method == "POST":
        error = "Korjaa korostetut kentät."

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
            if not admin_service.verify_fresh_2fa_code(user=current_user, code=code):
                error = "Salaisuuden näyttämiseen vaaditaan kelvollinen tuore 2FA-koodi."
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
                    error = f"Virheellinen arvo tyypille {row.type!r}: {err}"
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
                    flash("Asetus tallennettu.")
                    return redirect(url_for("admin.settings_edit", key=row.key))
        else:
            error = "Korjaa korostetut kentät."

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
            error = f"Käyttäjä '{normalized_email}' on jo olemassa."
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
                flash(f"Käyttäjä {user.email} luotu.")
                return redirect(url_for("admin.users_list"))
    elif request.method == "POST":
        error = "Korjaa korostetut kentät."

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
            flash("Käyttäjän tiedot päivitetty.")
            return redirect(url_for("admin.users_list"))
    elif request.method == "POST":
        error = "Korjaa korostetut kentät."

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
    try:
        target_user = admin_service.superadmin_toggle_user_active(
            user_id=user_id,
            actor_id=current_user.id,
            actor_email=current_user.email,
        )
    except admin_service.UserServiceError as err:
        flash(str(err))
        return redirect(url_for("admin.users_list"))
    flash(
        f"Käyttäjä {target_user.email} on nyt "
        f"{'aktiivinen' if target_user.is_active else 'poistettu käytöstä'}."
    )
    return redirect(url_for("admin.users_list"))


@admin_bp.route("/gdpr/<int:user_id>", methods=["GET", "POST"])
@require_superadmin_2fa
@check_impersonation_blocked
def gdpr_user(user_id: int):
    """Superadmin GDPR tools for a single user (export / anonymize / delete)."""

    target_user = User.query.get_or_404(user_id)
    error: str | None = None

    if request.method == "POST":
        action = (request.form.get("action") or "").strip()
        if action == "export":
            data = export_user_data(target_user.id)
            filename = f"gdpr-export-{target_user.id}.json"
            return Response(
                export_json_safe(data),
                mimetype="application/json; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        elif action == "anonymize":
            try:
                anonymize_user_data(target_user.id)
            except UserServiceError as err:
                error = str(err)
            else:
                flash("Käyttäjä anonymisoitu.")
                return redirect(url_for("admin.gdpr_user", user_id=user_id))
        elif action == "delete":
            password = request.form.get("password") or ""
            totp_code = (request.form.get("totp_code") or "").replace(" ", "").strip()
            if not current_user.check_password(password):
                error = "Virheellinen salasana."
            elif not current_user.verify_totp(totp_code):
                error = "Virheellinen 2FA-koodi."
            else:
                try:
                    delete_user_data(target_user.id, from_cli=False)
                except UserServiceError as err:
                    error = str(err)
                except GdprPermissionError:
                    abort(403)
                else:
                    flash("Käyttäjä poistettu pysyvästi.")
                    return redirect(url_for("admin.users_list"))
        else:
            error = "Tuntematon toiminto."

    return render_template("admin_gdpr.html", target_user=target_user, error=error)


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
        org, create_error = admin_service.create_organization_superadmin(
            name=form.name.data.strip(),
            actor_id=current_user.id,
            actor_email=current_user.email,
        )
        if create_error:
            error = create_error
        else:
            flash(f"Organisaatio '{org.name}' luotu.")
            return redirect(url_for("admin.organizations_list"))
    elif request.method == "POST":
        error = "Korjaa korostetut kentät."

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
        admin_service.update_organization_superadmin(
            org=org,
            new_name=form.name.data.strip(),
            actor_id=current_user.id,
            actor_email=current_user.email,
        )
        flash("Organisaation tiedot päivitetty.")
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
            owners_service.create_owner_with_optional_login_user_and_commit(
                organization_id=current_user.organization_id,
                name=(request.form.get("name") or "").strip(),
                email=(request.form.get("email") or "").strip(),
                phone=(request.form.get("phone") or "").strip() or None,
                payout_iban=(request.form.get("payout_iban") or "").strip() or None,
                password=(request.form.get("password") or "").strip() or None,
            )
            flash("Omistaja luotu.")
            return redirect(url_for("admin.owners_list"))
        except Exception:
            db.session.rollback()
            error = "Omistajan luonti epäonnistui."
    return render_template("admin/owners_new.html", error=error)


@admin_bp.post("/owners/<int:owner_id>/assign-property")
@require_superadmin_2fa
def owners_assign_property(owner_id: int):
    from datetime import date
    from decimal import Decimal

    try:
        valid_from = date.fromisoformat((request.form.get("valid_from") or "").strip())
        valid_to_raw = (request.form.get("valid_to") or "").strip()
        owners_service.assign_owner_property_and_commit(
            owner_id=owner_id,
            organization_id=current_user.organization_id,
            property_id=int(request.form.get("property_id")),
            ownership_pct=Decimal((request.form.get("ownership_pct") or "1").strip()),
            management_fee_pct=Decimal((request.form.get("management_fee_pct") or "0").strip()),
            valid_from=valid_from,
            valid_to=date.fromisoformat(valid_to_raw) if valid_to_raw else None,
        )
        flash("Kohde liitetty omistajalle.")
    except Exception:
        db.session.rollback()
        flash("Kohteen liittäminen omistajalle epäonnistui.")
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
    form.user_id.choices = [(0, "-- ei käyttäjää (organisaatiotaso) --")] + [(u.id, u.email) for u in users]
    error: str | None = None

    if form.validate_on_submit():
        selected_user_id = (
            form.user_id.data if form.user_id.data and form.user_id.data > 0 else None
        )
        expires_at = form.expires_at.data
        selected_scopes = list(form.scopes.data or [])
        try:
            api_key, raw_key = create_api_key_admin(
                name=form.name.data.strip(),
                organization_id=form.organization_id.data,
                user_id=selected_user_id,
                scopes=selected_scopes,
                expires_at=expires_at,
                actor_id=current_user.id,
                actor_email=current_user.email,
                actor_is_superadmin=current_user.is_superadmin,
            )
        except ApiKeyAdminError as err:
            error = err.message
        else:
            flash("API-avain luotu. Selväkielinen avain näytetään alla vain kerran — kopioi se heti.")
            return redirect(url_for("admin.api_keys_list", show_raw=raw_key))
    elif request.method == "POST":
        error = "Korjaa korostetut kentät."

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
    api_key = toggle_api_key_active_admin(
        key_id=key_id, actor_id=current_user.id, actor_email=current_user.email
    )
    flash(
        f"API-avain {api_key.key_prefix} on nyt "
        f"{'aktiivinen' if api_key.is_active else 'poistettu käytöstä'}."
    )
    return redirect(url_for("admin.api_keys_list"))


@admin_bp.post("/api-keys/<int:key_id>/delete")
@require_superadmin_2fa
def api_keys_delete(key_id: int):
    prefix = delete_api_key_admin(
        key_id=key_id, actor_id=current_user.id, actor_email=current_user.email
    )
    flash(f"API-avain {prefix} poistettu.")
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


# ---------------------------------------------------------------------------
# Outbound webhooks (tenant-scoped; superadmin + 2FA)
# ---------------------------------------------------------------------------


@admin_bp.get("/webhooks")
@require_superadmin_2fa
def webhooks_list():
    from app.webhooks.services import list_recent_deliveries, list_subscriptions_for_org

    org_id = _pms_org_id()
    subs = list_subscriptions_for_org(organization_id=org_id)
    deliveries_by_sub = {
        s.id: list_recent_deliveries(subscription_id=s.id, limit=10) for s in subs
    }
    raw_secret = (request.args.get("show_webhook_secret") or "").strip() or None
    return render_template(
        "admin_webhooks.html",
        subscriptions=subs,
        deliveries_by_sub=deliveries_by_sub,
        raw_secret=raw_secret,
    )


@admin_bp.get("/webhooks/<int:subscription_id>")
@require_superadmin_2fa
@require_tenant_access("webhook_subscription", id_arg="subscription_id")
def webhooks_detail(subscription_id: int):
    from app.webhooks.services import list_recent_deliveries

    sub = g.scoped_entity
    deliveries = list_recent_deliveries(subscription_id=sub.id, limit=20)
    return render_template(
        "admin_webhooks_detail.html",
        subscription=sub,
        deliveries=deliveries,
    )


@admin_bp.route("/webhooks/new", methods=["GET", "POST"])
@require_superadmin_2fa
def webhooks_new():
    from app.webhooks.services import create_outbound_subscription

    error: str | None = None
    if request.method == "POST":
        url = (request.form.get("url") or "").strip()
        events_raw = (request.form.get("events") or "").strip()
        events = [e.strip() for e in events_raw.replace("\n", ",").split(",") if e.strip()]
        if not url or not events:
            error = "URL ja vähintään yksi tapahtumatunniste (pilkuilla erotettu) vaaditaan."
        else:
            sub, raw = create_outbound_subscription(
                organization_id=_pms_org_id(),
                url=url,
                events=events,
                created_by_user_id=current_user.id,
            )
            audit_record(
                "webhook.subscription_created",
                status=AuditStatus.SUCCESS,
                actor_id=current_user.id,
                organization_id=_pms_org_id(),
                target_type="webhook_subscription",
                target_id=sub.id,
                metadata={"url": url, "events": events},
                commit=True,
            )
            flash(
                "Webhook-tilaus luotu. Allekirjoitusavain näytetään vain kerran — kopioi se heti.",
                "success",
            )
            return redirect(url_for("admin.webhooks_list", show_webhook_secret=raw))
    return render_template("admin_webhooks_new.html", error=error)


@admin_bp.post("/webhooks/<int:subscription_id>/deactivate")
@require_superadmin_2fa
def webhooks_deactivate(subscription_id: int):
    from app.webhooks.services import deactivate_outbound_subscription

    ok = deactivate_outbound_subscription(
        subscription_id=subscription_id,
        organization_id=_pms_org_id(),
    )
    if not ok:
        flash("Tilausta ei löytynyt tai se kuuluu toiselle organisaatiolle.", "error")
    else:
        audit_record(
            "webhook.subscription_deactivated",
            status=AuditStatus.SUCCESS,
            actor_id=current_user.id,
            organization_id=_pms_org_id(),
            target_type="webhook_subscription",
            target_id=subscription_id,
            commit=True,
        )
        flash("Webhook-tilaus poistettu käytöstä.", "success")
    return redirect(url_for("admin.webhooks_list"))


@admin_bp.post("/webhooks/<int:subscription_id>/send-test-event")
@require_superadmin_2fa
@require_tenant_access("webhook_subscription", id_arg="subscription_id")
def webhooks_send_test_event(subscription_id: int):
    from app.webhooks.services import dispatch

    sub = g.scoped_entity
    if not sub.is_active:
        flash("Webhook-tilaus ei ole aktiivinen.", "error")
        return redirect(url_for("admin.webhooks_detail", subscription_id=subscription_id))

    code = (request.form.get("totp_code") or "").replace(" ", "").strip()
    if not current_user.verify_totp(code):
        flash("Virheellinen 2FA-koodi.", "error")
        return redirect(url_for("admin.webhooks_detail", subscription_id=subscription_id))

    event_type = "test.ping"
    payload = {
        "event": event_type,
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "organization_id": sub.organization_id,
        "data": {"subscription_id": sub.id, "test": True},
    }
    try:
        dispatch(sub.id, event_type, payload)
    except ValueError:
        fallback_events = sub.events if isinstance(sub.events, list) else []
        if not fallback_events:
            flash("Tilauksella ei ole tapahtumia testiä varten.", "error")
            return redirect(url_for("admin.webhooks_detail", subscription_id=subscription_id))
        event_type = str(fallback_events[0])
        payload["event"] = event_type
        dispatch(sub.id, event_type, payload)

    audit_record(
        "webhook.test_event_sent",
        status=AuditStatus.SUCCESS,
        actor_id=current_user.id,
        organization_id=_pms_org_id(),
        target_type="webhook_subscription",
        target_id=sub.id,
        metadata={"event_type": event_type},
        commit=True,
    )
    flash("Testi-event lähetetty.", "success")
    return redirect(url_for("admin.webhooks_detail", subscription_id=subscription_id))


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
        for message in admin_service.apply_superadmin_status_post(form=request.form):
            flash(message)
    payload = admin_service.public_status_payload(window_days=90)
    return render_template("admin/superadmin_status.html", payload=payload)
