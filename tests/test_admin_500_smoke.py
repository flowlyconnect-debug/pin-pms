from __future__ import annotations

import pytest


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


@pytest.mark.parametrize(
    "path",
    [
        "/admin",
        "/admin/dashboard",
        "/admin/properties",
        "/admin/units",
        "/admin/availability",
        "/admin/calendar-sync/conflicts",
        "/admin/reports",
    ],
)
def test_admin_pages_do_not_500(client, admin_user, path):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get(path, follow_redirects=False)
    assert response.status_code != 500
