from __future__ import annotations

from app.core.security import hash_token


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _make_lease(admin_user):
    from app.billing import services as billing_service
    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(organization_id=admin_user.organization_id, name="Sign Prop", address="Test")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="S1", unit_type="double")
    db.session.add(unit)
    db.session.commit()
    return billing_service.create_lease(
        organization_id=admin_user.organization_id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date_raw="2026-06-01",
        end_date_raw=None,
        rent_amount_raw="100",
        deposit_amount_raw="10",
        billing_cycle="monthly",
        notes="Lease",
        actor_user_id=admin_user.id,
    )


def test_admin_lease_pdf_route_returns_pdf(client, admin_user):
    lease = _make_lease(admin_user)
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    resp = client.get(f"/admin/leases/{lease['id']}/pdf")
    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data.startswith(b"%PDF")


def test_send_for_signing_sets_pending_and_hash(client, admin_user, monkeypatch):
    from app.billing.models import Lease

    lease = _make_lease(admin_user)
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    def _ok(*args, **kwargs):
        return True

    monkeypatch.setattr("app.billing.services.send_template", _ok)
    resp = client.post(f"/admin/leases/{lease['id']}/send-for-signing", follow_redirects=True)
    assert resp.status_code == 200
    row = Lease.query.get(lease["id"])
    assert row.status == "pending_signature"
    assert row.signed_token_hash
    assert row.signed_token_hash != hash_token("not-the-token")


def test_public_sign_route_updates_signature(client, admin_user, monkeypatch):
    from app.billing import services as billing_service
    from app.billing.models import Lease

    lease = _make_lease(admin_user)
    token = "token-123"
    monkeypatch.setattr("app.billing.services.send_template", lambda *args, **kwargs: True)
    _ = billing_service.send_lease_for_signing(
        organization_id=admin_user.organization_id,
        lease_id=lease["id"],
        actor_user_id=admin_user.id,
        token=token,
        signed_pdf_filename="lease.pdf",
        signed_pdf_path=__file__,
        sign_url="http://example.test/lease/sign/token-123",
        recipient_email=admin_user.email,
    )
    get_page = client.get(f"/lease/sign/{token}")
    assert get_page.status_code == 200
    post_page = client.post(f"/lease/sign/{token}")
    assert post_page.status_code == 200
    row = Lease.query.get(lease["id"])
    assert row.status == "active"
    assert row.signed_at is not None
    assert row.signed_user_agent is not None


def test_invalid_sign_token_does_not_leak(client):
    resp = client.get("/lease/sign/invalid-token")
    assert resp.status_code == 404
