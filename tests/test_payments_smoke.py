"""Automated smoke tests for the Stripe and Paytrail payment flows.

These tests verify end-to-end "happy path" behaviour for both providers in
test mode without performing any real network calls. They mirror the manual
verification described under "Maksuintegraation manuaalitesti" in
``README.md`` (test card ``4242 4242 4242 4242`` for Stripe, merchant
``375917`` / secret ``SAIPPUAKAUPPIAS`` for Paytrail).

Mocking strategy follows the existing project convention (see
``tests/test_payments_stripe.py`` and ``tests/test_payments_paytrail.py``):

* Stripe SDK is monkey-patched via ``app.payments.providers.stripe._stripe``.
* Paytrail HTTP traffic is monkey-patched via ``requests.post``.
* Webhook signature checks are monkey-patched in tests only; production
  signature verification code in ``app/payments/providers/`` is untouched.

The repo does not depend on ``responses``, ``requests-mock`` or
``pytest-socket`` — Stripe SDK and Paytrail's ``requests.post`` are the only
outbound paths and both are stubbed out below.
"""

from __future__ import annotations

import json
from decimal import Decimal
from types import SimpleNamespace

from app.audit.models import AuditLog
from app.billing.models import Invoice
from app.extensions import db
from app.payments import services as payment_services
from app.payments.models import Payment
from app.payments.providers import stripe as stripe_provider_mod


def _create_smoke_invoice(organization, regular_user, *, invoice_number: str) -> Invoice:
    """Minimal open invoice the payment smoke tests can act on."""

    row = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=None,
        invoice_number=invoice_number,
        amount=Decimal("124.00"),
        vat_rate=Decimal("24.00"),
        vat_amount=Decimal("24.00"),
        subtotal_excl_vat=Decimal("100.00"),
        total_incl_vat=Decimal("124.00"),
        currency="EUR",
        due_date=regular_user.created_at.date(),
        status="open",
        created_by_id=regular_user.id,
        updated_by_id=None,
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_stripe_checkout_returns_redirect_url(app, organization, regular_user, monkeypatch):
    """Stripe ``create_checkout`` returns a redirect URL when the SDK is stubbed."""

    invoice = _create_smoke_invoice(organization, regular_user, invoice_number="INV-SMOKE-STRIPE")

    fake_url = "https://checkout.stripe.com/test-session-smoke"
    fake_session = SimpleNamespace(
        id="cs_test_smoke_create",
        payment_intent="pi_test_smoke_create",
        url=fake_url,
        expires_at=None,
    )

    fake_stripe = SimpleNamespace(
        api_key=None,
        checkout=SimpleNamespace(
            Session=SimpleNamespace(create=lambda **_kwargs: fake_session),
        ),
    )
    monkeypatch.setattr(stripe_provider_mod, "_stripe", lambda: fake_stripe)

    with app.app_context():
        app.config["STRIPE_ENABLED"] = True
        app.config["STRIPE_SECRET_KEY"] = "sk_test_smoke"

        result = payment_services.create_checkout(
            invoice.id,
            "stripe",
            "https://app.example/portal/return",
            "https://app.example/portal/cancel",
        )

    assert isinstance(result["redirect_url"], str)
    assert result["redirect_url"] == fake_url
    assert isinstance(result.get("payment_id"), int)


def test_paytrail_checkout_returns_redirect_url(app, organization, regular_user, monkeypatch):
    """Paytrail ``create_checkout`` returns a redirect URL when ``requests.post`` is stubbed."""

    invoice = _create_smoke_invoice(organization, regular_user, invoice_number="INV-SMOKE-PAYTRAIL")

    fake_url = "https://pay.paytrail.com/test-smoke"

    class _FakeResponse:
        status_code = 201
        content = b'{"transactionId":"pt-test-smoke-1","href":"https://pay.paytrail.com/test-smoke"}'

        def json(self):
            return {"transactionId": "pt-test-smoke-1", "href": fake_url}

        def raise_for_status(self):
            return None

    def fake_post(url, headers=None, data=None, timeout=None, **_kwargs):
        _ = (url, headers, data, timeout)
        return _FakeResponse()

    monkeypatch.setattr("requests.post", fake_post)

    with app.app_context():
        app.config["PAYTRAIL_ENABLED"] = True
        app.config["PAYTRAIL_MERCHANT_ID"] = "375917"
        app.config["PAYTRAIL_SECRET_KEY"] = "SAIPPUAKAUPPIAS"
        app.config["PAYTRAIL_API_BASE"] = "https://services.paytrail.com"
        app.config["PAYMENT_CALLBACK_URL"] = "https://app.example/api/v1/webhooks/paytrail"

        result = payment_services.create_checkout(
            invoice.id,
            "paytrail",
            "https://app.example/portal/return",
            "https://app.example/portal/cancel",
        )

    assert isinstance(result["redirect_url"], str)
    assert result["redirect_url"] == fake_url
    assert isinstance(result.get("payment_id"), int)


def test_stripe_webhook_marks_invoice_paid(
    app, client, organization, regular_user, monkeypatch
):
    """Stripe ``checkout.session.completed`` webhook flips the invoice to paid + audits."""

    invoice = _create_smoke_invoice(
        organization, regular_user, invoice_number="INV-SMOKE-STRIPE-WH"
    )
    payment = Payment(
        organization_id=organization.id,
        invoice_id=invoice.id,
        provider="stripe",
        provider_session_id="cs_test_smoke_session",
        amount=Decimal("124.00"),
        currency="EUR",
        status="pending",
    )
    db.session.add(payment)
    db.session.commit()
    payment_id = payment.id
    invoice_id = invoice.id

    monkeypatch.setattr(
        "app.payments.providers.stripe.StripeProvider.verify_webhook",
        lambda *args, **kwargs: True,
    )

    event = {
        "id": "evt_test_smoke_1",
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "id": "cs_test_smoke_session",
                "payment_intent": "pi_test_smoke",
                "amount_total": 12400,
                "currency": "eur",
                "metadata": {"invoice_id": str(invoice_id)},
            }
        },
    }

    response = client.post(
        "/api/v1/webhooks/stripe",
        data=json.dumps(event),
        headers={
            "Stripe-Signature": "test-signature",
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200

    with app.app_context():
        refreshed_payment = Payment.query.get(payment_id)
        refreshed_invoice = Invoice.query.get(invoice_id)
        assert refreshed_payment.status == "succeeded"
        assert refreshed_invoice.status == "paid"

        payment_audit = AuditLog.query.filter_by(
            action="payment.received",
            target_type="payment",
            target_id=payment_id,
        ).first()
        assert payment_audit is not None

        invoice_audit = AuditLog.query.filter_by(
            action="invoice.marked_paid",
            target_type="invoice",
            target_id=invoice_id,
        ).first()
        assert invoice_audit is not None


def test_paytrail_callback_marks_invoice_paid(
    app, client, organization, regular_user, monkeypatch
):
    """Paytrail success callback flips the invoice to paid + audits."""

    invoice = _create_smoke_invoice(
        organization, regular_user, invoice_number="INV-SMOKE-PAYTRAIL-WH"
    )
    payment = Payment(
        organization_id=organization.id,
        invoice_id=invoice.id,
        provider="paytrail",
        provider_payment_id="pt-test-smoke-callback",
        provider_session_id="pt-test-smoke-callback",
        amount=Decimal("124.00"),
        currency="EUR",
        status="pending",
    )
    db.session.add(payment)
    db.session.commit()
    payment_id = payment.id
    invoice_id = invoice.id

    # Mock the signature verifier in the test only (production verifier in
    # ``app/payments/providers/paytrail.py`` is untouched).
    monkeypatch.setattr(
        "app.payments.providers.paytrail.PaytrailProvider.verify_query_signature",
        lambda *args, **kwargs: True,
    )

    response = client.get(
        "/api/v1/webhooks/paytrail",
        query_string={
            "checkout-account": "375917",
            "checkout-algorithm": "sha256",
            "checkout-method": "GET",
            "checkout-nonce": "smoke-nonce",
            "checkout-timestamp": "2026-05-07T10:00:00Z",
            "checkout-status": "ok",
            "checkout-transaction-id": "pt-test-smoke-callback",
            "checkout-reference": str(invoice_id),
            "signature": "test-signature",
        },
    )

    assert response.status_code == 200

    with app.app_context():
        refreshed_payment = Payment.query.get(payment_id)
        refreshed_invoice = Invoice.query.get(invoice_id)
        assert refreshed_payment.status == "succeeded"
        assert refreshed_invoice.status == "paid"

        payment_audit = AuditLog.query.filter_by(
            action="payment.received",
            target_type="payment",
            target_id=payment_id,
        ).first()
        assert payment_audit is not None

        invoice_audit = AuditLog.query.filter_by(
            action="invoice.marked_paid",
            target_type="invoice",
            target_id=invoice_id,
        ).first()
        assert invoice_audit is not None
