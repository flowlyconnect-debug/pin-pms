from __future__ import annotations

import re

from werkzeug.security import generate_password_hash


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if not match:
        raise AssertionError("CSRF token not found in form")
    return match.group(1)


def _seed_invoice_for_admin(admin_user):
    from app.billing import services as billing_service
    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(
        organization_id=admin_user.organization_id, name="Invoice Admin Prop", address=None
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="IA-1", unit_type="double")
    db.session.add(unit)
    db.session.flush()

    lease = billing_service.create_lease(
        organization_id=admin_user.organization_id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date_raw="2026-05-01",
        end_date_raw=None,
        rent_amount_raw="100",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=admin_user.id,
    )
    return billing_service.create_invoice(
        organization_id=admin_user.organization_id,
        subtotal_excl_vat_raw="100.00",
        due_date_raw="2026-05-20",
        currency="EUR",
        description="Admin invoice",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=admin_user.id,
        vat_rate_raw="0",
    )


def test_mark_paid_html_form_redirects_with_flash(client, admin_user):
    invoice = _seed_invoice_for_admin(admin_user)
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.post(f"/admin/invoices/{invoice['id']}/mark-paid", follow_redirects=False)
    assert response.status_code == 302
    assert f"/admin/invoices/{invoice['id']}" in response.headers["Location"]

    page = client.get(response.headers["Location"])
    assert page.status_code == 200
    assert "Lasku merkitty maksetuksi." in page.get_data(as_text=True)


def test_mark_paid_json_request_returns_envelope(client, admin_user):
    invoice = _seed_invoice_for_admin(admin_user)
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.post(
        f"/admin/invoices/{invoice['id']}/mark-paid",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"]["invoice_id"] == invoice["id"]
    assert body["data"]["status"] == "paid"
    assert body["error"] is None


def test_mark_paid_already_paid_returns_409_or_flash_error(client, admin_user):
    from app.billing import services as billing_service

    invoice = _seed_invoice_for_admin(admin_user)
    billing_service.mark_invoice_paid(
        organization_id=admin_user.organization_id,
        invoice_id=invoice["id"],
        actor_user_id=admin_user.id,
    )
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    html_response = client.post(f"/admin/invoices/{invoice['id']}/mark-paid", follow_redirects=True)
    assert html_response.status_code == 200
    assert "Laskun tilaa ei voi muuttaa" in html_response.get_data(as_text=True)

    json_response = client.post(
        f"/admin/invoices/{invoice['id']}/mark-paid",
        headers={"Accept": "application/json"},
    )
    assert json_response.status_code == 409
    body = json_response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "invalid_state"


def test_mark_paid_writes_audit_row(client, admin_user):
    from app.audit.models import AuditLog

    invoice = _seed_invoice_for_admin(admin_user)
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.post(f"/admin/invoices/{invoice['id']}/mark-paid", follow_redirects=False)
    assert response.status_code == 302

    row = (
        AuditLog.query.filter_by(
            action="invoice.marked_paid", target_type="invoice", target_id=invoice["id"]
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None
    assert row.actor_id == admin_user.id
    assert row.organization_id == admin_user.organization_id


def test_mark_paid_enforces_tenant_scope(client, admin_user):
    from app.billing import services as billing_service
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.users.models import User, UserRole

    other_org = Organization(name="Invoice Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_admin = User(
        email="other-admin-invoice@test.local",
        password_hash=generate_password_hash("x"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_admin)
    db.session.flush()
    prop = Property(organization_id=other_org.id, name="Other Invoice Property", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="OI-1", unit_type=None)
    db.session.add(unit)
    db.session.commit()
    lease = billing_service.create_lease(
        organization_id=other_org.id,
        unit_id=unit.id,
        guest_id=other_admin.id,
        reservation_id=None,
        start_date_raw="2026-06-01",
        end_date_raw=None,
        rent_amount_raw="20",
        deposit_amount_raw="0",
        billing_cycle="monthly",
        notes=None,
        actor_user_id=other_admin.id,
    )
    other_invoice = billing_service.create_invoice(
        organization_id=other_org.id,
        subtotal_excl_vat_raw="20",
        due_date_raw="2026-06-10",
        currency="EUR",
        description="Other tenant invoice",
        lease_id=lease["id"],
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=other_admin.id,
        vat_rate_raw="0",
    )

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    json_response = client.post(
        f"/admin/invoices/{other_invoice['id']}/mark-paid",
        headers={"Accept": "application/json"},
    )
    assert json_response.status_code == 404
    json_body = json_response.get_json()
    assert json_body["success"] is False
    assert json_body["error"]["code"] == "invoice_not_found"

    html_response = client.post(
        f"/admin/invoices/{other_invoice['id']}/mark-paid",
        follow_redirects=True,
    )
    assert html_response.status_code == 200
    assert "Laskua ei löytynyt." in html_response.get_data(as_text=True)

    refreshed = billing_service.get_invoice_for_org(
        organization_id=other_org.id,
        invoice_id=other_invoice["id"],
    )
    assert refreshed["status"] == "open"


def test_mark_paid_requires_csrf_token(app, client, admin_user):
    original = app.config.get("WTF_CSRF_ENABLED", False)
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        invoice = _seed_invoice_for_admin(admin_user)
        _login(client, email=admin_user.email, password=admin_user.password_plain)
        response = client.post(f"/admin/invoices/{invoice['id']}/mark-paid", follow_redirects=False)
        assert response.status_code in (400, 403)
    finally:
        app.config["WTF_CSRF_ENABLED"] = original
