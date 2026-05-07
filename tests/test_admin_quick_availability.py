from __future__ import annotations

from datetime import date, timedelta

from app.extensions import db
from app.organizations.models import Organization
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.reservations.services import resolve_quick_availability_range


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _seed_unit(*, organization_id: int, property_name: str, unit_name: str) -> Unit:
    prop = Property(organization_id=organization_id, name=property_name, address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name=unit_name, unit_type="std")
    db.session.add(unit)
    db.session.flush()
    return unit


def test_quick_availability_today_returns_available_rooms(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    unit = _seed_unit(
        organization_id=admin_user.organization_id,
        property_name="Kohde A",
        unit_name="Huone 1",
    )
    db.session.commit()

    response = client.get("/admin/availability/quick?range=today")

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    room_ids = [room["id"] for room in payload["data"]["available_rooms"]]
    assert unit.id in room_ids


def test_quick_availability_excludes_booked_rooms(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    unit = _seed_unit(
        organization_id=admin_user.organization_id,
        property_name="Booked Hotel",
        unit_name="101",
    )
    today = date.today()
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_name="Booked Guest",
            start_date=today,
            end_date=today + timedelta(days=1),
            status="confirmed",
        )
    )
    db.session.commit()

    response = client.get("/admin/availability/quick?range=today")

    assert response.status_code == 200
    room_ids = [room["id"] for room in response.get_json()["data"]["available_rooms"]]
    assert unit.id not in room_ids


def test_quick_availability_rejects_invalid_range(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.get("/admin/availability/quick?range=invalid")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "invalid_range"


def test_quick_availability_is_tenant_scoped(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    own_unit = _seed_unit(
        organization_id=admin_user.organization_id,
        property_name="Own Property",
        unit_name="A1",
    )
    other_org = Organization(name="Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_unit = _seed_unit(
        organization_id=other_org.id,
        property_name="Other Property",
        unit_name="B1",
    )
    db.session.commit()

    response = client.get("/admin/availability/quick?range=today")

    assert response.status_code == 200
    room_ids = [room["id"] for room in response.get_json()["data"]["available_rooms"]]
    assert own_unit.id in room_ids
    assert other_unit.id not in room_ids


def test_resolve_quick_availability_ranges():
    monday = date(2026, 5, 4)
    assert resolve_quick_availability_range("today", today=monday) == (
        date(2026, 5, 4),
        date(2026, 5, 4),
    )
    assert resolve_quick_availability_range("tomorrow", today=monday) == (
        date(2026, 5, 5),
        date(2026, 5, 5),
    )
    assert resolve_quick_availability_range("weekend", today=monday) == (
        date(2026, 5, 9),
        date(2026, 5, 10),
    )
    assert resolve_quick_availability_range("7d", today=monday) == (
        date(2026, 5, 4),
        date(2026, 5, 10),
    )

    # On Sunday, the quick answer keeps the remaining current weekend day.
    sunday = date(2026, 5, 10)
    assert resolve_quick_availability_range("weekend", today=sunday) == (sunday, sunday)
