from __future__ import annotations


def _auth_headers(raw: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw}"}


def test_search_returns_only_own_org_results(app, client, organization, regular_user):
    from app.api.models import ApiKey
    from app.extensions import db
    from app.guests.models import Guest
    from app.organizations.models import Organization

    org_b = Organization(name="Org B")
    db.session.add(org_b)
    db.session.flush()
    guest_a = Guest(
        organization_id=organization.id, first_name="Matti", last_name="Meika", email="a@test"
    )
    guest_b = Guest(organization_id=org_b.id, first_name="Matti", last_name="Other", email="b@test")
    db.session.add_all([guest_a, guest_b])
    key, raw = ApiKey.issue(
        name="search",
        organization_id=organization.id,
        user_id=regular_user.id,
        scopes="search:read",
    )
    db.session.add(key)
    db.session.commit()

    rv = client.get("/api/v1/search?q=Matti", headers=_auth_headers(raw))
    assert rv.status_code == 200
    data = rv.get_json()["data"]
    assert all(item["id"] != guest_b.id for item in data)


def test_search_includes_all_resource_types(app, client, organization, regular_user):
    from datetime import date, timedelta

    from app.api.models import ApiKey
    from app.billing.models import Invoice
    from app.extensions import db
    from app.guests.models import Guest
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    guest = Guest(
        organization_id=organization.id, first_name="Matti", last_name="Meika", email="matti@test"
    )
    prop = Property(organization_id=organization.id, name="Matti House")
    db.session.add_all([guest, prop])
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A1")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=guest.id,
        guest_name="Matti",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=1),
        status="confirmed",
    )
    db.session.add(res)
    db.session.flush()
    inv = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=res.id,
        guest_id=guest.id,
        invoice_number="MATTI-1",
        amount=10,
        subtotal_excl_vat=10,
        total_incl_vat=10,
        vat_rate=0,
        vat_amount=0,
        currency="EUR",
        due_date=date.today(),
        status="open",
        created_by_id=regular_user.id,
    )
    db.session.add(inv)
    key, raw = ApiKey.issue(
        name="search",
        organization_id=organization.id,
        user_id=regular_user.id,
        scopes="search:read",
    )
    db.session.add(key)
    db.session.commit()

    rv = client.get("/api/v1/search?q=Matti", headers=_auth_headers(raw))
    assert rv.status_code == 200
    types = {x["type"] for x in rv.get_json()["data"]}
    assert {"guest", "reservation", "property", "invoice"}.issubset(types)


def test_search_requires_login(client):
    rv = client.get("/api/v1/search?q=test")
    assert rv.status_code == 401


def test_search_handles_empty_query(client, api_key):
    from app.api.models import ApiKey
    from app.extensions import db

    key, raw = ApiKey.issue(
        name="search-empty",
        organization_id=api_key.organization_id,
        user_id=api_key.user_id,
        scopes="search:read",
    )
    db.session.add(key)
    db.session.commit()
    rv = client.get("/api/v1/search?q=", headers=_auth_headers(raw))
    assert rv.status_code == 200
    payload = rv.get_json()
    assert payload["success"] is True
    assert payload["data"] == []
