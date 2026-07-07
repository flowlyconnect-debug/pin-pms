"""E2E: superadmin muokkaa asetusta ja muutos näkyy listassa."""

from __future__ import annotations


def test_superadmin_edits_setting_and_sees_new_value(superadmin_page, live_server, seed):
    superadmin_page.goto(f"{live_server}/admin/settings/company_name")
    superadmin_page.fill("input[name=value], textarea[name=value]", "E2E Yritys Oy")
    superadmin_page.click("button[name=action][value=save]")

    superadmin_page.goto(f"{live_server}/admin/settings")
    assert "E2E Yritys Oy" in superadmin_page.locator("body").inner_text()

    # The settings service (used by templates/frontend) returns the new value.
    from app.settings import services as settings_service

    settings_service._cache_invalidate("company_name")
    assert settings_service.get("company_name") == "E2E Yritys Oy"


def test_settings_require_superadmin(admin_page, live_server, seed):
    resp = admin_page.request.get(f"{live_server}/admin/settings", max_redirects=0)
    assert resp.status in (302, 303, 403)
