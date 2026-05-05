from __future__ import annotations

import json
import re
from datetime import date, timedelta
from decimal import Decimal

import pyotp
from app.extensions import db
from app.organizations.models import Organization
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.billing.models import Invoice
from app.maintenance.models import MaintenanceRequest


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _login_superadmin_2fa(client, superadmin):
    _login(client, email=superadmin.email, password=superadmin.password_plain)
    code = pyotp.TOTP(superadmin.totp_secret).now()
    return client.post("/2fa/verify", data={"code": code}, follow_redirects=False)


def _seed_property_unit(org_id: int, property_name: str, unit_name: str) -> tuple[Property, Unit]:
    prop = Property(organization_id=org_id, name=property_name, address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name=unit_name, unit_type="std")
    db.session.add(unit)
    db.session.flush()
    return prop, unit


def test_kpi_calculations_use_organization_filter(app, admin_user):
    from app.admin.services import dashboard_summary

    with app.app_context():
        org_a = admin_user.organization_id
        org_b = Organization(name="Other Org")
        db.session.add(org_b)
        db.session.flush()

        _, unit_a = _seed_property_unit(org_a, "A Property", "A1")
        _, unit_b = _seed_property_unit(org_b.id, "B Property", "B1")

        db.session.add(
            Reservation(
                unit_id=unit_a.id,
                guest_id=admin_user.id,
                guest_name="A Guest",
                start_date=date.today(),
                end_date=date.today() + timedelta(days=2),
                status="confirmed",
                amount=Decimal("100.00"),
            )
        )
        db.session.add(
            Reservation(
                unit_id=unit_b.id,
                guest_id=admin_user.id,
                guest_name="B Guest",
                start_date=date.today(),
                end_date=date.today() + timedelta(days=3),
                status="confirmed",
                amount=Decimal("999.00"),
            )
        )
        db.session.add(
            Invoice(
                organization_id=org_b.id,
                amount=Decimal("10.00"),
                subtotal_excl_vat=Decimal("10.00"),
                total_incl_vat=Decimal("10.00"),
                vat_amount=Decimal("0.00"),
                vat_rate=Decimal("0.00"),
                due_date=date.today(),
                status="overdue",
                created_by_id=admin_user.id,
            )
        )
        db.session.add(
            MaintenanceRequest(
                organization_id=org_b.id,
                property_id=unit_b.property_id,
                unit_id=unit_b.id,
                title="B fix",
                status="new",
                priority="normal",
                created_by_id=admin_user.id,
            )
        )
        db.session.commit()

        summary = dashboard_summary(organization_id=org_a)
        assert summary["kpi"]["active_reservations"] == 1
        assert summary["kpi"]["overdue_invoices"] == 0
        assert summary["kpi"]["open_maintenance"] == 0


def test_kpi_revenue_excludes_cancelled_reservations(app, admin_user):
    from app.admin.services import dashboard_summary

    with app.app_context():
        _, unit = _seed_property_unit(admin_user.organization_id, "Revenue Property", "R1")
        db.session.add_all(
            [
                Reservation(
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    guest_name="Confirmed",
                    start_date=date.today(),
                    end_date=date.today() + timedelta(days=2),
                    status="confirmed",
                    amount=Decimal("250.00"),
                ),
                Reservation(
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    guest_name="Cancelled",
                    start_date=date.today(),
                    end_date=date.today() + timedelta(days=1),
                    status="cancelled",
                    amount=Decimal("900.00"),
                ),
            ]
        )
        db.session.commit()

        summary = dashboard_summary(organization_id=admin_user.organization_id)
        assert summary["kpi"]["revenue_this_month"] == Decimal("250.00")


def test_dashboard_does_not_query_other_orgs(client, app, admin_user):
    from werkzeug.security import generate_password_hash

    from app.users.models import User, UserRole

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    with app.app_context():
        other_org = Organization(name="Tenant B")
        db.session.add(other_org)
        db.session.flush()
        other_org_id = other_org.id
        other_user = User(
            email="tenantb@test.local",
            password_hash=generate_password_hash("Pass123!"),
            organization_id=other_org_id,
            role=UserRole.ADMIN.value,
            is_active=True,
        )
        db.session.add(other_user)
        _, unit_b = _seed_property_unit(other_org_id, "Other Org Prop", "B1")
        db.session.add(
            Reservation(
                unit_id=unit_b.id,
                guest_id=other_user.id,
                guest_name="Other",
                start_date=date.today(),
                end_date=date.today() + timedelta(days=1),
                status="confirmed",
                amount=Decimal("1000.00"),
            )
        )
        db.session.commit()

    response = client.get(f"/admin?organization_id={other_org_id}")
    assert response.status_code == 200
    assert b"Other Org Prop" not in response.data


def test_dashboard_renders_skeleton_when_data_missing(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin")
    assert response.status_code == 200
    text = response.get_data(as_text=True)
    assert ("Lisää kohteet ensin" in text) or ("Liian vähän dataa graafiin" in text)


def test_dashboard_renders_chart_data_as_json(client, app, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    with app.app_context():
        _, unit = _seed_property_unit(admin_user.organization_id, "Chart Property", "C1")
        for i in range(6):
            start = date.today() - timedelta(days=i)
            db.session.add(
                Reservation(
                    unit_id=unit.id,
                    guest_id=admin_user.id,
                    guest_name=f"Guest {i}",
                    start_date=start,
                    end_date=start + timedelta(days=1),
                    status="confirmed",
                    amount=Decimal("100.00"),
                )
            )
        db.session.commit()

    response = client.get("/admin")
    html = response.get_data(as_text=True)
    assert 'id="dashboard-data"' in html
    match = re.search(
        r'<script type="application/json" id="dashboard-data">(.*?)</script>',
        html,
        flags=re.DOTALL,
    )
    assert match is not None
    payload = json.loads(match.group(1))
    assert "trend_revenue_30d" in payload
    assert "trend_occupancy_30d" in payload


def test_superadmin_can_select_organization(client, app, superadmin):
    _login_superadmin_2fa(client, superadmin)
    with app.app_context():
        org_b = Organization(name="Selected Org")
        db.session.add(org_b)
        db.session.flush()
        org_b_id = org_b.id
        _, unit_b = _seed_property_unit(org_b_id, "Selected Property", "S1")
        db.session.add(
            Reservation(
                unit_id=unit_b.id,
                guest_id=superadmin.id,
                guest_name="Selected Guest",
                start_date=date.today(),
                end_date=date.today() + timedelta(days=2),
                status="confirmed",
                amount=Decimal("420.00"),
            )
        )
        db.session.commit()

    response = client.get(f"/admin?organization_id={org_b_id}")
    assert response.status_code == 200
    assert b"Selected Property" in response.data
