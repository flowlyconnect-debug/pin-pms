from __future__ import annotations

import re
from datetime import date

import pyotp
from app.extensions import db
from app.guests.models import Guest
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _seed_reservation(admin_user) -> Reservation:
    prop = Property(organization_id=admin_user.organization_id, name="UI Test Property", address=None)
    db.session.add(prop)
    db.session.flush()

    unit = Unit(property_id=prop.id, name="UI-101", unit_type="std")
    db.session.add(unit)
    db.session.flush()

    guest = Guest(
        organization_id=admin_user.organization_id,
        first_name="Ui",
        last_name="Tester",
        email="ui-tester@example.local",
    )
    db.session.add(guest)
    db.session.flush()

    reservation = Reservation(
        unit_id=unit.id,
        guest_id=guest.id,
        guest_name=guest.full_name,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 4),
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()
    return reservation


def _login_superadmin_2fa(client, superadmin):
    _login(client, email=superadmin.email, password=superadmin.password_plain)
    code = pyotp.TOTP(superadmin.totp_secret).now()
    return client.post("/2fa/verify", data={"code": code}, follow_redirects=False)


def test_admin_pages_load_toast_js(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "js/admin-toast.js" in html
    assert "js/admin-confirm.js" in html
    assert "js/admin-loading.js" in html


def test_flash_messages_render_toast_bridge_and_html_fallback(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    with client.session_transaction() as session:
        session["_flashes"] = [("success", "Tallennus onnistui")]

    response = client.get("/admin")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'class="flash' in html
    assert 'id="flash-toast-data"' in html
    assert "data-flash-category=" in html
    assert "data-flash-message=" in html


def test_dangerous_actions_have_confirm_attribute(client, superadmin):
    _login_superadmin_2fa(client, superadmin)
    response = client.get(f"/admin/gdpr/{superadmin.id}")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "data-confirm=" in html
    assert "confirm(" not in html


def test_no_inline_event_handlers_in_admin_base(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "onclick=" not in html
    assert "onsubmit=" not in html
    assert "onload=" not in html
    assert "onchange=" not in html
    assert re.search(r"\son[a-zA-Z]+\s*=", html) is None


def test_status_badge_macro_available(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    _seed_reservation(admin_user)

    response = client.get("/admin/reservations")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "badge-success" in html
