"""Spec section 3 — superadmin can manage users / orgs / API keys via UI."""

from __future__ import annotations

import pyotp


def _login_superadmin(client, superadmin) -> None:
    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
    )
    code = pyotp.TOTP(superadmin.totp_secret).now()
    client.post("/2fa/verify", data={"code": code})


def test_users_list_requires_superadmin(client, regular_user):
    """A regular user must not see /admin/users."""

    client.post(
        "/login",
        data={"email": regular_user.email, "password": regular_user.password_plain},
    )
    response = client.get("/admin/users", follow_redirects=False)
    assert response.status_code in (302, 403)


def test_superadmin_can_list_users(client, superadmin):
    _login_superadmin(client, superadmin)
    response = client.get("/admin/users")
    assert response.status_code == 200
    assert superadmin.email.encode() in response.data


def test_superadmin_can_create_organization(client, superadmin):
    from app.organizations.models import Organization

    _login_superadmin(client, superadmin)
    response = client.post(
        "/admin/organizations/new",
        data={"name": "New Tenant"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert Organization.query.filter_by(name="New Tenant").first() is not None


def test_superadmin_can_issue_api_key(client, superadmin, organization):
    from app.api.models import ApiKey

    _login_superadmin(client, superadmin)
    before = ApiKey.query.count()

    response = client.post(
        "/admin/api-keys/new",
        data={
            "name": "Test integration",
            "organization_id": str(organization.id),
            "user_id": "",
            "scopes": "",
            "expires_days": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert ApiKey.query.count() == before + 1


def test_superadmin_can_disable_api_key(client, superadmin, api_key):
    _login_superadmin(client, superadmin)
    response = client.post(
        f"/admin/api-keys/{api_key.id}/toggle-active",
        follow_redirects=False,
    )
    assert response.status_code == 302

    from app.api.models import ApiKey

    refreshed = ApiKey.query.get(api_key.id)
    assert refreshed.is_active is False
