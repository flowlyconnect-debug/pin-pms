from __future__ import annotations

from datetime import date


def _portal_login(client, *, email: str, password: str):
    return client.post(
        "/portal/login",
        data={
            "email": email,
            "password": password,
        },
        follow_redirects=False,
    )


def test_portal_guest_login_works(client, regular_user):
    response = _portal_login(
        client,
        email=regular_user.email,
        password=regular_user.password_plain,
    )
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/portal/dashboard")


def test_portal_guest_cannot_access_another_guest_reservation(client, regular_user):
    from werkzeug.security import generate_password_hash

    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole

    _portal_login(client, email=regular_user.email, password=regular_user.password_plain)

    prop = Property(organization_id=regular_user.organization_id, name="Portal Prop", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="P1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    other_user = User(
        email="other-portal@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=regular_user.organization_id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_res = Reservation(
        unit_id=unit.id,
        guest_id=other_user.id,
        guest_name=other_user.email,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 4),
        status="confirmed",
    )
    db.session.add(other_res)
    db.session.commit()

    detail = client.get(f"/portal/reservations/{other_res.id}", follow_redirects=False)
    assert detail.status_code == 404


def test_portal_guest_can_view_own_invoices_only(client, regular_user):
    from werkzeug.security import generate_password_hash

    from app.billing.models import Invoice
    from app.extensions import db
    from app.users.models import User, UserRole

    _portal_login(client, email=regular_user.email, password=regular_user.password_plain)

    own = Invoice(
        organization_id=regular_user.organization_id,
        lease_id=None,
        reservation_id=None,
        guest_id=regular_user.id,
        invoice_number="BIL-OWN-001",
        amount=200,
        currency="EUR",
        due_date=date(2026, 6, 10),
        paid_at=None,
        status="open",
        description=None,
        metadata_json=None,
        created_by_id=regular_user.id,
        updated_by_id=None,
    )
    db.session.add(own)
    other_user = User(
        email="other-invoice-portal@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=regular_user.organization_id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other = Invoice(
        organization_id=regular_user.organization_id,
        lease_id=None,
        reservation_id=None,
        guest_id=other_user.id,
        invoice_number="BIL-OTHER-001",
        amount=300,
        currency="EUR",
        due_date=date(2026, 6, 11),
        paid_at=None,
        status="overdue",
        description=None,
        metadata_json=None,
        created_by_id=other_user.id,
        updated_by_id=None,
    )
    db.session.add(other)
    db.session.commit()

    response = client.get("/portal/invoices")
    assert response.status_code == 200
    assert b"BIL-OWN-001" in response.data
    assert b"BIL-OTHER-001" not in response.data


def test_portal_guest_can_create_maintenance_request(client, regular_user):
    from app.extensions import db
    from app.maintenance.models import MaintenanceRequest
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _portal_login(client, email=regular_user.email, password=regular_user.password_plain)

    prop = Property(organization_id=regular_user.organization_id, name="Maint Prop", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="M1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=regular_user.id,
        guest_name=regular_user.email,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 4),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = client.post(
        "/portal/maintenance",
        data={
            "reservation_id": str(res.id),
            "title": "Broken shower",
            "description": "No hot water",
            "priority": "high",
            "due_date": "2026-07-03",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    row = MaintenanceRequest.query.filter_by(
        organization_id=regular_user.organization_id,
        guest_id=regular_user.id,
        title="Broken shower",
    ).first()
    assert row is not None
    assert row.reservation_id == res.id


def test_portal_isolation_enforced_between_guests(client, regular_user):
    from werkzeug.security import generate_password_hash

    from app.extensions import db
    from app.maintenance.models import MaintenanceRequest
    from app.organizations.models import Organization
    from app.properties.models import Property
    from app.users.models import User, UserRole

    _portal_login(client, email=regular_user.email, password=regular_user.password_plain)

    own_org_prop = Property(
        organization_id=regular_user.organization_id, name="Own Org Prop", address=None
    )
    db.session.add(own_org_prop)
    db.session.flush()
    other_same_org = User(
        email="same-org-other@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=regular_user.organization_id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other_same_org)
    db.session.flush()
    db.session.add(
        MaintenanceRequest(
            organization_id=regular_user.organization_id,
            property_id=own_org_prop.id,
            unit_id=None,
            guest_id=other_same_org.id,
            reservation_id=None,
            title="Other same org",
            description=None,
            status="new",
            priority="normal",
            assigned_to_id=None,
            due_date=None,
            resolved_at=None,
            created_by_id=other_same_org.id,
        )
    )

    other_org = Organization(name="Portal Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_org_user = User(
        email="other-org-portal@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=other_org.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other_org_user)
    db.session.flush()
    other_org_prop = Property(organization_id=other_org.id, name="Other Org Prop", address=None)
    db.session.add(other_org_prop)
    db.session.flush()
    db.session.add(
        MaintenanceRequest(
            organization_id=other_org.id,
            property_id=other_org_prop.id,
            unit_id=None,
            guest_id=other_org_user.id,
            reservation_id=None,
            title="Other org request",
            description=None,
            status="new",
            priority="normal",
            assigned_to_id=None,
            due_date=None,
            resolved_at=None,
            created_by_id=other_org_user.id,
        )
    )
    db.session.commit()

    page = client.get("/portal/maintenance")
    assert page.status_code == 200
    assert b"Other same org" not in page.data
    assert b"Other org request" not in page.data
