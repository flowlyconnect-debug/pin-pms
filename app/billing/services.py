"""Tenant-scoped lease and invoice business logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping

from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.billing.models import Invoice, Lease
from app.extensions import db
from app.guests.models import Guest
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


@dataclass
class LeaseServiceError(Exception):
    code: str
    message: str
    status: int


@dataclass
class InvoiceServiceError(Exception):
    code: str
    message: str
    status: int


_BILLING_CYCLES = frozenset({"monthly", "weekly", "one_time"})
_INVOICE_STATUSES = frozenset({"draft", "open", "paid", "overdue", "cancelled"})


def _parse_iso_date(raw: str | None, field_name: str) -> date:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError as exc:
        raise LeaseServiceError(
            code="validation_error",
            message=f"Field '{field_name}' must be a valid ISO date (YYYY-MM-DD).",
            status=400,
        ) from exc


def _parse_iso_date_invoice(raw: str | None, field_name: str) -> date:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError as exc:
        raise InvoiceServiceError(
            code="validation_error",
            message=f"Field '{field_name}' must be a valid ISO date (YYYY-MM-DD).",
            status=400,
        ) from exc


def _parse_amount(raw: Any, *, error_cls: type) -> Decimal:
    if raw is None:
        raise error_cls(
            code="validation_error",
            message="Amount is required.",
            status=400,
        )
    text = str(raw).strip()
    if not text:
        raise error_cls(
            code="validation_error",
            message="Amount is required.",
            status=400,
        )
    try:
        value = Decimal(text).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        raise error_cls(
            code="validation_error",
            message="Amount must be a valid decimal number.",
            status=400,
        ) from None
    if value < Decimal("0.00"):
        raise error_cls(
            code="validation_error",
            message="Amount must be zero or greater.",
            status=400,
        )
    return value


def _parse_optional_amount(raw: Any, *, error_cls: type) -> Decimal:
    if raw is None or str(raw).strip() == "":
        return Decimal("0.00")
    return _parse_amount(raw, error_cls=error_cls)


def _parse_currency(raw: Any) -> str:
    text = str(raw or "EUR").strip().upper()
    if len(text) != 3 or not text.isalpha():
        raise InvoiceServiceError(
            code="validation_error",
            message="Currency must be a 3-letter ISO code.",
            status=400,
        )
    return text


def _ensure_unit_in_org(*, unit_id: int, organization_id: int) -> Unit:
    unit = (
        Unit.query.join(Property, Unit.property_id == Property.id)
        .filter(
            Unit.id == unit_id,
            Property.organization_id == organization_id,
        )
        .first()
    )
    if unit is None:
        raise LeaseServiceError(
            code="validation_error",
            message="Unit not found in this organization.",
            status=400,
        )
    return unit


def _ensure_guest_in_org(
    *,
    guest_id: int,
    organization_id: int,
    error_cls: type[LeaseServiceError] | type[InvoiceServiceError] = LeaseServiceError,
) -> Guest:
    guest = Guest.query.filter_by(id=guest_id, organization_id=organization_id).first()
    if guest is None:
        raise error_cls(
            code="validation_error",
            message="Guest not found in this organization.",
            status=400,
        )
    return guest


def _scoped_reservation(*, organization_id: int, reservation_id: int) -> Reservation | None:
    return (
        Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
        .join(Property, Unit.property_id == Property.id)
        .filter(
            Reservation.id == reservation_id,
            Property.organization_id == organization_id,
        )
        .first()
    )


def _get_lease_row(*, organization_id: int, lease_id: int) -> Lease | None:
    return Lease.query.filter_by(id=lease_id, organization_id=organization_id).first()


def _get_invoice_row(*, organization_id: int, invoice_id: int) -> Invoice | None:
    return Invoice.query.filter_by(id=invoice_id, organization_id=organization_id).first()


def _serialize_lease(row: Lease) -> dict:
    unit = row.unit
    prop = unit.property if unit is not None else None
    guest = row.guest
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "unit_id": row.unit_id,
        "unit_name": unit.name if unit is not None else None,
        "property_name": prop.name if prop is not None else None,
        "guest_id": row.guest_id,
        "guest_name": guest.full_name if guest is not None else None,
        "reservation_id": row.reservation_id,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat() if row.end_date else None,
        "rent_amount": str(row.rent_amount),
        "deposit_amount": str(row.deposit_amount),
        "billing_cycle": row.billing_cycle,
        "status": row.status,
        "notes": row.notes,
        "created_by_id": row.created_by_id,
        "updated_by_id": row.updated_by_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _serialize_invoice(row: Invoice) -> dict:
    return {
        "id": row.id,
        "organization_id": row.organization_id,
        "lease_id": row.lease_id,
        "reservation_id": row.reservation_id,
        "guest_id": row.guest_id,
        "invoice_number": row.invoice_number,
        "amount": str(row.amount),
        "currency": row.currency,
        "due_date": row.due_date.isoformat(),
        "paid_at": row.paid_at.isoformat() if row.paid_at else None,
        "status": row.status,
        "description": row.description,
        "metadata_json": row.metadata_json,
        "created_by_id": row.created_by_id,
        "updated_by_id": row.updated_by_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _finalize_invoice_number(row: Invoice) -> None:
    row.invoice_number = f"BIL-{row.organization_id}-{row.id:08d}"


def generate_invoice_number(*, organization_id: int, invoice_id: int) -> str:
    """Return the canonical invoice number for a persisted invoice id."""

    return f"BIL-{organization_id}-{invoice_id:08d}"


def get_lease_for_org(*, organization_id: int, lease_id: int) -> dict:
    row = _get_lease_row(organization_id=organization_id, lease_id=lease_id)
    if row is None:
        raise LeaseServiceError(
            code="not_found",
            message="Lease not found.",
            status=404,
        )
    return _serialize_lease(row)


def list_leases_paginated(
    *,
    organization_id: int,
    page: int,
    per_page: int,
) -> tuple[list[dict], int]:
    q = Lease.query.filter_by(organization_id=organization_id)
    total = q.count()
    rows = q.order_by(Lease.id.desc()).offset((page - 1) * per_page).limit(per_page).all()
    return [_serialize_lease(r) for r in rows], total


def create_lease(
    *,
    organization_id: int,
    unit_id: int,
    guest_id: int,
    reservation_id: int | None,
    start_date_raw: str,
    end_date_raw: str | None,
    rent_amount_raw: Any,
    deposit_amount_raw: Any,
    billing_cycle: str,
    notes: str | None,
    actor_user_id: int,
) -> dict:
    cycle = (billing_cycle or "").strip().lower()
    if cycle not in _BILLING_CYCLES:
        raise LeaseServiceError(
            code="validation_error",
            message="billing_cycle must be one of: monthly, weekly, one_time.",
            status=400,
        )

    _ensure_unit_in_org(unit_id=unit_id, organization_id=organization_id)
    _ensure_guest_in_org(guest_id=guest_id, organization_id=organization_id)

    res_id = reservation_id
    if res_id is not None:
        res = _scoped_reservation(organization_id=organization_id, reservation_id=res_id)
        if res is None:
            raise LeaseServiceError(
                code="validation_error",
                message="Reservation not found in this organization.",
                status=400,
            )

    start = _parse_iso_date(start_date_raw, "start_date")
    end = _parse_iso_date(end_date_raw, "end_date") if (end_date_raw or "").strip() else None
    if end is not None and end < start:
        raise LeaseServiceError(
            code="validation_error",
            message="end_date must be on or after start_date.",
            status=400,
        )

    rent = _parse_amount(rent_amount_raw, error_cls=LeaseServiceError)
    deposit = _parse_optional_amount(deposit_amount_raw, error_cls=LeaseServiceError)

    row = Lease(
        organization_id=organization_id,
        unit_id=unit_id,
        guest_id=guest_id,
        reservation_id=res_id,
        start_date=start,
        end_date=end,
        rent_amount=rent,
        deposit_amount=deposit,
        billing_cycle=cycle,
        status="draft",
        notes=(notes or "").strip() or None,
        created_by_id=actor_user_id,
        updated_by_id=None,
    )
    db.session.add(row)
    db.session.flush()
    db.session.commit()
    audit_record(
        "lease.created",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="lease",
        target_id=row.id,
        context={"unit_id": unit_id, "guest_id": guest_id},
        commit=True,
    )
    return _serialize_lease(row)


def update_lease(
    *,
    organization_id: int,
    lease_id: int,
    data: Mapping[str, Any],
    actor_user_id: int,
) -> dict:
    row = _get_lease_row(organization_id=organization_id, lease_id=lease_id)
    if row is None:
        raise LeaseServiceError(
            code="not_found",
            message="Lease not found.",
            status=404,
        )

    status = row.status
    if status in {"ended", "cancelled"}:
        notes_only = (data or {}).keys() <= {"notes"}
        if not notes_only:
            raise LeaseServiceError(
                code="validation_error",
                message="Only notes can be updated for a lease in this status.",
                status=400,
            )

    if "unit_id" in data or "guest_id" in data or "reservation_id" in data:
        if status not in {"draft"}:
            raise LeaseServiceError(
                code="validation_error",
                message="Unit, guest, and reservation cannot be changed unless the lease is draft.",
                status=400,
            )

    if "unit_id" in data:
        uid = int(data["unit_id"])
        _ensure_unit_in_org(unit_id=uid, organization_id=organization_id)
        row.unit_id = uid
    if "guest_id" in data:
        gid = int(data["guest_id"])
        _ensure_guest_in_org(guest_id=gid, organization_id=organization_id)
        row.guest_id = gid
    if "reservation_id" in data:
        raw_res = data["reservation_id"]
        if raw_res is None or raw_res == "":
            row.reservation_id = None
        else:
            rid = int(raw_res)
            res = _scoped_reservation(organization_id=organization_id, reservation_id=rid)
            if res is None:
                raise LeaseServiceError(
                    code="validation_error",
                    message="Reservation not found in this organization.",
                    status=400,
                )
            row.reservation_id = rid

    if "start_date" in data:
        if status != "draft":
            raise LeaseServiceError(
                code="validation_error",
                message="start_date can only be changed while the lease is draft.",
                status=400,
            )
        row.start_date = _parse_iso_date(str(data["start_date"]), "start_date")

    if "end_date" in data:
        raw_end = data["end_date"]
        if raw_end is None or str(raw_end).strip() == "":
            row.end_date = None
        else:
            if status not in {"draft", "active"}:
                raise LeaseServiceError(
                    code="validation_error",
                    message="end_date cannot be changed in the current status.",
                    status=400,
                )
            row.end_date = _parse_iso_date(str(raw_end), "end_date")

    if row.end_date is not None and row.end_date < row.start_date:
        raise LeaseServiceError(
            code="validation_error",
            message="end_date must be on or after start_date.",
            status=400,
        )

    if "rent_amount" in data:
        if status not in {"draft", "active"}:
            raise LeaseServiceError(
                code="validation_error",
                message="rent_amount cannot be changed in the current status.",
                status=400,
            )
        row.rent_amount = _parse_amount(data["rent_amount"], error_cls=LeaseServiceError)

    if "deposit_amount" in data:
        if status not in {"draft", "active"}:
            raise LeaseServiceError(
                code="validation_error",
                message="deposit_amount cannot be changed in the current status.",
                status=400,
            )
        row.deposit_amount = _parse_optional_amount(
            data["deposit_amount"], error_cls=LeaseServiceError
        )

    if "billing_cycle" in data:
        if status != "draft":
            raise LeaseServiceError(
                code="validation_error",
                message="billing_cycle can only be changed while the lease is draft.",
                status=400,
            )
        cycle = str(data["billing_cycle"] or "").strip().lower()
        if cycle not in _BILLING_CYCLES:
            raise LeaseServiceError(
                code="validation_error",
                message="billing_cycle must be one of: monthly, weekly, one_time.",
                status=400,
            )
        row.billing_cycle = cycle

    if "notes" in data:
        row.notes = (str(data["notes"] or "")).strip() or None

    row.updated_by_id = actor_user_id
    db.session.commit()
    audit_record(
        "lease.updated",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="lease",
        target_id=row.id,
        commit=True,
    )
    return _serialize_lease(row)


def activate_lease(*, organization_id: int, lease_id: int, actor_user_id: int) -> dict:
    row = _get_lease_row(organization_id=organization_id, lease_id=lease_id)
    if row is None:
        raise LeaseServiceError(
            code="not_found",
            message="Lease not found.",
            status=404,
        )
    if row.status != "draft":
        raise LeaseServiceError(
            code="validation_error",
            message="Only draft leases can be activated.",
            status=400,
        )
    row.status = "active"
    row.updated_by_id = actor_user_id
    db.session.commit()
    audit_record(
        "lease.activated",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="lease",
        target_id=row.id,
        commit=True,
    )
    return _serialize_lease(row)


def end_lease(
    *,
    organization_id: int,
    lease_id: int,
    end_date_raw: str | None,
    actor_user_id: int,
) -> dict:
    row = _get_lease_row(organization_id=organization_id, lease_id=lease_id)
    if row is None:
        raise LeaseServiceError(
            code="not_found",
            message="Lease not found.",
            status=404,
        )
    if row.status != "active":
        raise LeaseServiceError(
            code="validation_error",
            message="Only active leases can be ended.",
            status=400,
        )
    if (end_date_raw or "").strip():
        end_d = _parse_iso_date(end_date_raw, "end_date")
    else:
        end_d = date.today()
    if end_d < row.start_date:
        raise LeaseServiceError(
            code="validation_error",
            message="end_date must be on or after start_date.",
            status=400,
        )
    row.end_date = end_d
    row.status = "ended"
    row.updated_by_id = actor_user_id
    db.session.commit()
    audit_record(
        "lease.ended",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="lease",
        target_id=row.id,
        context={"end_date": end_d.isoformat()},
        commit=True,
    )
    return _serialize_lease(row)


def cancel_lease(*, organization_id: int, lease_id: int, actor_user_id: int) -> dict:
    row = _get_lease_row(organization_id=organization_id, lease_id=lease_id)
    if row is None:
        raise LeaseServiceError(
            code="not_found",
            message="Lease not found.",
            status=404,
        )
    if row.status in {"ended", "cancelled"}:
        raise LeaseServiceError(
            code="validation_error",
            message="Lease cannot be cancelled in its current status.",
            status=400,
        )
    row.status = "cancelled"
    row.updated_by_id = actor_user_id
    db.session.commit()
    audit_record(
        "lease.cancelled",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="lease",
        target_id=row.id,
        commit=True,
    )
    return _serialize_lease(row)


def create_invoice(
    *,
    organization_id: int,
    amount_raw: Any,
    due_date_raw: str,
    currency: str | None = None,
    description: str | None = None,
    lease_id: int | None = None,
    reservation_id: int | None = None,
    guest_id: int | None = None,
    status: str = "draft",
    metadata_json: Mapping[str, Any] | list[Any] | None = None,
    actor_user_id: int | None,
) -> dict:
    if actor_user_id is None:
        raise InvoiceServiceError(
            code="validation_error",
            message="Actor is required.",
            status=400,
        )

    st = (status or "draft").strip().lower()
    if st not in _INVOICE_STATUSES:
        raise InvoiceServiceError(
            code="validation_error",
            message="status must be one of: draft, open, paid, overdue, cancelled.",
            status=400,
        )
    if st in {"paid", "overdue", "cancelled"}:
        raise InvoiceServiceError(
            code="validation_error",
            message="New invoices must start as draft or open.",
            status=400,
        )

    amount = _parse_amount(amount_raw, error_cls=InvoiceServiceError)
    due = _parse_iso_date_invoice(due_date_raw, "due_date")
    cur = _parse_currency(currency)

    lid = lease_id
    lease_row: Lease | None = None
    if lid is not None:
        lease_row = _get_lease_row(organization_id=organization_id, lease_id=lid)
        if lease_row is None:
            raise InvoiceServiceError(
                code="validation_error",
                message="Lease not found in this organization.",
                status=400,
            )

    rid = reservation_id
    if rid is not None:
        res = _scoped_reservation(organization_id=organization_id, reservation_id=rid)
        if res is None:
            raise InvoiceServiceError(
                code="validation_error",
                message="Reservation not found in this organization.",
                status=400,
            )

    gid = guest_id
    if gid is None and lease_row is not None:
        gid = lease_row.guest_id
    if gid is not None:
        _ensure_guest_in_org(
            guest_id=gid,
            organization_id=organization_id,
            error_cls=InvoiceServiceError,
        )

    meta = dict(metadata_json) if isinstance(metadata_json, Mapping) else metadata_json

    row = Invoice(
        organization_id=organization_id,
        lease_id=lid,
        reservation_id=rid,
        guest_id=gid,
        invoice_number=None,
        amount=amount,
        currency=cur,
        due_date=due,
        paid_at=None,
        status=st,
        description=(description or "").strip() or None,
        metadata_json=meta,
        created_by_id=actor_user_id,
        updated_by_id=None,
    )
    db.session.add(row)
    db.session.flush()
    _finalize_invoice_number(row)
    db.session.commit()
    audit_record(
        "invoice.created",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="invoice",
        target_id=row.id,
        context={"invoice_number": row.invoice_number, "amount": str(amount)},
        commit=True,
    )
    return _serialize_invoice(row)


def create_invoice_for_lease(
    *,
    organization_id: int,
    lease_id: int,
    amount_raw: Any | None,
    due_date_raw: str,
    currency: str | None = None,
    description: str | None = None,
    status: str = "open",
    actor_user_id: int | None,
) -> dict:
    lease = _get_lease_row(organization_id=organization_id, lease_id=lease_id)
    if lease is None:
        raise InvoiceServiceError(
            code="validation_error",
            message="Lease not found in this organization.",
            status=400,
        )
    amt = amount_raw if amount_raw is not None else lease.rent_amount
    desc = description
    if desc is None or not str(desc).strip():
        desc = f"Lease #{lease.id} ({lease.billing_cycle})"
    return create_invoice(
        organization_id=organization_id,
        amount_raw=amt,
        due_date_raw=due_date_raw,
        currency=currency,
        description=desc,
        lease_id=lease.id,
        reservation_id=lease.reservation_id,
        guest_id=lease.guest_id,
        status=status,
        metadata_json=None,
        actor_user_id=actor_user_id,
    )


def get_invoice_for_org(*, organization_id: int, invoice_id: int) -> dict:
    row = _get_invoice_row(organization_id=organization_id, invoice_id=invoice_id)
    if row is None:
        raise InvoiceServiceError(
            code="not_found",
            message="Invoice not found.",
            status=404,
        )
    return _serialize_invoice(row)


def list_invoices_paginated(
    *,
    organization_id: int,
    page: int,
    per_page: int,
) -> tuple[list[dict], int]:
    q = Invoice.query.filter_by(organization_id=organization_id)
    total = q.count()
    rows = (
        q.order_by(Invoice.due_date.desc(), Invoice.id.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
        .all()
    )
    return [_serialize_invoice(r) for r in rows], total


def update_invoice_limited(
    *,
    organization_id: int,
    invoice_id: int,
    data: Mapping[str, Any],
    actor_user_id: int,
) -> dict:
    """Update safe fields on draft/open invoices (used by API PATCH-style flows)."""

    row = _get_invoice_row(organization_id=organization_id, invoice_id=invoice_id)
    if row is None:
        raise InvoiceServiceError(
            code="not_found",
            message="Invoice not found.",
            status=404,
        )

    if row.status in {"paid", "cancelled"}:
        allowed = {"description", "metadata_json"}
        if not set(data).issubset(allowed):
            raise InvoiceServiceError(
                code="validation_error",
                message="Only description and metadata can be changed for paid or cancelled invoices.",
                status=400,
            )
    elif row.status == "overdue":
        allowed = {"description", "metadata_json", "due_date"}
        if not set(data).issubset(allowed):
            raise InvoiceServiceError(
                code="validation_error",
                message="Overdue invoices only support limited updates.",
                status=400,
            )

    if "description" in data:
        row.description = (str(data["description"] or "")).strip() or None
    if "metadata_json" in data:
        m = data["metadata_json"]
        row.metadata_json = dict(m) if isinstance(m, Mapping) else m

    if row.status in {"draft", "open"}:
        if "amount" in data:
            row.amount = _parse_amount(data["amount"], error_cls=InvoiceServiceError)
        if "currency" in data:
            row.currency = _parse_currency(data["currency"])
        if "due_date" in data:
            row.due_date = _parse_iso_date_invoice(str(data["due_date"]), "due_date")
        if "guest_id" in data:
            raw_g = data["guest_id"]
            if raw_g is None or raw_g == "":
                row.guest_id = None
            else:
                gid = int(raw_g)
                _ensure_guest_in_org(
                    guest_id=gid,
                    organization_id=organization_id,
                    error_cls=InvoiceServiceError,
                )
                row.guest_id = gid
        if "reservation_id" in data:
            raw_r = data["reservation_id"]
            if raw_r is None or raw_r == "":
                row.reservation_id = None
            else:
                rid = int(raw_r)
                res = _scoped_reservation(organization_id=organization_id, reservation_id=rid)
                if res is None:
                    raise InvoiceServiceError(
                        code="validation_error",
                        message="Reservation not found in this organization.",
                        status=400,
                    )
                row.reservation_id = rid
        if "lease_id" in data:
            raw_l = data["lease_id"]
            if raw_l is None or raw_l == "":
                row.lease_id = None
            else:
                lid = int(raw_l)
                lease = _get_lease_row(organization_id=organization_id, lease_id=lid)
                if lease is None:
                    raise InvoiceServiceError(
                        code="validation_error",
                        message="Lease not found in this organization.",
                        status=400,
                    )
                row.lease_id = lid

    row.updated_by_id = actor_user_id
    db.session.commit()
    audit_record(
        "invoice.updated",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="invoice",
        target_id=row.id,
        commit=True,
    )
    return _serialize_invoice(row)


def mark_invoice_paid(
    *,
    organization_id: int,
    invoice_id: int,
    actor_user_id: int | None,
) -> dict:
    row = _get_invoice_row(organization_id=organization_id, invoice_id=invoice_id)
    if row is None:
        raise InvoiceServiceError(
            code="not_found",
            message="Invoice not found.",
            status=404,
        )
    if row.status == "paid":
        return _serialize_invoice(row)
    if row.status == "cancelled":
        raise InvoiceServiceError(
            code="validation_error",
            message="Cancelled invoices cannot be marked paid.",
            status=400,
        )
    if row.status == "draft":
        raise InvoiceServiceError(
            code="validation_error",
            message="Draft invoices must be opened before they can be marked paid.",
            status=400,
        )

    row.status = "paid"
    row.paid_at = datetime.now(timezone.utc)
    row.updated_by_id = actor_user_id
    db.session.commit()
    audit_record(
        "invoice.marked_paid",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="invoice",
        target_id=row.id,
        context={"invoice_number": row.invoice_number},
        commit=True,
    )
    return _serialize_invoice(row)


def mark_overdue_invoices(*, organization_id: int | None = None) -> int:
    """Mark open invoices overdue when due_date is before today (UTC date).

    When ``organization_id`` is ``None``, all organizations are processed
    (scheduled job / CLI). Returns the number of rows updated.
    """

    today = datetime.now(timezone.utc).date()
    q = Invoice.query.filter(Invoice.status == "open", Invoice.due_date < today)
    if organization_id is not None:
        q = q.filter(Invoice.organization_id == organization_id)
    rows = q.all()
    count = 0
    for row in rows:
        row.status = "overdue"
        row.updated_by_id = None
        count += 1
    if count:
        db.session.commit()
    for row in rows:
        audit_record(
            "invoice.marked_overdue",
            status=AuditStatus.SUCCESS,
            actor_type=ActorType.SYSTEM,
            actor_id=None,
            organization_id=row.organization_id,
            target_type="invoice",
            target_id=row.id,
            context={"invoice_number": row.invoice_number, "due_date": row.due_date.isoformat()},
            commit=True,
        )
    return count


def cancel_invoice(
    *,
    organization_id: int,
    invoice_id: int,
    actor_user_id: int | None,
) -> dict:
    row = _get_invoice_row(organization_id=organization_id, invoice_id=invoice_id)
    if row is None:
        raise InvoiceServiceError(
            code="not_found",
            message="Invoice not found.",
            status=404,
        )
    if row.status == "paid":
        raise InvoiceServiceError(
            code="validation_error",
            message="Paid invoices cannot be cancelled.",
            status=400,
        )
    if row.status == "cancelled":
        return _serialize_invoice(row)

    row.status = "cancelled"
    row.updated_by_id = actor_user_id
    db.session.commit()
    audit_record(
        "invoice.cancelled",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=organization_id,
        target_type="invoice",
        target_id=row.id,
        commit=True,
    )
    return _serialize_invoice(row)


def list_leases_for_org(*, organization_id: int) -> list[dict]:
    rows = Lease.query.filter_by(organization_id=organization_id).order_by(Lease.id.desc()).all()
    return [_serialize_lease(r) for r in rows]


def list_invoices_for_org(*, organization_id: int) -> list[dict]:
    rows = (
        Invoice.query.filter_by(organization_id=organization_id)
        .order_by(Invoice.due_date.desc(), Invoice.id.desc())
        .all()
    )
    return [_serialize_invoice(r) for r in rows]
