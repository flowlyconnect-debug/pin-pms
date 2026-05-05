"""Payload builders for outbound business webhooks (PII-minimized)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _base_payload(*, event: str, organization_id: int, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "event": event,
        "occurred_at": utc_now_iso(),
        "organization_id": int(organization_id),
        "data": data,
    }


def build_reservation_created_payload(reservation) -> dict[str, Any]:
    return _base_payload(
        event="reservation.created",
        organization_id=reservation.unit.property.organization_id,
        data={
            "reservation_id": reservation.id,
            "unit_id": reservation.unit_id,
            "start_date": reservation.start_date.isoformat(),
            "end_date": reservation.end_date.isoformat(),
            "status": reservation.status,
            "guest_id": reservation.guest_id,
        },
    )


def build_reservation_cancelled_payload(reservation) -> dict[str, Any]:
    return _base_payload(
        event="reservation.cancelled",
        organization_id=reservation.unit.property.organization_id,
        data={
            "reservation_id": reservation.id,
            "unit_id": reservation.unit_id,
            "status": reservation.status,
            "guest_id": reservation.guest_id,
            "payment_status": reservation.payment_status,
        },
    )


def build_reservation_updated_payload(reservation) -> dict[str, Any]:
    return _base_payload(
        event="reservation.updated",
        organization_id=reservation.unit.property.organization_id,
        data={
            "reservation_id": reservation.id,
            "unit_id": reservation.unit_id,
            "start_date": reservation.start_date.isoformat(),
            "end_date": reservation.end_date.isoformat(),
            "status": reservation.status,
            "guest_id": reservation.guest_id,
        },
    )


def build_invoice_created_payload(invoice) -> dict[str, Any]:
    return _base_payload(
        event="invoice.created",
        organization_id=invoice.organization_id,
        data={
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "guest_id": invoice.guest_id,
            "reservation_id": invoice.reservation_id,
            "lease_id": invoice.lease_id,
            "amount": str(invoice.total_incl_vat),
            "currency": invoice.currency,
            "status": invoice.status,
            "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        },
    )


def build_invoice_paid_payload(invoice) -> dict[str, Any]:
    return _base_payload(
        event="invoice.paid",
        organization_id=invoice.organization_id,
        data={
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "status": invoice.status,
            "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        },
    )


def build_invoice_refunded_payload(invoice) -> dict[str, Any]:
    return _base_payload(
        event="invoice.refunded",
        organization_id=invoice.organization_id,
        data={
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "status": invoice.status,
        },
    )


def build_guest_checked_in_payload(check_in, reservation) -> dict[str, Any]:
    return _base_payload(
        event="guest.checked_in",
        organization_id=reservation.unit.property.organization_id,
        data={
            "reservation_id": reservation.id,
            "check_in_id": check_in.id,
            "guest_id": reservation.guest_id,
            "checked_in_at": check_in.checked_in_at.isoformat() if check_in.checked_in_at else None,
        },
    )


def build_guest_checked_out_payload(access_code) -> dict[str, Any]:
    organization_id = access_code.reservation.unit.property.organization_id
    return _base_payload(
        event="guest.checked_out",
        organization_id=organization_id,
        data={
            "reservation_id": access_code.reservation_id,
            "guest_id": access_code.reservation.guest_id if access_code.reservation else None,
            "access_code_id": access_code.id,
            "revoked_at": access_code.revoked_at.isoformat() if access_code.revoked_at else None,
        },
    )


def build_maintenance_requested_payload(maintenance_request) -> dict[str, Any]:
    return _base_payload(
        event="maintenance.requested",
        organization_id=maintenance_request.organization_id,
        data={
            "request_id": maintenance_request.id,
            "property_id": maintenance_request.property_id,
            "unit_id": maintenance_request.unit_id,
            "reservation_id": maintenance_request.reservation_id,
            "guest_id": maintenance_request.guest_id,
            "status": maintenance_request.status,
            "priority": maintenance_request.priority,
        },
    )
