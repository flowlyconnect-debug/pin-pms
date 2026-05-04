from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _auth_headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def _property_unit_guest(*, organization_id: int):
    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(organization_id=organization_id, name="Billing Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A1", unit_type="double")
    db.session.add(unit)
    db.session.commit()
    return prop, unit


@pytest.fixture
def billing_api_key(regular_user):
    from app.api.models import ApiKey
    from app.extensions import db

    key, raw = ApiKey.issue(
        name="Billing key",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes="invoices:read,invoices:write",
    )
    db.session.add(key)
    db.session.commit()
    key.raw = raw
    return key


def test_lease_and_invoice_models_and_invoice_number_uniqueness(app, organization, admin_user):
    from app.billing.models import Invoice, Lease
    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(organization_id=organization.id, name="P", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U1", unit_type=None)
    db.session.add(unit)
    db.session.commit()

    lease = Lease(
        organization_id=organization.id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date=date(2026, 5, 1),
        end_date=None,
        rent_amount=Decimal("100.00"),
        deposit_amount=Decimal("0.00"),
        billing_cycle="monthly",
        status="draft",
        notes=None,
        created_by_id=admin_user.id,
    )
    db.session.add(lease)
    db.session.flush()

    inv = Invoice(
        organization_id=organization.id,
        lease_id=lease.id,
        reservation_id=None,
        guest_id=admin_user.id,
        invoice_number=None,
        amount=Decimal("50.00"),
        vat_rate=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
        subtotal_excl_vat=Decimal("50.00"),
        total_incl_vat=Decimal("50.00"),
        currency="EUR",
        due_date=date(2026, 5, 15),
        paid_at=None,
        status="draft",
        description=None,
        metadata_json=None,
        created_by_id=admin_user.id,
    )
    db.session.add(inv)
    db.session.flush()
    inv.invoice_number = f"BIL-{organization.id}-{inv.id:08d}"
    db.session.commit()

    assert lease.status == "draft"
    assert inv.status == "draft"
    dup = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=None,
        invoice_number=inv.invoice_number,
        amount=Decimal("1.00"),
        vat_rate=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
        subtotal_excl_vat=Decimal("1.00"),
        total_incl_vat=Decimal("1.00"),
        currency="EUR",
        due_date=date(2026, 6, 1),
        status="draft",
        description=None,
        metadata_json=None,
        created_by_id=admin_user.id,
    )
    db.session.add(dup)
    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()


def test_create_lease_rejects_foreign_unit(app, organization, admin_user):
    from app.billing import services as billing_service
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit

    other = Organization(name="Other")
    db.session.add(other)
    db.session.flush()
    prop = Property(organization_id=other.id, name="Foreign", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="X", unit_type=None)
    db.session.add(unit)
    db.session.commit()

    with pytest.raises(billing_service.LeaseServiceError) as exc:
        billing_service.create_lease(
            organization_id=organization.id,
            unit_id=unit.id,
            guest_id=admin_user.id,
            reservation_id=None,
            start_date_raw="2026-06-01",
            end_date_raw=None,
            rent_amount_raw="100",
            deposit_amount_raw="0",
            billing_cycle="monthly",
            notes=None,
            actor_user_id=admin_user.id,
        )
    assert exc.value.status == 400


def test_invoice_service_mark_paid_and_overdue_and_audit(app, organization, admin_user):
    from app.audit.models import AuditLog
    from app.billing import services as billing_service

    _property_unit_guest(organization_id=organization.id)
    from app.properties.models import Property, Unit

    unit = Unit.query.join(Property).filter(Property.organization_id == organization.id).first()

    lease = billing_service.create_lease(
        organization_id=organization.id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date_raw="2026-06-01",
        end_date_raw=None,
        rent_amount_raw="200.00",
        deposit_amount_raw="50",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=admin_user.id,
    )
    inv = billing_service.create_invoice(
        organization_id=organization.id,
        subtotal_excl_vat_raw="200.00",
        due_date_raw="2026-06-10",
        currency="EUR",
        description="Rent",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=admin_user.id,
        vat_rate_raw="0",
    )
    assert AuditLog.query.filter_by(action="lease.created").first() is not None
    assert AuditLog.query.filter_by(action="invoice.created").first() is not None

    out1 = billing_service.mark_invoice_paid(
        organization_id=organization.id,
        invoice_id=inv["id"],
        actor_user_id=admin_user.id,
    )
    out2 = billing_service.mark_invoice_paid(
        organization_id=organization.id,
        invoice_id=inv["id"],
        actor_user_id=admin_user.id,
    )
    assert out1["status"] == "paid"
    assert out2["status"] == "paid"

    inv2 = billing_service.create_invoice(
        organization_id=organization.id,
        subtotal_excl_vat_raw="10.00",
        due_date_raw=(date.today() - timedelta(days=2)).isoformat(),
        currency="EUR",
        description="Late",
        lease_id=None,
        reservation_id=None,
        guest_id=admin_user.id,
        status="open",
        metadata_json=None,
        actor_user_id=admin_user.id,
        vat_rate_raw="0",
    )
    n = billing_service.mark_overdue_invoices(organization_id=organization.id)
    assert n >= 1
    row = billing_service.get_invoice_for_org(
        organization_id=organization.id,
        invoice_id=inv2["id"],
    )
    assert row["status"] == "overdue"
    assert AuditLog.query.filter_by(action="invoice.marked_overdue").first() is not None


def test_cannot_mark_invoice_paid_other_organization(app, organization, admin_user):
    from app.billing import services as billing_service
    from app.extensions import db
    from app.organizations.models import Organization
    from app.users.models import User, UserRole

    _property_unit_guest(organization_id=organization.id)
    from app.properties.models import Property, Unit

    other_org = Organization(name="Org B")
    db.session.add(other_org)
    db.session.flush()
    other_admin = User(
        email="other-billing@test.local",
        password_hash=generate_password_hash("x"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_admin)
    db.session.flush()
    prop_b = Property(organization_id=other_org.id, name="PB", address=None)
    db.session.add(prop_b)
    db.session.flush()
    unit_b = Unit(property_id=prop_b.id, name="UB", unit_type=None)
    db.session.add(unit_b)
    db.session.commit()

    lease_b = billing_service.create_lease(
        organization_id=other_org.id,
        unit_id=unit_b.id,
        guest_id=other_admin.id,
        reservation_id=None,
        start_date_raw="2026-07-01",
        end_date_raw=None,
        rent_amount_raw="50",
        deposit_amount_raw="0",
        billing_cycle="weekly",
        notes=None,
        actor_user_id=other_admin.id,
    )
    inv_b = billing_service.create_invoice(
        organization_id=other_org.id,
        subtotal_excl_vat_raw="50",
        due_date_raw="2026-07-15",
        currency="EUR",
        description="Other",
        lease_id=lease_b["id"],
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=other_admin.id,
        vat_rate_raw="0",
    )

    with pytest.raises(billing_service.InvoiceServiceError) as exc:
        billing_service.mark_invoice_paid(
            organization_id=organization.id,
            invoice_id=inv_b["id"],
            actor_user_id=admin_user.id,
        )
    assert exc.value.status == 404


def test_admin_can_list_leases_and_invoices(client, admin_user):
    from app.billing import services as billing_service

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    r = client.get("/admin/leases")
    assert r.status_code == 200
    r2 = client.get("/admin/invoices")
    assert r2.status_code == 200

    _property_unit_guest(organization_id=admin_user.organization_id)
    from app.properties.models import Property, Unit

    unit = (
        Unit.query.join(Property)
        .filter(Property.organization_id == admin_user.organization_id)
        .first()
    )
    lease = billing_service.create_lease(
        organization_id=admin_user.organization_id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date_raw="2026-08-01",
        end_date_raw=None,
        rent_amount_raw="99",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=admin_user.id,
    )
    inv = billing_service.create_invoice(
        organization_id=admin_user.organization_id,
        subtotal_excl_vat_raw="99",
        due_date_raw="2026-08-10",
        currency="EUR",
        description="x",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=admin_user.id,
        vat_rate_raw="0",
    )

    d = client.get(f"/admin/leases/{lease['id']}")
    assert d.status_code == 200
    d2 = client.get(f"/admin/invoices/{inv['id']}")
    assert d2.status_code == 200


def test_admin_cannot_access_other_org_lease(client, admin_user):
    from app.billing import services as billing_service
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.users.models import User, UserRole

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    other_org = Organization(name="Foreign lease org")
    db.session.add(other_org)
    db.session.flush()
    u = User(
        email="foreign-lease@test.local",
        password_hash=generate_password_hash("x"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(u)
    db.session.flush()
    prop = Property(organization_id=other_org.id, name="F", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U", unit_type=None)
    db.session.add(unit)
    db.session.commit()

    lease = billing_service.create_lease(
        organization_id=other_org.id,
        unit_id=unit.id,
        guest_id=u.id,
        reservation_id=None,
        start_date_raw="2026-09-01",
        end_date_raw=None,
        rent_amount_raw="10",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=u.id,
    )

    r = client.get(f"/admin/leases/{lease['id']}")
    assert r.status_code == 404


def test_admin_mark_invoice_paid_posts(client, admin_user):
    from app.audit.models import AuditLog
    from app.billing import services as billing_service
    from app.properties.models import Property, Unit

    _property_unit_guest(organization_id=admin_user.organization_id)
    unit = (
        Unit.query.join(Property)
        .filter(Property.organization_id == admin_user.organization_id)
        .first()
    )
    lease = billing_service.create_lease(
        organization_id=admin_user.organization_id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date_raw="2026-10-01",
        end_date_raw=None,
        rent_amount_raw="40",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=admin_user.id,
    )
    billing_service.activate_lease(
        organization_id=admin_user.organization_id,
        lease_id=lease["id"],
        actor_user_id=admin_user.id,
    )
    inv = billing_service.create_invoice(
        organization_id=admin_user.organization_id,
        subtotal_excl_vat_raw="40",
        due_date_raw="2026-10-15",
        currency="EUR",
        description="Due",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=admin_user.id,
        vat_rate_raw="0",
    )

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    before = AuditLog.query.filter_by(action="invoice.marked_paid").count()
    r = client.post(f"/admin/invoices/{inv['id']}/mark-paid")
    assert r.status_code == 302
    assert AuditLog.query.filter_by(action="invoice.marked_paid").count() == before + 1


def test_api_missing_key_returns_401_json_shape(client):
    r = client.get("/api/v1/invoices")
    assert r.status_code == 401
    body = r.get_json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "unauthorized"


def test_api_invoices_list_and_mark_paid(client, billing_api_key, organization, admin_user):
    from app.billing import services as billing_service
    from app.properties.models import Property, Unit

    _property_unit_guest(organization_id=organization.id)
    unit = Unit.query.join(Property).filter(Property.organization_id == organization.id).first()
    lease = billing_service.create_lease(
        organization_id=organization.id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date_raw="2026-11-01",
        end_date_raw=None,
        rent_amount_raw="120",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=admin_user.id,
    )
    inv = billing_service.create_invoice(
        organization_id=organization.id,
        subtotal_excl_vat_raw="120",
        due_date_raw="2026-11-20",
        currency="EUR",
        description="API test",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=admin_user.id,
        vat_rate_raw="0",
    )

    raw = billing_api_key.raw
    assert billing_api_key.organization_id == organization.id

    lst = client.get("/api/v1/invoices", headers=_auth_headers(raw))
    assert lst.status_code == 200
    payload = lst.get_json()
    assert payload["success"] is True
    ids = {row["id"] for row in payload["data"]}
    assert inv["id"] in ids

    paid = client.post(
        f"/api/v1/invoices/{inv['id']}/mark-paid",
        headers=_auth_headers(raw),
    )
    assert paid.status_code == 200
    p2 = paid.get_json()
    assert p2["success"] is True
    assert p2["data"]["status"] == "paid"


def test_api_invoice_wrong_org_returns_404(client, billing_api_key, organization, admin_user):
    from app.billing import services as billing_service
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.users.models import User, UserRole

    other = Organization(name="API other")
    db.session.add(other)
    db.session.flush()
    u2 = User(
        email="api-other@test.local",
        password_hash=generate_password_hash("x"),
        organization_id=other.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(u2)
    db.session.flush()
    prop = Property(organization_id=other.id, name="O", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U2", unit_type=None)
    db.session.add(unit)
    db.session.commit()

    lease = billing_service.create_lease(
        organization_id=other.id,
        unit_id=unit.id,
        guest_id=u2.id,
        reservation_id=None,
        start_date_raw="2026-12-01",
        end_date_raw=None,
        rent_amount_raw="5",
        deposit_amount_raw="0",
        billing_cycle="one_time",
        notes=None,
        actor_user_id=u2.id,
    )
    inv = billing_service.create_invoice(
        organization_id=other.id,
        subtotal_excl_vat_raw="5",
        due_date_raw="2026-12-05",
        currency="EUR",
        description="x",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=u2.id,
        vat_rate_raw="0",
    )

    raw = billing_api_key.raw
    r = client.get(f"/api/v1/invoices/{inv['id']}", headers=_auth_headers(raw))
    assert r.status_code == 404
    body = r.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "not_found"


def test_invoice_calculates_vat_correctly(app, organization, admin_user):
    from app.billing import services as billing_service

    _property_unit_guest(organization_id=organization.id)
    from app.properties.models import Property, Unit

    unit = Unit.query.join(Property).filter(Property.organization_id == organization.id).first()
    lease = billing_service.create_lease(
        organization_id=organization.id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date_raw="2026-05-01",
        end_date_raw=None,
        rent_amount_raw="1",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=admin_user.id,
    )
    inv = billing_service.create_invoice(
        organization_id=organization.id,
        subtotal_excl_vat_raw="100",
        due_date_raw="2026-05-15",
        currency="EUR",
        description="VAT test",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="draft",
        metadata_json=None,
        actor_user_id=admin_user.id,
        vat_rate_raw="24",
    )
    assert inv["subtotal_excl_vat"] == "100.00"
    assert inv["vat_amount"] == "24.00"
    assert inv["total_incl_vat"] == "124.00"
    assert inv["amount"] == "124.00"


def test_invoice_uses_default_vat_when_not_specified(app, organization, admin_user):
    from app.billing import services as billing_service

    _property_unit_guest(organization_id=organization.id)
    from app.properties.models import Property, Unit

    unit = Unit.query.join(Property).filter(Property.organization_id == organization.id).first()
    lease = billing_service.create_lease(
        organization_id=organization.id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date_raw="2026-05-01",
        end_date_raw=None,
        rent_amount_raw="1",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=admin_user.id,
    )
    inv = billing_service.create_invoice(
        organization_id=organization.id,
        subtotal_excl_vat_raw="100",
        due_date_raw="2026-05-20",
        currency="EUR",
        description="Default VAT",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="draft",
        metadata_json=None,
        actor_user_id=admin_user.id,
        vat_rate_raw=None,
    )
    assert inv["vat_rate"] == "24.00"
    assert inv["vat_amount"] == "24.00"
    assert inv["total_incl_vat"] == "124.00"


def test_invoice_zero_vat(app, organization, admin_user):
    from app.billing import services as billing_service

    _property_unit_guest(organization_id=organization.id)
    from app.properties.models import Property, Unit

    unit = Unit.query.join(Property).filter(Property.organization_id == organization.id).first()
    lease = billing_service.create_lease(
        organization_id=organization.id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date_raw="2026-05-01",
        end_date_raw=None,
        rent_amount_raw="1",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=admin_user.id,
    )
    inv = billing_service.create_invoice(
        organization_id=organization.id,
        subtotal_excl_vat_raw="250.00",
        due_date_raw="2026-05-21",
        currency="EUR",
        description="Zero VAT",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="draft",
        metadata_json=None,
        actor_user_id=admin_user.id,
        vat_rate_raw="0",
    )
    assert inv["vat_amount"] == "0.00"
    assert inv["total_incl_vat"] == "250.00"


def test_legacy_invoice_migration_shape(app, organization, admin_user):
    """Row matching post-migration backfill (legacy ``amount`` was incl. 24 % VAT)."""

    from app.billing import services as billing_service
    from app.billing.models import Invoice
    from app.extensions import db

    row = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=None,
        invoice_number="BIL-LEG-124",
        amount=Decimal("124.00"),
        vat_rate=Decimal("24.00"),
        vat_amount=Decimal("24.00"),
        subtotal_excl_vat=Decimal("100.00"),
        total_incl_vat=Decimal("124.00"),
        currency="EUR",
        due_date=date(2026, 6, 1),
        paid_at=None,
        status="open",
        description=None,
        metadata_json=None,
        created_by_id=admin_user.id,
        updated_by_id=None,
    )
    db.session.add(row)
    db.session.commit()

    out = billing_service.get_invoice_for_org(
        organization_id=organization.id,
        invoice_id=row.id,
    )
    assert out["subtotal_excl_vat"] == "100.00"
    assert out["vat_amount"] == "24.00"
    assert out["total_incl_vat"] == "124.00"
    assert out["total"] == "124.00"
    assert out["amount"] == "124.00"
