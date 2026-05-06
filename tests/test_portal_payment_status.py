"""Portal payment return helpers (status JSON for polling)."""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.payments.models import Payment
from tests.test_portal import _portal_login


def test_portal_payment_status_json_for_own_payment(client, organization, regular_user):
    pay = Payment(
        organization_id=organization.id,
        provider="stripe",
        amount=Decimal("10.00"),
        currency="EUR",
        status="pending",
    )
    db.session.add(pay)
    db.session.commit()

    _portal_login(client, email=regular_user.email, password=regular_user.password_plain)
    r = client.get(f"/portal/payments/{pay.id}/status")
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["id"] == pay.id
    assert payload["status"] == "pending"


def test_portal_payment_status_404_for_other_org_payment(client, regular_user):
    from app.organizations.models import Organization

    other = Organization(name="Other portal org")
    db.session.add(other)
    db.session.flush()
    pay = Payment(
        organization_id=other.id,
        provider="stripe",
        amount=Decimal("1.00"),
        currency="EUR",
        status="pending",
    )
    db.session.add(pay)
    db.session.commit()

    _portal_login(client, email=regular_user.email, password=regular_user.password_plain)
    r = client.get(f"/portal/payments/{pay.id}/status")
    assert r.status_code == 404
