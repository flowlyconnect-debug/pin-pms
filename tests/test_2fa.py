"""Spec section 16 — superadmin 2FA -vaatimus."""

from __future__ import annotations


def test_superadmin_login_redirects_to_2fa_verify(client, superadmin):
    """Logging in as superadmin alone is not enough — must verify 2FA next."""

    response = client.post(
        "/login",
        data={
            "email": superadmin.email,
            "password": superadmin.password_plain,
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/2fa/verify" in response.headers["Location"]


def test_superadmin_cannot_reach_admin_pages_without_2fa_verify(client, superadmin):
    """A logged-in superadmin without ``2fa_verified`` cannot view /admin/*.

    The ``before_request`` guard in :func:`app.register_security_guards`
    intercepts the request and bounces the operator to ``/2fa/verify``.
    """

    # Step 1: log in.
    client.post(
        "/login",
        data={
            "email": superadmin.email,
            "password": superadmin.password_plain,
        },
    )

    # Step 2: try to reach an admin page *without* verifying the TOTP code.
    response = client.get("/admin/audit", follow_redirects=False)

    assert response.status_code == 302
    assert "/2fa/verify" in response.headers["Location"]


def test_superadmin_with_verified_session_reaches_admin_pages(client, superadmin):
    """After completing ``/2fa/verify`` the session is granted full access."""

    import pyotp

    # Log in first so Flask-Login knows who we are.
    client.post(
        "/login",
        data={
            "email": superadmin.email,
            "password": superadmin.password_plain,
        },
    )

    # Submit a fresh TOTP code.
    code = pyotp.TOTP(superadmin.totp_secret).now()
    client.post("/2fa/verify", data={"code": code})

    # Now /admin/audit must serve the page (200), not redirect.
    response = client.get("/admin/audit")
    assert response.status_code == 200


def test_superadmin_after_2fa_redirects_to_admin_home(client, superadmin):
    import pyotp

    client.post(
        "/login",
        data={
            "email": superadmin.email,
            "password": superadmin.password_plain,
        },
    )

    code = pyotp.TOTP(superadmin.totp_secret).now()
    response = client.post("/2fa/verify", data={"code": code}, follow_redirects=False)

    assert response.status_code == 302
    assert "/admin" in response.headers["Location"]
