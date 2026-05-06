from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from flask import current_app
from sqlalchemy import func

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.billing import services as billing_service
from app.billing.models import Invoice
from app.email.services import send_template
from app.extensions import db
from app.payments.models import Payment, PaymentRefund
from app.payments.providers import PaytrailProvider, StripeProvider
from app.payments.providers.base import PaymentProvider
from app.users.models import User, UserRole
from app.webhooks.events import INVOICE_PAID, INVOICE_REFUNDED
from app.webhooks.publisher import publish as publish_webhook_event


@dataclass
class PaymentServiceError(Exception):
    code: str
    message: str
    status: int


def get_provider(provider_name: str) -> PaymentProvider:
    if provider_name == "stripe":
        return StripeProvider()
    if provider_name == "paytrail":
        return PaytrailProvider()
    raise PaymentServiceError("validation_error", "Unsupported payment provider.", 400)


def _effective_idempotency_key(invoice_id: int, idempotency_key: str | None) -> str:
    return (idempotency_key or f"checkout-{invoice_id}-{int(time.time())}")[:128]


def _money(value: Any) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def _resolve_payment(provider_name: str, normalized_event: dict[str, Any]) -> Payment | None:
    provider_payment_id = normalized_event.get("provider_payment_id")
    provider_session_id = normalized_event.get("provider_session_id")
    payment = None
    if provider_payment_id:
        payment = Payment.query.filter_by(
            provider=provider_name,
            provider_payment_id=str(provider_payment_id),
        ).first()
    if payment is None and provider_session_id:
        payment = Payment.query.filter_by(
            provider=provider_name,
            provider_session_id=str(provider_session_id),
        ).first()
    return payment


def _refund_totals(payment_id: int) -> tuple[Decimal, Decimal]:
    succeeded = (
        db.session.query(func.coalesce(func.sum(PaymentRefund.amount), 0))
        .filter_by(payment_id=payment_id, status="succeeded")
        .scalar()
    )
    pending = (
        db.session.query(func.coalesce(func.sum(PaymentRefund.amount), 0))
        .filter_by(payment_id=payment_id, status="pending")
        .scalar()
    )
    return _money(succeeded), _money(pending)


def refundable_outstanding_amount(payment_id: int) -> Decimal:
    """Remaining amount that can still be refunded (payment total minus pending/succeeded refunds)."""

    payment = Payment.query.get(payment_id)
    if payment is None:
        return Decimal("0.00")
    succeeded_total, pending_total = _refund_totals(payment_id)
    out = _money(payment.amount) - succeeded_total - pending_total
    return out if out > Decimal("0.00") else Decimal("0.00")


def expire_pending_payments(*, max_age_hours: int | None = None) -> int:
    """Mark stale pending payments as ``expired`` and audit ``payment.expired``."""

    hours = max_age_hours
    if hours is None:
        hours = int(current_app.config.get("PAYMENT_PENDING_EXPIRY_HOURS", 24))
    hours = max(1, hours)
    cutoff_naive = datetime.utcnow() - timedelta(hours=hours)
    rows = (
        Payment.query.filter(Payment.status == "pending", Payment.created_at < cutoff_naive)
        .order_by(Payment.id.asc())
        .limit(500)
        .all()
    )
    n = 0
    for payment in rows:
        payment.status = "expired"
        n += 1
        audit_record(
            "payment.expired",
            status=AuditStatus.SUCCESS,
            organization_id=payment.organization_id,
            target_type="payment",
            target_id=payment.id,
            commit=False,
        )
    if n:
        db.session.commit()
    return n


def _payment_status_for_refunds(*, payment_amount: Decimal, refunded_total: Decimal) -> str:
    if refunded_total <= Decimal("0.00"):
        return "succeeded"
    if refunded_total < payment_amount:
        return "partially_refunded"
    return "refunded"


def create_checkout(
    invoice_id,
    provider_name,
    return_url,
    cancel_url,
    *,
    actor_user_id=None,
    idempotency_key=None,
) -> dict:
    provider = get_provider(provider_name)
    invoice = Invoice.query.get(invoice_id)
    if invoice is None:
        raise PaymentServiceError("not_found", "Invoice not found.", 404)

    actor = User.query.get(actor_user_id) if actor_user_id else None
    if actor is not None and not actor.is_superadmin and actor.organization_id != invoice.organization_id:
        raise PaymentServiceError("forbidden", "Invoice not found.", 403)

    idem = _effective_idempotency_key(invoice.id, idempotency_key)

    if provider_name == "stripe" and not bool(current_app.config.get("STRIPE_ENABLED")):
        raise PaymentServiceError("provider_disabled", "Stripe provider is disabled.", 503)
    if provider_name == "paytrail" and not bool(current_app.config.get("PAYTRAIL_ENABLED")):
        raise PaymentServiceError("provider_disabled", "Paytrail provider is disabled.", 503)

    amount = _money(invoice.total_incl_vat)
    if amount <= Decimal("0.00"):
        raise PaymentServiceError("validation_error", "Invoice amount must be greater than zero.", 400)
    payment = Payment(
        status="pending",
        provider=provider_name,
        invoice_id=invoice.id,
        reservation_id=invoice.reservation_id,
        organization_id=invoice.organization_id,
        amount=amount,
        currency=invoice.currency,
        idempotency_key=idem,
        return_url=return_url,
        cancel_url=cancel_url,
        metadata_json={"invoice_number": invoice.invoice_number},
    )
    db.session.add(payment)
    db.session.flush()

    if return_url and "{payment_id}" in return_url:
        return_url = return_url.format(payment_id=payment.id)
    if cancel_url and "{payment_id}" in cancel_url:
        cancel_url = cancel_url.format(payment_id=payment.id)
    payment.return_url = return_url
    payment.cancel_url = cancel_url

    provider_result = provider.create_checkout(
        amount=amount,
        currency=invoice.currency,
        invoice=invoice,
        return_url=return_url,
        cancel_url=cancel_url,
        idempotency_key=idem,
    )
    payment.provider_session_id = provider_result.get("provider_session_id")
    payment.provider_payment_id = provider_result.get("provider_payment_id")
    payment.metadata_json = {
        **(payment.metadata_json or {}),
        "provider": provider_name,
    }
    db.session.commit()

    audit_record(
        "payment.checkout_created",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=payment.organization_id,
        target_type="payment",
        target_id=payment.id,
        commit=True,
    )
    return {"payment_id": payment.id, "redirect_url": provider_result.get("redirect_url")}


def get_payment_for_org(*, payment_id: int, organization_id: int) -> Payment:
    row = Payment.query.filter_by(id=payment_id, organization_id=organization_id).first()
    if row is None:
        raise PaymentServiceError("not_found", "Payment not found.", 404)
    return row


def handle_webhook_event(provider_name, normalized_event) -> None:
    event_type = str(normalized_event.get("type") or "")
    payment = _resolve_payment(provider_name, normalized_event)
    if payment is None:
        return

    if event_type == "payment.succeeded":
        if payment.status == "succeeded":
            return
        payment.status = "succeeded"
        payment.completed_at = datetime.now(timezone.utc)
        if normalized_event.get("method"):
            payment.method = str(normalized_event.get("method"))
        billing_service.mark_invoice_paid(
            organization_id=payment.organization_id,
            invoice_id=payment.invoice_id,
            actor_user_id=None,
        )
        db.session.commit()
        audit_record(
            "payment.received",
            status=AuditStatus.SUCCESS,
            organization_id=payment.organization_id,
            target_type="payment",
            target_id=payment.id,
            commit=True,
        )
        publish_webhook_event(INVOICE_PAID, payment.organization_id, {"invoice_id": payment.invoice_id, "payment_id": payment.id})
        try:
            invoice = Invoice.query.get(payment.invoice_id)
            if invoice and invoice.guest and invoice.guest.email:
                send_template(
                    "payment_received",
                    to=invoice.guest.email,
                    context={
                        "invoice_number": invoice.invoice_number or f"#{invoice.id}",
                        "amount": str(payment.amount),
                        "currency": payment.currency,
                    },
                )
        except Exception:
            pass
        return

    if event_type == "payment.failed":
        if payment.status == "failed":
            return
        payment.status = "failed"
        payment.last_error = str(normalized_event.get("error") or "payment_failed")
        db.session.commit()
        audit_record(
            "payment.failed",
            status=AuditStatus.FAILURE,
            organization_id=payment.organization_id,
            target_type="payment",
            target_id=payment.id,
            commit=True,
        )
        return

    if event_type == "refund.succeeded":
        provider_refund_id = normalized_event.get("provider_refund_id")
        refund = None
        if provider_refund_id:
            refund = PaymentRefund.query.filter_by(
                payment_id=payment.id,
                provider_refund_id=str(provider_refund_id),
            ).first()
        if refund is None:
            refund = (
                PaymentRefund.query.filter_by(payment_id=payment.id, status="pending")
                .order_by(PaymentRefund.id.asc())
                .first()
            )
        if refund:
            refund.status = "succeeded"
            if provider_refund_id:
                refund.provider_refund_id = str(provider_refund_id)
            refund.completed_at = datetime.now(timezone.utc)
            refund.last_error = None
        succeeded_total, _pending_total = _refund_totals(payment.id)
        payment.status = _payment_status_for_refunds(payment_amount=_money(payment.amount), refunded_total=succeeded_total)
        db.session.commit()
        audit_record(
            "payment.refund_completed",
            status=AuditStatus.SUCCESS,
            organization_id=payment.organization_id,
            target_type="payment",
            target_id=payment.id,
            commit=True,
        )
        publish_webhook_event(INVOICE_REFUNDED, payment.organization_id, {"invoice_id": payment.invoice_id, "payment_id": payment.id})
        return

    # Unknown provider event types are intentionally no-op.
    return


def refund(payment_id, amount, reason, *, actor_user_id, idempotency_key=None) -> dict:
    payment = Payment.query.get(payment_id)
    if payment is None:
        raise PaymentServiceError("not_found", "Payment not found.", 404)
    actor = User.query.get(actor_user_id)
    if actor is None or actor.role not in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        raise PaymentServiceError("forbidden", "Admin permission required.", 403)
    if not actor.is_superadmin and actor.organization_id != payment.organization_id:
        raise PaymentServiceError("forbidden", "Payment not found.", 403)
    if payment.status not in {"succeeded", "partially_refunded"}:
        raise PaymentServiceError("validation_error", "Only succeeded payments can be refunded.", 400)

    refund_amount = _money(amount)
    if refund_amount <= Decimal("0.00"):
        raise PaymentServiceError("validation_error", "Refund amount must be greater than zero.", 400)
    idem = (idempotency_key or f"refund-{payment.id}-{int(time.time())}")[:128]
    if idempotency_key:
        existing = PaymentRefund.query.filter_by(idempotency_key=idem).first()
        if existing is not None:
            existing_reason = (existing.reason or "").strip()
            new_reason = (reason or "").strip()
            if _money(existing.amount) == refund_amount and existing_reason == new_reason:
                return {"refund_id": existing.id, "status": existing.status}
            raise PaymentServiceError(
                "idempotency_key_conflict",
                "This Idempotency-Key has already been used with different parameters.",
                409,
            )

    succeeded_total, pending_total = _refund_totals(payment.id)
    outstanding = _money(payment.amount) - succeeded_total - pending_total
    if refund_amount > outstanding:
        raise PaymentServiceError("validation_error", "Refund amount exceeds remaining payment amount.", 400)

    refund_row = PaymentRefund(
        payment_id=payment.id,
        amount=refund_amount,
        reason=(reason or "").strip() or None,
        status="pending",
        idempotency_key=idem,
        actor_user_id=actor_user_id,
    )
    db.session.add(refund_row)
    db.session.flush()
    provider = get_provider(payment.provider)
    try:
        result = provider.refund(
            provider_payment_id=payment.provider_payment_id,
            amount=refund_row.amount,
            reason=refund_row.reason,
            idempotency_key=idem,
        )
    except Exception as exc:  # noqa: BLE001
        refund_row.status = "failed"
        refund_row.last_error = str(exc)[:500]
        audit_record(
            "payment.refund_failed",
            status=AuditStatus.FAILURE,
            organization_id=payment.organization_id,
            target_type="payment_refund",
            target_id=refund_row.id,
            metadata={"reason": "provider_error"},
            commit=True,
        )
        db.session.commit()
        return {"refund_id": refund_row.id, "status": refund_row.status}

    refund_row.provider_refund_id = result.get("provider_refund_id")
    refund_row.status = result.get("status", "pending")
    if refund_row.status == "failed":
        refund_row.last_error = str(result.get("error") or "refund_failed")
        audit_record(
            "payment.refund_failed",
            status=AuditStatus.FAILURE,
            organization_id=payment.organization_id,
            target_type="payment_refund",
            target_id=refund_row.id,
            metadata={"reason": "provider_failed"},
            commit=False,
        )
    db.session.commit()
    audit_record(
        "payment.refund_initiated",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=payment.organization_id,
        target_type="payment_refund",
        target_id=refund_row.id,
        commit=True,
    )
    return {"refund_id": refund_row.id, "status": refund_row.status}


def retry_refund(refund_id: int, *, actor_user_id: int) -> dict:
    """Create a new pending refund row from a failed refund and call the provider."""

    old = PaymentRefund.query.get(refund_id)
    if old is None:
        raise PaymentServiceError("not_found", "Refund not found.", 404)
    if old.status != "failed":
        raise PaymentServiceError("validation_error", "Only failed refunds can be retried.", 400)

    payment = Payment.query.get(old.payment_id)
    if payment is None:
        raise PaymentServiceError("not_found", "Payment not found.", 404)

    actor = User.query.get(actor_user_id)
    if actor is None or actor.role not in {UserRole.ADMIN.value, UserRole.SUPERADMIN.value}:
        raise PaymentServiceError("forbidden", "Admin permission required.", 403)
    if not actor.is_superadmin and actor.organization_id != payment.organization_id:
        raise PaymentServiceError("forbidden", "Payment not found.", 403)

    idem = f"retry-refund-{old.id}-{int(time.time())}"[:128]
    refund_row = PaymentRefund(
        payment_id=payment.id,
        amount=old.amount,
        reason=old.reason,
        status="pending",
        idempotency_key=idem,
        actor_user_id=actor_user_id,
    )
    db.session.add(refund_row)
    db.session.flush()

    provider = get_provider(payment.provider)
    try:
        result = provider.refund(
            provider_payment_id=payment.provider_payment_id,
            amount=refund_row.amount,
            reason=refund_row.reason,
            idempotency_key=idem,
        )
    except Exception as exc:  # noqa: BLE001
        refund_row.status = "failed"
        refund_row.last_error = str(exc)[:500]
        audit_record(
            "payment.refund_failed",
            status=AuditStatus.FAILURE,
            organization_id=payment.organization_id,
            target_type="payment_refund",
            target_id=refund_row.id,
            metadata={"reason": "provider_error", "retry_of": old.id},
            commit=True,
        )
        db.session.commit()
        return {"refund_id": refund_row.id, "status": refund_row.status}

    refund_row.provider_refund_id = result.get("provider_refund_id")
    refund_row.status = result.get("status", "pending")
    if refund_row.status == "failed":
        refund_row.last_error = str(result.get("error") or "refund_failed")
        audit_record(
            "payment.refund_failed",
            status=AuditStatus.FAILURE,
            organization_id=payment.organization_id,
            target_type="payment_refund",
            target_id=refund_row.id,
            metadata={"reason": "provider_failed", "retry_of": old.id},
            commit=False,
        )
    db.session.commit()
    audit_record(
        "payment.refund_retried",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        organization_id=payment.organization_id,
        target_type="payment_refund",
        target_id=refund_row.id,
        metadata={"original_refund_id": old.id},
        commit=True,
    )
    return {"refund_id": refund_row.id, "status": refund_row.status}

