from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.billing.models import Invoice
from app.extensions import db
from app.payments import services as payment_services
from app.payments.models import Payment, PaymentRefund
from app.payments.providers import stripe as stripe_provider_mod
from app.payments.providers.stripe import StripeProvider


def _invoice(organization, regular_user) -> Invoice:
    row = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=None,
        invoice_number="INV-STRIPE-1",
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


def test_create_checkout_with_vat_breakdown_passes_correct_line_items_to_stripe(
    app, organization, regular_user, monkeypatch
):
    inv = _invoice(organization, regular_user)
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            id="cs_test", payment_intent="pi_test", url="https://stripe", expires_at=None
        )

    fake_stripe = SimpleNamespace()
    fake_stripe.checkout = SimpleNamespace(Session=SimpleNamespace(create=fake_create))
    monkeypatch.setattr(stripe_provider_mod, "_stripe", lambda: fake_stripe)
    with app.app_context():
        provider = StripeProvider()
        provider.create_checkout(
            amount=Decimal("124.00"),
            currency="EUR",
            invoice=inv,
            return_url="https://app/return",
            cancel_url="https://app/cancel",
            idempotency_key="idem-1",
        )
    assert len(captured["line_items"]) == 2
    assert captured["line_items"][0]["price_data"]["unit_amount"] == 10000
    assert captured["line_items"][1]["price_data"]["unit_amount"] == 2400


def test_webhook_invalid_signature_returns_false(app):
    _ = app
    provider = StripeProvider()
    assert provider.verify_webhook(payload_bytes=b"{}", signature_header="invalid") is False


def test_webhook_succeeded_marks_invoice_paid_and_publishes_event(
    app, organization, regular_user, monkeypatch
):
    inv = _invoice(organization, regular_user)
    payment = Payment(
        organization_id=organization.id,
        invoice_id=inv.id,
        provider="stripe",
        provider_session_id="cs_1",
        amount=Decimal("124.00"),
        currency="EUR",
        status="pending",
    )
    db.session.add(payment)
    db.session.commit()
    published = []
    monkeypatch.setattr(
        payment_services, "publish_webhook_event", lambda *args, **kwargs: published.append(args)
    )
    monkeypatch.setattr(payment_services, "send_template", lambda *args, **kwargs: True)
    with app.app_context():
        payment_services.handle_webhook_event(
            "stripe",
            {
                "type": "payment.succeeded",
                "provider_session_id": "cs_1",
                "provider_payment_id": "pi_1",
                "method": "card",
            },
        )
    db.session.refresh(payment)
    db.session.refresh(inv)
    assert payment.status == "succeeded"
    assert inv.status == "paid"
    assert any(item[0] == "invoice.paid" for item in published)


def test_refund_partial_then_full(app, organization, regular_user, admin_user, monkeypatch):
    inv = _invoice(organization, regular_user)
    payment = Payment(
        organization_id=organization.id,
        invoice_id=inv.id,
        provider="stripe",
        provider_payment_id="pi_ref_1",
        amount=Decimal("100.00"),
        currency="EUR",
        status="succeeded",
    )
    db.session.add(payment)
    db.session.commit()
    counter = {"n": 0}

    def fake_refund(**_kwargs):
        counter["n"] += 1
        return {"provider_refund_id": f"re_{counter['n']}", "status": "pending"}

    monkeypatch.setattr(
        payment_services, "get_provider", lambda _name: SimpleNamespace(refund=fake_refund)
    )
    with app.app_context():
        payment_services.refund(
            payment.id, "30.00", "partial", actor_user_id=admin_user.id, idempotency_key="r-1"
        )
        payment_services.handle_webhook_event(
            "stripe",
            {
                "type": "refund.succeeded",
                "provider_payment_id": "pi_ref_1",
                "provider_refund_id": "re_1",
            },
        )
    db.session.refresh(payment)
    assert payment.status == "partially_refunded"
    # second and third refunds
    with app.app_context():
        payment_services.refund(
            payment.id, "70.00", "final", actor_user_id=admin_user.id, idempotency_key="r-2"
        )
        # newest pending refund gets completed
        pending = PaymentRefund.query.filter_by(payment_id=payment.id, status="pending").first()
        payment_services.handle_webhook_event(
            "stripe",
            {
                "type": "refund.succeeded",
                "provider_payment_id": "pi_ref_1",
                "provider_refund_id": pending.provider_refund_id,
            },
        )
    db.session.refresh(payment)
    assert payment.status == "refunded"


def test_refund_exceeding_amount_returns_400(app, organization, regular_user, admin_user):
    inv = _invoice(organization, regular_user)
    payment = Payment(
        organization_id=organization.id,
        invoice_id=inv.id,
        provider="stripe",
        provider_payment_id="pi_ref_2",
        amount=Decimal("10.00"),
        currency="EUR",
        status="succeeded",
    )
    db.session.add(payment)
    db.session.commit()
    with app.app_context():
        try:
            payment_services.refund(
                payment.id, "20.00", "too much", actor_user_id=admin_user.id, idempotency_key="x-1"
            )
            raise AssertionError("expected PaymentServiceError")
        except payment_services.PaymentServiceError as err:
            assert err.status == 400


def test_refund_idempotency_with_key_conflict(
    app, organization, regular_user, admin_user, monkeypatch
):
    inv = _invoice(organization, regular_user)
    payment = Payment(
        organization_id=organization.id,
        invoice_id=inv.id,
        provider="stripe",
        provider_payment_id="pi_ref_3",
        amount=Decimal("10.00"),
        currency="EUR",
        status="succeeded",
    )
    db.session.add(payment)
    db.session.commit()
    monkeypatch.setattr(
        payment_services,
        "get_provider",
        lambda _name: SimpleNamespace(
            refund=lambda **_kwargs: {"provider_refund_id": "re_same", "status": "pending"}
        ),
    )
    with app.app_context():
        first = payment_services.refund(
            payment.id, "1.00", "a", actor_user_id=admin_user.id, idempotency_key="same-key"
        )
        second = payment_services.refund(
            payment.id, "1.00", "a", actor_user_id=admin_user.id, idempotency_key="same-key"
        )
        assert first["refund_id"] == second["refund_id"]
        try:
            payment_services.refund(
                payment.id, "2.00", "b", actor_user_id=admin_user.id, idempotency_key="same-key"
            )
            raise AssertionError("expected conflict")
        except payment_services.PaymentServiceError as err:
            assert err.status == 409


def test_payment_failed_event_sets_status(app, organization, regular_user):
    inv = _invoice(organization, regular_user)
    payment = Payment(
        organization_id=organization.id,
        invoice_id=inv.id,
        provider="stripe",
        provider_payment_id="pi_fail_1",
        amount=Decimal("124.00"),
        currency="EUR",
        status="pending",
    )
    db.session.add(payment)
    db.session.commit()
    with app.app_context():
        payment_services.handle_webhook_event(
            "stripe",
            {"type": "payment.failed", "provider_payment_id": "pi_fail_1", "error": "declined"},
        )
    db.session.refresh(payment)
    assert payment.status == "failed"
    assert payment.last_error == "declined"


def test_refund_provider_exception_marks_failed(
    app, organization, regular_user, admin_user, monkeypatch
):
    inv = _invoice(organization, regular_user)
    payment = Payment(
        organization_id=organization.id,
        invoice_id=inv.id,
        provider="stripe",
        provider_payment_id="pi_ref_exc",
        amount=Decimal("10.00"),
        currency="EUR",
        status="succeeded",
    )
    db.session.add(payment)
    db.session.commit()
    monkeypatch.setattr(
        payment_services,
        "get_provider",
        lambda _name: SimpleNamespace(
            refund=lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("boom"))
        ),
    )
    with app.app_context():
        out = payment_services.refund(
            payment.id,
            "1.00",
            "x",
            actor_user_id=admin_user.id,
            idempotency_key="refund-exc-1",
        )
    assert out["status"] == "failed"


def test_stripe_parse_webhook_event_variants():
    provider = StripeProvider()
    completed = provider.parse_webhook_event(
        payload={
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_1",
                    "payment_intent": "pi_1",
                    "amount_total": 1000,
                    "currency": "eur",
                }
            },
        }
    )
    failed = provider.parse_webhook_event(
        payload={
            "type": "payment_intent.payment_failed",
            "data": {
                "object": {
                    "id": "pi_2",
                    "currency": "eur",
                    "last_payment_error": {"message": "declined"},
                }
            },
        }
    )
    refunded = provider.parse_webhook_event(
        payload={
            "type": "charge.refunded",
            "data": {
                "object": {
                    "id": "ch_1",
                    "payment_intent": "pi_1",
                    "amount_refunded": 500,
                    "currency": "eur",
                }
            },
        }
    )
    unknown = provider.parse_webhook_event(payload={"type": "other", "data": {"object": {}}})
    assert completed["type"] == "payment.succeeded"
    assert failed["type"] == "payment.failed"
    assert refunded["type"] == "refund.succeeded"
    assert unknown["type"] == "unknown"


def test_stripe_refund_uses_payment_intent_or_charge(app, monkeypatch):
    provider = StripeProvider()
    calls = []

    def fake_refund_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(id="re_1", status="succeeded")

    fake_stripe = SimpleNamespace()
    fake_stripe.Refund = SimpleNamespace(create=fake_refund_create)
    monkeypatch.setattr(stripe_provider_mod, "_stripe", lambda: fake_stripe)
    with app.app_context():
        provider.refund(
            provider_payment_id="pi_123", amount=Decimal("1.00"), reason="a", idempotency_key="k1"
        )
        provider.refund(
            provider_payment_id="ch_123", amount=Decimal("1.00"), reason="a", idempotency_key="k2"
        )
    assert "payment_intent" in calls[0]
    assert "charge" in calls[1]
