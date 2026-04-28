"""Project brief section 12 — tenant isolation must be enforced server-side.

These tests deliberately use Org A's API key to attempt access to Org B's
records. Each resource type must respond with 404 (or 403) and never leak
the foreign row.
"""
from __future__ import annotations

from datetime import date, timedelta

from werkzeug.security import generate_password_hash


def _auth(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def _bootstrap_two_orgs():
    """Create two organizations, each with one user + one API key."""

    from app.api.models import ApiKey
    from app.extensions import db
    from app.organizations.models import Organization
    from app.users.models import User, UserRole

    def _make(name: str, email: str):
        org = Organization(name=name)
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
            name=f"{name} key",
            organization_id=org.id,
            user_id=user.id,
            scopes="",
        )
        db.session.add(key)
        return org, user, raw

    org_a, _user_a, raw_a = _make("Org A", "orga@iso.test")
    org_b, _user_b, raw_b = _make("Org B", "orgb@iso.test")
    db.session.commit()
    return org_a, raw_a, org_b, raw_b


def _seed_property_and_unit(org_id: int):
    """Create one property + one unit owned by ``org_id``. Returns ``(prop, unit)``."""

    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(organization_id=org_id, name=f"Prop {org_id}", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name=f"Unit {org_id}")
    db.session.add(unit)
    db.session.commit()
    return prop, unit


def test_property_get_returns_404_across_tenant(client):
    org_a, raw_a, org_b, _raw_b = _bootstrap_two_orgs()
    prop_b, _unit_b = _seed_property_and_unit(org_b.id)

    response = client.get(f"/api/v1/properties/{prop_b.id}", headers=_auth(raw_a))
    assert response.status_code == 404
    payload = response.get_json()
    assert payload["success"] is False
    # Ensure the foreign property name is not leaked anywhere in the body.
    assert prop_b.name not in (payload.get("error") or {}).get("message", "")


def test_property_list_does_not_leak_other_tenant(client):
    org_a, raw_a, org_b, _raw_b = _bootstrap_two_orgs()
    _seed_property_and_unit(org_a.id)
    _seed_property_and_unit(org_b.id)

    response = client.get("/api/v1/properties", headers=_auth(raw_a))
    assert response.status_code == 200
    names = {row["name"] for row in response.get_json()["data"]}
    assert names == {f"Prop {org_a.id}"}


def test_units_under_other_tenants_property_404(client):
    org_a, raw_a, org_b, _raw_b = _bootstrap_two_orgs()
    prop_b, _unit_b = _seed_property_and_unit(org_b.id)

    response = client.get(
        f"/api/v1/properties/{prop_b.id}/units",
        headers=_auth(raw_a),
    )
    assert response.status_code == 404


def test_create_unit_under_other_tenants_property_blocked(client):
    org_a, raw_a, org_b, _raw_b = _bootstrap_two_orgs()
    prop_b, _unit_b = _seed_property_and_unit(org_b.id)

    response = client.post(
        f"/api/v1/properties/{prop_b.id}/units",
        json={"name": "Smuggled"},
        headers=_auth(raw_a),
    )
    assert response.status_code == 404


def test_reservation_get_returns_404_across_tenant(client):
    from app.extensions import db
    from app.reservations.models import Reservation

    org_a, raw_a, org_b, _raw_b = _bootstrap_two_orgs()
    _prop_b, unit_b = _seed_property_and_unit(org_b.id)

    res_b = Reservation(
        unit_id=unit_b.id,
        guest_name="Foreign Guest",
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=3),
    )
    db.session.add(res_b)
    db.session.commit()

    response = client.get(
        f"/api/v1/reservations/{res_b.id}",
        headers=_auth(raw_a),
    )
    assert response.status_code == 404


def test_reservation_cancel_blocked_across_tenant(client):
    from app.extensions import db
    from app.reservations.models import Reservation

    org_a, raw_a, org_b, _raw_b = _bootstrap_two_orgs()
    _prop_b, unit_b = _seed_property_and_unit(org_b.id)

    res_b = Reservation(
        unit_id=unit_b.id,
        guest_name="Foreign Guest",
        start_date=date.today() + timedelta(days=1),
        end_date=date.today() + timedelta(days=3),
    )
    db.session.add(res_b)
    db.session.commit()

    response = client.patch(
        f"/api/v1/reservations/{res_b.id}/cancel",
        headers=_auth(raw_a),
    )
    assert response.status_code in (403, 404)


def test_invoice_get_blocked_across_tenant(client):
    from app.billing.models import Invoice
    from app.extensions import db
    from app.users.models import User

    org_a, raw_a, org_b, _raw_b = _bootstrap_two_orgs()

    creator_b = User.query.filter_by(organization_id=org_b.id).first()
    assert creator_b is not None

    inv_b = Invoice(
        organization_id=org_b.id,
        invoice_number=f"BIL-{org_b.id}-0001",
        amount=100,
        currency="EUR",
        due_date=date.today() + timedelta(days=14),
        status="draft",
        created_by_id=creator_b.id,
    )
    db.session.add(inv_b)
    db.session.commit()

    response = client.get(
        f"/api/v1/invoices/{inv_b.id}",
        headers=_auth(raw_a),
    )
    assert response.status_code == 404


def test_maintenance_request_get_blocked_across_tenant(client):
    from app.extensions import db
    from app.maintenance.models import MaintenanceRequest
    from app.users.models import User

    org_a, raw_a, org_b, _raw_b = _bootstrap_two_orgs()
    prop_b, _unit_b = _seed_property_and_unit(org_b.id)

    creator_b = User.query.filter_by(organization_id=org_b.id).first()
    assert creator_b is not None

    mr = MaintenanceRequest(
        organization_id=org_b.id,
        property_id=prop_b.id,
        title="Foreign issue",
        description="leaky tap",
        priority="normal",
        status="new",
        created_by_id=creator_b.id,
    )
    db.session.add(mr)
    db.session.commit()

    response = client.get(
        f"/api/v1/maintenance-requests/{mr.id}",
        headers=_auth(raw_a),
    )
    assert response.status_code == 404


def test_api_key_only_authenticates_against_own_org_resources(client):
    """A forged Bearer header that doesn't match any active key is 401."""

    response = client.get(
        "/api/v1/properties",
        headers={"Authorization": "Bearer pms_not_a_real_key"},
    )
    assert response.status_code == 401
    assert response.get_json()["success"] is False
