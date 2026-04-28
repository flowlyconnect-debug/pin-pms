from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from flask import current_app, g, url_for
from sqlalchemy import func

from app.audit.models import AuditLog
from app.billing.models import Invoice, Lease
from app.backups.models import Backup, BackupStatus
from app.email.models import OutgoingEmail, OutgoingEmailStatus
from app.integrations.ical.models import ImportedCalendarEvent
from app.integrations.ical.models import ImportedCalendarFeed
from app.maintenance.models import MaintenanceRequest
from app.portal.models import AccessCode, PortalCheckInToken
from app.properties.models import Property, Unit
from app.reports import services as report_service
from app.reservations.models import Reservation
from app.extensions import db


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


def _sum_invoice_amount(*, organization_id: int, statuses: tuple[str, ...]) -> Decimal:
    value = (
        Invoice.query.with_entities(func.coalesce(func.sum(Invoice.amount), 0))
        .filter(
            Invoice.organization_id == organization_id,
            Invoice.status.in_(statuses),
        )
        .scalar()
    )
    return Decimal(value or 0)


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
        occupancy_percent = round((reservations_count / total_units) * 100, 1) if total_units else 0.0
        by_day.append(
            {
                "date": current_day.isoformat(),
                "reservation_count": reservations_count,
                "occupancy_percent": occupancy_percent,
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
    cache: dict[tuple[int, bool, str], dict[str, Any]] = getattr(g, "_admin_dashboard_stats_cache", {})
    cache_key = (organization_id, bool(viewer_is_superadmin), normalized_range)
    if cache_key in cache:
        return cache[cache_key]

    total_properties = Property.query.filter_by(organization_id=organization_id).count()
    total_units = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
        .count()
    )
    today = date.today()
    range_start, range_end, range_days = _resolve_range_window(range_key=normalized_range, today=today)
    range_start_dt = datetime.combine(range_start, datetime.min.time(), tzinfo=timezone.utc)
    range_end_dt = datetime.combine(range_end + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)

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
            func.coalesce(func.sum(Invoice.amount).filter(Invoice.status.in_(("open", "overdue"))), 0).label(
                "open_receivables"
            ),
            func.coalesce(func.sum(Invoice.amount).filter(Invoice.status == "overdue"), 0).label("overdue_amount"),
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
            func.count().filter(MaintenanceRequest.status.in_(("new", "in_progress", "waiting"))).label(
                "open_maintenance_requests"
            ),
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

    range_total_revenue = _sum_paid_between(
        organization_id=organization_id,
        start_dt=range_start_dt,
        end_dt=range_end_dt,
    )
    compare_start = range_start_dt - timedelta(days=range_days)
    compare_end = range_start_dt
    range_compare_revenue = _sum_paid_between(
        organization_id=organization_id,
        start_dt=compare_start,
        end_dt=compare_end,
    )
    revenue_trend_pct: float | None = None
    if range_compare_revenue != Decimal("0"):
        revenue_trend_pct = float(((range_total_revenue - range_compare_revenue) / range_compare_revenue) * Decimal("100"))

    now_utc = datetime.now(timezone.utc)
    backup_metrics = (
        db.session.query(
            db.session.query(Backup.status).order_by(Backup.created_at.desc(), Backup.id.desc()).limit(1).scalar_subquery().label(
                "latest_status"
            ),
            func.max(Backup.created_at).filter(Backup.status == BackupStatus.SUCCESS).label("last_success_at"),
            func.max(Backup.created_at).filter(Backup.status == BackupStatus.FAILED).label("last_failure_at"),
        )
        .select_from(Backup)
        .one()
    )
    latest_status = backup_metrics.latest_status
    latest_success_at = backup_metrics.last_success_at
    latest_failure_at = backup_metrics.last_failure_at
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
        email_q = email_q.filter(getattr(OutgoingEmail, "organization_id") == organization_id)
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
        "last_failure_template_key": latest_failed_email.template_key if latest_failed_email else None,
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
    ical_feeds_active = ImportedCalendarFeed.query.filter_by(organization_id=organization_id, is_active=True).count()

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
        "top_overdue_invoices": top_overdue_invoices,
        "top_open_maintenance_requests": top_open_maintenance_requests,
        "today_arrivals": today_arrivals,
        "today_departures": today_departures,
        "action_required": action_required,
        "arrivals_this_week": arrivals_in_range,
        "departures_this_week": departures_in_range,
        "arrivals_in_range": arrivals_in_range,
        "departures_in_range": departures_in_range,
        "range_key": normalized_range,
        "range_label": range_label,
        "latest_audit_events": latest_audit_events,
        "week_overview": week_overview,
        "revenue": {
            "month_to_date": range_total_revenue,
            "previous_month": range_compare_revenue,
            "range_total": range_total_revenue,
            "range_compare": range_compare_revenue,
            "trend_pct": revenue_trend_pct,
            "open_receivables": open_receivables,
            "overdue_amount": overdue_amount,
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
    cache[cache_key] = result
    g._admin_dashboard_stats_cache = cache
    return result


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
