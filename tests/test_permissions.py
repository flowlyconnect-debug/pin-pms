"""Spec section 16 — oikeustarkistukset.

Three layers of access control are exercised here:

* ``@login_required`` — anonymous request to a protected page redirects to
  login.
* ``require_superadmin_2fa`` — authenticated non-superadmin gets 403.
* Per-view manual ``abort(403)`` for routes that are explicitly
  superadmin-only (``/2fa/setup``).
"""
from __future__ import annotations


def test_admin_audit_redirects_anonymous_to_login(client):
    response = client.get("/admin/audit", follow_redirects=False)

    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_admin_audit_forbidden_for_regular_user(client, regular_user):
    """Logged-in non-superadmin cannot view the audit log."""

    client.post(
        "/login",
        data={
            "email": regular_user.email,
            "password": regular_user.password_plain,
        },
    )

    response = client.get("/admin/audit", follow_redirects=False)

    assert response.status_code == 403


def test_two_factor_setup_forbidden_for_regular_user(client, regular_user):
    """``/2fa/setup`` is reserved for superadmins.

    A regular user reaching the route — accidentally or otherwise — gets a
    flat 403 rather than being walked through enrolling a TOTP factor that
    will never be enforced for them.
    """

    client.post(
        "/login",
        data={
            "email": regular_user.email,
            "password": regular_user.password_plain,
        },
    )

    response = client.get("/2fa/setup")

    assert response.status_code == 403
