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


def _free_units(response) -> list[dict]:
    payload = response.get_json()
    assert payload["success"] is True
    data = payload["data"]
    assert set(data.keys()) == {"range", "start_date", "end_date", "free_units"}
    return data["free_units"]


def test_quick_availability_tenant_scoped(client, admin_user):
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
    unit_ids = [row["unit_id"] for row in _free_units(response)]
    assert own_unit.id in unit_ids
    assert other_unit.id not in unit_ids


def test_quick_availability_today_only_free_units(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    free_unit = _seed_unit(
        organization_id=admin_user.organization_id,
        property_name="Free Hotel",
        unit_name="101",
    )
    booked_unit = _seed_unit(
        organization_id=admin_user.organization_id,
        property_name="Booked Hotel",
        unit_name="202",
    )
    today = date.today()
    db.session.add(
        Reservation(
            unit_id=booked_unit.id,
            guest_name="Booked Guest",
            start_date=today,
            end_date=today + timedelta(days=1),
            status="confirmed",
        )
    )
    db.session.commit()

    response = client.get("/admin/availability/quick?range=today")

    assert response.status_code == 200
    rows = _free_units(response)
    unit_ids = [row["unit_id"] for row in rows]
    assert free_unit.id in unit_ids
    assert booked_unit.id not in unit_ids
    free_row = next(row for row in rows if row["unit_id"] == free_unit.id)
    assert free_row == {
        "property": "Free Hotel",
        "unit": "101",
        "unit_id": free_unit.id,
        "free_days": 1,
        "next_reservation_in_days": None,
    }


def test_quick_availability_7d_free_days(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    unit = _seed_unit(
        organization_id=admin_user.organization_id,
        property_name="Partial Hotel",
        unit_name="303",
    )
    today = date.today()
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_name="Partial Guest",
            start_date=today + timedelta(days=2),
            end_date=today + timedelta(days=5),
            status="confirmed",
        )
    )
    db.session.commit()

    response = client.get("/admin/availability/quick?range=7d")

    assert response.status_code == 200
    row = next(row for row in _free_units(response) if row["unit_id"] == unit.id)
    assert row["free_days"] == 4
    assert row["next_reservation_in_days"] == 2


def test_quick_availability_rejects_invalid_range(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.get("/admin/availability/quick?range=invalid")

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "invalid_range"


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

    sunday = date(2026, 5, 10)
    assert resolve_quick_availability_range("weekend", today=sunday) == (sunday, sunday)
