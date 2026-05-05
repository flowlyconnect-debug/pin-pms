from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import requests
from flask import current_app

from app.payments.providers.base import PaymentProvider


def _to_cents(amount: Decimal) -> int:
    return int((Decimal(str(amount)) * Decimal("100")).quantize(Decimal("1")))


def calculate_signature(secret, headers, body):
    paytrail_headers = sorted(
        (k, v) for k, v in headers.items() if str(k).lower().startswith("checkout-")
    )
    message = "\n".join(f"{k}:{v}" for k, v in paytrail_headers) + "\n" + (body or "")
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()


class PaytrailProvider(PaymentProvider):
    name = "paytrail"

    def _secret(self) -> str:
        return str(current_app.config.get("PAYTRAIL_SECRET_KEY") or "")

    def create_checkout(
        self, *, amount, currency, invoice, return_url, cancel_url, idempotency_key
    ) -> dict:
        nonce = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        body_dict = {
            "stamp": idempotency_key,
            "reference": invoice.invoice_number or f"INV-{invoice.id}",
            "amount": _to_cents(Decimal(str(amount))),
            "currency": str(currency).upper(),
            "language": "FI",
            "providers": ["nordea", "op", "danske", "handelsbanken", "mobilepay", "visa", "mastercard"],
            "items": [
                {
                    "unitPrice": _to_cents(Decimal(str(amount))),
                    "units": 1,
                    "vatPercentage": int(Decimal(str(invoice.vat_rate)).quantize(Decimal("1"))),
                    "productCode": str(invoice.id),
                    "description": f"Lasku {invoice.invoice_number or invoice.id}",
                }
            ],
            "customer": {
                "email": getattr(invoice.guest, "email", "") or "guest@example.com",
            },
            "redirectUrls": {"success": return_url, "cancel": cancel_url},
            "callbackUrls": {
                "success": current_app.config.get("PAYMENT_CALLBACK_URL"),
                "cancel": current_app.config.get("PAYMENT_CALLBACK_URL"),
            },
        }
        body = json.dumps(body_dict, separators=(",", ":"), ensure_ascii=False)
        headers = {
            "checkout-account": str(current_app.config.get("PAYTRAIL_MERCHANT_ID") or ""),
            "checkout-algorithm": "sha256",
            "checkout-method": "POST",
            "checkout-nonce": nonce,
            "checkout-timestamp": timestamp,
        }
        headers["signature"] = calculate_signature(self._secret(), headers, body)
        response = requests.post(
            f"{current_app.config.get('PAYTRAIL_API_BASE').rstrip('/')}/payments",
            headers={**headers, "Content-Type": "application/json; charset=utf-8"},
            data=body.encode("utf-8"),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return {
            "provider_payment_id": data.get("transactionId"),
            "provider_session_id": data.get("transactionId"),
            "redirect_url": data.get("href"),
            "expires_at": None,
        }

    def verify_webhook(self, *, payload_bytes, signature_header) -> bool:
        return bool(payload_bytes and signature_header)

    def verify_query_signature(self, query_args: dict[str, str]) -> bool:
        signature = str(query_args.get("signature") or "")
        headers = {k: v for k, v in query_args.items() if k.lower().startswith("checkout-")}
        expected = calculate_signature(self._secret(), headers, "")
        return bool(signature) and hmac.compare_digest(signature.lower(), expected.lower())

    def parse_webhook_event(self, *, payload: dict) -> dict:
        status = str(payload.get("checkout-status") or "").lower()
        if status == "ok":
            return {
                "type": "payment.succeeded",
                "provider_payment_id": payload.get("checkout-transaction-id"),
                "provider_session_id": payload.get("checkout-transaction-id"),
                "amount": Decimal("0.00"),
                "currency": "EUR",
                "method": "other",
            }
        if status == "fail":
            return {
                "type": "payment.failed",
                "provider_payment_id": payload.get("checkout-transaction-id"),
                "provider_session_id": payload.get("checkout-transaction-id"),
                "amount": Decimal("0.00"),
                "currency": "EUR",
                "error": payload.get("checkout-provider") or "payment_failed",
            }
        return {"type": "invalid_status", "error": "invalid_checkout_status"}

    def refund(self, *, provider_payment_id, amount, reason, idempotency_key) -> dict:
        nonce = str(uuid.uuid4())
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        body_dict = {
            "refundStamp": idempotency_key,
            "amount": _to_cents(Decimal(str(amount))),
            "refundReference": reason or f"refund-{idempotency_key}",
            "callbackUrls": {
                "success": current_app.config.get("PAYMENT_CALLBACK_URL"),
                "cancel": current_app.config.get("PAYMENT_CALLBACK_URL"),
            },
        }
        body = json.dumps(body_dict, separators=(",", ":"), ensure_ascii=False)
        headers = {
            "checkout-account": str(current_app.config.get("PAYTRAIL_MERCHANT_ID") or ""),
            "checkout-algorithm": "sha256",
            "checkout-method": "POST",
            "checkout-nonce": nonce,
            "checkout-timestamp": timestamp,
        }
        headers["signature"] = calculate_signature(self._secret(), headers, body)
        response = requests.post(
            f"{current_app.config.get('PAYTRAIL_API_BASE').rstrip('/')}/payments/{provider_payment_id}/refund",
            headers={**headers, "Content-Type": "application/json; charset=utf-8"},
            data=body.encode("utf-8"),
            timeout=10,
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        return {
            "provider_refund_id": data.get("refundId") or idempotency_key,
            "status": "pending",
        }

