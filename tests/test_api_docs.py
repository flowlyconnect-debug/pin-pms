from __future__ import annotations


def _auth_headers(raw_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {raw_key}"}


def test_swagger_ui_requires_reports_read_scope(client, api_key):
    response = client.get("/api/v1/docs")
    assert response.status_code == 401

    response = client.get("/api/v1/docs", headers=_auth_headers(api_key.raw))
    assert response.status_code == 200
    assert b"SwaggerUIBundle" in response.data
    assert b"/api/v1/openapi.json" in response.data


def test_openapi_spec_requires_reports_read_scope_and_lists_api_routes(client, api_key):
    response = client.get("/api/v1/openapi.json")
    assert response.status_code == 401

    response = client.get("/api/v1/openapi.json", headers=_auth_headers(api_key.raw))
    assert response.status_code == 200

    payload = response.get_json()
    assert payload["openapi"].startswith("3.0")
    assert "/api/v1/health" in payload["paths"]
    assert "/api/v1/properties/{property_id}" in payload["paths"]
    assert "get" in payload["paths"]["/api/v1/me"]
