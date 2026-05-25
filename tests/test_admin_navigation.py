"""Admin sidebar and settings hub navigation."""

from __future__ import annotations

import pyotp

from app.admin.navigation import (
    SETTINGS_HUB_ACTIVE_ENDPOINTS,
    is_endpoint_active,
    SETTINGS_NAV_ITEM,
)


def _login(client, *, email: str, password: str):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _login_superadmin_2fa(client, superadmin):
    _ = _login(client, email=superadmin.email, password=superadmin.password_plain)
    code = pyotp.TOTP(superadmin.totp_secret).now()
    _ = client.post("/2fa/verify", data={"code": code}, follow_redirects=False)


def _sidebar_html(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    return response.get_data(as_text=True)


def test_org_admin_sidebar_has_daily_groups_not_technical_links(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    html = _sidebar_html(client, "/admin/")

    assert "Päätoiminnot" in html
    assert "Talous" in html
    assert "Operointi" in html
    assert "admin-nav-grp-admin" not in html
    assert "Kohteet" in html
    assert "Laskut" in html
    assert "Asetukset" in html
    assert "/admin/users" not in html
    assert "/admin/organizations" not in html
    assert "/admin/api-keys" not in html
    assert "/admin/webhooks" not in html
    assert "/admin/email-templates" not in html
    assert "/admin/audit" not in html
    assert "/admin/backups" not in html


def test_org_admin_settings_hub_shows_allowed_cards_only(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/settings")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "admin-settings-hub" in html
    assert "Saavutettavuus" in html
    assert "Käyttäjät" not in html
    assert "Organisaatiot" not in html
    assert "API-avaimet" not in html
    assert "Sähköpostipohjat" not in html
    assert "Uusi asetus" not in html


def test_superadmin_settings_hub_and_table(client, superadmin):
    _login_superadmin_2fa(client, superadmin)
    response = client.get("/admin/settings")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert "Uusi asetus" in html
    assert "Käyttäjät" in html
    assert "Organisaatiot" in html
    assert "API-avaimet" in html
    assert "Sähköpostipohjat" in html
    assert "Sopimuspohjat" in html
    assert "Webhookit" in html
    assert "Varmuuskopiot" in html
    assert "Audit-loki" in html
    assert "Tilannehallinta" in html


def test_superadmin_sidebar_hides_technical_links(client, superadmin):
    _login_superadmin_2fa(client, superadmin)
    html = _sidebar_html(client, "/admin/properties")

    assert "admin-nav-grp-admin" not in html
    assert "/admin/users" not in html
    assert 'href="/admin/settings"' in html or "/admin/settings" in html


def test_moved_pages_still_reachable_by_url(client, admin_user, superadmin):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    assert client.get("/admin/users", follow_redirects=False).status_code == 403

    _login_superadmin_2fa(client, superadmin)
    assert client.get("/admin/users").status_code == 200
    assert client.get("/admin/organizations").status_code == 200
    assert client.get("/admin/email-templates").status_code == 200
    assert client.get("/admin/backups").status_code == 200


def test_settings_nav_active_on_hub_subpages():
    for endpoint in (
        "admin.email_templates_list",
        "admin.users_list",
        "admin.audit",
        "backups_admin.backups_list",
        "core.accessibility_statement",
    ):
        assert endpoint in SETTINGS_HUB_ACTIVE_ENDPOINTS
        assert is_endpoint_active(SETTINGS_NAV_ITEM, endpoint)


def test_daily_nav_active_on_own_pages():
    from app.admin.navigation import SIDEBAR_GROUPS

    invoices = next(
        item for group in SIDEBAR_GROUPS for item in group.items if item.endpoint == "admin.invoices_list"
    )
    assert is_endpoint_active(invoices, "admin.invoices_edit")
    assert not is_endpoint_active(invoices, "admin.settings_list")

    notifications = next(
        item
        for group in SIDEBAR_GROUPS
        for item in group.items
        if item.endpoint == "admin.notifications_list"
    )
    assert is_endpoint_active(notifications, "admin.notifications_list")
    assert not is_endpoint_active(SETTINGS_NAV_ITEM, "admin.notifications_list")


def test_conflicts_badge_markup_preserved(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    html = _sidebar_html(client, "/admin/")
    assert "data-conflicts-nav-badge" in html
