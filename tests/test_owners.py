from __future__ import annotations

from datetime import date
from decimal import Decimal


def _seed_property_unit_and_reservation(
    *, organization_id: int, amount: str, start_date: date, end_date: date
):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    prop = Property(organization_id=organization_id, name="Owner Prop", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U1", unit_type="studio")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=None,
        guest_name="Guest",
        start_date=start_date,
        end_date=end_date,
        status="confirmed",
        amount=Decimal(amount),
        currency="EUR",
    )
    db.session.add(res)
    db.session.commit()
    return prop, unit, res


def test_owner_50_50_split_revenue(client, organization):
    from app.extensions import db
    from app.owners.services import assign_property, create_owner, generate_monthly_payout

    prop, _unit, _res = _seed_property_unit_and_reservation(
        organization_id=organization.id,
        amount="1000.00",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 6),
    )
    with client.application.app_context():
        owner = create_owner(
            organization_id=organization.id,
            name="Owner One",
            email="owner1@test.local",
            phone=None,
            payout_iban=None,
        )
        assign_property(
            owner_id=owner.id,
            organization_id=organization.id,
            property_id=prop.id,
            ownership_pct=Decimal("0.50"),
            management_fee_pct=Decimal("0.00"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
        )
        db.session.commit()
        payout = generate_monthly_payout(owner_id=owner.id, period_month="2026-05")
        assert payout.gross_revenue_cents == 50000


def test_owner_management_fee_before_net(client, organization):
    from app.extensions import db
    from app.owners.services import assign_property, create_owner, generate_monthly_payout

    prop, _unit, _res = _seed_property_unit_and_reservation(
        organization_id=organization.id,
        amount="1000.00",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 6),
    )
    with client.application.app_context():
        owner = create_owner(
            organization_id=organization.id,
            name="Owner Fee",
            email="ownerfee@test.local",
            phone=None,
            payout_iban=None,
        )
        assign_property(
            owner_id=owner.id,
            organization_id=organization.id,
            property_id=prop.id,
            ownership_pct=Decimal("1.0"),
            management_fee_pct=Decimal("0.15"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
        )
        db.session.commit()
        payout = generate_monthly_payout(owner_id=owner.id, period_month="2026-05")
        assert payout.gross_revenue_cents == 100000
        assert payout.management_fee_cents == 15000
        assert payout.net_payout_cents == 85000


def test_owner_assignment_prorata_across_month(client, organization):
    from app.extensions import db
    from app.owners.services import assign_property, create_owner, generate_monthly_payout

    prop, _unit, _res = _seed_property_unit_and_reservation(
        organization_id=organization.id,
        amount="310.00",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 6, 1),
    )
    with client.application.app_context():
        owner = create_owner(
            organization_id=organization.id,
            name="Owner Prorata",
            email="ownerprorata@test.local",
            phone=None,
            payout_iban=None,
        )
        assign_property(
            owner_id=owner.id,
            organization_id=organization.id,
            property_id=prop.id,
            ownership_pct=Decimal("1.0"),
            management_fee_pct=Decimal("0.0"),
            valid_from=date(2026, 5, 16),
            valid_to=None,
        )
        db.session.commit()
        payout = generate_monthly_payout(owner_id=owner.id, period_month="2026-05")
        # 16 days out of 31 -> 160.00 EUR
        assert payout.gross_revenue_cents == 16000


def test_owner_portal_isolated_to_assigned_properties(client, organization):
    from app.extensions import db
    from app.owners.services import assign_property, create_owner, create_owner_user
    from app.properties.models import Property

    with client.application.app_context():
        owner = create_owner(
            organization_id=organization.id,
            name="Owner Portal",
            email="ownerportal@test.local",
            phone=None,
            payout_iban=None,
        )
        create_owner_user(
            owner_id=owner.id, email="ownerportal@test.local", password="OwnerPass123!"
        )
        p1 = Property(organization_id=organization.id, name="P1", address=None)
        p2 = Property(organization_id=organization.id, name="P2", address=None)
        db.session.add_all([p1, p2])
        db.session.flush()
        assign_property(
            owner_id=owner.id,
            organization_id=organization.id,
            property_id=p1.id,
            ownership_pct=Decimal("1.0"),
            management_fee_pct=Decimal("0.0"),
            valid_from=date(2026, 1, 1),
            valid_to=None,
        )
        db.session.commit()
        p1_id = p1.id
        p2_id = p2.id

    login = client.post(
        "/owner/login", data={"email": "ownerportal@test.local", "password": "OwnerPass123!"}
    )
    assert login.status_code == 302
    client.post("/owner/2fa", data={})
    ok = client.get(f"/owner/properties/{p1_id}/calendar")
    denied = client.get(f"/owner/properties/{p2_id}/calendar")
    assert ok.status_code == 200
    assert denied.status_code == 404


def test_owner_cannot_access_admin_views(client, organization):
    from app.extensions import db
    from app.owners.services import create_owner, create_owner_user

    with client.application.app_context():
        owner = create_owner(
            organization_id=organization.id,
            name="Owner NoAdmin",
            email="owner-noadmin@test.local",
            phone=None,
            payout_iban=None,
        )
        create_owner_user(
            owner_id=owner.id, email="owner-noadmin@test.local", password="OwnerPass123!"
        )
        db.session.commit()
    client.post(
        "/owner/login", data={"email": "owner-noadmin@test.local", "password": "OwnerPass123!"}
    )
    client.post("/owner/2fa", data={})
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code in (302, 401, 403)
