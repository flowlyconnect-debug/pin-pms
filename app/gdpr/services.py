"""GDPR operations — business logic only; routes/CLI call into this module."""

from __future__ import annotations

import json
import secrets
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from flask_login import current_user

from app.api.models import ApiKey
from app.audit import record as audit_record
from app.audit.models import ActorType, AuditLog, AuditStatus
from app.billing.models import Invoice, Lease
from app.extensions import db
from app.guests.models import Guest
from app.maintenance.models import MaintenanceRequest
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.users.models import User
from app.users.services import UserServiceError


class GdprPermissionError(Exception):
    """Raised when the caller is not allowed to perform a GDPR action."""


def _iso(value: datetime | date | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return value.isoformat()


def _decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def serialize_user_public(user: User) -> dict[str, Any]:
    """Serialize profile fields without secrets or 2FA material."""

    return {
        "id": user.id,
        "organization_id": user.organization_id,
        "email": user.email,
        "role": user.role,
        "is_active": user.is_active,
        "is_2fa_enabled": user.is_2fa_enabled,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "address": user.address,
        "anonymized_at": _iso(user.anonymized_at),
        "created_at": _iso(user.created_at),
        "updated_at": _iso(user.updated_at),
    }


def serialize_guest_public(guest: Guest) -> dict[str, Any]:
    return {
        "id": guest.id,
        "organization_id": guest.organization_id,
        "first_name": guest.first_name,
        "last_name": guest.last_name,
        "email": guest.email,
        "phone": guest.phone,
        "notes": guest.notes,
        "preferences": guest.preferences,
        "created_at": _iso(guest.created_at),
        "updated_at": _iso(guest.updated_at),
    }


def serialize_reservation_public(row: Reservation) -> dict[str, Any]:
    return {
        "id": row.id,
        "unit_id": row.unit_id,
        "guest_id": row.guest_id,
        "guest_name": row.guest_name,
        "start_date": _iso(row.start_date),
        "end_date": _iso(row.end_date),
        "status": row.status,
        "amount": _decimal(row.amount),
        "currency": row.currency,
        "payment_status": row.payment_status,
        "invoice_number": row.invoice_number,
        "invoice_date": _iso(row.invoice_date),
        "due_date": _iso(row.due_date),
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def serialize_invoice_public(row: Invoice) -> dict[str, Any]:
    """Omit ``metadata_json`` — may contain integration tokens or opaque secrets."""

    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "lease_id": row.lease_id,
        "reservation_id": row.reservation_id,
        "guest_id": row.guest_id,
        "invoice_number": row.invoice_number,
        "amount": _decimal(row.amount),
        "vat_rate": _decimal(row.vat_rate),
        "vat_amount": _decimal(row.vat_amount),
        "subtotal_excl_vat": _decimal(row.subtotal_excl_vat),
        "total_incl_vat": _decimal(row.total_incl_vat),
        "currency": row.currency,
        "due_date": _iso(row.due_date),
        "paid_at": _iso(row.paid_at),
        "status": row.status,
        "description": row.description,
        "created_by_id": row.created_by_id,
        "updated_by_id": row.updated_by_id,
        "created_at": _iso(row.created_at),
        "updated_at": _iso(row.updated_at),
    }


def serialize_audit_public(row: AuditLog) -> dict[str, Any]:
    """Lightweight audit row for the data subject (no raw request context dump)."""

    return {
        "id": row.id,
        "created_at": _iso(row.created_at),
        "action": row.action,
        "status": row.status,
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "organization_id": row.organization_id,
        "target_type": row.target_type,
        "target_id": row.target_id,
    }


def _user_reservations_query(user: User):
    return (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == user.organization_id,
            Reservation.guest_id == user.id,
        )
    )


def _user_invoices_query(user: User):
    return Invoice.query.filter(
        Invoice.organization_id == user.organization_id,
        (Invoice.guest_id == user.id) | (Invoice.created_by_id == user.id),
    )


def _collect_guest_rows(user: User) -> list[Guest]:
    seen: dict[int, Guest] = {}
    shadow = db.session.get(Guest, user.id)
    if shadow is not None:
        seen[shadow.id] = shadow
    if user.email:
        for g in Guest.query.filter(
            Guest.organization_id == user.organization_id,
            Guest.email == user.email,
        ).all():
            seen[g.id] = g
    return list(seen.values())


def export_user_data(user_id: int) -> dict[str, Any]:
    user = db.session.get(User, user_id)
    if user is None:
        raise UserServiceError(f"User id {user_id} not found.")

    reservations = [serialize_reservation_public(r) for r in _user_reservations_query(user).all()]
    invoices = [serialize_invoice_public(r) for r in _user_invoices_query(user).all()]
    guests = [serialize_guest_public(g) for g in _collect_guest_rows(user)]
    audit_rows = [
        serialize_audit_public(r)
        for r in AuditLog.query.filter(AuditLog.actor_id == user_id)
        .order_by(AuditLog.created_at.asc())
        .all()
    ]

    data = {
        "users": serialize_user_public(user),
        "reservations": reservations,
        "invoices": invoices,
        "guests": guests,
        "audit_log": audit_rows,
    }

    audit_record(
        "gdpr.export",
        status=AuditStatus.SUCCESS,
        actor_id=user_id,
        actor_type=ActorType.USER,
        actor_email=user.email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user_id,
        metadata={},
        commit=True,
    )

    return data


def _sync_shadow_guest_anonymized(user: User) -> None:
    guest = db.session.get(Guest, user.id)
    if guest is None:
        return
    guest.first_name = user.first_name or "Anonyymi"
    guest.last_name = user.last_name or "Käyttäjä"
    guest.email = user.email
    guest.phone = None


def anonymize_user_data(user_id: int) -> None:
    user = db.session.get(User, user_id)
    if user is None:
        raise UserServiceError(f"User id {user_id} not found.")

    user.email = f"anonymized-{user_id}@deleted.local"
    user.first_name = "Anonyymi"
    user.last_name = "Käyttäjä"
    user.phone = None
    user.address = None
    user.is_active = False
    user.anonymized_at = datetime.now(timezone.utc)
    user.totp_secret = None
    user.is_2fa_enabled = False
    user.backup_codes = []
    user.set_password(secrets.token_urlsafe(48))
    _sync_shadow_guest_anonymized(user)

    audit_record(
        "gdpr.anonymize",
        status=AuditStatus.SUCCESS,
        actor_id=user_id,
        actor_type=ActorType.USER,
        actor_email=user.email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user_id,
        metadata={},
        commit=False,
    )
    db.session.commit()


def _replacement_creator_user(*, organization_id: int, exclude_user_id: int) -> Optional[User]:
    return (
        User.query.filter(
            User.organization_id == organization_id,
            User.id != exclude_user_id,
        )
        .order_by(User.id.asc())
        .first()
    )


def _reassign_created_by_before_user_delete(*, user_id: int, organization_id: int) -> None:
    replacement = _replacement_creator_user(
        organization_id=organization_id, exclude_user_id=user_id
    )
    if replacement is None:
        raise UserServiceError(
            "Cannot delete user: organization has no other user to reassign "
            "created_by_id references on leases, invoices, or maintenance requests."
        )
    Lease.query.filter_by(created_by_id=user_id).update(
        {"created_by_id": replacement.id}, synchronize_session=False
    )
    Invoice.query.filter_by(created_by_id=user_id).update(
        {"created_by_id": replacement.id}, synchronize_session=False
    )
    MaintenanceRequest.query.filter_by(created_by_id=user_id).update(
        {"created_by_id": replacement.id}, synchronize_session=False
    )


def delete_user_data(user_id: int, *, from_cli: bool = False) -> None:
    user = db.session.get(User, user_id)
    if user is None:
        raise UserServiceError(f"User id {user_id} not found.")
    if not from_cli:
        if not current_user.is_authenticated or not current_user.is_superadmin:
            raise GdprPermissionError("Only a superadmin may permanently delete user data.")

    organization_id = user.organization_id
    anonymize_user_data(user_id)

    user = db.session.get(User, user_id)
    if user is None:
        raise UserServiceError(f"User id {user_id} not found.")

    audit_record(
        "gdpr.delete",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.SYSTEM if from_cli else ActorType.USER,
        actor_id=None if from_cli else current_user.id,
        actor_email=None if from_cli else current_user.email,
        organization_id=organization_id,
        target_type="user",
        target_id=user_id,
        metadata={},
        commit=False,
    )
    db.session.flush()

    ApiKey.query.filter_by(user_id=user_id).delete(synchronize_session=False)
    _reassign_created_by_before_user_delete(user_id=user_id, organization_id=organization_id)

    db.session.delete(user)
    db.session.commit()


def export_json_safe(data: dict[str, Any]) -> str:
    """JSON text with stable key order for CLI output / downloads."""

    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True, default=str)
