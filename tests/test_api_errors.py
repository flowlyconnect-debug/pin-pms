"""Spec section 16 — API:n virhevastaukset.

Every error from ``/api/v1/*`` follows the same envelope:
``{"success": false, "data": null, "error": {"code": "...", "message": "..."}}``
"""
from __future__ import annotations


def test_api_404_returns_uniform_json_envelope(client):
    """Hitting a non-existent route under /api/v1 returns 404 in JSON, not HTML."""

    response = client.get("/api/v1/this_does_not_exist")

    assert response.status_code == 404
    assert response.is_json

    payload = response.get_json()
    assert payload["success"] is False
    assert payload["data"] is None
    assert payload["error"]["code"] == "not_found"
    assert isinstance(payload["error"]["message"], str)
    assert payload["error"]["message"] != ""


def test_api_405_method_not_allowed_returns_json(client):
    """``POST`` to a GET-only route returns the API JSON envelope at 405."""

    response = client.post("/api/v1/health")

    assert response.status_code == 405
    assert response.is_json

    payload = response.get_json()
    assert payload["success"] is False
    assert payload["error"]["code"] == "method_not_allowed"


def test_non_api_404_returns_html(client):
    """Sanity-check: outside /api/* the 404 still renders branded HTML.

    Distinguishes the API JSON path from the regular HTML error path defined
    in :func:`app.register_error_handlers`.
    """

    response = client.get("/this_definitely_does_not_exist")

    assert response.status_code == 404
    # Branded HTML response, not JSON.
    assert response.content_type.startswith("text/html")
    assert b"Not Found" in response.data
