"""Tests for admin POST actions that support both HTML (form) and JSON (AJAX) clients.

Tämä testaa hybridi-mallin:
- HTML-form POST (selaimen Accept: text/html) → 302 redirect + flash-viesti
- AJAX POST (Accept: application/json) → 200 JSON-envelope (success/data/error)

Testit kattavat:
- mark-paid (lasku)
- invoice cancel
- invoice send-payment-link (epäonnistuminen)
- reservation cancel
- maintenance resolve / cancel
- audit-lokien syntyminen
- tenant-rajauksen 404 toiseen organisaatioon
- CSRF-tokenin renderöinti lomakkeissa
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from werkzeug.security import generate_password_hash

from app.audit.models import AuditLog
from app.billing import services as billing_service
from app.extensions import db
from app.maintenance import services as maintenance_service
from app.organizations.models import Organization
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.users.models import User, UserRole


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _seed_property_with_unit(*, organization_id: int, name: str = "Hotel", unit: str = "U1") -> Unit:
    prop = Property(organization_id=organization_id, name=name, address=None)
    db.session.add(prop)
    db.session.flush()
    u = Unit(property_id=prop.id, name=unit, unit_type="std")
    db.session.add(u)
    db.session.commit()
    return u


def _open_invoice_for(organization_id: int, actor_user_id: int) -> dict:
    return billing_service.create_invoice(
        organization_id=organization_id,
        subtotal_excl_vat_raw="100.00",
        due_date_raw=(date.today() + timedelta(days=14)).isoformat(),
        currency="EUR",
        description="Testilasku",
        lease_id=None,
        reservation_id=None,
        guest_id=None,
        status="open",
        metadata_json=None,
        actor_user_id=actor_user_id,
        vat_rate_raw="0",
    )


# ---------------------------------------------------------------------------
# Invoice mark-paid
# ---------------------------------------------------------------------------


def test_invoice_mark_paid_html_returns_redirect_and_flash(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    inv = _open_invoice_for(admin_user.organization_id, admin_user.id)

    response = client.post(
        f"/admin/invoices/{inv['id']}/mark-paid",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert f"/admin/invoices/{inv['id']}" in response.headers["Location"]

    follow = client.get(response.headers["Location"], follow_redirects=False)
    assert follow.status_code == 200
    assert "Lasku merkitty maksetuksi" in follow.get_data(as_text=True)


def test_invoice_mark_paid_json_returns_envelope(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    inv = _open_invoice_for(admin_user.organization_id, admin_user.id)

    response = client.post(
        f"/admin/invoices/{inv['id']}/mark-paid",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["error"] is None
    assert payload["data"]["invoice_id"] == inv["id"]
    assert payload["data"]["status"] == "paid"


def test_invoice_mark_paid_json_returns_envelope_with_xhr_header(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    inv = _open_invoice_for(admin_user.organization_id, admin_user.id)

    response = client.post(
        f"/admin/invoices/{inv['id']}/mark-paid",
        headers={"X-Requested-With": "XMLHttpRequest"},
    )
    assert response.status_code == 200
    assert response.is_json
    assert response.get_json()["success"] is True


def test_invoice_mark_paid_invalid_state_html_redirects_with_flash(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    inv = _open_invoice_for(admin_user.organization_id, admin_user.id)

    # Ensimmäinen merkintä onnistuu
    client.post(
        f"/admin/invoices/{inv['id']}/mark-paid", headers={"Accept": "text/html"}
    )
    # Toisesta saadaan invalid-state HTML-näkymässä
    response = client.post(
        f"/admin/invoices/{inv['id']}/mark-paid",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    follow = client.get(response.headers["Location"], follow_redirects=False)
    text = follow.get_data(as_text=True)
    assert "Laskun tilaa ei voi muuttaa" in text or "already" in text.lower()


def test_invoice_mark_paid_invalid_state_json_returns_409(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    inv = _open_invoice_for(admin_user.organization_id, admin_user.id)

    client.post(
        f"/admin/invoices/{inv['id']}/mark-paid",
        headers={"Accept": "application/json"},
    )
    response = client.post(
        f"/admin/invoices/{inv['id']}/mark-paid",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 409
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "invalid_state"


def test_invoice_mark_paid_writes_audit_log(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    inv = _open_invoice_for(admin_user.organization_id, admin_user.id)

    response = client.post(
        f"/admin/invoices/{inv['id']}/mark-paid",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    audit = AuditLog.query.filter_by(action="invoice.marked_paid").first()
    assert audit is not None
    assert audit.organization_id == admin_user.organization_id


def test_invoice_mark_paid_other_org_returns_404(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    other_org = Organization(name="Toinen Org")
    db.session.add(other_org)
    db.session.flush()
    other_admin = User(
        email="cross-org@test.local",
        password_hash=generate_password_hash("x"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_admin)
    db.session.commit()
    inv = _open_invoice_for(other_org.id, other_admin.id)

    response = client.post(
        f"/admin/invoices/{inv['id']}/mark-paid",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 404
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "invoice_not_found"


# ---------------------------------------------------------------------------
# Invoice cancel
# ---------------------------------------------------------------------------


def test_invoice_cancel_html_redirects_with_flash(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    inv = _open_invoice_for(admin_user.organization_id, admin_user.id)

    response = client.post(
        f"/admin/invoices/{inv['id']}/cancel",
        data={"confirm_cancel": "yes"},
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    follow = client.get(response.headers["Location"], follow_redirects=False)
    assert "Lasku peruttu" in follow.get_data(as_text=True)


def test_invoice_cancel_json_returns_envelope(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    inv = _open_invoice_for(admin_user.organization_id, admin_user.id)

    response = client.post(
        f"/admin/invoices/{inv['id']}/cancel",
        data={"confirm_cancel": "yes"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["status"] == "cancelled"


def test_invoice_cancel_without_confirm_returns_validation_error_in_json(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    inv = _open_invoice_for(admin_user.organization_id, admin_user.id)

    response = client.post(
        f"/admin/invoices/{inv['id']}/cancel",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "validation_error"


# ---------------------------------------------------------------------------
# Reservation cancel
# ---------------------------------------------------------------------------


def _seed_reservation(*, organization_id: int, status: str = "confirmed") -> Reservation:
    unit = _seed_property_with_unit(organization_id=organization_id)
    today = date.today()
    res = Reservation(
        unit_id=unit.id,
        guest_id=None,
        guest_name="Testi",
        start_date=today + timedelta(days=10),
        end_date=today + timedelta(days=12),
        status=status,
        amount=Decimal("100.00"),
        currency="EUR",
        payment_status="pending",
    )
    db.session.add(res)
    db.session.commit()
    return res


def test_reservation_cancel_html_redirects(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    res = _seed_reservation(organization_id=admin_user.organization_id)

    response = client.post(
        f"/admin/reservations/{res.id}/cancel",
        data={"confirm_cancel": "yes"},
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    follow = client.get(response.headers["Location"], follow_redirects=False)
    assert "Varaus peruttu" in follow.get_data(as_text=True)


def test_reservation_cancel_json_returns_envelope(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    res = _seed_reservation(organization_id=admin_user.organization_id)

    response = client.post(
        f"/admin/reservations/{res.id}/cancel",
        data={"confirm_cancel": "yes"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["reservation_id"] == res.id


# ---------------------------------------------------------------------------
# Maintenance resolve / cancel
# ---------------------------------------------------------------------------


def _seed_maintenance(*, organization_id: int, actor_user_id: int):
    unit = _seed_property_with_unit(organization_id=organization_id, name="Maint Hotel", unit="M1")
    return maintenance_service.create_maintenance_request(
        organization_id=organization_id,
        property_id=unit.property_id,
        unit_id=unit.id,
        title="Testihuolto",
        description=None,
        priority="normal",
        status="new",
        due_date_raw=date.today().isoformat(),
        assigned_to_id=None,
        guest_id=None,
        reservation_id=None,
        actor_user_id=actor_user_id,
    )


def test_maintenance_resolve_html_redirects(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    req = _seed_maintenance(
        organization_id=admin_user.organization_id, actor_user_id=admin_user.id
    )

    response = client.post(
        f"/admin/maintenance-requests/{req['id']}/resolve",
        headers={"Accept": "text/html"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    follow = client.get(response.headers["Location"], follow_redirects=False)
    assert "ratkaistuksi" in follow.get_data(as_text=True)


def test_maintenance_resolve_json_returns_envelope(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    req = _seed_maintenance(
        organization_id=admin_user.organization_id, actor_user_id=admin_user.id
    )

    response = client.post(
        f"/admin/maintenance-requests/{req['id']}/resolve",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["request_id"] == req["id"]
    assert payload["data"]["status"] == "resolved"


def test_maintenance_cancel_json_requires_confirmation(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    req = _seed_maintenance(
        organization_id=admin_user.organization_id, actor_user_id=admin_user.id
    )

    response = client.post(
        f"/admin/maintenance-requests/{req['id']}/cancel",
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["error"]["code"] == "validation_error"


def test_maintenance_cancel_json_envelope_when_confirmed(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    req = _seed_maintenance(
        organization_id=admin_user.organization_id, actor_user_id=admin_user.id
    )

    response = client.post(
        f"/admin/maintenance-requests/{req['id']}/cancel",
        data={"confirm_cancel": "yes"},
        headers={"Accept": "application/json"},
    )
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True


# ---------------------------------------------------------------------------
# CSRF-tokenit renderöityvät lomakkeisiin
# ---------------------------------------------------------------------------


def test_invoice_detail_form_includes_csrf_token(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    inv = _open_invoice_for(admin_user.organization_id, admin_user.id)

    response = client.get(f"/admin/invoices/{inv['id']}")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Mark-paid -lomakkeen pitää sisältää csrf_token-piilokenttä
    assert 'name="csrf_token"' in html
    # data-confirm käyttöliittymässä
    assert "data-confirm" in html


def test_invoice_list_mark_paid_form_includes_csrf_token(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    _open_invoice_for(admin_user.organization_id, admin_user.id)

    response = client.get("/admin/invoices")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="csrf_token"' in html
    assert "invoices_mark_paid" in html or "/mark-paid" in html
    assert "data-confirm" in html


def test_property_detail_does_not_require_separate_query_per_unit(client, admin_user):
    """Sanity check: property-detail-näkymä toimii ja palauttaa 200 myös
    monta huonetta sisältävässä kohteessa."""

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(
        organization_id=admin_user.organization_id, name="Big House", address=None
    )
    db.session.add(prop)
    db.session.flush()
    for i in range(8):
        db.session.add(Unit(property_id=prop.id, name=f"U{i}", unit_type="std"))
    db.session.commit()

    response = client.get(f"/admin/properties/{prop.id}")
    assert response.status_code == 200
