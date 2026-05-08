from __future__ import annotations

import base64
import os
import secrets
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from flask import current_app, url_for

from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.billing.models import Invoice, Lease
from app.core.security import hash_token
from app.email.models import TemplateKey
from app.email.services import EmailTemplateNotFound, send_template
from app.extensions import db
from app.integrations.pindora_lock.service import PindoraLockService
from app.maintenance.models import MaintenanceRequest
from app.portal.models import (
    AccessCode,
    GuestCheckIn,
    LockDevice,
    PortalCheckInToken,
    PortalMagicLinkToken,
)
from app.properties.models import Property, PropertyImage, Unit
from app.reservations.models import Reservation
from app.users.models import User, UserRole
from app.webhooks.events import GUEST_CHECKED_IN, GUEST_CHECKED_OUT
from app.webhooks.publisher import publish as publish_webhook_event
from app.webhooks.schemas import build_guest_checked_in_payload, build_guest_checked_out_payload


@dataclass
class PortalServiceError(Exception):
    code: str
    message: str
    status: int


_OPEN_MAINTENANCE_STATUSES = frozenset({"new", "in_progress", "waiting"})
_UNPAID_INVOICE_STATUSES = frozenset({"open", "overdue"})


def authenticate_portal_user(*, email: str, password: str) -> User | None:
    user = User.query.filter_by(email=(email or "").strip().lower()).first()
    if user is None or not user.is_active:
        return None
    if user.role != UserRole.USER.value:
        return None
    if not user.check_password(password):
        return None
    return user


def get_portal_user_or_none(*, user_id: int | None) -> User | None:
    if user_id is None:
        return None
    user = User.query.filter_by(id=user_id, is_active=True).first()
    if user is None:
        return None
    if user.role != UserRole.USER.value:
        return None
    return user


def issue_magic_link(*, email: str) -> tuple[PortalMagicLinkToken, str] | None:
    user = User.query.filter_by(email=(email or "").strip().lower(), is_active=True).first()
    if user is None or user.role != UserRole.USER.value:
        return None
    row, raw = PortalMagicLinkToken.issue(user_id=user.id)
    db.session.add(row)
    db.session.commit()
    return row, raw


def authenticate_by_magic_link(*, raw_token: str) -> User | None:
    row = PortalMagicLinkToken.find_active_by_raw(raw_token)
    if row is None:
        return None
    user = row.user
    if user is None or not user.is_active or user.role != UserRole.USER.value:
        return None
    row.mark_used()
    db.session.commit()
    return user


def _scoped_reservation_query(*, organization_id: int, guest_id: int):
    return (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Property.organization_id == organization_id,
            Reservation.guest_id == guest_id,
        )
    )


def get_dashboard_stats(*, organization_id: int, guest_id: int) -> dict:
    today = date.today()
    scoped_reservations = _scoped_reservation_query(
        organization_id=organization_id, guest_id=guest_id
    )
    active_reservations = scoped_reservations.filter(
        Reservation.status == "confirmed",
        Reservation.start_date <= today,
        Reservation.end_date > today,
    ).count()
    active_lease = (
        Lease.query.filter_by(organization_id=organization_id, guest_id=guest_id)
        .filter(Lease.status == "active")
        .order_by(Lease.start_date.desc(), Lease.id.desc())
        .first()
    )
    unpaid_invoices = (
        Invoice.query.filter_by(organization_id=organization_id, guest_id=guest_id)
        .filter(Invoice.status.in_(_UNPAID_INVOICE_STATUSES))
        .count()
    )
    open_maintenance_requests = (
        MaintenanceRequest.query.filter_by(organization_id=organization_id, guest_id=guest_id)
        .filter(MaintenanceRequest.status.in_(_OPEN_MAINTENANCE_STATUSES))
        .count()
    )
    return {
        "active_reservations": active_reservations,
        "active_lease_id": active_lease.id if active_lease is not None else None,
        "unpaid_invoices": unpaid_invoices,
        "open_maintenance_requests": open_maintenance_requests,
    }


def list_reservations(*, organization_id: int, guest_id: int) -> list[dict]:
    rows = (
        _scoped_reservation_query(organization_id=organization_id, guest_id=guest_id)
        .order_by(Reservation.start_date.desc(), Reservation.id.desc())
        .all()
    )
    payload: list[dict] = []
    for row in rows:
        payload.append(
            {
                "id": row.id,
                "property_name": row.unit.property.name if row.unit and row.unit.property else "",
                "unit_name": row.unit.name if row.unit else "",
                "start_date": row.start_date.isoformat(),
                "end_date": row.end_date.isoformat(),
                "status": row.status,
            }
        )
    return payload


def get_reservation(*, organization_id: int, guest_id: int, reservation_id: int) -> dict:
    row = (
        _scoped_reservation_query(organization_id=organization_id, guest_id=guest_id)
        .filter(Reservation.id == reservation_id)
        .first()
    )
    if row is None:
        raise PortalServiceError(code="not_found", message="Reservation not found.", status=404)
    image_rows = (
        PropertyImage.query.filter_by(
            organization_id=organization_id,
            property_id=row.unit.property_id if row.unit else None,
        )
        .order_by(PropertyImage.sort_order.asc(), PropertyImage.id.asc())
        .all()
        if row.unit is not None
        else []
    )
    return {
        "id": row.id,
        "unit_id": row.unit_id,
        "property_name": row.unit.property.name if row.unit and row.unit.property else "",
        "unit_name": row.unit.name if row.unit else "",
        "guest_name": row.guest_name,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "status": row.status,
        "amount": str(row.amount) if row.amount is not None else None,
        "currency": row.currency,
        "payment_status": row.payment_status,
        "images": [
            {
                "id": image.id,
                "url": image.url,
                "thumbnail_url": image.thumbnail_url,
                "alt_text": image.alt_text,
            }
            for image in image_rows
        ],
    }


def get_unit_for_guest(*, organization_id: int, guest_id: int, unit_id: int) -> dict:
    row = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .join(Reservation, Reservation.unit_id == Unit.id)
        .filter(
            Unit.id == unit_id,
            Property.organization_id == organization_id,
            Reservation.guest_id == guest_id,
        )
        .first()
    )
    if row is None:
        raise PortalServiceError(code="not_found", message="Unit not found.", status=404)
    return {
        "id": row.id,
        "property_name": row.property.name if row.property else "",
        "name": row.name,
        "unit_type": row.unit_type,
        "floor": row.floor,
        "area_sqm": str(row.area_sqm) if row.area_sqm is not None else None,
        "bedrooms": row.bedrooms,
        "has_kitchen": row.has_kitchen,
        "has_bathroom": row.has_bathroom,
        "has_balcony": row.has_balcony,
        "has_terrace": row.has_terrace,
        "has_dishwasher": row.has_dishwasher,
        "has_washing_machine": row.has_washing_machine,
        "has_tv": row.has_tv,
        "has_wifi": row.has_wifi,
        "max_guests": row.max_guests,
        "description": row.description,
    }


def list_invoices(*, organization_id: int, guest_id: int) -> list[dict]:
    rows = (
        Invoice.query.filter_by(organization_id=organization_id, guest_id=guest_id)
        .order_by(Invoice.due_date.desc(), Invoice.id.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "invoice_number": row.invoice_number,
            "amount": str(row.total_incl_vat),
            "subtotal_excl_vat": str(row.subtotal_excl_vat),
            "vat_rate": str(row.vat_rate),
            "vat_amount": str(row.vat_amount),
            "total_incl_vat": str(row.total_incl_vat),
            "currency": row.currency,
            "due_date": row.due_date.isoformat(),
            "status": row.status,
        }
        for row in rows
    ]


def get_invoice(*, organization_id: int, guest_id: int, invoice_id: int) -> dict:
    row = Invoice.query.filter_by(
        id=invoice_id,
        organization_id=organization_id,
        guest_id=guest_id,
    ).first()
    if row is None:
        raise PortalServiceError(code="not_found", message="Invoice not found.", status=404)
    return {
        "id": row.id,
        "invoice_number": row.invoice_number,
        "amount": str(row.total_incl_vat),
        "subtotal_excl_vat": str(row.subtotal_excl_vat),
        "vat_rate": str(row.vat_rate),
        "vat_amount": str(row.vat_amount),
        "total_incl_vat": str(row.total_incl_vat),
        "currency": row.currency,
        "due_date": row.due_date.isoformat(),
        "status": row.status,
    }


def list_maintenance_requests(*, organization_id: int, guest_id: int) -> list[dict]:
    rows = (
        MaintenanceRequest.query.filter_by(organization_id=organization_id, guest_id=guest_id)
        .order_by(MaintenanceRequest.id.desc())
        .all()
    )
    return [
        {
            "id": row.id,
            "title": row.title,
            "status": row.status,
            "priority": row.priority,
            "priority_label": row.priority_label,
            "property_name": row.property.name if row.property else "",
            "unit_name": row.unit.name if row.unit else "",
            "due_date": row.due_date.isoformat() if row.due_date else None,
        }
        for row in rows
    ]


def get_maintenance_request(*, organization_id: int, guest_id: int, request_id: int) -> dict:
    row = MaintenanceRequest.query.filter_by(
        id=request_id,
        organization_id=organization_id,
        guest_id=guest_id,
    ).first()
    if row is None:
        raise PortalServiceError(
            code="not_found", message="Maintenance request not found.", status=404
        )
    return {
        "id": row.id,
        "title": row.title,
        "description": row.description or "",
        "status": row.status,
        "priority": row.priority,
        "priority_label": row.priority_label,
        "property_name": row.property.name if row.property else "",
        "unit_name": row.unit.name if row.unit else "",
        "due_date": row.due_date.isoformat() if row.due_date else None,
    }


def maintenance_form_scope(*, organization_id: int, guest_id: int) -> list[dict]:
    rows = (
        _scoped_reservation_query(organization_id=organization_id, guest_id=guest_id)
        .filter(Reservation.status == "confirmed")
        .order_by(Reservation.start_date.desc(), Reservation.id.desc())
        .all()
    )
    options: list[dict] = []
    seen_units: set[int] = set()
    for row in rows:
        if row.unit_id in seen_units:
            continue
        seen_units.add(row.unit_id)
        options.append(
            {
                "reservation_id": row.id,
                "property_id": row.unit.property_id if row.unit else None,
                "property_name": row.unit.property.name if row.unit and row.unit.property else "",
                "unit_id": row.unit_id,
                "unit_name": row.unit.name if row.unit else "",
            }
        )
    return options


def create_maintenance_request(
    *,
    organization_id: int,
    guest_id: int,
    reservation_id: int,
    title: str,
    description: str | None,
    priority: str,
    due_date_raw: str | None,
) -> dict:
    res = (
        _scoped_reservation_query(organization_id=organization_id, guest_id=guest_id)
        .filter(Reservation.id == reservation_id)
        .first()
    )
    if res is None:
        raise PortalServiceError(code="not_found", message="Reservation not found.", status=404)

    due_date = None
    if (due_date_raw or "").strip():
        try:
            due_date = date.fromisoformat(due_date_raw.strip())
        except ValueError as exc:
            raise PortalServiceError(
                code="validation_error",
                message="Due date must be a valid ISO date.",
                status=400,
            ) from exc

    title_clean = (title or "").strip()
    if not title_clean:
        raise PortalServiceError(code="validation_error", message="Title is required.", status=400)

    row = MaintenanceRequest(
        organization_id=organization_id,
        property_id=res.unit.property_id if res.unit else None,
        unit_id=res.unit_id,
        guest_id=guest_id,
        reservation_id=res.id,
        title=title_clean,
        description=(description or "").strip() or None,
        status="new",
        priority=(priority or "normal").strip().lower() or "normal",
        assigned_to_id=None,
        due_date=due_date,
        resolved_at=None,
        created_by_id=guest_id,
    )
    db.session.add(row)
    db.session.commit()
    return {
        "id": row.id,
        "title": row.title,
        "status": row.status,
        "priority": row.priority,
    }


def issue_checkin_token(*, reservation_id: int) -> str:
    row, raw = PortalCheckInToken.issue(reservation_id=reservation_id)
    db.session.add(row)
    db.session.commit()
    return raw


def issue_access_code_for_reservation(
    *,
    reservation_id: int,
    organization_id: int,
    actor_user_id: int | None = None,
    idempotency_key: str | None = None,
) -> tuple[AccessCode, str] | None:
    reservation = (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(Reservation.id == reservation_id, Property.organization_id == organization_id)
        .first()
    )
    if reservation is None:
        return None
    lock = LockDevice.query.filter_by(
        organization_id=organization_id,
        unit_id=reservation.unit_id,
        provider="pindora",
    ).first()
    if lock is None:
        return None
    if idempotency_key:
        existing = AccessCode.query.filter_by(idempotency_key=idempotency_key).first()
        if existing is not None:
            return existing, ""
    now = datetime.now(timezone.utc)
    checkin_start = datetime.combine(reservation.start_date, time.min).replace(tzinfo=timezone.utc)
    checkout = datetime.combine(reservation.end_date, time.min).replace(tzinfo=timezone.utc)
    valid_from = max(now, checkin_start)
    valid_until = checkout + timedelta(hours=1)
    plaintext_code = f"{secrets.randbelow(1_000_000):06d}"
    integration = PindoraLockService()
    result = integration.provision_access_code(
        provider_device_id=lock.provider_device_id,
        code=plaintext_code,
        valid_from_iso=valid_from.isoformat(),
        valid_until_iso=valid_until.isoformat(),
    )
    row = AccessCode(
        reservation_id=reservation.id,
        lock_device_id=lock.id,
        code_hash=hash_token(plaintext_code),
        provider_code_id=result.get("provider_code_id"),
        idempotency_key=idempotency_key,
        valid_from=valid_from,
        valid_until=valid_until,
        is_active=True,
    )
    db.session.add(row)
    db.session.flush()
    audit_record(
        "lock.code_issued",
        status=AuditStatus.SUCCESS,
        organization_id=organization_id,
        target_type="reservation",
        target_id=reservation.id,
        actor_id=actor_user_id,
        context={
            "access_code_id": row.id,
            "user_id": actor_user_id,
            "currency": reservation.currency,
            "amount": str(reservation.amount) if reservation.amount is not None else None,
            "external_id": row.provider_code_id,
        },
        commit=False,
    )
    db.session.commit()
    return row, plaintext_code


def revoke_access_codes_for_reservation(
    *,
    reservation_id: int,
    organization_id: int,
    actor_user_id: int | None = None,
    reason: str = "reservation_updated",
) -> int:
    rows = (
        AccessCode.query.join(Reservation, AccessCode.reservation_id == Reservation.id)
        .join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            AccessCode.reservation_id == reservation_id,
            AccessCode.is_active.is_(True),
            Property.organization_id == organization_id,
        )
        .all()
    )
    if not rows:
        return 0
    integration = PindoraLockService()
    revoked = 0
    for row in rows:
        lock = LockDevice.query.filter_by(id=row.lock_device_id).first()
        if lock is not None and row.provider_code_id:
            integration.revoke_access_code(
                provider_device_id=lock.provider_device_id,
                provider_code_id=row.provider_code_id,
            )
        row.is_active = False
        row.revoked_at = datetime.now(timezone.utc)
        row.revoked_by = actor_user_id
        revoked += 1
        audit_record(
            "lock.code_revoked",
            status=AuditStatus.SUCCESS,
            organization_id=organization_id,
            target_type="reservation",
            target_id=reservation_id,
            actor_id=actor_user_id,
            context={
                "access_code_id": row.id,
                "reason": reason,
                "external_id": row.provider_code_id,
            },
            commit=False,
        )
    db.session.commit()
    return revoked


def _fernet_from_config():
    try:
        from cryptography.fernet import Fernet
    except Exception:  # noqa: BLE001
        return None

    key = (current_app.config.get("CHECKIN_FERNET_KEY") or "").strip()
    if key:
        return Fernet(key.encode("utf-8"))
    fallback = base64.urlsafe_b64encode(
        hash_token(current_app.config.get("SECRET_KEY", "")).encode("utf-8")[:32]
    )
    return Fernet(fallback)


def complete_checkin(
    *,
    token: str,
    full_name: str,
    date_of_birth: date,
    id_document_bytes: bytes,
    id_document_name: str,
    rules_signature: str,
    idempotency_key: str | None = None,
) -> tuple[Reservation, str]:
    token_row = PortalCheckInToken.find_active_by_raw(token)
    if token_row is None:
        raise PortalServiceError(code="invalid_token", message="Invalid check-in link.", status=404)
    reservation = Reservation.query.filter_by(id=token_row.reservation_id).first()
    if reservation is None:
        raise PortalServiceError(code="not_found", message="Reservation not found.", status=404)
    lock_code = issue_access_code_for_reservation(
        reservation_id=reservation.id,
        organization_id=reservation.unit.property.organization_id,
        actor_user_id=reservation.guest_id,
        idempotency_key=idempotency_key,
    )
    if lock_code is None:
        raise PortalServiceError(
            code="no_lock", message="No lock configured for this reservation.", status=400
        )
    _, plaintext_code = lock_code
    if current_app.config.get("TESTING"):
        uploads_dir = os.path.join(current_app.instance_path, "test_checkin_uploads")
    else:
        uploads_dir = current_app.config.get("UPLOADS_DIR") or os.path.join(
            current_app.instance_path, "uploads"
        )
    checkin_dir = os.path.join(uploads_dir, "checkin_docs")
    os.makedirs(checkin_dir, exist_ok=True)
    safe_name = (
        "".join(ch for ch in id_document_name if ch.isalnum() or ch in {"-", "_", "."}) or "id.bin"
    )
    file_name = f"reservation-{reservation.id}-{secrets.token_hex(8)}-{safe_name}"
    file_path = os.path.join(checkin_dir, file_name)
    fernet = _fernet_from_config()
    encrypted = fernet.encrypt(id_document_bytes) if fernet is not None else id_document_bytes
    with open(file_path, "wb") as handle:
        handle.write(encrypted)
    row = GuestCheckIn.query.filter_by(reservation_id=reservation.id).first()
    if row is None:
        row = GuestCheckIn(
            reservation_id=reservation.id,
            full_name=full_name.strip(),
            date_of_birth=date_of_birth,
            id_document_path=file_path,
            rules_accepted=True,
            rules_signature=rules_signature.strip(),
        )
        db.session.add(row)
    else:
        row.full_name = full_name.strip()
        row.date_of_birth = date_of_birth
        row.id_document_path = file_path
        row.rules_accepted = True
        row.rules_signature = rules_signature.strip()
        row.checked_in_at = datetime.now(timezone.utc)
    token_row.mark_used()
    audit_record(
        "guest.checked_in",
        status=AuditStatus.SUCCESS,
        organization_id=reservation.unit.property.organization_id,
        target_type="reservation",
        target_id=reservation.id,
        actor_id=reservation.guest_id,
        context={"guest_id": reservation.guest_id, "lock_code_issued": True},
        commit=False,
    )
    db.session.commit()
    publish_webhook_event(
        GUEST_CHECKED_IN,
        reservation.unit.property.organization_id,
        build_guest_checked_in_payload(row, reservation),
    )
    if reservation.guest is not None and reservation.guest.email:
        try:
            send_template(
                TemplateKey.ADMIN_NOTIFICATION,
                to=reservation.guest.email,
                context={
                    "user_email": reservation.guest.email,
                    "subject_line": "Your door access code",
                    "message": f"Reservation #{reservation.id} access code: {plaintext_code}",
                },
            )
        except EmailTemplateNotFound:
            current_app.logger.warning(
                "admin_notification template missing for check-in code email."
            )
        except Exception:  # noqa: BLE001
            current_app.logger.exception("Failed sending check-in access code email.")
    return reservation, plaintext_code


def auto_revoke_expired_access_codes(*, now: datetime | None = None) -> int:
    now_dt = now or datetime.now(timezone.utc)
    rows = AccessCode.query.filter(
        AccessCode.is_active.is_(True),
        AccessCode.valid_until <= now_dt,
    ).all()
    if not rows:
        return 0
    integration = PindoraLockService()
    count = 0
    for row in rows:
        lock = LockDevice.query.filter_by(id=row.lock_device_id).first()
        if lock is not None and row.provider_code_id:
            integration.revoke_access_code(
                provider_device_id=lock.provider_device_id,
                provider_code_id=row.provider_code_id,
            )
        row.is_active = False
        row.revoked_at = now_dt
        count += 1
        audit_record(
            "guest.checked_out",
            status=AuditStatus.SUCCESS,
            target_type="reservation",
            target_id=row.reservation_id,
            context={"access_code_id": row.id},
            commit=False,
        )
    db.session.commit()
    for row in rows:
        if (
            row.reservation is None
            or row.reservation.unit is None
            or row.reservation.unit.property is None
        ):
            continue
        publish_webhook_event(
            GUEST_CHECKED_OUT,
            row.reservation.unit.property.organization_id,
            build_guest_checked_out_payload(row),
        )
    return count


def portal_login_with_audit(*, email: str, password: str) -> User | None:
    user = authenticate_portal_user(email=email, password=password)
    if user is None:
        audit_record(
            "portal.login.failure",
            status=AuditStatus.FAILURE,
            actor_type=ActorType.ANONYMOUS,
            actor_email=email or None,
            commit=True,
        )
        return None
    audit_record(
        "portal.login.success",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=user.id,
        actor_email=user.email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        commit=True,
    )
    return user


def send_portal_magic_link_email_and_audit(*, email: str) -> None:
    issued = issue_magic_link(email=email)
    if issued is None:
        return
    row, raw_token = issued
    magic_url = url_for("portal.magic_link_login", token=raw_token, _external=True)
    try:
        send_template(
            TemplateKey.ADMIN_NOTIFICATION,
            to=email,
            context={
                "user_email": email,
                "subject_line": "Pindora-portaalin kirjautumislinkki",
                "message": f"Kirjaudu sisään tästä linkistä: {magic_url}",
            },
        )
    except EmailTemplateNotFound:
        current_app.logger.warning("Magic link email template missing for portal login.")
    except Exception:  # noqa: BLE001
        current_app.logger.exception("Failed sending portal magic link email.")
    audit_record(
        "portal.magic_link.issued",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=row.user_id,
        actor_email=email,
        target_type="user",
        target_id=row.user_id,
        commit=True,
    )


def complete_portal_magic_link_login(*, raw_token: str) -> User | None:
    user = authenticate_by_magic_link(raw_token=raw_token)
    if user is None:
        return None
    audit_record(
        "portal.magic_link.login",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.USER,
        actor_id=user.id,
        actor_email=user.email,
        organization_id=user.organization_id,
        target_type="user",
        target_id=user.id,
        commit=True,
    )
    return user
