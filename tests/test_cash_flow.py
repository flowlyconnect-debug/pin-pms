from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal


def _login_admin(client, admin_user):
    client.post("/login", data={"email": admin_user.email, "password": admin_user.password_plain})


def _seed_property_unit(app, organization_id: int, name: str = "P1"):
    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(organization_id=organization_id, name=name, address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U1", unit_type=None)
    db.session.add(unit)
    db.session.commit()
    return prop, unit


def test_cash_flow_report_groups_by_month(app, organization, admin_user):
    from app.billing.models import Invoice
    from app.extensions import db
    from app.reports.services import cash_flow_report

    prop, unit = _seed_property_unit(app, organization.id)
    _ = prop
    inv1 = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=admin_user.id,
        invoice_number="INV-CF-1",
        amount=Decimal("100.00"),
        subtotal_excl_vat=Decimal("100.00"),
        vat_rate=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
        total_incl_vat=Decimal("100.00"),
        currency="EUR",
        due_date=date(2026, 1, 10),
        paid_at=datetime(2026, 1, 10, 8, 0, 0),
        status="paid",
        created_by_id=admin_user.id,
    )
    inv2 = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=admin_user.id,
        invoice_number="INV-CF-2",
        amount=Decimal("200.00"),
        subtotal_excl_vat=Decimal("200.00"),
        vat_rate=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
        total_incl_vat=Decimal("200.00"),
        currency="EUR",
        due_date=date(2026, 2, 10),
        paid_at=datetime(2026, 2, 10, 8, 0, 0),
        status="paid",
        created_by_id=admin_user.id,
    )
    db.session.add_all([inv1, inv2])
    db.session.commit()
    report = cash_flow_report(
        organization_id=organization.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 2, 28),
    )
    assert [row["label"] for row in report["groups"]] == ["2026-01", "2026-02"]
    assert report["totals"]["income"] == Decimal("300.00")


def test_income_breakdown_excludes_cancelled_invoices(app, organization, admin_user):
    from app.billing.models import Invoice
    from app.extensions import db
    from app.reports.services import income_breakdown_report

    _seed_property_unit(app, organization.id)
    paid = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=admin_user.id,
        invoice_number="INV-INC-OK",
        amount=Decimal("80.00"),
        subtotal_excl_vat=Decimal("80.00"),
        vat_rate=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
        total_incl_vat=Decimal("80.00"),
        currency="EUR",
        due_date=date(2026, 1, 10),
        paid_at=datetime(2026, 1, 10, 8, 0, 0),
        status="paid",
        metadata_json={"invoice_kind": "service"},
        created_by_id=admin_user.id,
    )
    cancelled = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=admin_user.id,
        invoice_number="INV-INC-CAN",
        amount=Decimal("999.00"),
        subtotal_excl_vat=Decimal("999.00"),
        vat_rate=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
        total_incl_vat=Decimal("999.00"),
        currency="EUR",
        due_date=date(2026, 1, 11),
        paid_at=datetime(2026, 1, 11, 8, 0, 0),
        status="cancelled",
        metadata_json={"invoice_kind": "rent"},
        created_by_id=admin_user.id,
    )
    db.session.add_all([paid, cancelled])
    db.session.commit()

    data = income_breakdown_report(
        organization_id=organization.id,
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
    )
    groups = {row["label"]: row["amount"] for row in data["groups"]}
    assert groups["service"] == Decimal("80.00")
    assert data["total"] == Decimal("80.00")


def test_reports_export_csv(app, client, organization, admin_user):
    from app.billing.models import Invoice
    from app.extensions import db

    _seed_property_unit(app, organization.id)
    invoice = Invoice(
        organization_id=organization.id,
        lease_id=None,
        reservation_id=None,
        guest_id=admin_user.id,
        invoice_number="INV-CSV",
        amount=Decimal("120.00"),
        subtotal_excl_vat=Decimal("120.00"),
        vat_rate=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
        total_incl_vat=Decimal("120.00"),
        currency="EUR",
        due_date=date(2026, 3, 2),
        paid_at=datetime(2026, 3, 2, 8, 0, 0),
        status="paid",
        created_by_id=admin_user.id,
    )
    db.session.add(invoice)
    db.session.commit()
    _login_admin(client, admin_user)
    rv = client.get("/admin/reports/cash-flow?start_date=2026-03-01&end_date=2026-03-31&export=csv")
    assert rv.status_code == 200
    text = rv.data.decode("utf-8")
    assert "period,income,expenses,net" in text
    assert "2026-03,120.00,0.00,120.00" in text
