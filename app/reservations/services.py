from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
import logging
from typing import Any, Mapping

from flask import Response
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy.orm import noload

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.email.models import TemplateKey
from app.email.services import send_template
from app.extensions import db
from app.guests.models import Guest
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.users.models import User, UserRole

logger = logging.getLogger(__name__)

_RESERVATION_EDIT_STATUSES = frozenset({"confirmed", "cancelled"})
_PAYMENT_STATUSES = frozenset({"pending", "paid", "cancelled"})


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
        "guest_name": row.guest_name,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status,
        "amount": str(row.amount) if row.amount is not None else None,
        "currency": row.currency,
        "payment_status": row.payment_status,
        "invoice_number": row.invoice_number,
        "invoice_date": row.invoice_date.isoformat() if row.invoice_date else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _parse_amount(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        value = Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise ReservationServiceError(
            code="validation_error",
            message="Amount must be a valid decimal number.",
            status=400,
        ) from None
    if value < Decimal("0.00"):
        raise ReservationServiceError(
            code="validation_error",
            message="Amount must be zero or greater.",
            status=400,
        )
    return value


def _parse_currency(raw: Any) -> str:
    text = str(raw or "EUR").strip().upper()
    if len(text) != 3 or not text.isalpha():
        raise ReservationServiceError(
            code="validation_error",
            message="Currency must be a 3-letter ISO code.",
            status=400,
        )
    return text


def _scoped_reservation_query(*, organization_id: int):
    return (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Property.organization_id == organization_id)
    )


def _guest_full_name(guest: Guest | None) -> str:
    if guest is None:
        return ""
    return f"{(guest.first_name or '').strip()} {(guest.last_name or '').strip()}".strip()


def _display_guest_name(*, guest: Guest | None, guest_name: str) -> str:
    if guest is not None:
        # Prefer explicit first+last guest profiles; legacy shadow profiles
        # may only have a local-part first name and should render as email.
        if (guest.first_name or "").strip() and (guest.last_name or "").strip():
            return _guest_full_name(guest)
        if (guest.email or "").strip():
            return str(guest.email).strip()
    trimmed = (guest_name or "").strip()
    return trimmed or "Guest"


def get_calendar_events(
    *,
    organization_id: int,
    start_date: date | None = None,
    end_date: date | None = None,
    property_id: int | None = None,
    unit_id: int | None = None,
) -> list[dict]:
    """Reservations overlapping ``[start_date, end_date)`` for calendar display.

    When both bounds are omitted, no date filter is applied (still tenant-scoped).
    ``end`` in each event is the reservation checkout date (exclusive night boundary),
    aligned with :class:`~app.reservations.models.Reservation` semantics.

    Optional ``property_id`` / ``unit_id`` must belong to ``organization_id`` or
    :class:`ReservationServiceError` is raised (no cross-tenant filter leakage).
    """

    query = _scoped_reservation_query(organization_id=organization_id)
    if property_id is not None:
        prop = Property.query.filter_by(
            id=property_id, organization_id=organization_id
        ).first()
        if prop is None:
            raise ReservationServiceError(
                code="validation_error",
                message="Invalid property filter.",
                status=400,
            )
        query = query.filter(Property.id == property_id)
    if unit_id is not None:
        unit = (
            Unit.query.join(Property, Unit.property_id == Property.id)
            .filter(
                Unit.id == unit_id,
                Property.organization_id == organization_id,
            )
            .first()
        )
        if unit is None:
            raise ReservationServiceError(
                code="validation_error",
                message="Invalid unit filter.",
                status=400,
            )
        if property_id is not None and unit.property_id != property_id:
            raise ReservationServiceError(
                code="validation_error",
                message="Unit does not belong to the selected property.",
                status=400,
            )
        query = query.filter(Reservation.unit_id == unit_id)
    if start_date is not None:
        query = query.filter(Reservation.end_date > start_date)
    if end_date is not None:
        query = query.filter(Reservation.start_date < end_date)
    rows = query.order_by(Reservation.start_date.asc(), Reservation.id.asc()).all()

    def _calendar_color(status: str) -> str:
        if status == "confirmed":
            return "#10b981"
        if status == "cancelled":
            return "#9ca3af"
        return "#3b82f6"

    def _calendar_title_guest(label: str) -> str:
        trimmed = (label or "").strip()
        if not trimmed:
            return "Guest"
        if "@" in trimmed:
            return trimmed.split("@", 1)[0].strip() or "Guest"
        return trimmed

    events: list[dict] = []
    for row in rows:
        guest = row.guest
        unit = row.unit
        guest_name = _display_guest_name(guest=guest, guest_name=row.guest_name)
        guest_title = _calendar_title_guest(guest_name)
        unit_name = unit.name if unit is not None else "Unit"
        property_name = unit.property.name if unit is not None and unit.property is not None else ""
        property_id = unit.property_id if unit is not None else None
        events.append(
            {
                "id": row.id,
                "title": f"{guest_title} – {unit_name}",
                "start": row.start_date.isoformat(),
                "end": row.end_date.isoformat(),
                "status": row.status,
                "unit_id": row.unit_id,
                "property_id": property_id,
                "color": _calendar_color(row.status),
                "extendedProps": {
                    "guest_name": guest_name,
                    "guest_id": row.guest_id,
                    "property_name": property_name,
                    "unit_name": unit_name,
                    "status": row.status,
                    "unit_id": row.unit_id,
                },
                "url": f"/admin/reservations/{row.id}/edit",
                "editable": row.status != "cancelled",
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


def _reservation_display_dict(*, row: Reservation) -> dict:
    guest = row.guest
    unit = row.unit
    prop = unit.property if unit is not None else None
    return {
        "id": row.id,
        "unit_id": row.unit_id,
        "property_id": unit.property_id if unit is not None else None,
        "guest_id": row.guest_id,
        "guest_name": _display_guest_name(guest=guest, guest_name=row.guest_name),
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status,
        "amount": str(row.amount) if row.amount is not None else None,
        "currency": row.currency,
        "payment_status": row.payment_status,
        "invoice_number": row.invoice_number,
        "invoice_date": row.invoice_date.isoformat() if row.invoice_date else None,
        "due_date": row.due_date.isoformat() if row.due_date else None,
        "property_name": prop.name if prop is not None else "",
        "unit_name": unit.name if unit is not None else "",
    }


def get_reservation_detail(*, organization_id: int, reservation_id: int) -> dict:
    """Rich reservation payload for the admin detail page (tenant-scoped)."""

    row = _scoped_reservation_query(organization_id=organization_id).filter(
        Reservation.id == reservation_id
    ).first()
    if row is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )
    return _reservation_display_dict(row=row)


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
    return _reservation_display_dict(row=row)


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

    guest_id_raw = data.get("guest_id")
    guest_name_raw = (data.get("guest_name") or "").strip()
    guest: Guest | None = None
    if str(guest_id_raw or "").strip():
        try:
            parsed_guest_id = int(guest_id_raw)
        except (TypeError, ValueError):
            raise ReservationServiceError(
                code="validation_error",
                message="Guest must be a valid ID.",
                status=400,
            ) from None
        guest = Guest.query.filter_by(id=parsed_guest_id, organization_id=organization_id).first()
        if guest is None:
            raise ReservationServiceError(
                code="validation_error",
                message="Selected guest was not found in your organization.",
                status=400,
            )
    guest_name = guest_name_raw or _display_guest_name(guest=guest, guest_name="")
    if not guest_name:
        raise ReservationServiceError(
            code="validation_error",
            message="Guest name is required when no linked guest is selected.",
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
    amount = _parse_amount(data.get("amount"))
    currency = _parse_currency(data.get("currency"))

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
        "guest_name": row.guest_name,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status,
        "amount": str(row.amount) if row.amount is not None else None,
        "currency": row.currency,
        "payment_status": row.payment_status,
    }

    row.unit_id = unit.id
    row.guest_id = guest.id if guest is not None else None
    row.guest_name = guest_name
    row.start_date = start_date
    row.end_date = end_date
    row.status = status
    row.amount = amount
    row.currency = currency

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
                "guest_name": row.guest_name,
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat(),
                "status": row.status,
                "amount": str(row.amount) if row.amount is not None else None,
                "currency": row.currency,
                "payment_status": row.payment_status,
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
    guest_id: int | None,
    guest_name: str | None = None,
    start_date_raw: str,
    end_date_raw: str,
    amount: Any = None,
    currency: Any = "EUR",
    actor_user_id: int | None = None,
) -> dict:
    amount_value = _parse_amount(amount)
    currency_value = _parse_currency(currency)
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

    guest: Guest | None = None
    resolved_guest_name = (guest_name or "").strip()
    if guest_id is not None:
        guest = Guest.query.filter_by(id=guest_id, organization_id=organization_id).first()
        if guest is None:
            # Back-compat: existing tests/forms may post a user id in guest_id.
            legacy_user = User.query.filter_by(id=guest_id, organization_id=organization_id).first()
            if legacy_user is not None:
                resolved_guest_name = resolved_guest_name or legacy_user.email
            else:
                raise ReservationServiceError(
                    code="not_found",
                    message="Guest not found.",
                    status=404,
                )
        else:
            resolved_guest_name = resolved_guest_name or _display_guest_name(guest=guest, guest_name="")
    if not resolved_guest_name:
        raise ReservationServiceError(
            code="validation_error",
            message="Guest name is required when no linked guest is selected.",
            status=400,
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
        guest_id=guest.id if guest is not None else None,
        guest_name=resolved_guest_name,
        start_date=start_date,
        end_date=end_date,
        status="confirmed",
        amount=amount_value,
        currency=currency_value,
        payment_status="pending",
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
            "guest_name": row.guest_name,
            "start_date": row.start_date.isoformat(),
            "end_date": row.end_date.isoformat(),
            "amount": str(row.amount) if row.amount is not None else None,
            "currency": row.currency,
            "payment_status": row.payment_status,
            "user_id": actor_user_id,
        },
        commit=True,
    )
    if guest is not None and guest.email:
        _send_reservation_email(
            template_key=TemplateKey.RESERVATION_CONFIRMATION,
            to_email=guest.email,
            reservation=row,
            guest_name=_display_guest_name(guest=guest, guest_name=row.guest_name),
        )
    return _serialize_reservation(row)


def move_reservation(
    *,
    reservation_id: int,
    organization_id: int,
    payload: Mapping[str, Any],
    actor_user_id: int | None = None,
    actor_role: str | None = None,
) -> dict:
    """Move a reservation to new dates and/or unit (admin/superadmin, tenant-scoped, overlap-safe)."""

    if actor_role not in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        raise ReservationServiceError(
            code="forbidden",
            message="Admin privileges required.",
            status=403,
        )

    start_raw = payload.get("start_date")
    end_raw = payload.get("end_date")
    start_date = _parse_iso_date(str(start_raw or ""), "start_date")
    end_date = _parse_iso_date(str(end_raw or ""), "end_date")
    if start_date >= end_date:
        raise ReservationServiceError(
            code="validation_error",
            message="Field 'start_date' must be before 'end_date'.",
            status=400,
        )

    try:
        unit_id = int(payload.get("unit_id"))
    except (TypeError, ValueError):
        raise ReservationServiceError(
            code="validation_error",
            message="Field 'unit_id' must be a valid integer.",
            status=400,
        ) from None

    unit = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Unit.id == unit_id, Property.organization_id == organization_id)
        .first()
    )
    if unit is None:
        raise ReservationServiceError(
            code="validation_error",
            message="Unit not found.",
            status=400,
        )

    # Lock the reservation row without loading ``joined`` relationships, otherwise
    # PostgreSQL rejects ``FOR UPDATE`` on the nullable side of outer joins.
    row = (
        Reservation.query.options(noload(Reservation.unit), noload(Reservation.guest))
        .filter_by(id=reservation_id)
        .with_for_update()
        .first()
    )
    if row is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )
    in_tenant = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Unit.id == row.unit_id, Property.organization_id == organization_id)
        .first()
    )
    if in_tenant is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )

    before = {
        "unit_id": row.unit_id,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status,
    }

    if row.status == "confirmed":
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
                code="reservation_overlap",
                message="Reservation overlaps with another reservation.",
                status=409,
            )

    row.unit_id = unit.id
    row.start_date = start_date
    row.end_date = end_date

    audit_record(
        "reservation_moved",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="reservation",
        target_id=row.id,
        context={
            "before": before,
            "after": {
                "unit_id": row.unit_id,
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


def resize_reservation(
    *,
    reservation_id: int,
    organization_id: int,
    payload: Mapping[str, Any],
    actor_user_id: int | None = None,
    actor_role: str | None = None,
) -> dict:
    """Resize a reservation in-place (admin/superadmin, tenant-scoped, overlap-safe)."""

    if actor_role not in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        raise ReservationServiceError(
            code="forbidden",
            message="Admin privileges required.",
            status=403,
        )

    start_raw = payload.get("start_date")
    end_raw = payload.get("end_date")
    start_date = _parse_iso_date(str(start_raw or ""), "start_date")
    end_date = _parse_iso_date(str(end_raw or ""), "end_date")
    if start_date >= end_date:
        raise ReservationServiceError(
            code="validation_error",
            message="Field 'start_date' must be before 'end_date'.",
            status=400,
        )

    # Lock the reservation row without joined eager relationships.
    row = (
        Reservation.query.options(noload(Reservation.unit), noload(Reservation.guest))
        .filter_by(id=reservation_id)
        .with_for_update()
        .first()
    )
    if row is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )
    in_tenant = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(Unit.id == row.unit_id, Property.organization_id == organization_id)
        .first()
    )
    if in_tenant is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )

    if row.status == "confirmed":
        overlapping = (
            Reservation.query.filter(
                Reservation.unit_id == row.unit_id,
                Reservation.id != reservation_id,
                Reservation.status != "cancelled",
                Reservation.start_date < end_date,
                Reservation.end_date > start_date,
            )
            .first()
        )
        if overlapping is not None:
            raise ReservationServiceError(
                code="reservation_overlap",
                message="Reservation overlaps with another reservation.",
                status=409,
            )

    before = {
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status,
    }

    row.start_date = start_date
    row.end_date = end_date

    audit_record(
        "reservation_resized",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="reservation",
        target_id=row.id,
        context={
            "before": before,
            "after": {
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


def cancel_reservation(
    *,
    organization_id: int,
    reservation_id: int,
    actor_user_id: int | None = None,
) -> dict:
    """Mark reservation cancelled (tenant-safe). Idempotent if already cancelled."""

    row = _scoped_reservation_query(organization_id=organization_id).filter(
        Reservation.id == reservation_id
    ).first()
    if row is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )

    if row.status == "cancelled":
        return _serialize_reservation(row)

    row.status = "cancelled"
    if row.payment_status != "paid":
        row.payment_status = "cancelled"
    audit_record(
        "reservation_cancelled",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="reservation",
        target_id=row.id,
        context={"unit_id": row.unit_id, "guest_id": row.guest_id, "user_id": actor_user_id},
        commit=False,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    if row.guest is not None and row.guest.email:
        _send_reservation_email(
            template_key=TemplateKey.RESERVATION_CANCELLED,
            to_email=row.guest.email,
            reservation=row,
            guest_name=_display_guest_name(guest=row.guest, guest_name=row.guest_name),
        )
    return _serialize_reservation(row)


def mark_reservation_paid(
    *,
    reservation_id: int,
    organization_id: int,
    actor_user: User,
) -> dict:
    """Mark reservation paid (admin/superadmin, tenant-safe)."""

    if actor_user.role not in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        raise ReservationServiceError(
            code="forbidden",
            message="Admin privileges required.",
            status=403,
        )

    row = _scoped_reservation_query(organization_id=organization_id).filter(
        Reservation.id == reservation_id
    ).first()
    if row is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )
    if row.payment_status == "paid":
        return _serialize_reservation(row)
    if row.payment_status not in _PAYMENT_STATUSES:
        raise ReservationServiceError(
            code="validation_error",
            message="Reservation has an invalid payment status.",
            status=400,
        )

    before_status = row.payment_status
    row.payment_status = "paid"
    audit_record(
        "reservation_paid",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user.id,
        organization_id=organization_id,
        target_type="reservation",
        target_id=row.id,
        context={
            "before": {"payment_status": before_status},
            "after": {"payment_status": row.payment_status},
            "user_id": actor_user.id,
        },
        commit=False,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return _serialize_reservation(row)


def _next_invoice_number(*, organization_id: int, reservation_id: int) -> str:
    return f"INV-{organization_id}-{reservation_id:06d}"


def _build_invoice_pdf_bytes(*, row: Reservation, organization_id: int) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    page_w, page_h = A4
    y = page_h - 48

    def write_line(text: str, *, size: int = 11, step: int = 18) -> None:
        nonlocal y
        pdf.setFont("Helvetica", size)
        pdf.drawString(48, y, text)
        y -= step

    invoice_number = row.invoice_number or _next_invoice_number(
        organization_id=organization_id,
        reservation_id=row.id,
    )
    invoice_date = row.invoice_date.isoformat() if row.invoice_date else "-"
    due_date = row.due_date.isoformat() if row.due_date else "-"
    amount = str(row.amount) if row.amount is not None else "-"
    guest_email = ""
    if row.guest is not None and row.guest.email:
        guest_email = str(row.guest.email)

    pdf.setTitle(f"Invoice {invoice_number}")
    write_line("Pindora PMS Invoice", size=16, step=26)
    write_line(f"Invoice number: {invoice_number}")
    write_line(f"Invoice date: {invoice_date}")
    write_line(f"Due date: {due_date}")
    y -= 8
    write_line(f"Guest name: {row.guest_name}")
    write_line(f"Guest email: {guest_email or '-'}")
    write_line(f"Property: {row.unit.property.name}")
    write_line(f"Unit: {row.unit.name}")
    write_line(f"Reservation start: {row.start_date.isoformat()}")
    write_line(f"Reservation end: {row.end_date.isoformat()}")
    y -= 8
    write_line(f"Amount: {amount}")
    write_line(f"Currency: {row.currency}")
    write_line(f"Payment status: {row.payment_status}")

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def generate_invoice(
    *,
    reservation_id: int,
    organization_id: int,
    actor_user: User,
) -> Response:
    """Generate PDF invoice/receipt for a reservation (tenant-safe, admin-only)."""

    if actor_user.role not in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        raise ReservationServiceError(
            code="forbidden",
            message="Admin privileges required.",
            status=403,
        )

    row = _scoped_reservation_query(organization_id=organization_id).filter(
        Reservation.id == reservation_id
    ).first()
    if row is None:
        raise ReservationServiceError(
            code="not_found",
            message="Reservation not found.",
            status=404,
        )

    if not row.invoice_number:
        row.invoice_number = _next_invoice_number(
            organization_id=organization_id,
            reservation_id=row.id,
        )
    if row.invoice_date is None:
        row.invoice_date = date.today()
    if row.due_date is None:
        row.due_date = row.invoice_date + timedelta(days=14)

    audit_record(
        "invoice_generated",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user.id,
        organization_id=organization_id,
        target_type="reservation",
        target_id=row.id,
        context={
            "invoice_number": row.invoice_number,
            "invoice_date": row.invoice_date.isoformat() if row.invoice_date else None,
            "due_date": row.due_date.isoformat() if row.due_date else None,
            "payment_status": row.payment_status,
            "amount": str(row.amount) if row.amount is not None else None,
            "currency": row.currency,
            "user_id": actor_user.id,
        },
        commit=False,
    )
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    pdf_bytes = _build_invoice_pdf_bytes(row=row, organization_id=organization_id)
    filename = f"invoice-{row.invoice_number or row.id}.pdf"
    response = Response(pdf_bytes, mimetype="application/pdf")
    response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.headers["Content-Length"] = str(len(pdf_bytes))
    response.headers["Cache-Control"] = "no-store"
    return response


def _send_reservation_email(
    *,
    template_key: str,
    to_email: str,
    reservation: Reservation,
    guest_name: str,
) -> None:
    try:
        send_template(
            template_key,
            to=to_email,
            context={
                "user_email": to_email,
                "guest_name": guest_name,
                "reservation_id": reservation.id,
                "unit_name": reservation.unit.name,
                "start_date": reservation.start_date.isoformat(),
                "end_date": reservation.end_date.isoformat(),
            },
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send reservation notification email to %s", to_email)
