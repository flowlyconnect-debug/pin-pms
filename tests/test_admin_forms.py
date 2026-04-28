from __future__ import annotations

import pyotp


def _login_superadmin_2fa(client, superadmin):
    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
        follow_redirects=True,
    )
    code = pyotp.TOTP(superadmin.totp_secret).now()
    client.post("/2fa/verify", data={"code": code}, follow_redirects=True)


def _force_superadmin_session(client, superadmin):
    with client.session_transaction() as session:
        session["_user_id"] = str(superadmin.id)
        session["_fresh"] = True
        session["2fa_verified"] = True


def test_users_new_missing_required_field_rerenders(client, superadmin):
    from app.users.models import User

    _login_superadmin_2fa(client, superadmin)

    response = client.post(
        "/admin/users/new",
        data={
            "email": "",
            "role": "user",
            "organization_id": str(superadmin.organization_id),
            "password": "ValidPassword123!",
        },
    )

    assert response.status_code == 200
    assert b"Create user" in response.data
    assert User.query.filter_by(email="").first() is None


def test_users_new_rejects_post_without_csrf(client, superadmin, app):
    original = app.config.get("WTF_CSRF_ENABLED", False)
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        _force_superadmin_session(client, superadmin)
        response = client.post(
            "/admin/users/new",
            data={
                "email": "no-csrf@test.local",
                "role": "user",
                "organization_id": str(superadmin.organization_id),
                "password": "ValidPassword123!",
            },
        )
        assert response.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = original


