from __future__ import annotations

from decimal import Decimal

import pytest
import requests

from app.extensions import db
from app.integrations.geocoding import service as geocoding_service
from app.properties.models import Property


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _sample_digitransit_body() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [24.9384, 60.1699]},
                "properties": {
                    "label": "Mannerheimintie 1, Helsinki",
                    "name": "Mannerheimintie 1",
                    "street": "Mannerheimintie",
                    "housenumber": "1",
                    "postalcode": "00100",
                    "locality": "Helsinki",
                    "layer": "address",
                },
            }
        ],
    }


@pytest.fixture(autouse=True)
def _clear_geocoding_cache():
    geocoding_service._cache.clear()
    yield
    geocoding_service._cache.clear()


def test_suggest_addresses_parses_mock_http_response(app, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return _sample_digitransit_body()

    def fake_get(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr("app.integrations.geocoding.service.requests.get", fake_get)

    with app.app_context():
        app.config["GEOCODING_API_KEY"] = "test-key"
        app.config["GEOCODING_PROVIDER"] = "digitransit"
        results = geocoding_service.suggest_addresses("Manner", limit=5)

    assert len(results) == 1
    item = results[0]
    assert item["label"] == "Mannerheimintie 1, Helsinki"
    assert item["street"] == "Mannerheimintie 1"
    assert item["postal_code"] == "00100"
    assert item["city"] == "Helsinki"
    assert item["lat"] == pytest.approx(60.1699)
    assert item["lon"] == pytest.approx(24.9384)


def test_suggest_addresses_api_error_returns_empty_list(app, monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.exceptions.HTTPError("503")

    monkeypatch.setattr("app.integrations.geocoding.service.requests.get", fake_get)

    with app.app_context():
        app.config["GEOCODING_API_KEY"] = "test-key"
        results = geocoding_service.suggest_addresses("Helsinki", limit=5)

    assert results == []


def test_suggest_addresses_missing_api_key_returns_empty_list(app):
    with app.app_context():
        app.config["GEOCODING_API_KEY"] = ""
        results = geocoding_service.suggest_addresses("Helsinki", limit=5)

    assert results == []


def test_suggest_addresses_short_query_returns_empty_list(app):
    with app.app_context():
        app.config["GEOCODING_API_KEY"] = "test-key"
        assert geocoding_service.suggest_addresses("he", limit=5) == []


def test_address_suggest_endpoint_requires_login(client):
    response = client.get("/admin/api/address-suggest?q=Helsinki", follow_redirects=False)
    assert response.status_code in {302, 401, 403}


def test_address_suggest_endpoint_json_for_logged_in_admin(client, admin_user, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return _sample_digitransit_body()

    monkeypatch.setattr("app.integrations.geocoding.service.requests.get", lambda *a, **k: FakeResponse())

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/api/address-suggest?q=Manner")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["error"] is None
    assert isinstance(body["data"], list)
    assert body["data"][0]["street"] == "Mannerheimintie 1"


def test_property_form_renders_without_geocoding_config(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(
        organization_id=admin_user.organization_id,
        name="Autocomplete Kohde",
    )
    db.session.add(prop)
    db.session.commit()

    for path in (
        "/admin/properties/new",
        f"/admin/properties/{prop.id}/edit",
    ):
        response = client.get(path)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert 'name="street_address"' in html
        assert 'id="street_address"' in html
        assert 'data-address-input="street_address"' in html
        assert "admin-address-autocomplete.js" in html
        assert "GEOCODING_API_KEY" not in html
        assert "digitransit-subscription-key" not in html
        assert "data-address-suggest-url" in html


def test_property_edit_preserves_coordinates_without_autocomplete_change(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(
        organization_id=admin_user.organization_id,
        name="Coords Kohde",
        latitude=Decimal("60.1234567"),
        longitude=Decimal("24.7654321"),
    )
    db.session.add(prop)
    db.session.commit()

    response = client.post(
        f"/admin/properties/{prop.id}/edit",
        data={
            "name": "Coords Kohde päivitetty",
            "address": "Testikatu 1",
            "street_address": "Testikatu 1",
            "postal_code": "00100",
            "city": "Helsinki",
            "latitude": "60.1234567",
            "longitude": "24.7654321",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    db.session.refresh(prop)
    assert prop.name == "Coords Kohde päivitetty"
    assert prop.latitude == Decimal("60.1234567")
    assert prop.longitude == Decimal("24.7654321")
