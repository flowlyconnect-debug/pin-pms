"""Outbound webhook event type constants."""

from __future__ import annotations

RESERVATION_CREATED = "reservation.created"
RESERVATION_CANCELLED = "reservation.cancelled"
RESERVATION_UPDATED = "reservation.updated"
INVOICE_CREATED = "invoice.created"
INVOICE_PAID = "invoice.paid"
INVOICE_REFUNDED = "invoice.refunded"
GUEST_CHECKED_IN = "guest.checked_in"
GUEST_CHECKED_OUT = "guest.checked_out"
MAINTENANCE_REQUESTED = "maintenance.requested"

SUPPORTED_WEBHOOK_EVENTS = {
    RESERVATION_CREATED,
    RESERVATION_CANCELLED,
    RESERVATION_UPDATED,
    INVOICE_CREATED,
    INVOICE_PAID,
    INVOICE_REFUNDED,
    GUEST_CHECKED_IN,
    GUEST_CHECKED_OUT,
    MAINTENANCE_REQUESTED,
}
