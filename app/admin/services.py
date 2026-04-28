from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from flask import url_for

from app.audit.models import AuditLog
from app.billing.models import Invoice, Lease
from app.integrations.ical.models import ImportedCalendarEvent
from app.maintenance.models import MaintenanceRequest
from app.portal.models import AccessCode, PortalCheckInToken
from app.properties.models import Property, Unit
from app.reports import services as report_service
from app.reservations.models import Reservation


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
        if endpoint == "admin.calendar_sync_conflicts":
            return "/admin/calendar-sync/conflicts"
        return "#"


def get_dashboard_stats(*, organization_id: int) -> dict:
    """Aggregate operational KPIs for the admin dashboard (single-tenant scope)."""

    total_properties = Property.query.filter_by(organization_id=organization_id).count()
    total_units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .count()
    )
    scoped_reservations = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
    )
    active_reservations = scoped_reservations.filter(Reservation.status == "confirmed").count()
    cancelled_reservations = scoped_reservations.filter(Reservation.status == "cancelled").count()

    today = date.today()
    occupancy = report_service.occupancy_report(
        organization_id=organization_id,
        start_date=today,
        end_date=today + timedelta(days=1),
    )
    occupancy_percent = float(occupancy["occupancy_percentage"])

    confirmed = scoped_reservations.filter(Reservation.status == "confirmed")
    arrivals_today = confirmed.filter(Reservation.start_date == today).count()
    departures_today = confirmed.filter(Reservation.end_date == today).count()
    current_guests = confirmed.filter(
        Reservation.start_date <= today,
        Reservation.end_date > today,
    ).count()
    upcoming_reservations = confirmed.filter(Reservation.start_date > today).count()
    active_leases = (
        Lease.query.filter_by(organization_id=organization_id)
        .filter(Lease.status == "active")
        .count()
    )
    open_invoices = (
        Invoice.query.filter_by(organization_id=organization_id)
        .filter(Invoice.status.in_(("open", "overdue")))
        .count()
    )
    overdue_invoices = (
        Invoice.query.filter_by(organization_id=organization_id)
        .filter(Invoice.status == "overdue")
        .count()
    )
    open_maintenance_requests = (
        MaintenanceRequest.query.filter_by(organization_id=organization_id)
        .filter(MaintenanceRequest.status.in_(("new", "in_progress", "waiting")))
        .count()
    )
    urgent_maintenance_requests = (
        MaintenanceRequest.query.filter_by(organization_id=organization_id)
        .filter(
            MaintenanceRequest.priority == "urgent",
            MaintenanceRequest.status.in_(("new", "in_progress", "waiting")),
        )
        .count()
    )
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
    top_overdue_invoices_rows = (
        Invoice.query.filter_by(organization_id=organization_id)
        .filter(Invoice.status == "overdue")
        .order_by(Invoice.due_date.asc(), Invoice.id.asc())
        .limit(5)
        .all()
    )
    top_overdue_invoices = [
        {
            "id": row.id,
            "invoice_number": row.invoice_number,
            "due_date": row.due_date.isoformat() if row.due_date else None,
            "amount": str(row.amount),
            "currency": row.currency,
            "status": row.status,
        }
        for row in top_overdue_invoices_rows
    ]
    top_maintenance_rows = (
        MaintenanceRequest.query.filter_by(organization_id=organization_id)
        .filter(
            MaintenanceRequest.status.in_(("new", "in_progress", "waiting")),
            MaintenanceRequest.priority.in_(("urgent", "high")),
        )
        .order_by(
            MaintenanceRequest.priority.desc(),
            MaintenanceRequest.due_date.asc().nulls_last(),
            MaintenanceRequest.id.desc(),
        )
        .limit(5)
        .all()
    )
    top_open_maintenance_requests = [
        {
            "id": row.id,
            "title": row.title,
            "priority": row.priority,
            "status": row.status,
            "due_date": row.due_date.isoformat() if row.due_date else None,
        }
        for row in top_maintenance_rows
    ]
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
                part for part in [(row.guest.first_name or "").strip(), (row.guest.last_name or "").strip()] if part
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

    now_utc = datetime.now(timezone.utc)
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
        PortalCheckInToken.query.join(Reservation, PortalCheckInToken.reservation_id == Reservation.id)
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
    action_required = [
        {
            "kind": "invoice_overdue",
            "label": f"Myöhässä oleva lasku {row.invoice_number or f'#{row.id}'}",
            "link": _safe_url_for("admin.invoices_detail", invoice_id=row.id),
            "severity": "danger",
            "since": row.due_date.isoformat() if row.due_date else None,
        }
        for row in overdue_invoice_rows
    ] + [
        {
            "kind": "maintenance_new",
            "label": f"Uusi huoltopyyntö #{row.id}: {row.title}",
            "link": _safe_url_for("admin.maintenance_requests_detail", request_id=row.id),
            "severity": "warning",
            "since": row.created_at.isoformat() if row.created_at else None,
        }
        for row in new_maintenance_rows
    ] + [
        {
            "kind": "checkin_expired",
            "label": f"Vanhentunut sisäänkirjautumislinkki varaukselle #{row.reservation_id}",
            "link": _safe_url_for("admin.reservations_detail", reservation_id=row.reservation_id),
            "severity": "warning",
            "since": row.expires_at.isoformat() if row.expires_at else None,
        }
        for row in expired_checkin_rows
    ] + [
        {
            "kind": "ical_conflict",
            "label": f"iCal-konflikti: {(row.summary or f'Tapahtuma #{row.id}')}",
            "link": _safe_url_for("admin.calendar_sync_conflicts"),
            "severity": "danger",
            "since": row.created_at.isoformat() if row.created_at else None,
        }
        for row in ical_conflict_rows
    ]
    action_required.sort(key=lambda item: item["since"] or "")

    arrivals_this_week = confirmed.filter(
        Reservation.start_date >= today,
        Reservation.start_date <= today + timedelta(days=6),
    ).count()

    latest_rows = (
        AuditLog.query.filter_by(organization_id=organization_id)
        .order_by(AuditLog.created_at.desc())
        .limit(5)
        .all()
    )
    latest_audit_events = [_serialize_audit_event(r) for r in latest_rows]

    return {
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
        "top_overdue_invoices": top_overdue_invoices,
        "top_open_maintenance_requests": top_open_maintenance_requests,
        "today_arrivals": today_arrivals,
        "today_departures": today_departures,
        "action_required": action_required,
        "arrivals_this_week": arrivals_this_week,
        "latest_audit_events": latest_audit_events,
        # Back-compat for templates/tests that used the older names:
        "occupancy_percentage": occupancy_percent,
        "latest_events": latest_rows,
    }


def dashboard_summary(*, organization_id: int) -> dict:
    """Deprecated alias — use :func:`get_dashboard_stats`."""

    return get_dashboard_stats(organization_id=organization_id)


# User lifecycle — delegated to :mod:`app.users.services`.
from app.users import services as _users_services  # noqa: E402

UserServiceError = _users_services.UserServiceError
create_user = _users_services.create_user
update_user_role = _users_services.update_user_role
deactivate_user = _users_services.deactivate_user
reactivate_user = _users_services.reactivate_user
change_password = _users_services.change_password
