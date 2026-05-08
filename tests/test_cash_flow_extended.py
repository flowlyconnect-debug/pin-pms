from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from werkzeug.security import generate_password_hash


def _login_admin(client, admin_user):
    client.post("/login", data={"email": admin_user.email, "password": admin_user.password_plain})


def _seed_property_and_unit(*, organization_id: int, property_name: str, unit_name: str):
    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(organization_id=organization_id, name=property_name, address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name=unit_name, unit_type="std")
    db.session.add(unit)
    db.session.flush()
    return prop, unit


def test_aging_receivables_boundaries(app, organization, admin_user):
    from app.billing.models import Invoice
    from app.extensions import db
    from app.reports.services import compute_aging_receivables

    with app.app_context():
        as_of = date(2026, 5, 8)
        days = [30, 31, 60, 61, 90, 91]
        for idx, overdue_days in enumerate(days, start=1):
            due_date = as_of - timedelta(days=overdue_days)
            amount = Decimal(f"{idx}0.00")
            db.session.add(
                Invoice(
                    organization_id=organization.id,
                    invoice_number=f"INV-AGING-{idx}",
                    amount=amount,
                    subtotal_excl_vat=amount,
                    vat_rate=Decimal("0.00"),
                    vat_amount=Decimal("0.00"),
                    total_incl_vat=amount,
                    currency="EUR",
                    due_date=due_date,
                    status="overdue",
                    created_by_id=admin_user.id,
                )
            )
        db.session.commit()

        out = compute_aging_receivables(organization_id=organization.id, as_of=as_of)
        assert out["0_30"] == Decimal("10.00")
        assert out["31_60"] == Decimal("50.00")
        assert out["61_90"] == Decimal("90.00")
        assert out["90_plus"] == Decimal("60.00")


def test_forecasted_cash_flow_uses_only_active_leases_and_confirmed_reservations(
    app, organization, admin_user
):
    from app.billing.models import Lease
    from app.extensions import db
    from app.reports.services import compute_forecasted_cash_flow
    from app.reservations.models import Reservation

    with app.app_context():
        _, unit = _seed_property_and_unit(
            organization_id=organization.id,
            property_name="Forecast House",
            unit_name="F1",
        )
        today = date.today()
        db.session.add_all(
            [
                Lease(
                    organization_id=organization.id,
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    reservation_id=None,
                    start_date=today,
                    end_date=today + timedelta(days=60),
                    rent_amount=Decimal("100.00"),
                    deposit_amount=Decimal("0.00"),
                    billing_cycle="one_time",
                    status="active",
                    created_by_id=admin_user.id,
                ),
                Lease(
                    organization_id=organization.id,
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    reservation_id=None,
                    start_date=today,
                    end_date=today + timedelta(days=60),
                    rent_amount=Decimal("700.00"),
                    deposit_amount=Decimal("0.00"),
                    billing_cycle="one_time",
                    status="ended",
                    created_by_id=admin_user.id,
                ),
                Lease(
                    organization_id=organization.id,
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    reservation_id=None,
                    start_date=today,
                    end_date=today + timedelta(days=60),
                    rent_amount=Decimal("800.00"),
                    deposit_amount=Decimal("0.00"),
                    billing_cycle="one_time",
                    status="cancelled",
                    created_by_id=admin_user.id,
                ),
                Lease(
                    organization_id=organization.id,
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    reservation_id=None,
                    start_date=today,
                    end_date=today + timedelta(days=60),
                    rent_amount=Decimal("900.00"),
                    deposit_amount=Decimal("0.00"),
                    billing_cycle="one_time",
                    status="pending_signature",
                    created_by_id=admin_user.id,
                ),
            ]
        )
        db.session.add_all(
            [
                Reservation(
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    guest_name="Confirmed",
                    start_date=today + timedelta(days=5),
                    end_date=today + timedelta(days=6),
                    status="confirmed",
                    amount=Decimal("200.00"),
                ),
                Reservation(
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    guest_name="Cancelled",
                    start_date=today + timedelta(days=5),
                    end_date=today + timedelta(days=6),
                    status="cancelled",
                    amount=Decimal("300.00"),
                ),
                Reservation(
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    guest_name="Pending",
                    start_date=today + timedelta(days=5),
                    end_date=today + timedelta(days=6),
                    status="pending",
                    amount=Decimal("400.00"),
                ),
            ]
        )
        db.session.commit()

        forecast = compute_forecasted_cash_flow(organization_id=organization.id, days_ahead=30)
        assert forecast == Decimal("300.00")


def test_profitability_by_property_is_tenant_scoped(app, organization, admin_user):
    from app.billing.models import Invoice, Lease
    from app.expenses.models import Expense
    from app.extensions import db
    from app.organizations.models import Organization
    from app.reports.services import compute_profitability_by_property
    from app.users.models import User, UserRole

    with app.app_context():
        own_prop, own_unit = _seed_property_and_unit(
            organization_id=organization.id,
            property_name="Org A Property",
            unit_name="A1",
        )
        own_lease = Lease(
            organization_id=organization.id,
            unit_id=own_unit.id,
            guest_id=admin_user.id,
            reservation_id=None,
            start_date=date(2026, 5, 1),
            end_date=None,
            rent_amount=Decimal("100.00"),
            deposit_amount=Decimal("0.00"),
            billing_cycle="monthly",
            status="active",
            created_by_id=admin_user.id,
        )
        db.session.add(own_lease)
        db.session.flush()
        db.session.add(
            Invoice(
                organization_id=organization.id,
                lease_id=own_lease.id,
                guest_id=admin_user.id,
                invoice_number="INV-OWN-1",
                amount=Decimal("1000.00"),
                subtotal_excl_vat=Decimal("1000.00"),
                vat_rate=Decimal("0.00"),
                vat_amount=Decimal("0.00"),
                total_incl_vat=Decimal("1000.00"),
                currency="EUR",
                due_date=date(2026, 5, 10),
                paid_at=datetime(2026, 5, 10, 8, 0, 0),
                status="paid",
                created_by_id=admin_user.id,
            )
        )
        db.session.add(
            Expense(
                organization_id=organization.id,
                property_id=own_prop.id,
                category="maintenance",
                amount=Decimal("300.00"),
                vat=Decimal("0.00"),
                date=date(2026, 5, 11),
            )
        )

        other_org = Organization(name="Profitability Other")
        db.session.add(other_org)
        db.session.flush()
        other_user = User(
            email="profitability-other@test.local",
            password_hash=generate_password_hash("Pass123!"),
            organization_id=other_org.id,
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        db.session.add(other_user)
        db.session.flush()
        other_prop, other_unit = _seed_property_and_unit(
            organization_id=other_org.id,
            property_name="Org B Property",
            unit_name="B1",
        )
        other_lease = Lease(
            organization_id=other_org.id,
            unit_id=other_unit.id,
            guest_id=other_user.id,
            reservation_id=None,
            start_date=date(2026, 5, 1),
            end_date=None,
            rent_amount=Decimal("500.00"),
            deposit_amount=Decimal("0.00"),
            billing_cycle="monthly",
            status="active",
            created_by_id=other_user.id,
        )
        db.session.add(other_lease)
        db.session.flush()
        db.session.add(
            Invoice(
                organization_id=other_org.id,
                lease_id=other_lease.id,
                guest_id=other_user.id,
                invoice_number="INV-OTH-1",
                amount=Decimal("2000.00"),
                subtotal_excl_vat=Decimal("2000.00"),
                vat_rate=Decimal("0.00"),
                vat_amount=Decimal("0.00"),
                total_incl_vat=Decimal("2000.00"),
                currency="EUR",
                due_date=date(2026, 5, 10),
                paid_at=datetime(2026, 5, 10, 8, 0, 0),
                status="paid",
                created_by_id=other_user.id,
            )
        )
        db.session.add(
            Expense(
                organization_id=other_org.id,
                property_id=other_prop.id,
                category="maintenance",
                amount=Decimal("999.00"),
                vat=Decimal("0.00"),
                date=date(2026, 5, 11),
            )
        )
        db.session.commit()

        rows = compute_profitability_by_property(
            start=date(2026, 5, 1),
            end=date(2026, 5, 31),
            organization_id=organization.id,
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["property"] == "Org A Property"
        assert row["income"] == Decimal("1000.00")
        assert row["expenses"] == Decimal("300.00")
        assert row["net"] == Decimal("700.00")


def test_profitability_export_csv_and_xlsx(client, app, organization, admin_user):
    from app.billing.models import Invoice, Lease
    from app.extensions import db

    with app.app_context():
        _, unit = _seed_property_and_unit(
            organization_id=organization.id,
            property_name="Export Property",
            unit_name="E1",
        )
        lease = Lease(
            organization_id=organization.id,
            unit_id=unit.id,
            guest_id=admin_user.id,
            reservation_id=None,
            start_date=date(2026, 5, 1),
            end_date=None,
            rent_amount=Decimal("100.00"),
            deposit_amount=Decimal("0.00"),
            billing_cycle="monthly",
            status="active",
            created_by_id=admin_user.id,
        )
        db.session.add(lease)
        db.session.flush()
        db.session.add(
            Invoice(
                organization_id=organization.id,
                lease_id=lease.id,
                guest_id=admin_user.id,
                invoice_number="INV-EXP-1",
                amount=Decimal("200.00"),
                subtotal_excl_vat=Decimal("200.00"),
                vat_rate=Decimal("0.00"),
                vat_amount=Decimal("0.00"),
                total_incl_vat=Decimal("200.00"),
                currency="EUR",
                due_date=date(2026, 5, 10),
                paid_at=datetime(2026, 5, 10, 8, 0, 0),
                status="paid",
                created_by_id=admin_user.id,
            )
        )
        db.session.commit()

    _login_admin(client, admin_user)
    csv_rv = client.get(
        "/admin/reports/profitability?start_date=2026-05-01&end_date=2026-05-31&export=csv"
    )
    assert csv_rv.status_code == 200
    assert csv_rv.mimetype.startswith("text/csv")
    xlsx_rv = client.get(
        "/admin/reports/profitability?start_date=2026-05-01&end_date=2026-05-31&export=xlsx"
    )
    if xlsx_rv.status_code == 200:
        assert (
            xlsx_rv.mimetype
            == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    else:
        assert xlsx_rv.status_code == 400
