from __future__ import annotations

import pyotp


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _login_superadmin_2fa(client, superadmin):
    _login(client, email=superadmin.email, password=superadmin.password_plain)
    code = pyotp.TOTP(superadmin.totp_secret).now()
    return client.post("/2fa/verify", data={"code": code}, follow_redirects=False)


def test_superadmin_can_crud_lease_templates(client, superadmin):
    from app.audit.models import AuditLog

    _login_superadmin_2fa(client, superadmin)
    create = client.post(
        "/admin/lease-templates/new",
        data={
            "name": "Default lease",
            "description": "Main template",
            "body_markdown": "Hello {{ tenant_name }}",
            "is_default": "y",
        },
        follow_redirects=True,
    )
    assert create.status_code == 200
    list_resp = client.get("/admin/lease-templates")
    assert list_resp.status_code == 200
    assert b"Default lease" in list_resp.data
    assert AuditLog.query.filter_by(action="lease.template.created").first() is not None

    from app.billing.services import list_lease_templates_for_organization

    rows = list_lease_templates_for_organization(organization_id=superadmin.organization_id)
    tid = rows[0]["id"]
    edit = client.post(
        f"/admin/lease-templates/{tid}/edit",
        data={
            "name": "Updated lease",
            "description": "Updated",
            "body_markdown": "Updated {{ tenant_name }}",
            "is_default": "y",
        },
        follow_redirects=True,
    )
    assert edit.status_code == 200
    assert AuditLog.query.filter_by(action="lease.template.updated").first() is not None

    delete = client.post(f"/admin/lease-templates/{tid}/delete", follow_redirects=True)
    assert delete.status_code == 200
    assert AuditLog.query.filter_by(action="lease.template.deleted").first() is not None


def test_default_template_only_one_per_org(app, superadmin):
    from app.billing import services as billing_service

    billing_service.create_lease_template(
        organization_id=superadmin.organization_id,
        name="A",
        description=None,
        body_markdown="A",
        is_default=True,
        actor_user_id=superadmin.id,
    )
    t2 = billing_service.create_lease_template(
        organization_id=superadmin.organization_id,
        name="B",
        description=None,
        body_markdown="B",
        is_default=True,
        actor_user_id=superadmin.id,
    )
    rows = billing_service.list_lease_templates_for_organization(
        organization_id=superadmin.organization_id
    )
    defaults = [r for r in rows if r["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == t2["id"]
