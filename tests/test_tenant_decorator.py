from __future__ import annotations

from decimal import Decimal

from app.billing.models import Invoice
from app.extensions import db
from app.organizations.models import Organization
from app.payments.models import Payment


def _login_admin(client, admin_user) -> None:
    response = client.post(
        "/login",
        data={"email": admin_user.email, "password": admin_user.password_plain},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def _invoice(organization, regular_user) -> Invoice:
    row = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=None,
        invoice_number=f"INV-TENANT-{organization.id}",
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


def test_require_tenant_access_string_model_allows_same_org(
    client, organization, regular_user, admin_user, monkeypatch
):
    from app.admin import routes as admin_routes

    inv = _invoice(organization, regular_user)
    payment = Payment(
        organization_id=organization.id,
        invoice_id=inv.id,
        provider="stripe",
        provider_payment_id="pi_tenant_same_org",
        amount=Decimal("100.00"),
        currency="EUR",
        status="succeeded",
    )
    db.session.add(payment)
    db.session.commit()
    monkeypatch.setattr(admin_routes.payment_service, "refund", lambda **_kwargs: {})
    _login_admin(client, admin_user)

    response = client.post(
        f"/admin/payments/{payment.id}/refund",
        data={"amount": "10.00", "reason": "test"},
        headers={"Idempotency-Key": "tenant-same-org"},
        follow_redirects=False,
    )
    assert response.status_code in {302, 303}


def test_require_tenant_access_string_model_blocks_cross_org(
    client, organization, regular_user, admin_user
):
    other_org = Organization(name="Other Org")
    db.session.add(other_org)
    db.session.commit()
    inv = _invoice(other_org, regular_user)
    payment = Payment(
        organization_id=other_org.id,
        invoice_id=inv.id,
        provider="stripe",
        provider_payment_id="pi_tenant_other_org",
        amount=Decimal("100.00"),
        currency="EUR",
        status="succeeded",
    )
    db.session.add(payment)
    db.session.commit()
    _login_admin(client, admin_user)

    response = client.post(
        f"/admin/payments/{payment.id}/refund",
        data={"amount": "10.00", "reason": "forbidden"},
        headers={"Idempotency-Key": "tenant-other-org"},
        follow_redirects=False,
    )
    assert response.status_code == 404
