"""Harness smoke: live-server toimii ilman selainta (ei Playwright-riippuvuutta).

Nämä ajetaan samassa suitessa kuin selaintestit, mutta ne käyttävät vain
``requests``-kirjastoa — jos nämä menevät läpi ja selaintestit eivät,
vika on selainpuolella eikä palvelinharnessissa.
"""

from __future__ import annotations

import re

import requests

from e2e.conftest import ADMIN_PASSWORD


def _csrf_token(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    assert match, "csrf_token input not found on page"
    return match.group(1)


def test_login_page_renders(live_server, seed):
    resp = requests.get(f"{live_server}/login", timeout=10)
    assert resp.status_code == 200
    assert "csrf_token" in resp.text


def test_admin_login_via_http(live_server, seed):
    session = requests.Session()
    page = session.get(f"{live_server}/login", timeout=10)
    resp = session.post(
        f"{live_server}/login",
        data={
            "email": seed.admin_email,
            "password": ADMIN_PASSWORD,
            "csrf_token": _csrf_token(page.text),
        },
        timeout=10,
        allow_redirects=True,
    )
    assert resp.status_code == 200
    assert "/admin" in resp.url


def test_csrf_is_enforced_on_live_server(live_server, seed):
    resp = requests.post(
        f"{live_server}/login",
        data={"email": seed.admin_email, "password": ADMIN_PASSWORD},
        timeout=10,
        allow_redirects=False,
    )
    # Missing CSRF token must not create a session.
    assert resp.status_code in (400, 302, 303)
    if resp.status_code in (302, 303):
        assert "/admin" not in (resp.headers.get("Location") or "")
