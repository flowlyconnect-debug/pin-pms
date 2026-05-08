from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from flask import current_app

from app.payments.providers.base import PaymentProvider


def _stripe():
    """Load the Stripe SDK only when Stripe code paths run (keeps ``import app`` working without it)."""

    try:
        import stripe as stripe_module
    except ImportError as exc:
        raise RuntimeError(
            "Stripe integration requires the 'stripe' package. "
            "Install dependencies: pip install -r requirements.txt"
        ) from exc
    return stripe_module


def _to_cents(amount: Decimal) -> int:
    return int((Decimal(str(amount)) * Decimal("100")).quantize(Decimal("1")))


def _build_line_items(invoice, currency: str) -> list[dict]:
    subtotal = Decimal(str(getattr(invoice, "subtotal_excl_vat", 0) or 0)).quantize(Decimal("0.01"))
    vat_amount = Decimal(str(getattr(invoice, "vat_amount", 0) or 0)).quantize(Decimal("0.01"))
    items: list[dict] = []
    if subtotal > Decimal("0.00"):
        items.append(
            {
                "price_data": {
                    "currency": str(currency).lower(),
                    "product_data": {
                        "name": f"Lasku {invoice.invoice_number or invoice.id} - veroton osuus"
                    },
                    "unit_amount": _to_cents(subtotal),
                },
                "quantity": 1,
            }
        )
    if vat_amount > Decimal("0.00"):
        items.append(
            {
                "price_data": {
                    "currency": str(currency).lower(),
                    "product_data": {"name": "ALV"},
                    "unit_amount": _to_cents(vat_amount),
                },
                "quantity": 1,
            }
        )
    if not items:
        items.append(
            {
                "price_data": {
                    "currency": str(currency).lower(),
                    "product_data": {"name": f"Lasku {invoice.invoice_number or invoice.id}"},
                    "unit_amount": _to_cents(
                        Decimal(str(getattr(invoice, "total_incl_vat", 0) or 0))
                    ),
                },
                "quantity": 1,
            }
        )
    return items


class StripeProvider(PaymentProvider):
    name = "stripe"

    def _api_key(self) -> str:
        return str(current_app.config.get("STRIPE_SECRET_KEY") or "")

    def create_checkout(
        self, *, amount, currency, invoice, return_url, cancel_url, idempotency_key
    ) -> dict:
        stripe = _stripe()
        stripe.api_key = self._api_key()
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=_build_line_items(invoice, str(currency)),
            mode="payment",
            success_url=return_url,
            cancel_url=cancel_url,
            customer_email=getattr(invoice.guest, "email", None),
            metadata={
                "invoice_id": str(invoice.id),
                "organization_id": str(invoice.organization_id),
            },
            idempotency_key=idempotency_key,
        )
        expires = None
        if getattr(session, "expires_at", None):
            expires = datetime.fromtimestamp(int(session.expires_at), tz=timezone.utc)
        return {
            "provider_session_id": session.id,
            "provider_payment_id": getattr(session, "payment_intent", None),
            "redirect_url": session.url,
            "expires_at": expires,
        }

    def verify_webhook(self, *, payload_bytes, signature_header) -> bool:
        try:
            stripe = _stripe()
            stripe.Webhook.construct_event(
                payload_bytes,
                signature_header,
                current_app.config.get("STRIPE_WEBHOOK_SECRET"),
            )
            return True
        except Exception:
            return False

    def parse_webhook_event(self, *, payload: dict) -> dict:
        event_type = str(payload.get("type") or "")
        obj = (payload.get("data") or {}).get("object") or {}
        if event_type == "checkout.session.completed":
            amount_total = Decimal(str((obj.get("amount_total") or 0) / 100)).quantize(
                Decimal("0.01")
            )
            return {
                "type": "payment.succeeded",
                "provider_payment_id": obj.get("payment_intent"),
                "provider_session_id": obj.get("id"),
                "amount": amount_total,
                "currency": str(obj.get("currency") or "eur").upper(),
                "method": "card",
            }
        if event_type == "payment_intent.payment_failed":
            return {
                "type": "payment.failed",
                "provider_payment_id": obj.get("id"),
                "provider_session_id": None,
                "amount": Decimal("0.00"),
                "currency": str(obj.get("currency") or "eur").upper(),
                "error": (
                    ((obj.get("last_payment_error") or {}).get("message")) or "payment_failed"
                ),
            }
        if event_type == "charge.refunded":
            amount_refunded = Decimal(str((obj.get("amount_refunded") or 0) / 100)).quantize(
                Decimal("0.01")
            )
            return {
                "type": "refund.succeeded",
                "provider_payment_id": obj.get("payment_intent") or obj.get("id"),
                "provider_session_id": None,
                "amount": amount_refunded,
                "currency": str(obj.get("currency") or "eur").upper(),
                "provider_refund_id": obj.get("id"),
            }
        return {"type": "unknown"}

    def refund(self, *, provider_payment_id, amount, reason, idempotency_key) -> dict:
        stripe = _stripe()
        stripe.api_key = self._api_key()
        refund_kwargs = {
            "amount": _to_cents(Decimal(str(amount))),
            "reason": "requested_by_customer",
            "metadata": {"reason": reason or ""},
            "idempotency_key": idempotency_key,
        }
        if str(provider_payment_id).startswith("pi_"):
            refund_kwargs["payment_intent"] = provider_payment_id
        else:
            refund_kwargs["charge"] = provider_payment_id
        refund = stripe.Refund.create(**refund_kwargs)
        status = "succeeded" if str(refund.status) == "succeeded" else "pending"
        if str(refund.status) == "failed":
            status = "failed"
        return {"provider_refund_id": refund.id, "status": status}
