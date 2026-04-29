from __future__ import annotations

import pyotp


def _login_superadmin(client, superadmin) -> None:
    client.post("/login", data={"email": superadmin.email, "password": superadmin.password_plain})
    code = pyotp.TOTP(superadmin.totp_secret).now()
    client.post("/2fa/verify", data={"code": code})


def test_impersonation_writes_audit_log(client, superadmin, regular_user):
    from app.audit.models import AuditLog

    _login_superadmin(client, superadmin)
    response = client.post(
        f"/admin/superadmin/impersonate/{regular_user.id}",
        data={"reason": "Debug support issue"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    row = (
        AuditLog.query.filter_by(action="support.impersonate.started")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None
    assert row.target_id == regular_user.id


def test_impersonation_blocked_action_returns_403(client, superadmin, regular_user):
    _login_superadmin(client, superadmin)
    client.post(
        f"/admin/superadmin/impersonate/{regular_user.id}",
        data={"reason": "Debug support issue"},
        follow_redirects=False,
    )
    response = client.post(f"/admin/users/{regular_user.id}/toggle-active", follow_redirects=False)
    assert response.status_code == 403


def test_exit_impersonation_restores_original_user(client, superadmin, regular_user):
    _login_superadmin(client, superadmin)
    client.post(
        f"/admin/superadmin/impersonate/{regular_user.id}",
        data={"reason": "Debug support issue"},
        follow_redirects=False,
    )
    response = client.post("/admin/exit-impersonation", follow_redirects=True)
    assert response.status_code == 200
    assert superadmin.email.encode() in response.data
