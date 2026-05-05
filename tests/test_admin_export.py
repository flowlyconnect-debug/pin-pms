from __future__ import annotations

from datetime import date


def _login_admin(client, admin_user):
    client.post("/login", data={"email": admin_user.email, "password": admin_user.password_plain})


def _seed_invoice(app, organization, admin_user, number: str = "INV-1"):
    from app.billing.models import Invoice
    from app.extensions import db

    row = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=None,
        invoice_number=number,
        amount=10,
        subtotal_excl_vat=10,
        total_incl_vat=10,
        vat_rate=0,
        vat_amount=0,
        currency="EUR",
        due_date=date.today(),
        status="open",
        created_by_id=admin_user.id,
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_csv_export_returns_correct_rows(app, client, organization, admin_user):
    _seed_invoice(app, organization, admin_user, "INV-ROW")
    _login_admin(client, admin_user)
    rv = client.get("/admin/invoices/export?format=csv")
    assert rv.status_code == 200
    text = rv.data.decode("utf-8")
    assert "INV-ROW" in text


def test_csv_export_respects_filters(app, client, organization, admin_user):
    _seed_invoice(app, organization, admin_user, "CONF")
    _seed_invoice(app, organization, admin_user, "CANC")
    from app.billing.models import Invoice
    from app.extensions import db

    bad = Invoice.query.filter_by(invoice_number="CANC").first()
    bad.status = "cancelled"
    db.session.commit()

    _login_admin(client, admin_user)
    rv = client.get("/admin/invoices/export?format=csv&status=open")
    text = rv.data.decode("utf-8")
    assert "CONF" in text
    assert "CANC" not in text


def test_large_export_queues_email_delivery(app, client, organization, admin_user, monkeypatch):
    _login_admin(client, admin_user)

    monkeypatch.setattr(
        "app.admin.routes.admin_service.list_admin_invoices",
        lambda **kwargs: ([{"id": 1, "invoice_number": "X"}], 10001),
    )
    rv = client.get("/admin/invoices/export?format=csv")
    assert rv.status_code == 200
    assert rv.get_json()["data"]["queued"] is True


def test_csv_export_does_not_include_secret_fields(app, client, organization, admin_user):
    _seed_invoice(app, organization, admin_user, "INV-SEC")
    _login_admin(client, admin_user)
    rv = client.get("/admin/invoices/export?format=csv")
    text = rv.data.decode("utf-8")
    assert "password_hash" not in text
    assert "api_key_hash" not in text
    assert "totp_secret" not in text
    assert "token" not in text


def test_export_audit_log_created(app, client, organization, admin_user):
    from app.audit.models import AuditLog

    _seed_invoice(app, organization, admin_user, "INV-AUDIT")
    _login_admin(client, admin_user)
    rv = client.get("/admin/invoices/export?format=csv")
    assert rv.status_code == 200
    assert AuditLog.query.filter_by(action="invoices.exported").first() is not None

