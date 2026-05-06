from __future__ import annotations

from app.api.models import ApiKey
from app.extensions import db
from app.organizations.models import Organization
from app.properties.models import Property
from app.users.models import User, UserRole
from werkzeug.security import generate_password_hash


def _auth_headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def _create_org_user_and_key(*, scopes: str):
    org = Organization(name="Props Org")
    db.session.add(org)
    db.session.flush()
    user = User(
        email="props@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=org.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(user)
    db.session.flush()
    key, raw = ApiKey.issue(
        name="props-key",
        organization_id=org.id,
        user_id=user.id,
        scopes=scopes,
    )
    db.session.add(key)
    db.session.commit()
    return org, user, raw


def test_property_create_with_all_fields(client):
    _org, _user, raw = _create_org_user_and_key(scopes="properties:write,properties:read")
    payload = {
        "name": "Merikatu Homes",
        "address": "Merikatu 1, 00100 Helsinki",
        "city": "Helsinki",
        "postal_code": "00100",
        "street_address": "Merikatu 1",
        "latitude": "60.1675000",
        "longitude": "24.9421000",
        "year_built": 1998,
        "has_elevator": True,
        "has_parking": True,
        "has_sauna": True,
        "has_courtyard": False,
        "description": "Tilava kerrostalokohde meren vieressa.",
        "url": "https://example.test/merikatu",
    }
    response = client.post("/api/v1/properties", json=payload, headers=_auth_headers(raw))
    assert response.status_code == 201
    data = response.get_json()["data"]
    assert data["city"] == "Helsinki"
    assert data["postal_code"] == "00100"
    assert data["street_address"] == "Merikatu 1"
    assert data["latitude"] == "60.1675000"
    assert data["longitude"] == "24.9421000"
    assert data["year_built"] == 1998
    assert data["has_elevator"] is True
    assert data["has_parking"] is True
    assert data["has_sauna"] is True
    assert data["url"] == "https://example.test/merikatu"


def test_unit_with_features_serialized_correctly(client):
    org, _user, raw = _create_org_user_and_key(scopes="properties:write,properties:read")
    prop = Property(organization_id=org.id, name="Helsinki Flat")
    db.session.add(prop)
    db.session.commit()
    create = client.post(
        f"/api/v1/properties/{prop.id}/units",
        json={
            "name": "A12",
            "unit_type": "studio",
            "floor": 5,
            "area_sqm": "37.50",
            "bedrooms": 1,
            "has_kitchen": True,
            "has_bathroom": True,
            "has_balcony": True,
            "has_terrace": False,
            "has_dishwasher": True,
            "has_washing_machine": True,
            "has_tv": True,
            "has_wifi": True,
            "max_guests": 3,
            "description": "Valoisa studio.",
        },
        headers=_auth_headers(raw),
    )
    assert create.status_code == 201
    unit = create.get_json()["data"]
    assert unit["floor"] == 5
    assert unit["area_sqm"] == "37.50"
    assert unit["has_kitchen"] is True
    assert unit["has_balcony"] is True
    assert unit["has_dishwasher"] is True
    assert unit["has_wifi"] is True
    assert unit["max_guests"] == 3


def test_property_search_by_city(client):
    org, user, _raw = _create_org_user_and_key(scopes="properties:read")
    key, search_raw = ApiKey.issue(
        name="search-key",
        organization_id=org.id,
        user_id=user.id,
        scopes="search:read",
    )
    db.session.add(key)
    db.session.add(
        Property(
            organization_id=org.id,
            name="City Center",
            city="Helsinki",
            street_address="Mannerheimintie 1",
        )
    )
    db.session.commit()
    response = client.get("/api/v1/search?q=Helsinki", headers=_auth_headers(search_raw))
    assert response.status_code == 200
    matches = [row for row in response.get_json()["data"] if row["type"] == "property"]
    assert any(row["label"] == "City Center" for row in matches)


def test_unit_max_guests_validation(client):
    org, _user, raw = _create_org_user_and_key(scopes="properties:write,properties:read")
    prop = Property(organization_id=org.id, name="Guest Limit House")
    db.session.add(prop)
    db.session.commit()
    response = client.post(
        f"/api/v1/properties/{prop.id}/units",
        json={"name": "B1", "max_guests": 0},
        headers=_auth_headers(raw),
    )
    assert response.status_code == 400
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "validation_error"
