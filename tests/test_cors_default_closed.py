"""Project brief section 10 — CORS sallitaan vain määritetyille domaineille.

When ``CORS_ALLOWED_ORIGINS`` is empty (the default), no
``Access-Control-Allow-Origin`` header is emitted on cross-origin requests,
i.e. browsers will block any third-party origin from reading API responses.
"""

from __future__ import annotations


def test_no_cors_header_when_origins_empty(client):
    response = client.get(
        "/api/v1/health",
        headers={"Origin": "https://evil.example.com"},
    )
    assert response.status_code == 200
    assert "Access-Control-Allow-Origin" not in response.headers


def test_no_cors_preflight_when_origins_empty(client):
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    # Either 405/404 or 200 — but no ACL header should be set.
    assert "Access-Control-Allow-Origin" not in response.headers
