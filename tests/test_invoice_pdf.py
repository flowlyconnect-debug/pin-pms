"""Tests for invoice PDF generation, admin/API routes, scopes, and audit."""

from __future__ import annotations

from werkzeug.security import generate_password_hash


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _auth_headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def _make_open_invoice(*, organization_id: int, actor_user_id: int):
    """Create property, unit, lease, and one open invoice (VAT 24 %)."""

    from app.billing import services as billing_service
    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(organization_id=organization_id, name="PDF Hotel", address="Testikatu 1")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    lease = billing_service.create_lease(
        organization_id=organization_id,
        unit_id=unit.id,
        guest_id=actor_user_id,
        reservation_id=None,
        start_date_raw="2026-06-01",
        end_date_raw=None,
        rent_amount_raw="100.00",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=actor_user_id,
    )
    inv = billing_service.create_invoice(
        organization_id=organization_id,
        subtotal_excl_vat_raw="100.00",
        due_date_raw="2026-06-15",
        currency="EUR",
        description="Majoitus testi",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=actor_user_id,
        vat_rate_raw="24",
    )
    return inv


def test_generate_pdf_returns_bytes(app, organization, admin_user):
    from app.billing.pdf import generate_invoice_pdf

    inv = _make_open_invoice(organization_id=organization.id, actor_user_id=admin_user.id)
    with app.app_context():
        raw = generate_invoice_pdf(inv["id"])
    assert isinstance(raw, bytes)
    assert raw.startswith(b"%PDF")


def test_pdf_contains_invoice_number(app, organization, admin_user):
    from app.billing.pdf import generate_invoice_pdf

    inv = _make_open_invoice(organization_id=organization.id, actor_user_id=admin_user.id)
    num = inv["invoice_number"]
    assert num
    with app.app_context():
        raw = generate_invoice_pdf(inv["id"])
    assert num.encode("utf-8") in raw


def test_pdf_contains_vat_breakdown(app, organization, admin_user):
    from app.billing.pdf import generate_invoice_pdf

    inv = _make_open_invoice(organization_id=organization.id, actor_user_id=admin_user.id)
    with app.app_context():
        raw = generate_invoice_pdf(inv["id"])
    # Amounts and summary labels (ReportLab encodes them literally in the PDF stream).
    assert b"100.00" in raw
    assert b"24.00" in raw
    assert b"124.00" in raw
    assert b"Veroton" in raw
    assert b"ALV:" in raw
    assert b"Yhteens" in raw


def test_admin_route_requires_login(client, organization, admin_user):
    inv = _make_open_invoice(organization_id=organization.id, actor_user_id=admin_user.id)
    r = client.get(f"/admin/invoices/{inv['id']}/pdf", follow_redirects=False)
    assert r.status_code in (302, 401)


def test_admin_route_tenant_isolation(client, admin_user):
    from app.billing import services as billing_service
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.users.models import User, UserRole

    other = Organization(name="Org B PDF")
    db.session.add(other)
    db.session.flush()
    foreign_admin = User(
        email="foreign-pdf@test.local",
        password_hash=generate_password_hash("Secret123!"),
        organization_id=other.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(foreign_admin)
    db.session.flush()
    prop = Property(organization_id=other.id, name="Other prop", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U", unit_type=None)
    db.session.add(unit)
    db.session.commit()

    lease = billing_service.create_lease(
        organization_id=other.id,
        unit_id=unit.id,
        guest_id=foreign_admin.id,
        reservation_id=None,
        start_date_raw="2026-07-01",
        end_date_raw=None,
        rent_amount_raw="50",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=foreign_admin.id,
    )
    inv = billing_service.create_invoice(
        organization_id=other.id,
        subtotal_excl_vat_raw="50",
        due_date_raw="2026-07-10",
        currency="EUR",
        description="Foreign",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=foreign_admin.id,
        vat_rate_raw="0",
    )

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    r = client.get(f"/admin/invoices/{inv['id']}/pdf")
    assert r.status_code == 404


def test_api_route_requires_scope(app, client, organization, regular_user):
    from app.api.models import ApiKey
    from app.extensions import db

    inv = _make_open_invoice(organization_id=organization.id, actor_user_id=regular_user.id)

    key_noscope, raw_no = ApiKey.issue(
        name="no invoices read",
        organization_id=organization.id,
        user_id=regular_user.id,
        scopes="properties:read",
    )
    db.session.add(key_noscope)
    db.session.commit()

    r1 = client.get(
        f"/api/v1/invoices/{inv['id']}/pdf",
        headers=_auth_headers(raw_no),
    )
    assert r1.status_code == 403

    key_ok, raw_ok = ApiKey.issue(
        name="invoices read",
        organization_id=organization.id,
        user_id=regular_user.id,
        scopes="invoices:read",
    )
    db.session.add(key_ok)
    db.session.commit()

    r2 = client.get(
        f"/api/v1/invoices/{inv['id']}/pdf",
        headers=_auth_headers(raw_ok),
    )
    assert r2.status_code == 200
    assert r2.mimetype == "application/pdf"
    assert r2.data.startswith(b"%PDF")


def test_audit_log_created_on_download(client, organization, admin_user):
    from app.audit.models import AuditLog

    inv = _make_open_invoice(organization_id=organization.id, actor_user_id=admin_user.id)

    before = AuditLog.query.filter_by(action="invoice.pdf_downloaded", target_id=inv["id"]).count()

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    r = client.get(f"/admin/invoices/{inv['id']}/pdf")
    assert r.status_code == 200

    row = AuditLog.query.filter_by(
        action="invoice.pdf_downloaded",
        target_type="invoice",
        target_id=inv["id"],
    ).order_by(AuditLog.id.desc()).first()
    assert row is not None
    assert AuditLog.query.filter_by(action="invoice.pdf_downloaded", target_id=inv["id"]).count() > before
