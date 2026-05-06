from __future__ import annotations


def test_root_redirects_directly_to_login(client):
    response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert "/login" in (response.headers.get("Location") or "")
    assert b"Public status" not in response.data


def test_root_follow_redirect_renders_modern_login(client):
    response = client.get("/", follow_redirects=True)

    assert response.status_code == 200
    assert "Toiminnot, varaukset ja huolto samassa paikassa.".encode("utf-8") in response.data
    assert b"Public status" not in response.data


def test_login_route_still_works(client):
    response = client.get("/login")

    assert response.status_code == 200
    assert "Toiminnot, varaukset ja huolto samassa paikassa.".encode("utf-8") in response.data
