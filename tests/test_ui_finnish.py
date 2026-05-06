from __future__ import annotations

from app.extensions import db
from app.maintenance.models import MaintenanceRequest
from app.properties.models import Property, Unit


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _seed_property_and_unit(admin_user):
    prop = Property(organization_id=admin_user.organization_id, name="Kielitesti", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A1", unit_type="double")
    db.session.add(unit)
    db.session.commit()
    return prop, unit


def test_admin_pages_have_finnish_buttons(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, unit = _seed_property_and_unit(admin_user)

    row = MaintenanceRequest(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="Vuotava hana",
        description="Kylpyhuoneessa vuotaa.",
        status="new",
        priority="normal",
        assigned_to_id=None,
        due_date=None,
        resolved_at=None,
        created_by_id=admin_user.id,
    )
    db.session.add(row)
    db.session.commit()

    urls = [
        "/admin/maintenance-requests",
        "/admin/maintenance-requests/new",
        f"/admin/maintenance-requests/{row.id}",
        f"/admin/maintenance-requests/{row.id}/edit",
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Save" not in html
        assert "Cancel" not in html
        assert "Delete" not in html
        assert "Edit" not in html
        assert "Create" not in html
        assert "Submit" not in html


def test_maintenance_priority_dropdown_in_finnish(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    _seed_property_and_unit(admin_user)

    response = client.get("/admin/maintenance-requests/new")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '<option value="low"' in html and ">Matala</option>" in html
    assert '<option value="normal"' in html and ">Normaali</option>" in html
    assert '<option value="high"' in html and ">Korkea</option>" in html
    assert '<option value="urgent"' in html and ">Kiireellinen</option>" in html
    assert "value=\"Matala\"" not in html


def test_calendar_sync_page_does_not_500(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/calendar-sync/conflicts")
    assert response.status_code == 200
