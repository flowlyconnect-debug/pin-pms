"""Maintenance requests (work orders) — model, service, API, admin, audit."""

from __future__ import annotations

import pytest
from werkzeug.security import generate_password_hash


def _auth_headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _portal_login(client, *, email: str, password: str):
    return client.post("/portal/login", data={"email": email, "password": password})


@pytest.fixture
def maintenance_api_key(regular_user):
    from app.api.models import ApiKey
    from app.extensions import db

    key, raw = ApiKey.issue(
        name="Maintenance API key",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes="maintenance:read,maintenance:write",
    )
    db.session.add(key)
    db.session.commit()
    key.raw = raw
    return key


def _property_and_unit(*, organization_id: int):
    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(organization_id=organization_id, name="Maint Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()
    return prop, unit


def test_maintenance_request_model_persists(app, organization, admin_user):
    from app.extensions import db
    from app.maintenance.models import MaintenanceRequest

    _property_and_unit(organization_id=organization.id)
    from app.properties.models import Property, Unit

    prop = Property.query.filter_by(organization_id=organization.id).first()
    unit = Unit.query.filter_by(property_id=prop.id).first()

    row = MaintenanceRequest(
        organization_id=organization.id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="Leaky faucet",
        description="Kitchen sink",
        status="new",
        priority="high",
        assigned_to_id=None,
        due_date=None,
        resolved_at=None,
        created_by_id=admin_user.id,
    )
    db.session.add(row)
    db.session.commit()

    loaded = MaintenanceRequest.query.get(row.id)
    assert loaded is not None
    assert loaded.title == "Leaky faucet"
    assert loaded.status == "new"
    assert loaded.priority == "high"
    assert loaded.organization_id == organization.id


def test_maintenance_service_create_and_status_and_audit(app, organization, admin_user):
    from app.audit.models import AuditLog
    from app.maintenance import services as maintenance_service

    _property_and_unit(organization_id=organization.id)
    from app.properties.models import Property, Unit

    prop = Property.query.filter_by(organization_id=organization.id).first()
    unit = Unit.query.filter_by(property_id=prop.id).first()

    row = maintenance_service.create_maintenance_request(
        organization_id=organization.id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="HVAC noise",
        description=None,
        priority="normal",
        status="new",
        due_date_raw=None,
        assigned_to_id=None,
        actor_user_id=admin_user.id,
    )
    assert row["id"] > 0
    assert row["status"] == "new"

    log = (
        AuditLog.query.filter_by(
            action="maintenance_request.created",
            target_type="maintenance_request",
            target_id=row["id"],
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert log is not None

    updated = maintenance_service.update_maintenance_request(
        organization_id=organization.id,
        request_id=row["id"],
        data={"status": "in_progress"},
        actor_user_id=admin_user.id,
    )
    assert updated["status"] == "in_progress"

    status_log = (
        AuditLog.query.filter_by(
            action="maintenance_request.status_changed",
            target_id=row["id"],
        )
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert status_log is not None
    assert status_log.context.get("to_status") == "in_progress"


def test_maintenance_tenant_isolation(app, organization, admin_user):
    from app.extensions import db
    from app.maintenance import services as maintenance_service
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.users.models import User, UserRole

    _property_and_unit(organization_id=organization.id)
    prop = Property.query.filter_by(organization_id=organization.id).first()
    unit = Unit.query.filter_by(property_id=prop.id).first()

    row = maintenance_service.create_maintenance_request(
        organization_id=organization.id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="Our issue",
        description=None,
        priority="low",
        status="new",
        due_date_raw=None,
        assigned_to_id=None,
        actor_user_id=admin_user.id,
    )

    other = Organization(name="Other Org Maint")
    db.session.add(other)
    db.session.flush()
    u2 = User(
        email="othermaint@test.local",
        password_hash=generate_password_hash("x"),
        organization_id=other.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(u2)
    db.session.commit()

    with pytest.raises(maintenance_service.MaintenanceServiceError) as exc:
        maintenance_service.get_maintenance_request(
            organization_id=other.id,
            request_id=row["id"],
        )
    assert exc.value.status == 404


def test_maintenance_admin_list_forbidden_for_regular_user(client, regular_user):
    client.post(
        "/login",
        data={"email": regular_user.email, "password": regular_user.password_plain},
    )
    response = client.get("/admin/maintenance-requests", follow_redirects=False)
    assert response.status_code == 403


def test_maintenance_admin_list_ok_for_admin(client, admin_user):
    client.post(
        "/login",
        data={"email": admin_user.email, "password": admin_user.password_plain},
    )
    response = client.get("/admin/maintenance-requests")
    assert response.status_code == 200


def test_maintenance_api_requires_auth(client):
    response = client.get("/api/v1/maintenance-requests?page=1&per_page=5")
    assert response.status_code == 401


def test_maintenance_api_crud_and_resolve_cancel(app, organization, maintenance_api_key):
    from app.extensions import db
    from app.properties.models import Property, Unit

    _property_and_unit(organization_id=organization.id)
    prop = Property.query.filter_by(organization_id=organization.id).first()
    unit = Unit.query.filter_by(property_id=prop.id).first()

    app_client = app.test_client()
    headers = _auth_headers(maintenance_api_key.raw)

    create_body = {
        "property_id": prop.id,
        "unit_id": unit.id,
        "title": "API maintenance",
        "description": "From test",
        "priority": "urgent",
        "status": "waiting",
    }
    r = app_client.post(
        "/api/v1/maintenance-requests",
        json=create_body,
        headers=headers,
    )
    assert r.status_code == 201, r.get_json()
    rid = r.get_json()["data"]["id"]

    r2 = app_client.get(f"/api/v1/maintenance-requests/{rid}", headers=headers)
    assert r2.status_code == 200
    assert r2.get_json()["data"]["title"] == "API maintenance"

    r3 = app_client.patch(
        f"/api/v1/maintenance-requests/{rid}",
        json={"status": "in_progress"},
        headers=headers,
    )
    assert r3.status_code == 200
    assert r3.get_json()["data"]["status"] == "in_progress"

    r4 = app_client.post(
        f"/api/v1/maintenance-requests/{rid}/resolve",
        headers=headers,
    )
    assert r4.status_code == 200
    assert r4.get_json()["data"]["status"] == "resolved"
    assert r4.get_json()["data"]["resolved_at"] is not None

    # second resolve fails
    r5 = app_client.post(
        f"/api/v1/maintenance-requests/{rid}/resolve",
        headers=headers,
    )
    assert r5.status_code == 400

    # new row for cancel test
    r_new = app_client.post(
        "/api/v1/maintenance-requests",
        json={
            "property_id": prop.id,
            "title": "To cancel",
            "priority": "normal",
            "status": "new",
        },
        headers=headers,
    )
    rid2 = r_new.get_json()["data"]["id"]
    r6 = app_client.post(
        f"/api/v1/maintenance-requests/{rid2}/cancel",
        headers=headers,
    )
    assert r6.status_code == 200
    assert r6.get_json()["data"]["status"] == "cancelled"
    db.session.remove()


def test_maintenance_api_unlinked_key_cannot_create(app, organization):
    from app.api.models import ApiKey
    from app.extensions import db
    from app.properties.models import Property

    _property_and_unit(organization_id=organization.id)
    prop = Property.query.filter_by(organization_id=organization.id).first()

    key, raw = ApiKey.issue(
        name="No user key",
        organization_id=organization.id,
        user_id=None,
        scopes="maintenance:write",
    )
    db.session.add(key)
    db.session.commit()

    app_client = app.test_client()
    r = app_client.post(
        "/api/v1/maintenance-requests",
        json={"property_id": prop.id, "title": "x"},
        headers=_auth_headers(raw),
    )
    assert r.status_code == 400


def test_maintenance_list_renders_priority_in_finnish(client, admin_user):
    from app.extensions import db
    from app.maintenance.models import MaintenanceRequest

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, unit = _property_and_unit(organization_id=admin_user.organization_id)

    rows = [
        ("Pyynto matala", "low"),
        ("Pyynto normaali", "normal"),
        ("Pyynto korkea", "high"),
        ("Pyynto kiireellinen", "urgent"),
    ]
    for title, priority in rows:
        db.session.add(
            MaintenanceRequest(
                organization_id=admin_user.organization_id,
                property_id=prop.id,
                unit_id=unit.id,
                guest_id=None,
                reservation_id=None,
                title=title,
                description=None,
                status="new",
                priority=priority,
                assigned_to_id=None,
                due_date=None,
                resolved_at=None,
                created_by_id=admin_user.id,
            )
        )
    db.session.commit()

    response = client.get("/admin/maintenance-requests")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Matala" in html
    assert "Normaali" in html
    assert "Korkea" in html
    assert "Kiireellinen" in html
    # Avoid false negatives from option value attributes in filters.
    assert ">low<" not in html
    assert ">normal<" not in html
    assert ">high<" not in html
    assert ">urgent<" not in html


def test_maintenance_create_form_submits_with_finnish_label_value(client, admin_user):
    from app.maintenance.models import MaintenanceRequest

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, unit = _property_and_unit(organization_id=admin_user.organization_id)

    ok_resp = client.post(
        "/admin/maintenance-requests/new",
        data={
            "property_id": str(prop.id),
            "unit_id": str(unit.id),
            "guest_id": "",
            "reservation_id": "",
            "title": "Valid raw priority",
            "description": "",
            "priority": "high",
            "status": "new",
            "due_date": "",
            "assigned_to_id": "",
        },
        follow_redirects=True,
    )
    assert ok_resp.status_code == 200
    good_row = MaintenanceRequest.query.filter_by(
        organization_id=admin_user.organization_id,
        title="Valid raw priority",
    ).first()
    assert good_row is not None
    assert good_row.priority == "high"
    assert good_row.priority_label == "Korkea"
    assert "Korkea" in ok_resp.get_data(as_text=True)

    bad_resp = client.post(
        "/admin/maintenance-requests/new",
        data={
            "property_id": str(prop.id),
            "unit_id": str(unit.id),
            "guest_id": "",
            "reservation_id": "",
            "title": "Invalid localized priority",
            "description": "",
            "priority": "Korkea",
            "status": "new",
            "due_date": "",
            "assigned_to_id": "",
        },
        follow_redirects=False,
    )
    assert bad_resp.status_code == 200
    assert b"priority must be one of" in bad_resp.data
    bad_row = MaintenanceRequest.query.filter_by(
        organization_id=admin_user.organization_id,
        title="Invalid localized priority",
    ).first()
    assert bad_row is None


def test_priority_label_for_unknown_value_returns_dash(app, organization, admin_user):
    from app.extensions import db
    from app.maintenance.models import MaintenanceRequest

    prop, _ = _property_and_unit(organization_id=organization.id)
    row = MaintenanceRequest(
        organization_id=organization.id,
        property_id=prop.id,
        unit_id=None,
        guest_id=None,
        reservation_id=None,
        title="Unknown priority label",
        description=None,
        status="new",
        priority="weird",
        assigned_to_id=None,
        due_date=None,
        resolved_at=None,
        created_by_id=admin_user.id,
    )
    db.session.add(row)
    db.session.commit()
    assert row.priority_label == "-"


def test_portal_maintenance_renders_only_own_requests_and_priority_in_finnish(client, regular_user):
    from app.extensions import db
    from app.maintenance.models import MaintenanceRequest
    from app.properties.models import Property
    from app.users.models import User, UserRole

    _portal_login(client, email=regular_user.email, password=regular_user.password_plain)

    prop = Property(organization_id=regular_user.organization_id, name="Portal Maint Prop", address=None)
    db.session.add(prop)
    db.session.flush()

    other_user = User(
        email="portal-maint-other@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=regular_user.organization_id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()

    own_row = MaintenanceRequest(
        organization_id=regular_user.organization_id,
        property_id=prop.id,
        unit_id=None,
        guest_id=regular_user.id,
        reservation_id=None,
        title="Oma huolto",
        description=None,
        status="new",
        priority="high",
        assigned_to_id=None,
        due_date=None,
        resolved_at=None,
        created_by_id=regular_user.id,
    )
    other_row = MaintenanceRequest(
        organization_id=regular_user.organization_id,
        property_id=prop.id,
        unit_id=None,
        guest_id=other_user.id,
        reservation_id=None,
        title="Toisen huolto",
        description=None,
        status="new",
        priority="urgent",
        assigned_to_id=None,
        due_date=None,
        resolved_at=None,
        created_by_id=other_user.id,
    )
    db.session.add(own_row)
    db.session.add(other_row)
    db.session.commit()

    page = client.get("/portal/maintenance")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Oma huolto" in html
    assert "Toisen huolto" not in html
    assert "Korkea" in html
