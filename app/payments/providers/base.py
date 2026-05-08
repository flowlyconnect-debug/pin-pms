from __future__ import annotations

from abc import ABC, abstractmethod


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    def create_checkout(
        self, *, amount, currency, invoice, return_url, cancel_url, idempotency_key
    ) -> dict:
        """
        Returns:
        {
            "provider_session_id": "...",
            "provider_payment_id": "...",
            "redirect_url": "...",
            "expires_at": datetime | None,
        }
        """

    @abstractmethod
    def verify_webhook(self, *, payload_bytes, signature_header) -> bool:
        """Provider-specific HMAC/signature check."""

    @abstractmethod
    def parse_webhook_event(self, *, payload: dict) -> dict:
        """
        Returns normalized event:
        {
            "type": "payment.succeeded" | "payment.failed" | "refund.succeeded",
            "provider_payment_id": "...",
            "provider_session_id": "...",
            "amount": Decimal,
            "currency": "EUR",
            "error": "...",
            ...
        }
        """

    @abstractmethod
    def refund(self, *, provider_payment_id, amount, reason, idempotency_key) -> dict:
        """
        Returns:
        {
            "provider_refund_id": "...",
            "status": "pending" | "succeeded" | "failed"
        }
        """
