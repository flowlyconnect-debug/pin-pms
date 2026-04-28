"""Project brief section 10 — baseline security headers.

Every HTML and API response must carry CSP, X-Frame-Options,
X-Content-Type-Options, Referrer-Policy and Permissions-Policy. HSTS only
fires for HTTPS requests (or behind a TLS-terminating proxy).
"""
from __future__ import annotations


def _assert_baseline(response):
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    csp = response.headers.get("Content-Security-Policy") or ""
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp

    perms = response.headers.get("Permissions-Policy") or ""
    assert "geolocation=()" in perms


def test_health_endpoint_has_security_headers(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    _assert_baseline(response)


def test_login_page_has_security_headers(client):
    response = client.get("/login")
    assert response.status_code == 200
    _assert_baseline(response)


def test_hsts_only_on_https(client):
    """HSTS must not be sent over plaintext HTTP."""

    response = client.get("/api/v1/health")
    assert "Strict-Transport-Security" not in response.headers


def test_hsts_present_when_forwarded_proto_https(client):
    response = client.get(
        "/api/v1/health",
        headers={"X-Forwarded-Proto": "https"},
    )
    hsts = response.headers.get("Strict-Transport-Security") or ""
    assert "max-age=" in hsts
    assert "includeSubDomains" in hsts


def test_admin_page_uses_no_store_cache(client, superadmin):
    """Authenticated admin HTML must not be cached by browsers/proxies."""

    import pyotp

    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
        follow_redirects=False,
    )
    code = pyotp.TOTP(superadmin.totp_secret).now()
    client.post("/2fa/verify", data={"code": code}, follow_redirects=False)

    response = client.get("/admin/audit")
    assert response.status_code == 200
    cache_control = (response.headers.get("Cache-Control") or "").lower()
    assert "no-store" in cache_control
