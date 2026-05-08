from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from app.audit.models import AuditLog
from app.billing.models import Invoice
from app.extensions import db
from app.payments import services as payment_services
from app.payments.models import Payment, PaymentRefund


def _invoice(organization, regular_user) -> Invoice:
    row = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=None,
        invoice_number="INV-UI-REF",
        amount=Decimal("100.00"),
        vat_rate=Decimal("24.00"),
        vat_amount=Decimal("19.35"),
        subtotal_excl_vat=Decimal("80.65"),
        total_incl_vat=Decimal("100.00"),
        currency="EUR",
        due_date=regular_user.created_at.date(),
        status="open",
        created_by_id=regular_user.id,
        updated_by_id=None,
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_admin_partial_refund_posts_update_payment_status(
    app, client, organization, regular_user, admin_user, monkeypatch
):
    inv = _invoice(organization, regular_user)
    payment = Payment(
        organization_id=organization.id,
        invoice_id=inv.id,
        provider="stripe",
        provider_payment_id="pi_ui_partial",
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

    login = client.post(
        "/login",
        data={"email": admin_user.email, "password": admin_user.password_plain},
        follow_redirects=False,
    )
    assert login.status_code in {302, 303}

    rv = client.post(
        f"/admin/payments/{payment.id}/refund",
        data={"amount": "30.00", "reason": "first"},
        headers={"Idempotency-Key": "ui-refund-1"},
        follow_redirects=False,
    )
    assert rv.status_code in {302, 303}

    with app.app_context():
        payment_services.handle_webhook_event(
            "stripe",
            {
                "type": "refund.succeeded",
                "provider_payment_id": "pi_ui_partial",
                "provider_refund_id": "re_1",
            },
        )
        pay = Payment.query.get(payment.id)
        assert pay is not None
        assert pay.status == "partially_refunded"

    rv2 = client.post(
        f"/admin/payments/{payment.id}/refund",
        data={"amount": "20.00", "reason": "second"},
        headers={"Idempotency-Key": "ui-refund-2"},
        follow_redirects=False,
    )
    assert rv2.status_code in {302, 303}

    with app.app_context():
        pending = PaymentRefund.query.filter_by(payment_id=payment.id, status="pending").first()
        assert pending is not None
        payment_services.handle_webhook_event(
            "stripe",
            {
                "type": "refund.succeeded",
                "provider_payment_id": "pi_ui_partial",
                "provider_refund_id": pending.provider_refund_id,
            },
        )
        pay2 = Payment.query.get(payment.id)
        assert pay2 is not None
        assert pay2.status == "partially_refunded"


def test_retry_failed_refund_creates_new_row(
    app, organization, regular_user, admin_user, monkeypatch
):
    inv = _invoice(organization, regular_user)
    payment = Payment(
        organization_id=organization.id,
        invoice_id=inv.id,
        provider="stripe",
        provider_payment_id="pi_retry",
        amount=Decimal("50.00"),
        currency="EUR",
        status="succeeded",
    )
    db.session.add(payment)
    db.session.commit()

    failed = PaymentRefund(
        payment_id=payment.id,
        amount=Decimal("10.00"),
        status="failed",
        reason="x",
    )
    db.session.add(failed)
    db.session.commit()
    failed_id = failed.id

    monkeypatch.setattr(
        payment_services,
        "get_provider",
        lambda _name: SimpleNamespace(
            refund=lambda **_k: {"provider_refund_id": "re_retry_1", "status": "pending"}
        ),
    )

    with app.app_context():
        out = payment_services.retry_refund(failed_id, actor_user_id=admin_user.id)
        assert out["status"] == "pending"

    rows = (
        PaymentRefund.query.filter_by(payment_id=payment.id).order_by(PaymentRefund.id.asc()).all()
    )
    assert len(rows) == 2
    assert rows[-1].status == "pending"

    with app.app_context():
        audit = AuditLog.query.filter_by(action="payment.refund_retried").first()
        assert audit is not None
