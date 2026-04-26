from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import logging
from typing import Any, Mapping

from sqlalchemy import func as sa_func

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.email.models import TemplateKey
from app.email.services import send_template
from app.extensions import db
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.users.models import User

logger = logging.getLogger(__name__)

_RESERVATION_EDIT_STATUSES = frozenset({"confirmed", "cancelled"})


@dataclass
class ReservationServiceError(Exception):
    code: str
    message: str
    status: int


def parse_calendar_iso_bound(raw: str | None) -> date | None:
    """Parse FullCalendar ``start`` / ``end`` query params (date or datetime ISO)."""

    if raw is None or not str(raw).strip():
        return None
    value = str(raw).strip()
    if "T" in value:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).date()
    return date.fromisoformat(value[:10])


def _parse_iso_date(raw: str, field_name: str) -> date:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError as exc:
        raise ReservationServiceError(
            code="validation_error",
            message=f"Field '{field_name}' must be a valid ISO date (YYYY-MM-DD).",
            status=400,
        ) from exc


def _serialize_reservation(row: Reservation) -> dict:
    return {
        "id": row.id,
        "unit_id": row.unit_id,
        "guest_id": row.guest_id,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _scoped_reservation_query(*, organization_id: int):
    return (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
    )


def get_calendar_events(
    *,
    organization_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[dict]:
    """Reservations overlapping ``[start_date, end_date)`` for calendar display.

    When both bounds are omitted, no date filter is applied (still tenant-scoped).
    ``end`` in each event is the reservation checkout date (exclusive night boundary),
    aligned with :class:`~app.reservations.models.Reservation` semantics.
    """

    query = _scoped_reservation_query(organization_id=organization_id)
    if start_date is not None:
        query = query.filter(Reservation.end_date > start_date)
    if end_date is not None:
        query = query.filter(Reservation.start_date < end_date)
    rows = query.order_by(Reservation.start_date.asc(), Reservation.id.asc()).all()

    events: list[dict] = []
    for row in rows:
        guest = row.guest
        unit = row.unit
        guest_label = guest.email if guest is not None else "Guest"
        unit_name = unit.name if unit is not None else "Unit"
        property_id = unit.property_id if unit is not None else None
        events.append(
            {
                "id": row.id,
                "title": f"{guest_label} / {unit_name}",
                "start": row.start_date.isoformat(),
                "end": row.end_date.isoformat(),
                "status": row.status,
                "unit_id": row.unit_id,
                "property_id": property_id,
                "url": f"/admin/reservations/{row.id}/edit",
            }
        )
    return events


def list_reservations(*, organization_id: int) -> list[dict]:
    rows = _scoped_reservation_query(organization_id=organization_id).order_by(Reservation.id.asc()).all()
    return [_serialize_reservation(row) for row in rows]


def list_reservations_paginated(
    *,
    organization_id: int,
    page: int,
    per_page: int,
) -> tuple[list[dict], int]:
    query = _scoped_reservation_query(organization_id=organization_id)
    total = query.count()
    rows = (
        query.order_by(Reservation.id.asc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return [_serialize_reservation(row) for row in rows], total


def get_reservation(*, organization_id: int, reservation_id: int) -> dict:
    row = _scoped_reservation_query(organization_id=organization_id).filter(
        Reservation.id == reservation_id
    ).first()
    if row is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )
    return _serialize_reservation(row)


def get_reservation_for_edit(*, organization_id: int, reservation_id: int) -> dict:
    """Return reservation fields needed for the admin edit form (tenant-scoped)."""

    row = _scoped_reservation_query(organization_id=organization_id).filter(
        Reservation.id == reservation_id
    ).first()
    if row is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )
    guest = row.guest
    unit = row.unit
    prop = unit.property if unit is not None else None
    return {
        "id": row.id,
        "unit_id": row.unit_id,
        "property_id": unit.property_id if unit is not None else None,
        "guest_id": row.guest_id,
        "guest_name": guest.email if guest is not None else "",
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status,
        "property_name": prop.name if prop is not None else "",
        "unit_name": unit.name if unit is not None else "",
    }


def update_reservation(
    *,
    reservation_id: int,
    organization_id: int,
    data: Mapping[str, Any],
    actor_user_id: int | None = None,
) -> dict:
    """Update a reservation from validated form-like input; tenant- and overlap-safe."""

    row = _scoped_reservation_query(organization_id=organization_id).filter(
        Reservation.id == reservation_id
    ).first()
    if row is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )

    guest_name_raw = (data.get("guest_name") or "").strip()
    if not guest_name_raw:
        raise ReservationServiceError(
            code="validation_error",
            message="Guest name (email) is required.",
            status=400,
        )
    guest_email_norm = guest_name_raw.lower()
    guest = (
        User.query.filter(
            User.organization_id == organization_id,
            sa_func.lower(User.email) == guest_email_norm,
        ).first()
    )
    if guest is None:
        raise ReservationServiceError(
            code="validation_error",
            message="No user in your organization matches that guest email.",
            status=400,
        )

    try:
        property_id = int(data.get("property_id"))
        unit_id = int(data.get("unit_id"))
    except (TypeError, ValueError):
        raise ReservationServiceError(
            code="validation_error",
            message="Property and unit must be valid IDs.",
            status=400,
        ) from None

    unit = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(
            Unit.id == unit_id,
            Property.organization_id == organization_id,
        )
        .first()
    )
    if unit is None or unit.property_id != property_id:
        raise ReservationServiceError(
            code="validation_error",
            message="Selected unit does not belong to the chosen property.",
            status=400,
        )

    start_date = _parse_iso_date(str(data.get("start_date") or ""), "start_date")
    end_date = _parse_iso_date(str(data.get("end_date") or ""), "end_date")
    if start_date >= end_date:
        raise ReservationServiceError(
            code="validation_error",
            message="Field 'start_date' must be before 'end_date'.",
            status=400,
        )

    status = (data.get("status") or "").strip().lower()
    if status not in _RESERVATION_EDIT_STATUSES:
        raise ReservationServiceError(
            code="validation_error",
            message=f"Status must be one of: {', '.join(sorted(_RESERVATION_EDIT_STATUSES))}.",
            status=400,
        )

    if status == "confirmed":
        overlapping = (
            Reservation.query.filter(
                Reservation.unit_id == unit.id,
                Reservation.id != reservation_id,
                Reservation.status != "cancelled",
                Reservation.start_date < end_date,
                Reservation.end_date > start_date,
            )
            .first()
        )
        if overlapping is not None:
            raise ReservationServiceError(
                code="validation_error",
                message="Unit already has an overlapping reservation for the given dates.",
                status=400,
            )

    before = {
        "unit_id": row.unit_id,
        "guest_id": row.guest_id,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status,
    }

    row.unit_id = unit.id
    row.guest_id = guest.id
    row.start_date = start_date
    row.end_date = end_date
    row.status = status

    audit_record(
        "reservation_updated",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="reservation",
        target_id=row.id,
        context={
            "before": before,
            "after": {
                "unit_id": row.unit_id,
                "guest_id": row.guest_id,
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat(),
                "status": row.status,
            },
            "user_id": actor_user_id,
        },
        commit=False,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return _serialize_reservation(row)


def create_reservation(
    *,
    organization_id: int,
    unit_id: int,
    guest_id: int,
    start_date_raw: str,
    end_date_raw: str,
    actor_user_id: int | None = None,
) -> dict:
    unit = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Unit.id == unit_id, Property.organization_id == organization_id)
        .first()
    )
    if unit is None:
        raise ReservationServiceError(
            code="not_found",
            message="Unit not found.",
            status=404,
        )

    guest = User.query.filter_by(id=guest_id, organization_id=organization_id).first()
    if guest is None:
        raise ReservationServiceError(
            code="not_found",
            message="Guest not found.",
            status=404,
        )

    start_date = _parse_iso_date(start_date_raw, "start_date")
    end_date = _parse_iso_date(end_date_raw, "end_date")
    if start_date >= end_date:
        raise ReservationServiceError(
            code="validation_error",
            message="Field 'start_date' must be before 'end_date'.",
            status=400,
        )

    overlapping = (
        Reservation.query.filter(
            Reservation.unit_id == unit.id,
            Reservation.status != "cancelled",
            Reservation.start_date < end_date,
            Reservation.end_date > start_date,
        )
        .first()
    )
    if overlapping is not None:
        raise ReservationServiceError(
            code="validation_error",
            message="Unit already has an overlapping reservation for the given dates.",
            status=400,
        )

    row = Reservation(
        unit_id=unit.id,
        guest_id=guest.id,
        start_date=start_date,
        end_date=end_date,
        status="confirmed",
    )
    db.session.add(row)
    db.session.commit()
    audit_record(
        "reservation_created",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="reservation",
        target_id=row.id,
        context={
            "unit_id": row.unit_id,
            "guest_id": row.guest_id,
            "start_date": row.start_date.isoformat(),
            "end_date": row.end_date.isoformat(),
            "user_id": actor_user_id,
        },
        commit=True,
    )
    _send_reservation_email(
        template_key=TemplateKey.RESERVATION_CONFIRMATION,
        to_email=guest.email,
        reservation=row,
        guest=guest,
    )
    return _serialize_reservation(row)


def cancel_reservation(
    *,
    organization_id: int,
    reservation_id: int,
    actor_user_id: int | None = None,
) -> dict:
    row = _scoped_reservation_query(organization_id=organization_id).filter(
        Reservation.id == reservation_id
    ).first()
    if row is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )

    row.status = "cancelled"
    db.session.commit()
    audit_record(
        "reservation_cancelled",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="reservation",
        target_id=row.id,
        context={"unit_id": row.unit_id, "guest_id": row.guest_id, "user_id": actor_user_id},
        commit=True,
    )
    _send_reservation_email(
        template_key=TemplateKey.RESERVATION_CANCELLED,
        to_email=row.guest.email,
        reservation=row,
        guest=row.guest,
    )
    return _serialize_reservation(row)


def _send_reservation_email(
    *,
    template_key: str,
    to_email: str,
    reservation: Reservation,
    guest: User,
) -> None:
    try:
        send_template(
            template_key,
            to=to_email,
            context={
                "user_email": guest.email,
                "reservation_id": reservation.id,
                "unit_name": reservation.unit.name,
                "start_date": reservation.start_date.isoformat(),
                "end_date": reservation.end_date.isoformat(),
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send reservation notification email to %s", to_email)
