from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func as sa_func
from sqlalchemy import or_

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.extensions import db
from app.guests.models import Guest
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


@dataclass
class GuestServiceError(Exception):
    code: str
    message: str
    status: int


def _serialize_guest(row: Guest) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "first_name": row.first_name,
        "last_name": row.last_name,
        "full_name": row.full_name,
        "email": row.email,
        "phone": row.phone,
        "notes": row.notes,
        "preferences": row.preferences,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _normalize_email(raw: str | None) -> str | None:
    value = (raw or "").strip().lower()
    return value or None


def _assert_unique_email(
    *, organization_id: int, email: str | None, exclude_guest_id: int | None = None
) -> None:
    if not email:
        return
    query = Guest.query.filter(
        Guest.organization_id == organization_id,
        sa_func.lower(Guest.email) == email,
    )
    if exclude_guest_id is not None:
        query = query.filter(Guest.id != exclude_guest_id)
    if query.first() is not None:
        raise GuestServiceError(
            code="validation_error",
            message="A guest with this email already exists in your organization.",
            status=400,
        )


def list_guests(
    *, organization_id: int, search: str | None = None, page: int = 1, per_page: int = 20
) -> tuple[list[dict], int]:
    query = Guest.query.filter(Guest.organization_id == organization_id)
    search_value = (search or "").strip()
    if search_value:
        needle = f"%{search_value}%"
        query = query.filter(
            or_(
                Guest.first_name.ilike(needle),
                Guest.last_name.ilike(needle),
                Guest.email.ilike(needle),
                Guest.phone.ilike(needle),
            )
        )
    total = query.count()
    rows = (
        query.order_by(Guest.last_name.asc(), Guest.first_name.asc(), Guest.id.asc())
        .offset((max(page, 1) - 1) * max(per_page, 1))
        .limit(max(per_page, 1))
        .all()
    )
    return [_serialize_guest(row) for row in rows], total


def get_guest(guest_id: int, organization_id: int) -> dict:
    row = Guest.query.filter_by(id=guest_id, organization_id=organization_id).first()
    if row is None:
        raise GuestServiceError(code="not_found", message="Guest not found.", status=404)
    return _serialize_guest(row)


def create_guest(organization_id: int, data: dict, actor_user) -> dict:
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    if not first_name or not last_name:
        raise GuestServiceError(
            code="validation_error", message="First name and last name are required.", status=400
        )
    email = _normalize_email(data.get("email"))
    _assert_unique_email(organization_id=organization_id, email=email)
    row = Guest(
        organization_id=organization_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
        phone=(data.get("phone") or "").strip() or None,
        notes=(data.get("notes") or "").strip() or None,
        preferences=(data.get("preferences") or "").strip() or None,
    )
    db.session.add(row)
    db.session.flush()
    audit_record(
        "guest_created",
        status=AuditStatus.SUCCESS,
        actor_id=getattr(actor_user, "id", None),
        organization_id=organization_id,
        target_type="guest",
        target_id=row.id,
        context={"email": row.email},
        commit=False,
    )
    db.session.commit()
    return _serialize_guest(row)


def update_guest(guest_id: int, organization_id: int, data: dict, actor_user) -> dict:
    row = Guest.query.filter_by(id=guest_id, organization_id=organization_id).first()
    if row is None:
        raise GuestServiceError(code="not_found", message="Guest not found.", status=404)
    first_name = (data.get("first_name") or "").strip()
    last_name = (data.get("last_name") or "").strip()
    if not first_name or not last_name:
        raise GuestServiceError(
            code="validation_error", message="First name and last name are required.", status=400
        )
    email = _normalize_email(data.get("email"))
    _assert_unique_email(organization_id=organization_id, email=email, exclude_guest_id=row.id)
    row.first_name = first_name
    row.last_name = last_name
    row.email = email
    row.phone = (data.get("phone") or "").strip() or None
    row.notes = (data.get("notes") or "").strip() or None
    row.preferences = (data.get("preferences") or "").strip() or None
    audit_record(
        "guest_updated",
        status=AuditStatus.SUCCESS,
        actor_id=getattr(actor_user, "id", None),
        organization_id=organization_id,
        target_type="guest",
        target_id=row.id,
        context={"email": row.email},
        commit=False,
    )
    db.session.commit()
    return _serialize_guest(row)


def get_guest_reservations(guest_id: int, organization_id: int) -> list[dict]:
    row = Guest.query.filter_by(id=guest_id, organization_id=organization_id).first()
    if row is None:
        raise GuestServiceError(code="not_found", message="Guest not found.", status=404)
    reservations = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.guest_id == guest_id,
        )
        .order_by(Reservation.start_date.desc(), Reservation.id.desc())
        .all()
    )
    return [
        {
            "id": res.id,
            "start_date": res.start_date.isoformat(),
            "end_date": res.end_date.isoformat(),
            "status": res.status,
            "property_name": res.unit.property.name if res.unit and res.unit.property else "",
            "unit_name": res.unit.name if res.unit else "",
            "guest_name": res.guest_name,
        }
        for res in reservations
    ]
