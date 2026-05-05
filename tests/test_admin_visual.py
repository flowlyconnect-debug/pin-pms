from __future__ import annotations


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def test_dashboard_uses_kpi_card_class(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "kpi-card" in html


def test_admin_login_form_has_modern_input_styles_class(client):
    response = client.get("/login")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="modern-input"' in html


def test_dark_mode_meta_color_scheme_present(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert '<meta name="color-scheme" content="light dark">' in html


def test_topbar_does_not_duplicate_h1(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "admin-topbar-title" in html
    assert "<h1>Hallintapaneeli</h1>" not in html


def test_topbar_search_input_removed(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'id="admin-global-search"' not in html
    assert 'class="topbar-search"' not in html
    assert 'placeholder="Etsi..."' not in html


def test_notification_bell_still_present(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "admin-notifications" in html


def test_avatar_dropdown_present(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "admin-avatar-menu" in html
    assert "admin-avatar-dropdown" in html


def test_admin_can_set_theme_cookie(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.post("/admin/theme", data={"theme": "dark"})
    assert response.status_code in (302, 303)
    cookie = response.headers.get("Set-Cookie") or ""
    assert "ui_theme=dark" in cookie
