from __future__ import annotations

from decimal import Decimal
from pathlib import Path

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
        status_code = 200
        text = '{"type":"FeatureCollection","features":[]}'

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
        app.config["GEOCODING_DEV_FALLBACK"] = False
        results = geocoding_service.suggest_addresses("Helsinki", limit=5)

    assert results == []


def test_dev_fallback_valtion_without_api_key(app):
    with app.app_context():
        app.config["GEOCODING_API_KEY"] = ""
        app.config["GEOCODING_DEV_FALLBACK"] = True
        results = geocoding_service.suggest_addresses("Valtion", limit=5)

    assert len(results) == 1
    assert results[0]["street"] == "Valtiontie 1"
    assert results[0]["city"] == "Ilmajoki"


def test_dev_fallback_valtio_prefix_without_api_key(app):
    with app.app_context():
        app.config["GEOCODING_API_KEY"] = ""
        app.config["GEOCODING_DEV_FALLBACK"] = True
        results = geocoding_service.suggest_addresses("Valtio", limit=5)

    assert len(results) == 1
    assert "Ilmajoki" in results[0]["label"]


def test_dev_fallback_valtion_when_digitransit_returns_no_features(app, monkeypatch):
    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        @property
        def text(self):
            return '{"type":"FeatureCollection","features":[]}'

        def json(self):
            return {"type": "FeatureCollection", "features": []}

    monkeypatch.setattr(
        "app.integrations.geocoding.service.requests.get",
        lambda *a, **k: FakeResponse(),
    )

    with app.app_context():
        app.config["GEOCODING_API_KEY"] = "test-key"
        app.config["GEOCODING_DEV_FALLBACK"] = True
        results = geocoding_service.suggest_addresses("Valtion", limit=5)

    assert len(results) == 1
    assert "Ilmajoki" in results[0]["label"]


def test_digitransit_request_uses_subscription_key_header(app, monkeypatch):
    captured: dict = {}

    class FakeResponse:
        status_code = 200
        text = '{"type":"FeatureCollection","features":[]}'

        def raise_for_status(self):
            return None

        def json(self):
            return _sample_digitransit_body()

    def fake_get(url, *args, **kwargs):
        captured["url"] = url
        captured["headers"] = kwargs.get("headers") or {}
        captured["params"] = kwargs.get("params") or {}
        return FakeResponse()

    monkeypatch.setattr("app.integrations.geocoding.service.requests.get", fake_get)

    with app.app_context():
        app.config["GEOCODING_API_KEY"] = "my-secret-digitransit-key"
        geocoding_service.suggest_addresses("Manner", limit=3)

    assert captured["headers"]["digitransit-subscription-key"] == "my-secret-digitransit-key"
    assert captured["params"]["layers"] == "address,street"
    assert "autocomplete" in captured["url"]


def test_parses_pelias_name_only_address_feature(app):
    """Digitransit often returns combined street+number in name, not separate street fields."""
    body = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [24.9384, 60.1699]},
                "properties": {
                    "label": "Mannerheimintie 1, 00100 Helsinki",
                    "name": "Mannerheimintie 1",
                    "postalcode": 100,
                    "locality": "Helsinki",
                    "layer": "address",
                    "source": "openaddresses",
                },
            }
        ],
    }
    with app.app_context():
        parsed = geocoding_service._parse_digitransit_features(body["features"], limit=5)

    assert len(parsed) == 1
    assert parsed[0]["street"] == "Mannerheimintie 1"
    assert parsed[0]["postal_code"] == "00100"
    assert parsed[0]["city"] == "Helsinki"
    assert parsed[0]["label"] == "Mannerheimintie 1, 00100 Helsinki"


def test_parses_address_parts_nested_properties(app):
    feature = {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [22.5744, 62.7335]},
        "properties": {
            "label": "Valtiontie 1, 60800 Ilmajoki",
            "name": "Valtiontie 1",
            "layer": "address",
            "locality": "Ilmajoki",
            "address_parts": {
                "street": "Valtiontie",
                "number": "1",
                "zip": "60800",
            },
        },
    }
    with app.app_context():
        parsed = geocoding_service._parse_digitransit_feature(feature)

    assert parsed is not None
    assert parsed["street"] == "Valtiontie 1"
    assert parsed["postal_code"] == "60800"
    assert parsed["city"] == "Ilmajoki"


def test_parses_street_layer_feature(app):
    body = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [22.5744, 62.7335]},
                "properties": {
                    "label": "Valtiontie, Ilmajoki",
                    "name": "Valtiontie",
                    "layer": "street",
                    "locality": "Ilmajoki",
                },
            }
        ],
    }
    with app.app_context():
        parsed = geocoding_service._parse_digitransit_features(body["features"], limit=5)

    assert len(parsed) == 1
    assert parsed[0]["street"] == "Valtiontie"
    assert parsed[0]["city"] == "Ilmajoki"


@pytest.mark.parametrize(
    "query",
    [
        "Valtiontie 1 Ilmajoki",
        "Valtatie Ilmajoki",
        "Valtionkatu Helsinki",
    ],
)
def test_sample_queries_use_search_fallback_when_autocomplete_empty(app, monkeypatch, query):
    calls: list[str] = []

    class FakeResponse:
        status_code = 200

        def __init__(self, payload: dict):
            self._payload = payload

        def raise_for_status(self):
            return None

        @property
        def text(self):
            return "{}"

        def json(self):
            return self._payload

    def fake_get(url, *args, **kwargs):
        calls.append(url)
        if "autocomplete" in url:
            return FakeResponse({"type": "FeatureCollection", "features": []})
        return FakeResponse(_sample_digitransit_body())

    monkeypatch.setattr("app.integrations.geocoding.service.requests.get", fake_get)

    with app.app_context():
        app.config["GEOCODING_API_KEY"] = "test-key"
        app.config["GEOCODING_DEV_FALLBACK"] = False
        results = geocoding_service.suggest_addresses(query, limit=5)

    assert len(results) == 1
    assert any("search" in url for url in calls)


def test_address_suggest_endpoint_valtion_dev_fallback(client, admin_user, app):
    with app.app_context():
        app.config["GEOCODING_API_KEY"] = ""
        app.config["GEOCODING_DEV_FALLBACK"] = True

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/api/address-suggest?q=Valtion")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert len(body["data"]) >= 1
    assert body["data"][0]["postal_code"] == "60800"


def test_suggest_addresses_short_query_returns_empty_list(app):
    with app.app_context():
        app.config["GEOCODING_API_KEY"] = "test-key"
        assert geocoding_service.suggest_addresses("he", limit=5) == []


def test_address_suggest_endpoint_requires_login(client):
    response = client.get("/admin/api/address-suggest?q=Helsinki", follow_redirects=False)
    assert response.status_code in {302, 401, 403}


@pytest.mark.parametrize(
    "query",
    ["Mannerheimintie", "Valtatie", "Keskuskatu"],
)
def test_address_suggest_endpoint_returns_results_for_street_queries(
    client, admin_user, monkeypatch, query
):
    class FakeResponse:
        status_code = 200
        text = '{"type":"FeatureCollection","features":[]}'

        def raise_for_status(self):
            return None

        def json(self):
            return _sample_digitransit_body()

    monkeypatch.setattr(
        "app.integrations.geocoding.service.requests.get",
        lambda *a, **k: FakeResponse(),
    )

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get(f"/admin/api/address-suggest?q={query}")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert isinstance(body["data"], list)
    assert len(body["data"]) >= 1
    item = body["data"][0]
    assert item["label"]
    assert item["street"]
    assert "postal_code" in item
    assert "city" in item


def test_address_suggest_endpoint_json_for_logged_in_admin(client, admin_user, monkeypatch):
    class FakeResponse:
        status_code = 200
        text = '{"type":"FeatureCollection","features":[]}'

        def raise_for_status(self):
            return None

        def json(self):
            return _sample_digitransit_body()

    monkeypatch.setattr(
        "app.integrations.geocoding.service.requests.get", lambda *a, **k: FakeResponse()
    )

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/api/address-suggest?q=Manner")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["error"] is None
    assert isinstance(body["data"], list)
    assert body["data"][0]["street"] == "Mannerheimintie 1"


def test_address_suggest_endpoint_empty_data_when_no_api_key(client, admin_user, app):
    with app.app_context():
        app.config["GEOCODING_API_KEY"] = ""
        app.config["GEOCODING_DEV_FALLBACK"] = False

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/api/address-suggest?q=Keskuskatu")
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["data"] == []


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


def test_address_autocomplete_script_shows_empty_state_message():
    script = Path("app/static/js/admin-address-autocomplete.js").read_text(encoding="utf-8")
    assert "Ei ehdotuksia" in script
    assert "Haetaan..." in script


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
