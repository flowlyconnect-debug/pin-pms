"""Admin-työpöydän otsikkokortti: iso otsikko näkyy, pientä Hallinta ·/Hallinta - -riviä ei."""

from __future__ import annotations


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def test_dashboard_shows_title_without_hallinta_subtitle(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    for path in ("/admin/dashboard", "/admin", "/admin/"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 200, path
        html = response.get_data(as_text=True)
        assert "Hallintapaneeli" in html, path
        assert "Hallinta · Hallintapaneeli" not in html, path
        assert "Hallinta - Hallintapaneeli" not in html, path
        assert 'class="admin-topbar-breadcrumb"' not in html, path


def test_guests_list_shows_title_without_hallinta_subtitle(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/guests", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Asiakkaat" in html
    assert "Hallinta · Asiakkaat" not in html
    assert "Hallinta - Asiakkaat" not in html
    assert 'class="admin-topbar-breadcrumb"' not in html
