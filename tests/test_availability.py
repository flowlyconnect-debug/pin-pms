from __future__ import annotations

from datetime import date

from app.extensions import db
from app.maintenance.models import MaintenanceRequest
from app.organizations.models import Organization
from app.properties.models import Property, Unit
from app.reservations import services as reservation_service
from app.reservations.models import Reservation


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


def _unit_days_map(matrix: dict, *, unit_id: int) -> dict[str, dict]:
    for prop in matrix["properties"]:
        for unit in prop["units"]:
            if unit["id"] == unit_id:
                return {day["date"]: day for day in unit["days"]}
    raise AssertionError(f"Unit {unit_id} missing from matrix")


def test_availability_returns_only_own_org(app, admin_user):
    with app.app_context():
        own_unit = _seed_unit(
            organization_id=admin_user.organization_id,
            property_name="Own Property",
            unit_name="A1",
        )
        other_org = Organization(name="Other Org")
        db.session.add(other_org)
        db.session.flush()
        _seed_unit(organization_id=other_org.id, property_name="Other Property", unit_name="B1")
        db.session.commit()

        matrix = reservation_service.availability_matrix(
            organization_id=admin_user.organization_id,
            start_date=date(2026, 5, 5),
            end_date=date(2026, 5, 10),
        )
        unit_ids = [u["id"] for p in matrix["properties"] for u in p["units"]]
        assert own_unit.id in unit_ids
        assert len(unit_ids) == 1


def test_availability_marks_reserved_days(app, admin_user):
    with app.app_context():
        unit = _seed_unit(
            organization_id=admin_user.organization_id,
            property_name="Reserved Property",
            unit_name="101",
        )
        db.session.add(
            Reservation(
                unit_id=unit.id,
                guest_id=admin_user.id,
                guest_name="Matti M.",
                start_date=date(2026, 5, 6),
                end_date=date(2026, 5, 8),
                status="confirmed",
            )
        )
        db.session.commit()

        matrix = reservation_service.availability_matrix(
            organization_id=admin_user.organization_id,
            start_date=date(2026, 5, 5),
            end_date=date(2026, 5, 9),
        )
        days = _unit_days_map(matrix, unit_id=unit.id)
        assert days["2026-05-06"]["status"] == "reserved"
        assert days["2026-05-07"]["status"] == "reserved"
        assert days["2026-05-08"]["status"] == "checkout"


def test_availability_marks_maintenance_days(app, admin_user):
    with app.app_context():
        unit = _seed_unit(
            organization_id=admin_user.organization_id,
            property_name="Maintenance Property",
            unit_name="M1",
        )
        db.session.add(
            MaintenanceRequest(
                organization_id=admin_user.organization_id,
                property_id=unit.property_id,
                unit_id=unit.id,
                title="Fix heater",
                status="new",
                priority="normal",
                due_date=date(2026, 5, 9),
                created_by_id=admin_user.id,
            )
        )
        db.session.commit()

        matrix = reservation_service.availability_matrix(
            organization_id=admin_user.organization_id,
            start_date=date(2026, 5, 7),
            end_date=date(2026, 5, 10),
        )
        days = _unit_days_map(matrix, unit_id=unit.id)
        assert days["2026-05-09"]["status"] == "maintenance"


def test_availability_handles_overlapping_reservations(app, admin_user):
    with app.app_context():
        unit = _seed_unit(
            organization_id=admin_user.organization_id,
            property_name="Overlap Property",
            unit_name="O1",
        )
        db.session.add_all(
            [
                Reservation(
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    guest_name="Guest A",
                    start_date=date(2026, 5, 10),
                    end_date=date(2026, 5, 12),
                    status="confirmed",
                ),
                Reservation(
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    guest_name="Guest B",
                    start_date=date(2026, 5, 11),
                    end_date=date(2026, 5, 13),
                    status="confirmed",
                ),
            ]
        )
        db.session.commit()

        matrix = reservation_service.availability_matrix(
            organization_id=admin_user.organization_id,
            start_date=date(2026, 5, 10),
            end_date=date(2026, 5, 13),
        )
        days = _unit_days_map(matrix, unit_id=unit.id)
        assert days["2026-05-11"]["status"] == "reserved"


def test_availability_route_requires_admin_role(client, regular_user):
    _login(client, email=regular_user.email, password=regular_user.password_plain)
    response = client.get("/admin/availability", follow_redirects=False)
    assert response.status_code == 403
