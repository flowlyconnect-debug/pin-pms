"""Spec section 16 — API-avainautentikointi."""

from __future__ import annotations


def test_api_health_does_not_require_a_key(client):
    """``/api/v1/health`` is a public liveness probe — no auth, no tenant data."""

    response = client.get("/api/v1/health")
    assert response.status_code == 200

    payload = response.get_json()
    assert payload == {"success": True, "data": {"status": "ok"}, "error": None}


def test_api_me_requires_a_key(client):
    """Calling a protected route without credentials returns 401 in JSON."""

    response = client.get("/api/v1/me")

    assert response.status_code == 401
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "unauthorized"


def test_api_me_rejects_invalid_key(client):
    """A bogus bearer token is treated the same as a missing one."""

    response = client.get(
        "/api/v1/me",
        headers={"Authorization": "Bearer pms_does_not_exist"},
    )

    assert response.status_code == 401
    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "unauthorized"


def test_api_me_with_valid_key_returns_owner_context(client, api_key):
    """A live key is accepted via either supported header form."""

    # Authorization: Bearer <key>
    bearer = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {api_key.raw}"},
    )
    assert bearer.status_code == 200

    payload = bearer.get_json()
    assert payload["success"] is True
    assert payload["data"]["api_key"]["prefix"] == api_key.key_prefix
    assert payload["data"]["api_key"]["name"] == "Test key"
    assert payload["data"]["organization"]["id"] is not None

    # X-API-Key: <key>
    xapikey = client.get(
        "/api/v1/me",
        headers={"X-API-Key": api_key.raw},
    )
    assert xapikey.status_code == 200
