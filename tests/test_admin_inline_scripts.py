from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from html.parser import HTMLParser

from app.billing.models import Lease
from app.extensions import db
from app.guests.models import Guest
from app.maintenance.models import MaintenanceRequest
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


class _ScriptParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.scripts: list[dict[str, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "script":
            self.scripts.append(dict(attrs))


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _assert_scripts_are_csp_safe(html: str) -> None:
    parser = _ScriptParser()
    parser.feed(html)
    for script in parser.scripts:
        assert script.get("src") or script.get("nonce")
    assert re.search(r"\son[a-zA-Z]+\s*=", html) is None


def _seed_edit_entities(admin_user):
    prop = Property(organization_id=admin_user.organization_id, name="Inline Test Property", address=None)
    db.session.add(prop)
    db.session.flush()

    unit = Unit(property_id=prop.id, name="101", unit_type="single")
    db.session.add(unit)
    db.session.flush()

    guest = Guest(
        organization_id=admin_user.organization_id,
        first_name="Test",
        last_name="Guest",
        email="guest-inline@test.local",
    )
    db.session.add(guest)
    db.session.flush()

    reservation = Reservation(
        unit_id=unit.id,
        guest_id=guest.id,
        guest_name=guest.full_name,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 5),
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.flush()

    lease = Lease(
        organization_id=admin_user.organization_id,
        unit_id=unit.id,
        guest_id=guest.id,
        reservation_id=reservation.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        rent_amount=Decimal("1000.00"),
        deposit_amount=Decimal("100.00"),
        billing_cycle="monthly",
        status="draft",
        notes=None,
        created_by_id=admin_user.id,
    )
    db.session.add(lease)
    db.session.flush()

    maintenance = MaintenanceRequest(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=guest.id,
        reservation_id=reservation.id,
        title="Fix sink",
        description="Leak",
        status="new",
        priority="normal",
        created_by_id=admin_user.id,
    )
    db.session.add(maintenance)
    db.session.commit()
    return reservation.id, lease.id, maintenance.id


def test_admin_pages_inline_scripts_are_csp_safe(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    reservation_id, lease_id, maintenance_id = _seed_edit_entities(admin_user)

    routes = [
        "/admin/calendar",
        "/admin/reservations/new",
        f"/admin/reservations/{reservation_id}/edit",
        "/admin/leases/new",
        f"/admin/leases/{lease_id}/edit",
        "/admin/maintenance-requests/new",
        f"/admin/maintenance-requests/{maintenance_id}/edit",
    ]

    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, route
        html = response.get_data(as_text=True)
        _assert_scripts_are_csp_safe(html)

        csp = response.headers.get("Content-Security-Policy") or ""
        script_src = ""
        for directive in csp.split(";"):
            part = directive.strip()
            if part.startswith("script-src "):
                script_src = part
                break
        assert "'unsafe-inline'" not in script_src
