from __future__ import annotations

from datetime import date

from werkzeug.security import generate_password_hash

DEFAULT_TEST_API_SCOPES = ",".join(
    [
        "reservations:read",
        "reservations:write",
        "invoices:read",
        "invoices:write",
        "guests:read",
        "guests:write",
        "properties:read",
        "properties:write",
        "maintenance:read",
        "maintenance:write",
        "reports:read",
    ]
)


def _auth_headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def _create_org_user_and_key(*, org_name: str, email: str):
    from app.api.models import ApiKey
    from app.extensions import db
    from app.organizations.models import Organization
    from app.users.models import User, UserRole

    org = Organization(name=org_name)
    db.session.add(org)
    db.session.flush()

    user = User(
        email=email,
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=org.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()

    key, raw = ApiKey.issue(
        name=f"{org_name} key",
        organization_id=org.id,
        user_id=user.id,
        scopes=DEFAULT_TEST_API_SCOPES,
    )
    db.session.add(key)
    db.session.commit()
    return org, user, key, raw


def test_create_property(client):
    _org, _user, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="orga@test.local",
    )

    response = client.post(
        "/api/v1/properties",
        json={"name": "Hotel One", "address": "Main Street 1"},
        headers=_auth_headers(raw),
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["name"] == "Hotel One"
    assert payload["data"]["address"] == "Main Street 1"


def test_list_only_own_org_properties(client):
    from app.extensions import db
    from app.properties.models import Property

    org_a, _user_a, _key_a, raw_a = _create_org_user_and_key(
        org_name="Org A",
        email="orga@test.local",
    )
    org_b, _user_b, _key_b, _raw_b = _create_org_user_and_key(
        org_name="Org B",
        email="orgb@test.local",
    )

    db.session.add(Property(organization_id=org_a.id, name="A Property", address=None))
    db.session.add(Property(organization_id=org_b.id, name="B Property", address=None))
    db.session.commit()

    response = client.get("/api/v1/properties", headers=_auth_headers(raw_a))
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["meta"]["page"] == 1
    assert payload["meta"]["per_page"] == 20
    assert payload["meta"]["total"] == 1
    names = [row["name"] for row in payload["data"]]
    assert names == ["A Property"]


def test_create_unit(client):
    from app.extensions import db
    from app.properties.models import Property

    org, _user, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="orga@test.local",
    )

    prop = Property(organization_id=org.id, name="Hotel One", address=None)
    db.session.add(prop)
    db.session.commit()

    response = client.post(
        f"/api/v1/properties/{prop.id}/units",
        json={"name": "101", "unit_type": "double"},
        headers=_auth_headers(raw),
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["property_id"] == prop.id
    assert payload["data"]["name"] == "101"


def test_create_reservation(client):
    from app.extensions import db
    from app.properties.models import Property, Unit

    org, guest, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="guest@test.local",
    )

    prop = Property(organization_id=org.id, name="Hotel One", address=None)
    db.session.add(prop)
    db.session.flush()

    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    response = client.post(
        "/api/v1/reservations",
        json={
            "unit_id": unit.id,
            "guest_id": guest.id,
            "start_date": "2026-05-01",
            "end_date": "2026-05-03",
        },
        headers=_auth_headers(raw),
    )

    assert response.status_code == 201
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["unit_id"] == unit.id
    assert payload["data"]["guest_id"] == guest.id
    assert payload["data"]["status"] == "confirmed"


def test_reservation_requires_start_date_before_end_date(client):
    from app.extensions import db
    from app.properties.models import Property, Unit

    org, guest, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="guest@test.local",
    )
    prop = Property(organization_id=org.id, name="Hotel One", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    response = client.post(
        "/api/v1/reservations",
        json={
            "unit_id": unit.id,
            "guest_id": guest.id,
            "start_date": "2026-05-03",
            "end_date": "2026-05-03",
        },
        headers=_auth_headers(raw),
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "validation_error"


def test_prevent_overlapping_reservations_for_same_unit(client):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    org, guest, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="guest@test.local",
    )
    prop = Property(organization_id=org.id, name="Hotel One", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    existing = Reservation(
        unit_id=unit.id,
        guest_id=guest.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 5),
        status="confirmed",
    )
    db.session.add(existing)
    db.session.commit()

    response = client.post(
        "/api/v1/reservations",
        json={
            "unit_id": unit.id,
            "guest_id": guest.id,
            "start_date": "2026-05-03",
            "end_date": "2026-05-06",
        },
        headers=_auth_headers(raw),
    )

    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "validation_error"


def test_prevent_access_to_other_organization_data(client):
    from app.extensions import db
    from app.properties.models import Property

    org_a, _user_a, _key_a, raw_a = _create_org_user_and_key(
        org_name="Org A",
        email="orga@test.local",
    )
    org_b, _user_b, _key_b, _raw_b = _create_org_user_and_key(
        org_name="Org B",
        email="orgb@test.local",
    )

    prop_a = Property(organization_id=org_a.id, name="A Property", address=None)
    prop_b = Property(organization_id=org_b.id, name="B Property", address=None)
    db.session.add(prop_a)
    db.session.add(prop_b)
    db.session.commit()

    forbidden_read = client.get(f"/api/v1/properties/{prop_b.id}", headers=_auth_headers(raw_a))
    assert forbidden_read.status_code == 404
    assert forbidden_read.get_json()["success"] is False

    own_read = client.get(f"/api/v1/properties/{prop_a.id}", headers=_auth_headers(raw_a))
    assert own_read.status_code == 200
    assert own_read.get_json()["success"] is True


def test_cancel_reservation(client):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    org, guest, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="guest@test.local",
    )

    prop = Property(organization_id=org.id, name="Hotel One", address=None)
    db.session.add(prop)
    db.session.flush()

    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.flush()

    reservation = Reservation(
        unit_id=unit.id,
        guest_id=guest.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()

    response = client.patch(
        f"/api/v1/reservations/{reservation.id}/cancel",
        headers=_auth_headers(raw),
    )
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["success"] is True
    assert payload["data"]["id"] == reservation.id
    assert payload["data"]["status"] == "cancelled"

    second = client.patch(
        f"/api/v1/reservations/{reservation.id}/cancel",
        headers=_auth_headers(raw),
    )
    assert second.status_code == 200
    assert second.get_json()["data"]["status"] == "cancelled"


def test_reservations_list_returns_pagination_meta(client):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    org, guest, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="guest@test.local",
    )
    prop = Property(organization_id=org.id, name="Hotel One", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_id=guest.id,
            start_date=date(2026, 5, 1),
            end_date=date(2026, 5, 3),
            status="confirmed",
        )
    )
    db.session.commit()

    response = client.get("/api/v1/reservations?page=1&per_page=10", headers=_auth_headers(raw))
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["meta"] == {"page": 1, "per_page": 10, "total": 1}


def test_audit_log_created_on_reservation(client):
    from app.audit.models import AuditLog
    from app.extensions import db
    from app.properties.models import Property, Unit

    org, guest, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="guest@test.local",
    )

    prop = Property(organization_id=org.id, name="Hotel One", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    create_response = client.post(
        "/api/v1/reservations",
        json={
            "unit_id": unit.id,
            "guest_id": guest.id,
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
        },
        headers=_auth_headers(raw),
    )
    assert create_response.status_code == 201
    reservation_id = create_response.get_json()["data"]["id"]

    row = AuditLog.query.filter_by(action="reservation_created", target_id=reservation_id).first()
    assert row is not None
    assert row.target_type == "reservation"
    assert row.actor_id == guest.id


def test_audit_log_created_on_property_create(client):
    from app.audit.models import AuditLog

    _org, user, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="orga@test.local",
    )

    response = client.post(
        "/api/v1/properties",
        json={"name": "Hotel One", "address": "Main Street 1"},
        headers=_auth_headers(raw),
    )
    assert response.status_code == 201
    property_id = response.get_json()["data"]["id"]

    row = AuditLog.query.filter_by(action="property_created", target_id=property_id).first()
    assert row is not None
    assert row.target_type == "property"
    assert row.actor_id == user.id


def test_audit_log_created_on_unit_create(client):
    from app.audit.models import AuditLog
    from app.extensions import db
    from app.properties.models import Property

    org, user, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="orga@test.local",
    )

    prop = Property(organization_id=org.id, name="Hotel One", address=None)
    db.session.add(prop)
    db.session.commit()

    response = client.post(
        f"/api/v1/properties/{prop.id}/units",
        json={"name": "101", "unit_type": "double"},
        headers=_auth_headers(raw),
    )
    assert response.status_code == 201
    unit_id = response.get_json()["data"]["id"]

    row = AuditLog.query.filter_by(action="unit_created", target_id=unit_id).first()
    assert row is not None
    assert row.target_type == "unit"
    assert row.actor_id == user.id


def test_email_service_called_on_reservation_create_and_cancel(client, monkeypatch):
    from app.email.models import TemplateKey
    from app.extensions import db
    from app.properties.models import Property, Unit

    org, guest, _key, raw = _create_org_user_and_key(
        org_name="Org A",
        email="guest@test.local",
    )

    prop = Property(organization_id=org.id, name="Hotel One", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    sent_calls: list[tuple[str, str, dict]] = []

    def _fake_send_template(key: str, *, to: str, context: dict | None = None) -> bool:
        sent_calls.append((key, to, context or {}))
        return True

    monkeypatch.setattr("app.reservations.services.send_template", _fake_send_template)

    create_response = client.post(
        "/api/v1/reservations",
        json={
            "unit_id": unit.id,
            "guest_id": guest.id,
            "start_date": "2026-06-01",
            "end_date": "2026-06-02",
        },
        headers=_auth_headers(raw),
    )
    assert create_response.status_code == 201
    reservation_id = create_response.get_json()["data"]["id"]

    cancel_response = client.patch(
        f"/api/v1/reservations/{reservation_id}/cancel",
        headers=_auth_headers(raw),
    )
    assert cancel_response.status_code == 200

    assert len(sent_calls) == 2
    assert sent_calls[0][0] == TemplateKey.RESERVATION_CONFIRMATION
    assert sent_calls[1][0] == TemplateKey.RESERVATION_CANCELLED
    assert sent_calls[0][1] == guest.email
    assert sent_calls[1][1] == guest.email
    assert sent_calls[0][2]["reservation_id"] == reservation_id
    assert sent_calls[1][2]["reservation_id"] == reservation_id
