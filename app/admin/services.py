from __future__ import annotations

from datetime import date, timedelta

from app.audit.models import AuditLog
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
        "current_guests": current_guests,
        "upcoming_reservations": upcoming_reservations,
        "latest_audit_events": latest_audit_events,
        # Back-compat for templates/tests that used the older names:
        "occupancy_percentage": occupancy_percent,
        "latest_events": latest_rows,
    }


def dashboard_summary(*, organization_id: int) -> dict:
    """Deprecated alias — use :func:`get_dashboard_stats`."""

    return get_dashboard_stats(organization_id=organization_id)
