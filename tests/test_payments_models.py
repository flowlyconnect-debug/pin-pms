from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.payments.models import Payment, PaymentRefund


def test_payment_and_refund_models_basic(organization):
    payment = Payment(
        organization_id=organization.id,
        provider="stripe",
        amount=Decimal("12.34"),
        currency="EUR",
        status="pending",
    )
    db.session.add(payment)
    db.session.commit()
    refund = PaymentRefund(
        payment_id=payment.id,
        amount=Decimal("1.00"),
        status="pending",
    )
    db.session.add(refund)
    db.session.commit()
    assert payment.id is not None
    assert refund.id is not None


def test_provider_payment_id_unique_per_provider(organization):
    db.session.add(
        Payment(
            organization_id=organization.id,
            provider="stripe",
            provider_payment_id="abc",
            amount=Decimal("10.00"),
            currency="EUR",
            status="pending",
        )
    )
    db.session.commit()
    db.session.add(
        Payment(
            organization_id=organization.id,
            provider="stripe",
            provider_payment_id="abc",
            amount=Decimal("10.00"),
            currency="EUR",
            status="pending",
        )
    )
    with pytest.raises((ValueError, IntegrityError)):
        db.session.commit()
