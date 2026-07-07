"""E2E: kirjautuminen, väärä salasana, superadminin 2FA-pakko."""

from __future__ import annotations

import pyotp

from e2e.conftest import ADMIN_PASSWORD, SUPERADMIN_PASSWORD, login


def test_admin_can_log_in(page, live_server, seed):
    login(page, live_server, seed.admin_email, ADMIN_PASSWORD)
    page.wait_for_url("**/admin/**")
    assert "/admin" in page.url


def test_wrong_password_shows_error_and_no_session(page, live_server, seed):
    login(page, live_server, seed.admin_email, "VaaraSalasana123!")
    # Must stay on the login page (no admin session).
    page.wait_for_selector("#pms-login-card")
    assert "/admin" not in page.url

    page.goto(f"{live_server}/admin/dashboard")
    page.wait_for_url("**/login**")


def test_admin_pages_require_login(page, live_server, seed):
    page.goto(f"{live_server}/admin/reservations")
    page.wait_for_url("**/login**")


def test_superadmin_login_requires_totp(page, live_server, seed):
    login(page, live_server, seed.superadmin_email, SUPERADMIN_PASSWORD)
    page.wait_for_url("**/2fa/verify**")

    # Wrong code is rejected.
    page.fill("input[name=code]", "000000")
    page.click("button[type=submit]")
    page.wait_for_url("**/2fa/verify**")

    # Correct TOTP passes.
    page.fill("input[name=code]", pyotp.TOTP(seed.superadmin_totp_secret).now())
    page.click("button[type=submit]")
    page.wait_for_url("**/admin/**")
    assert "/2fa/verify" not in page.url
