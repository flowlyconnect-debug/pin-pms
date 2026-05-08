from __future__ import annotations

from datetime import date, timedelta

from app.extensions import db
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def test_admin_calendar_renders_calendar_container(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.get("/admin/calendar")
    assert response.status_code == 200
    assert 'id="calendar"' in response.get_data(as_text=True)


def test_admin_calendar_events_json_returns_reservations(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(
        organization_id=admin_user.organization_id, name="Calendar Test Property", address=None
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="Calendar Unit 1", unit_type="std")
    db.session.add(unit)
    db.session.flush()
    reservation = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        guest_name="Klikattava Varaus",
        start_date=date(2026, 5, 10),
        end_date=date(2026, 5, 12),
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()

    response = client.get("/admin/calendar/events?start=2026-05-01&end=2026-05-31")
    assert response.status_code == 200
    payload = response.get_json()
    assert isinstance(payload, list)
    assert any(event.get("id") == reservation.id for event in payload)
    event = next(event for event in payload if event.get("id") == reservation.id)
    assert "/admin/reservations/" in str(event.get("url", ""))


def test_admin_calendar_css_contains_clickable_event_rules():
    css_path = "app/static/css/admin.css"
    with open(css_path, encoding="utf-8") as handle:
        css = handle.read()

    assert ".fc-event" in css
    assert "cursor: pointer" in css
    assert ".fc-event *" in css
    assert ".fc-event {\n  pointer-events: none;" not in css


def test_availability_cell_links_are_block_level(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(
        organization_id=admin_user.organization_id, name="Availability Property", address=None
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="Availability Unit", unit_type="std")
    db.session.add(unit)
    db.session.flush()
    today = date.today()
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_id=admin_user.id,
            guest_name="Saatavuus Asiakas",
            start_date=today,
            end_date=today + timedelta(days=2),
            status="confirmed",
        )
    )
    db.session.commit()

    response = client.get(
        f"/admin/availability?from={today.isoformat()}&days=3&property_id={prop.id}"
    )
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Availability Property" in html
    assert "availability-cell-link" in html

    css_path = "app/static/css/admin.css"
    with open(css_path, encoding="utf-8") as handle:
        css = handle.read()
    assert ".availability-cell-link" in css
    assert "display: block" in css
    assert "height: 100%" in css
