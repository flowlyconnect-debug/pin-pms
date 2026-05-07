from __future__ import annotations

import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
from typing import Any
from zoneinfo import ZoneInfo

from flask import current_app, url_for
from sqlalchemy import case, func
from sqlalchemy import or_

from app.audit.models import AuditLog
from app.admin.models import SavedFilter
from app.backups.models import Backup, BackupStatus
from app.billing.models import Invoice, Lease
from app.email.models import OutgoingEmail, OutgoingEmailStatus
from app.email.services import render_template as render_email_template
from app.email.services import send_test_template_email
from app.expenses.models import Expense
from app.extensions import db
from app.guests.models import Guest
from app.integrations.ical.models import ImportedCalendarEvent, ImportedCalendarFeed
from app.maintenance.models import MaintenanceRequest
from app.organizations.models import Organization
from app.portal.models import AccessCode, PortalCheckInToken
from app.properties.models import Property, Unit
from app.reports import services as report_service
from app.reservations.models import Reservation
from app.status.models import StatusCheck, StatusComponent, StatusIncident
from app.tags.models import GuestTag, Tag
from app.users.models import User
from app.idempotency.services import get_or_create, record_response  # noqa: F401 - re-exported via admin_service module


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def email_preview_context() -> dict[str, object]:
    return {
        "user_email": "demo@example.com",
        "organization_name": "Demo Organisaatio",
        "login_url": "https://example.com/login",
        "reset_url": "https://example.com/reset/demo-token",
        "expires_minutes": 30,
        "code": "123 456",
        "backup_name": "demo-backup",
        "completed_at": "2026-04-25 10:00:00 UTC",
        "size_human": "12.3 MB",
        "location": "/var/backups/pindora/demo.sql.gz",
        "failed_at": "2026-04-25 10:00:00 UTC",
        "error_message": "demo error",
        "subject_line": "Demo ilmoitus",
        "message": "Tama on turvallinen esikatseluviesti.",
        "from_name": "Pin PMS",
        "reservation_id": 1001,
        "unit_name": "A-101",
        "start_date": "2026-05-01",
        "end_date": "2026-05-05",
        "invoice_number": "INV-1001",
        "amount": "124.00",
        "subtotal_excl_vat": "100.00",
        "vat_rate": "24.00",
        "vat_amount": "24.00",
        "total_incl_vat": "124.00",
        "currency": "EUR",
        "due_date": "2026-05-10",
        "description": "Testilaskun kuvaus",
    }


def build_email_template_preview(*, template_key: str):
    return render_email_template(template_key, email_preview_context())


def send_email_template_test(*, template_key: str, to: str, actor_user):
    return send_test_template_email(template_key, to, actor_user)


def _serialize_audit_event(row: AuditLog) -> dict:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "action": row.action,
        "status": row.status or "",
        "target_type": row.target_type,
        "target_id": row.target_id,
        "actor_email": row.actor_email,
    }


def _safe_url_for(endpoint: str, **values) -> str:
    try:
        return url_for(endpoint, **values)
    except RuntimeError:
        if endpoint == "admin.invoices_detail":
            return f"/admin/invoices/{values['invoice_id']}"
        if endpoint == "admin.maintenance_requests_detail":
            return f"/admin/maintenance-requests/{values['request_id']}"
        if endpoint == "admin.reservations_detail":
            return f"/admin/reservations/{values['reservation_id']}"
        if endpoint == "admin.conflicts_page":
            return "/admin/konfliktit"
        if endpoint == "admin.units_edit":
            return f"/admin/units/{values['unit_id']}/edit"
        if endpoint == "admin.units_detail":
            return f"/admin/units/{values['unit_id']}"
        return "#"


def normalize_dashboard_range(raw_value: str | None) -> str:
    value = (raw_value or "").strip().lower()
    if value in {"today", "7d", "30d"}:
        return value
    return "today"


def _resolve_range_window(*, range_key: str, today: date) -> tuple[date, date, int]:
    if range_key == "30d":
        days = 30
    elif range_key == "7d":
        days = 7
    else:
        days = 1
    start_date = today
    end_date = today + timedelta(days=days - 1)
    return start_date, end_date, days


def _sum_paid_between(*, organization_id: int, start_dt: datetime, end_dt: datetime) -> Decimal:
    value = (
        Invoice.query.with_entities(func.coalesce(func.sum(Invoice.amount), 0))
        .filter(
            Invoice.organization_id == organization_id,
            Invoice.status == "paid",
            Invoice.paid_at.isnot(None),
            Invoice.paid_at >= start_dt,
            Invoice.paid_at < end_dt,
        )
        .scalar()
    )
    return Decimal(value or 0)


def _format_eur_fi(amount: Decimal | int | float) -> str:
    value = Decimal(amount or 0).quantize(Decimal("0.01"))
    formatted = f"{value:,.2f}".replace(",", " ").replace(".", ",")
    return f"{formatted} €"


def _weekday_label_fi(day: date) -> str:
    names = ["Ma", "Ti", "Ke", "To", "Pe", "La", "Su"]
    return f"{names[day.weekday()]} {day.day}.{day.month}."


def _day_month_label_fi(day: date) -> str:
    return f"{day.day}.{day.month}."


def get_unit_status_overview(*, organization_id: int, on_date: date) -> list[dict]:
    has_unit_active = hasattr(Unit, "is_active")
    blocked_expr = (
        Unit.is_active.is_(False)
        if has_unit_active
        else func.lower(func.coalesce(Unit.unit_type, "")).in_(
            ("blocked", "out_of_service", "inactive")
        )
    )
    relevant_reservation = (Reservation.status == "confirmed") & (
        (Reservation.start_date == on_date)
        | (Reservation.end_date == on_date)
        | ((Reservation.start_date <= on_date) & (Reservation.end_date > on_date))
    )
    reservation_rank = case(
        (Reservation.start_date == on_date, 3),
        (Reservation.end_date == on_date, 2),
        (((Reservation.start_date <= on_date) & (Reservation.end_date > on_date)), 1),
        else_=0,
    )
    ranked_rows = (
        db.session.query(
            Unit.id.label("unit_id"),
            Property.name.label("property_name"),
            Unit.name.label("unit_name"),
            Unit.unit_type.label("unit_type"),
            blocked_expr.label("unit_blocked"),
            Reservation.id.label("reservation_id"),
            Reservation.start_date.label("reservation_start"),
            Reservation.end_date.label("reservation_end"),
            Reservation.guest_name.label("guest_name"),
            func.row_number()
            .over(
                partition_by=Unit.id,
                order_by=(
                    reservation_rank.desc(),
                    Reservation.start_date.desc(),
                    Reservation.id.desc(),
                ),
            )
            .label("rn"),
        )
        .select_from(Unit)
        .join(Property, Unit.property_id == Property.id)
        .outerjoin(Reservation, (Reservation.unit_id == Unit.id) & relevant_reservation)
        .filter(Property.organization_id == organization_id)
        .subquery()
    )
    rows = (
        db.session.query(ranked_rows)
        .filter(ranked_rows.c.rn == 1)
        .order_by(
            ranked_rows.c.property_name.asc(),
            ranked_rows.c.unit_name.asc(),
            ranked_rows.c.unit_id.asc(),
        )
        .all()
    )
    result: list[dict] = []
    for row in rows:
        guest_name = (row.guest_name or "").strip() or "Vieras"
        if row.unit_blocked:
            state = "blocked"
        elif row.reservation_id is None:
            state = "free"
        elif row.reservation_start == on_date:
            state = "arriving"
        elif row.reservation_end == on_date:
            state = "departing"
        else:
            state = "occupied"
        until_date = None
        if state in {"occupied", "arriving"} and row.reservation_end is not None:
            until_date = row.reservation_end
        link = (
            _safe_url_for("admin.reservations_detail", reservation_id=row.reservation_id)
            if row.reservation_id
            else _safe_url_for("admin.units_edit", unit_id=row.unit_id)
        )
        result.append(
            {
                "unit_id": row.unit_id,
                "unit_label": f"{(row.property_name or '').strip()} · {(row.unit_name or '').strip()}",
                "state": state,
                "guest_name": (
                    guest_name if state in {"occupied", "arriving", "departing"} else None
                ),
                "until_date": until_date.isoformat() if until_date else None,
                "reservation_id": row.reservation_id,
                "link": link,
            }
        )
    return result


def get_week_overview(*, organization_id: int, start_date: date) -> list[dict]:
    total_units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .count()
    )
    week_end = start_date + timedelta(days=6)
    rows = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status == "confirmed",
            Reservation.start_date <= week_end,
            Reservation.end_date > start_date,
        )
        .with_entities(Reservation.start_date, Reservation.end_date)
        .all()
    )
    by_day: list[dict] = []
    for day_offset in range(7):
        current_day = start_date + timedelta(days=day_offset)
        reservations_count = 0
        for row in rows:
            if row.start_date <= current_day < row.end_date:
                reservations_count += 1
        occupancy_percent = (
            round((reservations_count / total_units) * 100, 1) if total_units else 0.0
        )
        by_day.append(
            {
                "date_iso": current_day.isoformat(),
                "weekday_label_fi": _weekday_label_fi(current_day),
                "reservations_count": reservations_count,
                "occupancy_pct": occupancy_percent,
                "arrivals_count": sum(1 for r in rows if r.start_date == current_day),
                "departures_count": sum(1 for r in rows if r.end_date == current_day),
                "calendar_link": f"/admin/calendar?date={current_day.isoformat()}",
            }
        )
    return by_day


def get_dashboard_stats(
    *,
    organization_id: int,
    viewer_is_superadmin: bool = False,
    range_key: str = "today",
) -> dict:
    """Aggregate operational KPIs for the admin dashboard (single-tenant scope)."""
    normalized_range = normalize_dashboard_range(range_key)
    total_properties = Property.query.filter_by(organization_id=organization_id).count()
    total_units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .count()
    )
    today = date.today()
    active_units_subq = (
        db.session.query(Reservation.unit_id.label("unit_id"))
        .select_from(Reservation)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status == "confirmed",
            Reservation.start_date <= today,
            Reservation.end_date > today,
        )
        .distinct()
        .subquery()
    )
    next_reservations_subq = (
        db.session.query(
            Reservation.unit_id.label("unit_id"),
            func.min(Reservation.start_date).label("next_start_date"),
        )
        .select_from(Reservation)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status == "confirmed",
            Reservation.start_date > today,
        )
        .group_by(Reservation.unit_id)
        .subquery()
    )
    free_units_rows = (
        db.session.query(
            Unit.id.label("unit_id"),
            Unit.name.label("unit_name"),
            Property.name.label("property_name"),
            next_reservations_subq.c.next_start_date.label("next_start_date"),
        )
        .select_from(Unit)
        .join(Property, Unit.property_id == Property.id)
        .outerjoin(active_units_subq, active_units_subq.c.unit_id == Unit.id)
        .outerjoin(next_reservations_subq, next_reservations_subq.c.unit_id == Unit.id)
        .filter(
            Property.organization_id == organization_id,
            active_units_subq.c.unit_id.is_(None),
        )
        .order_by(Property.name.asc(), Unit.name.asc(), Unit.id.asc())
        .limit(10)
        .all()
    )
    free_units_now = []
    for row in free_units_rows:
        property_name = (row.property_name or "").strip()
        unit_name = (row.unit_name or "").strip()
        if property_name and unit_name:
            unit_label = f"{property_name} / {unit_name}"
        else:
            unit_label = property_name or unit_name or f"Yksikkö #{row.unit_id}"
        next_reservation_label = (
            f"Vapaa kunnes {_day_month_label_fi(row.next_start_date)}"
            if row.next_start_date is not None
            else "Ei tulevia varauksia"
        )
        free_units_now.append(
            {
                "unit_label": unit_label,
                "link": _safe_url_for("admin.units_detail", unit_id=row.unit_id),
                "next_reservation_label": next_reservation_label,
            }
        )

    range_start, range_end, range_days = _resolve_range_window(
        range_key=normalized_range, today=today
    )
    range_start_dt = datetime.combine(range_start, datetime.min.time())
    range_end_dt = datetime.combine(range_end + timedelta(days=1), datetime.min.time())

    reservation_metrics = (
        db.session.query(
            func.count().filter(Reservation.status == "confirmed").label("active_reservations"),
            func.count().filter(Reservation.status == "cancelled").label("cancelled_reservations"),
            func.count()
            .filter(
                Reservation.status == "confirmed",
                Reservation.start_date == today,
            )
            .label("arrivals_today"),
            func.count()
            .filter(
                Reservation.status == "confirmed",
                Reservation.end_date == today,
            )
            .label("departures_today"),
            func.count()
            .filter(
                Reservation.status == "confirmed",
                Reservation.start_date <= today,
                Reservation.end_date > today,
            )
            .label("current_guests"),
            func.count()
            .filter(
                Reservation.status == "confirmed",
                Reservation.start_date > today,
            )
            .label("upcoming_reservations"),
            func.count()
            .filter(
                Reservation.status == "confirmed",
                Reservation.start_date >= range_start,
                Reservation.start_date <= range_end,
            )
            .label("arrivals_in_range"),
            func.count()
            .filter(
                Reservation.status == "confirmed",
                Reservation.end_date >= range_start,
                Reservation.end_date <= range_end,
            )
            .label("departures_in_range"),
        )
        .select_from(Reservation)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .one()
    )
    active_reservations = int(reservation_metrics.active_reservations or 0)
    cancelled_reservations = int(reservation_metrics.cancelled_reservations or 0)
    arrivals_today = int(reservation_metrics.arrivals_today or 0)
    departures_today = int(reservation_metrics.departures_today or 0)
    current_guests = int(reservation_metrics.current_guests or 0)
    upcoming_reservations = int(reservation_metrics.upcoming_reservations or 0)
    arrivals_in_range = int(reservation_metrics.arrivals_in_range or 0)
    departures_in_range = int(reservation_metrics.departures_in_range or 0)

    scoped_reservations = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
    )
    occupancy = report_service.occupancy_report(
        organization_id=organization_id,
        start_date=today,
        end_date=today + timedelta(days=1),
    )
    occupancy_percent = float(occupancy["occupancy_percentage"])

    confirmed = scoped_reservations.filter(Reservation.status == "confirmed")
    active_leases = (
        Lease.query.filter_by(organization_id=organization_id)
        .filter(Lease.status == "active")
        .count()
    )
    invoice_metrics = (
        db.session.query(
            func.count().filter(Invoice.status.in_(("open", "overdue"))).label("open_invoices"),
            func.count().filter(Invoice.status == "overdue").label("overdue_invoices"),
            func.coalesce(
                func.sum(Invoice.amount).filter(Invoice.status.in_(("open", "overdue"))), 0
            ).label("open_receivables"),
            func.coalesce(func.sum(Invoice.amount).filter(Invoice.status == "overdue"), 0).label(
                "overdue_amount"
            ),
        )
        .select_from(Invoice)
        .filter(Invoice.organization_id == organization_id)
        .one()
    )
    open_invoices = int(invoice_metrics.open_invoices or 0)
    overdue_invoices = int(invoice_metrics.overdue_invoices or 0)
    open_receivables = Decimal(invoice_metrics.open_receivables or 0)
    overdue_amount = Decimal(invoice_metrics.overdue_amount or 0)

    maintenance_metrics = (
        db.session.query(
            func.count()
            .filter(MaintenanceRequest.status.in_(("new", "in_progress", "waiting")))
            .label("open_maintenance_requests"),
            func.count()
            .filter(
                MaintenanceRequest.priority == "urgent",
                MaintenanceRequest.status.in_(("new", "in_progress", "waiting")),
            )
            .label("urgent_maintenance_requests"),
        )
        .select_from(MaintenanceRequest)
        .filter(MaintenanceRequest.organization_id == organization_id)
        .one()
    )
    open_maintenance_requests = int(maintenance_metrics.open_maintenance_requests or 0)
    urgent_maintenance_requests = int(maintenance_metrics.urgent_maintenance_requests or 0)
    leases_ending_next_7_days = (
        Lease.query.filter_by(organization_id=organization_id)
        .filter(
            Lease.status == "active",
            Lease.end_date.isnot(None),
            Lease.end_date >= today,
            Lease.end_date <= today + timedelta(days=7),
        )
        .count()
    )
    arrivals_today_rows = (
        confirmed.filter(Reservation.start_date == today)
        .order_by(Reservation.start_date.asc(), Reservation.id.asc())
        .limit(10)
        .all()
    )
    departures_today_rows = (
        confirmed.filter(Reservation.end_date == today)
        .order_by(Reservation.end_date.asc(), Reservation.id.asc())
        .limit(10)
        .all()
    )
    arrivals_departures_ids = {row.id for row in arrivals_today_rows + departures_today_rows}
    active_access_reservation_ids: set[int] = set()
    if arrivals_departures_ids:
        active_access_reservation_ids = {
            reservation_id
            for reservation_id, in AccessCode.query.filter(
                AccessCode.reservation_id.in_(arrivals_departures_ids),
                AccessCode.is_active.is_(True),
            )
            .distinct(AccessCode.reservation_id)
            .all()
        }

    def _reservation_row(row: Reservation) -> dict:
        property_name = (row.unit.property.name if row.unit and row.unit.property else "").strip()
        unit_name = (row.unit.name if row.unit else "").strip()
        if property_name and unit_name:
            unit_label = f"{property_name} / {unit_name}"
        else:
            unit_label = property_name or unit_name or f"Yksikkö #{row.unit_id}"
        guest_name = (row.guest_name or "").strip()
        if not guest_name and row.guest:
            guest_name = " ".join(
                part
                for part in [
                    (row.guest.first_name or "").strip(),
                    (row.guest.last_name or "").strip(),
                ]
                if part
            ).strip()
        return {
            "reservation_id": row.id,
            "unit_label": unit_label,
            "guest_name": guest_name or "Vieras",
            "start_date": row.start_date.isoformat(),
            "end_date": row.end_date.isoformat(),
            "status": row.status,
            "has_access_code": row.id in active_access_reservation_ids,
        }

    today_arrivals = [_reservation_row(row) for row in arrivals_today_rows]
    today_departures = [_reservation_row(row) for row in departures_today_rows]

    now_utc = datetime.utcnow()
    overdue_invoice_rows = (
        Invoice.query.filter_by(organization_id=organization_id)
        .filter(Invoice.status == "overdue")
        .order_by(Invoice.due_date.asc(), Invoice.id.asc())
        .limit(5)
        .all()
    )
    new_maintenance_rows = (
        MaintenanceRequest.query.filter_by(organization_id=organization_id, status="new")
        .order_by(MaintenanceRequest.created_at.asc(), MaintenanceRequest.id.asc())
        .limit(5)
        .all()
    )
    expired_checkin_rows = (
        PortalCheckInToken.query.join(
            Reservation, PortalCheckInToken.reservation_id == Reservation.id
        )
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            PortalCheckInToken.used_at.is_(None),
            PortalCheckInToken.expires_at < now_utc,
        )
        .order_by(PortalCheckInToken.expires_at.asc(), PortalCheckInToken.id.asc())
        .all()
    )
    ical_conflict_rows = (
        ImportedCalendarEvent.query.filter_by(organization_id=organization_id)
        .filter(ImportedCalendarEvent.summary.ilike("%conflict%"))
        .order_by(ImportedCalendarEvent.created_at.asc(), ImportedCalendarEvent.id.asc())
        .all()
    )
    action_required = (
        [
            {
                "kind": "invoice_overdue",
                "label": f"Myöhässä oleva lasku {row.invoice_number or f'#{row.id}'}",
                "link": _safe_url_for("admin.invoices_detail", invoice_id=row.id),
                "severity": "danger",
                "since": row.due_date.isoformat() if row.due_date else None,
            }
            for row in overdue_invoice_rows
        ]
        + [
            {
                "kind": "maintenance_new",
                "label": f"Uusi huoltopyyntö #{row.id}: {row.title}",
                "link": _safe_url_for("admin.maintenance_requests_detail", request_id=row.id),
                "severity": "warning",
                "since": row.created_at.isoformat() if row.created_at else None,
            }
            for row in new_maintenance_rows
        ]
        + [
            {
                "kind": "checkin_expired",
                "label": f"Vanhentunut sisäänkirjautumislinkki varaukselle #{row.reservation_id}",
                "link": _safe_url_for(
                    "admin.reservations_detail", reservation_id=row.reservation_id
                ),
                "severity": "warning",
                "since": row.expires_at.isoformat() if row.expires_at else None,
            }
            for row in expired_checkin_rows
        ]
        + [
            {
                "kind": "ical_conflict",
                "label": f"iCal-konflikti: {(row.summary or f'Tapahtuma #{row.id}')}",
                "link": _safe_url_for("admin.conflicts_page"),
                "severity": "warning",
                "since": row.created_at.isoformat() if row.created_at else None,
            }
            for row in ical_conflict_rows
        ]
    )
    action_required.sort(key=lambda item: item["since"] or "")

    range_total_revenue = _sum_paid_between(
        organization_id=organization_id,
        start_dt=range_start_dt,
        end_dt=range_end_dt,
    )
    month_start = datetime(today.year, today.month, 1)
    now_utc = datetime.utcnow()
    month_to_date_revenue = _sum_paid_between(
        organization_id=organization_id,
        start_dt=month_start,
        end_dt=now_utc,
    )
    previous_month_start = (month_start - timedelta(days=1)).replace(day=1)
    month_to_date_revenue_previous = _sum_paid_between(
        organization_id=organization_id,
        start_dt=previous_month_start,
        end_dt=month_start,
    )
    month_expenses = (
        db.session.query(func.coalesce(func.sum(Expense.amount), 0))
        .select_from(Expense)
        .filter(
            Expense.organization_id == organization_id,
            Expense.date >= month_start.date(),
            Expense.date <= today,
        )
        .scalar()
    )
    month_expenses_dec = Decimal(month_expenses or 0).quantize(Decimal("0.01"))
    month_net_cash_flow = (month_to_date_revenue - month_expenses_dec).quantize(Decimal("0.01"))
    compare_start = range_start_dt - timedelta(days=range_days)
    compare_end = range_start_dt
    range_compare_revenue = _sum_paid_between(
        organization_id=organization_id,
        start_dt=compare_start,
        end_dt=compare_end,
    )
    revenue_trend_pct: float | None = None
    if range_compare_revenue != Decimal("0"):
        revenue_trend_pct = float(
            ((range_total_revenue - range_compare_revenue) / range_compare_revenue) * Decimal("100")
        )

    backup_metrics = (
        db.session.query(
            db.session.query(Backup.status)
            .order_by(Backup.created_at.desc(), Backup.id.desc())
            .limit(1)
            .scalar_subquery()
            .label("latest_status"),
            func.max(Backup.created_at)
            .filter(Backup.status == BackupStatus.SUCCESS)
            .label("last_success_at"),
            func.max(Backup.created_at)
            .filter(Backup.status == BackupStatus.FAILED)
            .label("last_failure_at"),
        )
        .select_from(Backup)
        .one()
    )
    latest_status = backup_metrics.latest_status
    latest_success_at = _as_utc(backup_metrics.last_success_at)
    latest_failure_at = _as_utc(backup_metrics.last_failure_at)
    backup_state = "missing"
    if latest_status is not None:
        if latest_status == BackupStatus.FAILED:
            backup_state = "failed"
        elif latest_success_at is None:
            backup_state = "missing"
        else:
            age = now_utc - latest_success_at
            backup_state = "ok" if age <= timedelta(hours=36) else "stale"
    backup_status = {
        "last_success_at": latest_success_at,
        "last_failure_at": latest_failure_at,
        "state": backup_state,
        "scheduler_enabled": bool(current_app.config.get("BACKUP_SCHEDULER_ENABLED", False)),
    }

    email_window_start = range_start_dt
    email_scope_is_org = hasattr(OutgoingEmail, "organization_id")
    email_q = OutgoingEmail.query.filter(
        OutgoingEmail.created_at >= email_window_start,
        OutgoingEmail.created_at < range_end_dt,
    )
    if email_scope_is_org:
        email_q = email_q.filter(
            or_(
                OutgoingEmail.organization_id == organization_id,
                OutgoingEmail.organization_id.is_(None),
            )
        )
    sent_count = email_q.filter(OutgoingEmail.status == OutgoingEmailStatus.SENT).count()
    failed_rows = (
        email_q.filter(OutgoingEmail.status == OutgoingEmailStatus.FAILED)
        .order_by(OutgoingEmail.created_at.desc(), OutgoingEmail.id.desc())
        .all()
    )
    latest_failed_email = failed_rows[0] if failed_rows else None
    email_health = {
        "sent_count": sent_count,
        "failed_count": len(failed_rows),
        "last_failure_at": latest_failed_email.created_at if latest_failed_email else None,
        "last_failure_template_key": (
            latest_failed_email.template_key if latest_failed_email else None
        ),
        "is_org_scoped": email_scope_is_org,
    }

    last_ical_sync = (
        ImportedCalendarFeed.query.filter_by(organization_id=organization_id, is_active=True)
        .order_by(ImportedCalendarFeed.last_synced_at.desc(), ImportedCalendarFeed.id.desc())
        .first()
    )
    ical_conflicts_open = (
        ImportedCalendarEvent.query.filter_by(organization_id=organization_id)
        .filter(ImportedCalendarEvent.summary.ilike("%conflict%"))
        .count()
    )
    ical_feeds_active = ImportedCalendarFeed.query.filter_by(
        organization_id=organization_id, is_active=True
    ).count()

    pindora_configured = bool(current_app.config.get("PINDORA_LOCK_BASE_URL")) and bool(
        current_app.config.get("PINDORA_LOCK_API_KEY")
    )
    pindora_success = (
        AuditLog.query.filter_by(organization_id=organization_id, status="success")
        .filter(AuditLog.action.in_(("lock.code_issued", "lock.code_revoked")))
        .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .first()
    )
    pindora_failed_calls_24h = (
        AuditLog.query.filter_by(organization_id=organization_id, status="failure")
        .filter(AuditLog.action.in_(("lock.code_issued", "lock.code_revoked")))
        .filter(AuditLog.created_at >= now_utc - timedelta(hours=24))
        .count()
    )

    integrations = {
        "ical": {
            "last_sync_at": last_ical_sync.last_synced_at if last_ical_sync else None,
            "conflicts_open": ical_conflicts_open,
            "feeds_active": ical_feeds_active,
        },
        "pindora": {
            "configured": pindora_configured,
            "last_call_at": pindora_success.created_at if pindora_success else None,
            "failed_calls_24h": pindora_failed_calls_24h,
        },
    }

    latest_rows = (
        AuditLog.query.filter_by(organization_id=organization_id)
        .order_by(AuditLog.created_at.desc())
        .limit(5)
        .all()
    )
    latest_audit_events = [_serialize_audit_event(r) for r in latest_rows]

    week_overview = get_week_overview(organization_id=organization_id, start_date=today)
    unit_status_overview = get_unit_status_overview(organization_id=organization_id, on_date=today)
    range_label = {"today": "Tänään", "7d": "7 vrk", "30d": "30 vrk"}[normalized_range]
    result = {
        "total_properties": total_properties,
        "total_units": total_units,
        "active_reservations": active_reservations,
        "cancelled_reservations": cancelled_reservations,
        "occupancy_percent": occupancy_percent,
        "arrivals_today": arrivals_today,
        "departures_today": departures_today,
        "today_iso": today.isoformat(),
        "current_guests": current_guests,
        "upcoming_reservations": upcoming_reservations,
        "active_leases": active_leases,
        "open_invoices": open_invoices,
        "overdue_invoices": overdue_invoices,
        "open_maintenance_requests": open_maintenance_requests,
        "urgent_maintenance_requests": urgent_maintenance_requests,
        "leases_ending_next_7_days": leases_ending_next_7_days,
        "today_arrivals": today_arrivals,
        "today_departures": today_departures,
        "free_units_now": free_units_now,
        "action_required": action_required,
        "arrivals_this_week": arrivals_in_range,
        "departures_this_week": departures_in_range,
        "arrivals_in_range": arrivals_in_range,
        "departures_in_range": departures_in_range,
        "range_key": normalized_range,
        "range_label": range_label,
        "latest_audit_events": latest_audit_events,
        "week_overview": week_overview,
        "unit_status_overview": unit_status_overview,
        "open_invoices_amount_fi": _format_eur_fi(open_receivables),
        "revenue": {
            "month_to_date": month_to_date_revenue,
            "month_to_date_previous": month_to_date_revenue_previous,
            "previous_month": range_compare_revenue,
            "range_total": range_total_revenue,
            "range_compare": range_compare_revenue,
            "trend_pct": revenue_trend_pct,
            "open_receivables": open_receivables,
            "overdue_amount": overdue_amount,
            "month_to_date_fi": _format_eur_fi(month_to_date_revenue),
            "month_to_date_previous_fi": _format_eur_fi(month_to_date_revenue_previous),
            "open_receivables_fi": _format_eur_fi(open_receivables),
            "overdue_amount_fi": _format_eur_fi(overdue_amount),
        },
        "cash_flow": {
            "income_this_month": month_to_date_revenue,
            "expenses_this_month": month_expenses_dec,
            "net_cash_flow_this_month": month_net_cash_flow,
            "income_this_month_fi": _format_eur_fi(month_to_date_revenue),
            "expenses_this_month_fi": _format_eur_fi(month_expenses_dec),
            "net_cash_flow_this_month_fi": _format_eur_fi(month_net_cash_flow),
        },
        "integrations": integrations,
        "backup_status": backup_status if viewer_is_superadmin else None,
        "email_health": (
            {
                **email_health,
                "window_label": range_label,
            }
            if viewer_is_superadmin
            else None
        ),
        # Back-compat for templates/tests that used the older names:
        "occupancy_percentage": occupancy_percent,
        "latest_events": latest_rows,
    }
    return result


def _coerce_timezone_name(raw_timezone: str | None) -> str:
    candidate = (raw_timezone or "").strip() or "Europe/Helsinki"
    try:
        ZoneInfo(candidate)
    except Exception:
        return "Europe/Helsinki"
    return candidate


def _daily_sum_by_start_date(
    *, organization_id: int, start_date: date, end_date: date
) -> dict[date, Decimal]:
    rows = (
        db.session.query(
            Reservation.start_date.label("day"),
            func.coalesce(func.sum(Reservation.amount), 0).label("value"),
        )
        .select_from(Reservation)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status != "cancelled",
            Reservation.amount.isnot(None),
            Reservation.start_date >= start_date,
            Reservation.start_date <= end_date,
        )
        .group_by(Reservation.start_date)
        .all()
    )
    return {row.day: Decimal(row.value or 0) for row in rows}


def dashboard_summary(*, organization_id: int, timezone: str = "Europe/Helsinki") -> dict:
    tz_name = _coerce_timezone_name(timezone)
    tz = ZoneInfo(tz_name)
    today_local = datetime.now(tz).date()
    trend_start = today_local - timedelta(days=29)
    trend_end = today_local
    arrivals_window_end = today_local + timedelta(days=7)

    total_properties = Property.query.filter_by(organization_id=organization_id).count()
    total_units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .count()
    )
    reservation_base = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
    )
    confirmed_base = reservation_base.filter(Reservation.status == "confirmed")
    non_cancelled_base = reservation_base.filter(Reservation.status != "cancelled")
    reservations_count = non_cancelled_base.count()

    active_reservations = (
        confirmed_base.filter(
            Reservation.start_date <= today_local,
            Reservation.end_date > today_local,
        ).count()
    )
    checkins_today = confirmed_base.filter(Reservation.start_date == today_local).count()
    checkouts_today = confirmed_base.filter(Reservation.end_date == today_local).count()

    month_start = today_local.replace(day=1)
    prev_month_end = month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)

    revenue_this_month = (
        db.session.query(func.coalesce(func.sum(Reservation.amount), 0))
        .select_from(Reservation)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status != "cancelled",
            Reservation.amount.isnot(None),
            Reservation.start_date >= month_start,
            Reservation.start_date <= today_local,
        )
        .scalar()
    )
    revenue_last_month = (
        db.session.query(func.coalesce(func.sum(Reservation.amount), 0))
        .select_from(Reservation)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status != "cancelled",
            Reservation.amount.isnot(None),
            Reservation.start_date >= prev_month_start,
            Reservation.start_date <= prev_month_end,
        )
        .scalar()
    )

    invoice_metrics = (
        db.session.query(
            func.count().filter(Invoice.status.in_(("open", "overdue"))).label("open_invoices"),
            func.count().filter(Invoice.status == "overdue").label("overdue_invoices"),
        )
        .select_from(Invoice)
        .filter(Invoice.organization_id == organization_id)
        .one()
    )
    open_invoices = int(invoice_metrics.open_invoices or 0)
    overdue_invoices = int(invoice_metrics.overdue_invoices or 0)

    open_maintenance = (
        MaintenanceRequest.query.filter(
            MaintenanceRequest.organization_id == organization_id,
            MaintenanceRequest.status.in_(("new", "in_progress", "waiting")),
        ).count()
    )

    # SQL-aggregate sources for occupancy trend (arrivals/departures), then cumulative walk.
    arrivals_rows = (
        db.session.query(Reservation.start_date.label("day"), func.count(Reservation.id).label("count"))
        .select_from(Reservation)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status == "confirmed",
            Reservation.start_date >= trend_start,
            Reservation.start_date <= trend_end,
        )
        .group_by(Reservation.start_date)
        .all()
    )
    departures_rows = (
        db.session.query(Reservation.end_date.label("day"), func.count(Reservation.id).label("count"))
        .select_from(Reservation)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.status == "confirmed",
            Reservation.end_date >= trend_start,
            Reservation.end_date <= trend_end,
        )
        .group_by(Reservation.end_date)
        .all()
    )
    base_occupied = (
        confirmed_base.filter(
            Reservation.start_date < trend_start,
            Reservation.end_date > trend_start,
        ).count()
    )
    arrivals_map = {row.day: int(row.count or 0) for row in arrivals_rows}
    departures_map = {row.day: int(row.count or 0) for row in departures_rows}
    running_occupied = base_occupied
    trend_occupancy_30d: list[dict[str, object]] = []
    for day_offset in range(30):
        day = trend_start + timedelta(days=day_offset)
        running_occupied += arrivals_map.get(day, 0)
        running_occupied -= departures_map.get(day, 0)
        day_pct = round((running_occupied / total_units) * 100, 1) if total_units else 0.0
        trend_occupancy_30d.append({"date": day.isoformat(), "pct": day_pct})

    occupancy_today_pct = float(trend_occupancy_30d[-1]["pct"]) if trend_occupancy_30d else 0.0
    last_7 = trend_occupancy_30d[-7:] if trend_occupancy_30d else []
    occupancy_7d_avg_pct = (
        round(sum(float(item["pct"]) for item in last_7) / len(last_7), 1) if last_7 else 0.0
    )

    revenue_by_day = _daily_sum_by_start_date(
        organization_id=organization_id,
        start_date=trend_start,
        end_date=trend_end,
    )
    trend_revenue_30d: list[dict[str, object]] = []
    for day_offset in range(30):
        day = trend_start + timedelta(days=day_offset)
        value = revenue_by_day.get(day, Decimal("0"))
        trend_revenue_30d.append({"date": day.isoformat(), "value": float(value)})

    upcoming_rows = (
        confirmed_base.filter(
            Reservation.start_date >= today_local,
            Reservation.start_date <= arrivals_window_end,
        )
        .order_by(Reservation.start_date.asc(), Reservation.id.asc())
        .limit(10)
        .all()
    )
    upcoming_arrivals = [
        {
            "reservation_id": row.id,
            "start_date": row.start_date.isoformat(),
            "end_date": row.end_date.isoformat(),
            "guest_name": ((row.guest_name or "").strip() or "Vieras"),
            "unit_label": (
                f"{(row.unit.property.name or '').strip()} / {(row.unit.name or '').strip()}"
                if row.unit and row.unit.property
                else f"Yksikkö #{row.unit_id}"
            ),
            "link": _safe_url_for("admin.reservations_detail", reservation_id=row.id),
        }
        for row in upcoming_rows
    ]

    alerts: list[dict[str, str]] = []
    if overdue_invoices > 0:
        alerts.append(
            {
                "type": "warning",
                "message": f"{overdue_invoices} laskua erääntynyt",
                "link": "/admin/invoices?status=overdue",
            }
        )
    if open_maintenance > 0:
        alerts.append(
            {
                "type": "warning",
                "message": f"{open_maintenance} avointa huoltopyyntöä",
                "link": "/admin/maintenance-requests?status=new",
            }
        )
    if checkins_today > total_units and total_units > 0:
        alerts.append(
            {
                "type": "info",
                "message": "Poikkeuksellisen paljon check-intejä tänään",
                "link": "/admin/reservations",
            }
        )

    insufficient_properties = total_properties < 3
    insufficient_chart_data = reservations_count < 5
    return {
        "kpi": {
            "occupancy_today_pct": occupancy_today_pct,
            "occupancy_7d_avg_pct": occupancy_7d_avg_pct,
            "revenue_this_month": Decimal(revenue_this_month or 0),
            "revenue_last_month": Decimal(revenue_last_month or 0),
            "active_reservations": active_reservations,
            "checkins_today": checkins_today,
            "checkouts_today": checkouts_today,
            "open_invoices": open_invoices,
            "overdue_invoices": overdue_invoices,
            "open_maintenance": open_maintenance,
        },
        "trend_revenue_30d": trend_revenue_30d,
        "trend_occupancy_30d": trend_occupancy_30d,
        "upcoming_arrivals": upcoming_arrivals,
        "alerts": alerts,
        "meta": {
            "timezone": tz_name,
            "total_properties": total_properties,
            "total_reservations": reservations_count,
            "insufficient_properties": insufficient_properties,
            "insufficient_chart_data": insufficient_chart_data,
            "can_render_charts": not insufficient_chart_data,
        },
    }


# User lifecycle — delegated to :mod:`app.users.services`.
from app.users import services as _users_services  # noqa: E402

UserServiceError = _users_services.UserServiceError
create_user = _users_services.create_user
update_user_role = _users_services.update_user_role
deactivate_user = _users_services.deactivate_user
reactivate_user = _users_services.reactivate_user
change_password = _users_services.change_password


def start_impersonation(*, actor_user: User, target_user: User, reason: str) -> None:
    if not actor_user.is_superadmin:
        raise ValueError("Only superadmin can impersonate users.")
    normalized_reason = (reason or "").strip()
    if not normalized_reason:
        raise ValueError("Reason is required.")
    if not target_user.is_active:
        raise ValueError("Target user is not active.")
    from app.audit import record as audit_record

    audit_record(
        "support.impersonate.started",
        status="success",
        organization_id=target_user.organization_id,
        target_type="user",
        target_id=target_user.id,
        context={
            "target_user_id": target_user.id,
            "reason": normalized_reason,
            "impersonator_user_id": actor_user.id,
        },
        commit=True,
    )


def end_impersonation(*, actor_user: User, impersonator_user: User, duration_seconds: int) -> None:
    from app.audit import record as audit_record

    audit_record(
        "support.impersonate.ended",
        status="success",
        organization_id=actor_user.organization_id,
        target_type="user",
        target_id=actor_user.id,
        context={
            "target_user_id": actor_user.id,
            "impersonator_user_id": impersonator_user.id,
            "duration_seconds": max(0, int(duration_seconds or 0)),
        },
        commit=True,
    )


def build_tenant_debug_view(*, organization_id: int) -> dict[str, Any]:
    org = Organization.query.get(organization_id)
    if org is None:
        raise ValueError("Organization not found.")
    users = User.query.filter_by(organization_id=organization_id).all()
    user_ids = [u.id for u in users]
    last_login = (
        AuditLog.query.filter(
            AuditLog.action == "login",
            AuditLog.status == "success",
            AuditLog.actor_id.in_(user_ids),
        )
        .order_by(AuditLog.created_at.desc())
        .first()
        if user_ids
        else None
    )
    now = datetime.now(timezone.utc)
    month_ago = now - timedelta(days=30)
    reservations_count = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id, Reservation.created_at >= month_ago)
        .count()
    )
    audits = (
        AuditLog.query.filter_by(organization_id=organization_id)
        .order_by(AuditLog.created_at.desc())
        .limit(20)
        .all()
    )
    emails = (
        OutgoingEmail.query.filter(OutgoingEmail.created_at >= month_ago)
        .order_by(OutgoingEmail.created_at.desc())
        .limit(20)
        .all()
    )
    backups = Backup.query.order_by(Backup.created_at.desc()).limit(5).all()
    return {
        "organization": org,
        "users_count": len(users),
        "last_login_at": last_login.created_at if last_login else None,
        "reservations_30d_count": reservations_count,
        "audit_events": audits,
        "emails": emails,
        "backups": backups,
        "subscription": {"plan": "L3-C", "status": "active"},
        "usage_metrics": {
            "api_keys": 0,
            "properties": Property.query.filter_by(organization_id=organization_id).count(),
            "units": Unit.query.join(Property, Unit.property_id == Property.id)
            .filter(Property.organization_id == organization_id)
            .count(),
        },
    }


def status_uptime_percent(*, component_key: str, window_days: int = 30) -> float:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=window_days)
    rows = StatusCheck.query.filter(
        StatusCheck.component_key == component_key,
        StatusCheck.checked_at >= start,
        StatusCheck.checked_at <= now,
    ).all()
    if not rows:
        return 100.0
    ok_count = sum(1 for row in rows if row.ok)
    return round((ok_count / len(rows)) * 100.0, 2)


def public_status_payload(*, window_days: int = 90) -> dict[str, Any]:
    components = StatusComponent.query.order_by(StatusComponent.name.asc()).all()
    incidents = StatusIncident.query.order_by(StatusIncident.started_at.desc()).limit(5).all()
    return {
        "components": [
            {
                "key": c.key,
                "name": c.name,
                "current_state": c.current_state,
                "uptime_percent": status_uptime_percent(
                    component_key=c.key, window_days=window_days
                ),
            }
            for c in components
        ],
        "incidents": incidents,
    }


def verify_fresh_2fa_code(*, user: User, code: str) -> bool:
    """Match the admin settings reveal gate: TOTP, backup code, or email code."""

    from app.auth.models import TwoFactorEmailCode

    if not (code or "").strip():
        return False
    if user.verify_totp(code):
        return True
    if user.consume_backup_code(code):
        db.session.commit()
        return True
    if TwoFactorEmailCode.consume_active_code(user_id=user.id, raw_code=code):
        db.session.commit()
        return True
    return False


def create_organization_superadmin(
    *, name: str, actor_id: int, actor_email: str
) -> tuple[Organization | None, str | None]:
    """Create org or return ``(None, error_message)`` on duplicate name."""

    from app.audit import record as audit_record
    from app.audit.models import ActorType, AuditStatus

    org_name = name.strip()
    if Organization.query.filter_by(name=org_name).first() is not None:
        return None, f"Organisaatio '{org_name}' on jo olemassa."
    org = Organization(name=org_name)
    db.session.add(org)
    db.session.flush()
    audit_record(
        "organization.created",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=actor_id,
        actor_email=actor_email,
        target_type="organization",
        target_id=org.id,
        context={"name": org.name},
        commit=True,
    )
    return org, None


def update_organization_superadmin(
    *, org: Organization, new_name: str, actor_id: int, actor_email: str
) -> None:
    from app.audit import record as audit_record
    from app.audit.models import ActorType, AuditStatus

    old_name = org.name
    org.name = new_name.strip()
    audit_record(
        "organization.updated",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=actor_id,
        actor_email=actor_email,
        target_type="organization",
        target_id=org.id,
        context={"old_name": old_name, "new_name": org.name},
        commit=True,
    )


def superadmin_toggle_user_active(*, user_id: int, actor_id: int, actor_email: str) -> User:
    from app.audit.models import ActorType

    target_user = User.query.get_or_404(user_id)
    if target_user.is_active:
        deactivate_user(
            user_id=target_user.id,
            actor_type=ActorType.USER,
            actor_id=actor_id,
            actor_email=actor_email,
            commit=True,
        )
    else:
        reactivate_user(
            user_id=target_user.id,
            actor_type=ActorType.USER,
            actor_id=actor_id,
            actor_email=actor_email,
            commit=True,
        )
    db.session.refresh(target_user)
    return target_user


def apply_superadmin_status_post(*, form) -> list[str]:
    """Apply POST actions on the superadmin status page; return flash messages."""

    messages: list[str] = []
    action = (form.get("action") or "").strip()
    if action == "component_state":
        comp = StatusComponent.query.filter_by(
            key=(form.get("component_key") or "").strip()
        ).first_or_404()
        comp.current_state = (form.get("current_state") or "operational").strip()
        comp.scheduled_maintenance = bool(form.get("scheduled_maintenance"))
        db.session.commit()
        messages.append("Komponentin tila päivitetty.")
    elif action == "incident_create":
        incident = StatusIncident(
            title=(form.get("title") or "").strip() or "Nimeämätön häiriö",
            body=(form.get("body") or "").strip(),
            severity=(form.get("severity") or "minor").strip(),
            component_keys=[
                x.strip()
                for x in (form.get("component_keys") or "").split(",")
                if x.strip()
            ],
            status="open",
        )
        db.session.add(incident)
        db.session.commit()
        messages.append("Häiriö luotu.")
    elif action == "incident_close":
        incident = StatusIncident.query.get_or_404(int(form.get("incident_id")))
        incident.status = "resolved"
        incident.resolved_at = datetime.now(timezone.utc)
        db.session.commit()
        messages.append("Häiriö suljettu.")
    return messages


def search_all_resources(*, organization_id: int, q: str, limit: int = 20) -> list[dict[str, Any]]:
    needle = (q or "").strip()
    if len(needle) < 2:
        return []
    ilike = f"%{needle}%"
    out: list[dict[str, Any]] = []

    guests = (
        Guest.query.filter(
            Guest.organization_id == organization_id,
            or_(
                Guest.first_name.ilike(ilike),
                Guest.last_name.ilike(ilike),
                Guest.email.ilike(ilike),
                Guest.phone.ilike(ilike),
            ),
        )
        .order_by(Guest.id.desc())
        .limit(limit)
        .all()
    )
    for row in guests:
        out.append(
            {
                "type": "guest",
                "id": row.id,
                "label": row.full_name or f"Guest #{row.id}",
                "sublabel": row.email or row.phone or "",
                "url": f"/admin/guests/{row.id}",
            }
        )

    guest_tag_matches = (
        Guest.query.join(GuestTag, GuestTag.guest_id == Guest.id)
        .join(Tag, Tag.id == GuestTag.tag_id)
        .filter(Guest.organization_id == organization_id, Tag.name.ilike(ilike))
        .order_by(Guest.id.desc())
        .limit(limit)
        .all()
    )
    seen = {(item["type"], item["id"]) for item in out}
    for row in guest_tag_matches:
        key = ("guest", row.id)
        if key in seen:
            continue
        out.append(
            {
                "type": "guest",
                "id": row.id,
                "label": row.full_name or f"Guest #{row.id}",
                "sublabel": row.email or row.phone or "",
                "url": f"/admin/guests/{row.id}",
            }
        )
        seen.add(key)

    reservations = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            or_(Reservation.guest_name.ilike(ilike), db.cast(Reservation.id, db.String).ilike(ilike)),
        )
        .order_by(Reservation.id.desc())
        .limit(limit)
        .all()
    )
    for row in reservations:
        out.append(
            {
                "type": "reservation",
                "id": row.id,
                "label": f"Reservation #{row.id}",
                "sublabel": row.guest_name or "",
                "url": f"/admin/reservations/{row.id}",
            }
        )

    properties = (
        Property.query.filter(Property.organization_id == organization_id, Property.name.ilike(ilike))
        .order_by(Property.id.desc())
        .limit(limit)
        .all()
    )
    for row in properties:
        out.append(
            {
                "type": "property",
                "id": row.id,
                "label": row.name,
                "sublabel": row.address or "",
                "url": f"/admin/properties/{row.id}",
            }
        )

    invoices = (
        Invoice.query.filter(
            Invoice.organization_id == organization_id,
            Invoice.invoice_number.ilike(ilike),
        )
        .order_by(Invoice.id.desc())
        .limit(limit)
        .all()
    )
    for row in invoices:
        out.append(
            {
                "type": "invoice",
                "id": row.id,
                "label": row.invoice_number or f"Invoice #{row.id}",
                "sublabel": row.status or "",
                "url": f"/admin/invoices/{row.id}",
            }
        )
    return out[:limit]


def create_saved_filter(*, user_id: int, name: str, view_type: str, filter_params: dict[str, Any]) -> dict:
    row = SavedFilter(
        user_id=user_id,
        name=(name or "").strip()[:128] or "Saved filter",
        view_type=(view_type or "").strip(),
        filter_params=filter_params or {},
    )
    db.session.add(row)
    db.session.flush()
    audit_record(
        "saved_filter.created",
        status=AuditStatus.SUCCESS,
        actor_id=user_id,
        target_type="saved_filter",
        target_id=row.id,
        metadata={"view_type": row.view_type, "name": row.name},
        commit=False,
    )
    db.session.commit()
    return {
        "id": row.id,
        "name": row.name,
        "view_type": row.view_type,
        "filter_params": row.filter_params,
    }


def delete_saved_filter(*, user_id: int, saved_filter_id: int) -> None:
    row = SavedFilter.query.filter_by(id=saved_filter_id, user_id=user_id).first()
    if row is None:
        raise ValueError("Saved filter not found.")
    db.session.delete(row)
    audit_record(
        "saved_filter.deleted",
        status=AuditStatus.SUCCESS,
        actor_id=user_id,
        target_type="saved_filter",
        target_id=saved_filter_id,
        commit=False,
    )
    db.session.commit()


def list_saved_filters(*, user_id: int, view_type: str) -> list[dict[str, Any]]:
    rows = (
        SavedFilter.query.filter_by(user_id=user_id, view_type=view_type)
        .order_by(SavedFilter.created_at.desc(), SavedFilter.id.desc())
        .all()
    )
    return [{"id": r.id, "name": r.name, "filter_params": r.filter_params} for r in rows]


def _apply_idempotency_key(*, key: str, endpoint: str, organization_id: int, request_hash: str):
    row, created = get_or_create(
        key=key,
        endpoint=endpoint,
        request_hash=request_hash,
        organization_id=organization_id,
    )
    return row, created


def list_admin_reservations(
    *,
    organization_id: int,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 25,
    sort: str = "created_at",
    direction: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    query = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
    )
    if status:
        query = query.filter(Reservation.status == status)
    if date_from:
        query = query.filter(Reservation.start_date >= date_from)
    if date_to:
        query = query.filter(Reservation.end_date <= date_to)
    if q:
        ilike = f"%{q.strip()}%"
        query = query.filter(or_(Reservation.guest_name.ilike(ilike), db.cast(Reservation.id, db.String).ilike(ilike)))
    sort_map = {"created_at": Reservation.created_at, "start_date": Reservation.start_date, "id": Reservation.id}
    col = sort_map.get(sort, Reservation.created_at)
    query = query.order_by(col.asc() if direction == "asc" else col.desc(), Reservation.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    return [
        {
            "id": r.id,
            "unit_id": r.unit_id,
            "guest_id": r.guest_id,
            "guest_name": r.guest_name,
            "start_date": r.start_date.isoformat(),
            "end_date": r.end_date.isoformat(),
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ], total


def list_admin_guests(
    *,
    organization_id: int,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 25,
    sort: str = "created_at",
    direction: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    query = Guest.query.filter(Guest.organization_id == organization_id)
    if q:
        ilike = f"%{q.strip()}%"
        query = query.filter(
            or_(
                Guest.first_name.ilike(ilike),
                Guest.last_name.ilike(ilike),
                Guest.email.ilike(ilike),
                Guest.phone.ilike(ilike),
            )
        )
    if date_from:
        query = query.filter(db.func.date(Guest.created_at) >= date_from)
    if date_to:
        query = query.filter(db.func.date(Guest.created_at) <= date_to)
    _ = status
    sort_map = {"created_at": Guest.created_at, "name": Guest.last_name, "id": Guest.id}
    col = sort_map.get(sort, Guest.created_at)
    query = query.order_by(col.asc() if direction == "asc" else col.desc(), Guest.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    return [
        {
            "id": r.id,
            "full_name": r.full_name,
            "first_name": r.first_name,
            "last_name": r.last_name,
            "email": r.email,
            "phone": r.phone,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ], total


def list_admin_invoices(
    *,
    organization_id: int,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    q: str | None = None,
    page: int = 1,
    per_page: int = 25,
    sort: str = "created_at",
    direction: str = "desc",
) -> tuple[list[dict[str, Any]], int]:
    query = Invoice.query.filter(Invoice.organization_id == organization_id)
    if status:
        query = query.filter(Invoice.status == status)
    if date_from:
        query = query.filter(Invoice.due_date >= date_from)
    if date_to:
        query = query.filter(Invoice.due_date <= date_to)
    if q:
        ilike = f"%{q.strip()}%"
        query = query.filter(Invoice.invoice_number.ilike(ilike))
    sort_map = {"created_at": Invoice.created_at, "due_date": Invoice.due_date, "id": Invoice.id}
    col = sort_map.get(sort, Invoice.created_at)
    query = query.order_by(col.asc() if direction == "asc" else col.desc(), Invoice.id.desc())
    total = query.count()
    rows = query.offset((page - 1) * per_page).limit(per_page).all()
    guest_cache: dict[int, str] = {}
    lease_guest_cache: dict[int, str] = {}

    def _guest_name(guest_id: int | None) -> str | None:
        if guest_id is None:
            return None
        if guest_id not in guest_cache:
            guest = Guest.query.filter_by(id=guest_id, organization_id=organization_id).first()
            guest_cache[guest_id] = guest.full_name if guest is not None else ""
        return guest_cache[guest_id] or None

    def _lease_guest_name(lease_id: int | None) -> str | None:
        if lease_id is None:
            return None
        if lease_id not in lease_guest_cache:
            lease = Lease.query.filter_by(id=lease_id, organization_id=organization_id).first()
            lease_guest_cache[lease_id] = (
                lease.guest.full_name if lease is not None and lease.guest is not None else ""
            )
        return lease_guest_cache[lease_id] or None

    return [
        {
            "id": r.id,
            "invoice_number": r.invoice_number,
            "customer_name": _guest_name(r.guest_id) or _lease_guest_name(r.lease_id),
            "status": r.status,
            "due_date": r.due_date.isoformat() if r.due_date else None,
            "currency": r.currency,
            "subtotal_excl_vat": str(r.subtotal_excl_vat),
            "vat_rate": str(r.vat_rate),
            "vat_amount": str(r.vat_amount),
            "total_incl_vat": str(r.total_incl_vat),
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ], total


def _csv_for_rows(*, rows: list[dict[str, Any]], columns: list[str]) -> str:
    buf = StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    for row in rows:
        writer.writerow({k: row.get(k) for k in columns})
    return buf.getvalue()
