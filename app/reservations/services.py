from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import logging

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.email.models import TemplateKey
from app.email.services import send_template
from app.extensions import db
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.users.models import User

logger = logging.getLogger(__name__)


@dataclass
class ReservationServiceError(Exception):
    code: str
    message: str
    status: int


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
