from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app.audit.models import AuditLog
from app.extensions import db
from app.payments.models import Payment
from app.payments.services import expire_pending_payments


def test_expire_pending_payments_marks_old_pending_as_expired(app, organization):
    with app.app_context():
        old = datetime.utcnow() - timedelta(hours=25)
        pay = Payment(
            organization_id=organization.id,
            provider="stripe",
            amount=Decimal("10.00"),
            currency="EUR",
            status="pending",
            created_at=old,
        )
        db.session.add(pay)
        db.session.commit()
        pay_id = pay.id

        n = expire_pending_payments(max_age_hours=24)
        assert n == 1

        row = Payment.query.get(pay_id)
        assert row is not None
        assert row.status == "expired"

        audit = AuditLog.query.filter_by(action="payment.expired", target_id=pay_id).first()
        assert audit is not None


def test_expire_pending_payments_skips_recent_pending(app, organization):
    with app.app_context():
        pay = Payment(
            organization_id=organization.id,
            provider="stripe",
            amount=Decimal("5.00"),
            currency="EUR",
            status="pending",
        )
        db.session.add(pay)
        db.session.commit()

        n = expire_pending_payments(max_age_hours=24)
        assert n == 0
        db.session.refresh(pay)
        assert pay.status == "pending"
