from __future__ import annotations

from datetime import date, timedelta


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def test_admin_can_access_pms_pages(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    properties = client.get("/admin/properties")
    reservations = client.get("/admin/reservations")

    assert properties.status_code == 200
    assert reservations.status_code == 200


def test_admin_can_access_dashboard(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Admin dashboard" in response.data

    dash = client.get("/admin/dashboard")
    assert dash.status_code == 200
    assert b"Admin dashboard" in dash.data


def test_admin_can_open_reservation_creation_form(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="UI Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    db.session.add(Unit(property_id=prop.id, name="101", unit_type="double"))
    db.session.commit()

    response = client.get("/admin/reservations/new")
    assert response.status_code == 200
    assert b"Create reservation" in response.data


def test_normal_user_cannot_access_pms_pages(client, regular_user):
    _login(client, email=regular_user.email, password=regular_user.password_plain)

    response = client.get("/admin/properties", follow_redirects=False)
    assert response.status_code == 403


def test_normal_user_cannot_access_dashboard(client, regular_user):
    _login(client, email=regular_user.email, password=regular_user.password_plain)

    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 403

    dash = client.get("/admin/dashboard", follow_redirects=False)
    assert dash.status_code == 403


def test_normal_user_cannot_access_reservation_creation_page(client, regular_user):
    _login(client, email=regular_user.email, password=regular_user.password_plain)

    response = client.get("/admin/reservations/new", follow_redirects=False)
    assert response.status_code == 403


def test_normal_user_cannot_access_property_and_unit_edit_pages(client, regular_user):
    _login(client, email=regular_user.email, password=regular_user.password_plain)

    property_response = client.get("/admin/properties/1/edit", follow_redirects=False)
    unit_response = client.get("/admin/units/1/edit", follow_redirects=False)
    assert property_response.status_code == 403
    assert unit_response.status_code == 403


def test_admin_sees_only_own_organization_data(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    own_property = Property(
        organization_id=admin_user.organization_id,
        name="Own Property",
        address=None,
    )
    db.session.add(own_property)
    db.session.flush()

    own_unit = Unit(property_id=own_property.id, name="101", unit_type="double")
    db.session.add(own_unit)
    db.session.flush()

    own_res = Reservation(
        unit_id=own_unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
        status="confirmed",
    )
    db.session.add(own_res)

    other_org = Organization(name="Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_user = User(
        email="other-admin@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_property = Property(organization_id=other_org.id, name="Other Property", address=None)
    db.session.add(other_property)
    db.session.flush()
    other_unit = Unit(property_id=other_property.id, name="201", unit_type="single")
    db.session.add(other_unit)
    db.session.flush()
    other_res = Reservation(
        unit_id=other_unit.id,
        guest_id=other_user.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
        status="confirmed",
    )
    db.session.add(other_res)
    db.session.commit()

    properties_page = client.get("/admin/properties")
    reservations_page = client.get("/admin/reservations")

    assert b"Own Property" in properties_page.data
    assert b"Other Property" not in properties_page.data
    assert f"/admin/reservations/{own_res.id}".encode() in reservations_page.data
    assert f"/admin/reservations/{other_res.id}".encode() not in reservations_page.data


def test_admin_can_create_property_through_ui(client, admin_user):
    from app.properties.models import Property

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.post(
        "/admin/properties/new",
        data={"name": "UI Property", "address": "Street 1"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    row = Property.query.filter_by(
        organization_id=admin_user.organization_id,
        name="UI Property",
    ).first()
    assert row is not None


def test_admin_can_create_unit_through_ui(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="UI Hotel", address=None)
    db.session.add(prop)
    db.session.commit()

    response = client.post(
        f"/admin/properties/{prop.id}/units/new",
        data={"name": "301", "unit_type": "suite"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    row = Unit.query.filter_by(property_id=prop.id, name="301").first()
    assert row is not None


def test_admin_can_open_property_edit_page(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(organization_id=admin_user.organization_id, name="Old Name", address="Old Address")
    db.session.add(prop)
    db.session.commit()

    response = client.get(f"/admin/properties/{prop.id}/edit")
    assert response.status_code == 200
    assert b"Edit property" in response.data


def test_admin_can_edit_own_property(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(organization_id=admin_user.organization_id, name="Old Name", address="Old Address")
    db.session.add(prop)
    db.session.commit()

    response = client.post(
        f"/admin/properties/{prop.id}/edit",
        data={"name": "New Name", "address": "New Address"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    refreshed = Property.query.get(prop.id)
    assert refreshed is not None
    assert refreshed.name == "New Name"
    assert refreshed.address == "New Address"


def test_admin_cannot_edit_another_organizations_property(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    other_org = Organization(name="Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_property = Property(organization_id=other_org.id, name="Other Property", address=None)
    db.session.add(other_property)
    db.session.commit()

    response = client.get(f"/admin/properties/{other_property.id}/edit", follow_redirects=False)
    assert response.status_code == 404


def test_admin_can_open_unit_edit_page(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(organization_id=admin_user.organization_id, name="Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    response = client.get(f"/admin/units/{unit.id}/edit")
    assert response.status_code == 200
    assert b"Edit unit" in response.data


def test_admin_can_edit_own_unit(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(organization_id=admin_user.organization_id, name="Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    response = client.post(
        f"/admin/units/{unit.id}/edit",
        data={"name": "102", "unit_type": "suite"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    refreshed = Unit.query.get(unit.id)
    assert refreshed is not None
    assert refreshed.name == "102"
    assert refreshed.unit_type == "suite"


def test_admin_cannot_edit_another_organizations_unit(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    other_org = Organization(name="Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_property = Property(organization_id=other_org.id, name="Other Property", address=None)
    db.session.add(other_property)
    db.session.flush()
    other_unit = Unit(property_id=other_property.id, name="201", unit_type="single")
    db.session.add(other_unit)
    db.session.commit()

    response = client.get(f"/admin/units/{other_unit.id}/edit", follow_redirects=False)
    assert response.status_code == 404


def test_property_update_creates_audit_log(client, admin_user):
    from app.audit.models import AuditLog
    from app.extensions import db
    from app.properties.models import Property

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(organization_id=admin_user.organization_id, name="Old Name", address="Old Address")
    db.session.add(prop)
    db.session.commit()

    response = client.post(
        f"/admin/properties/{prop.id}/edit",
        data={"name": "New Name", "address": "New Address"},
    )
    assert response.status_code == 302

    row = AuditLog.query.filter_by(action="property_updated", target_id=prop.id).first()
    assert row is not None
    assert row.target_type == "property"
    assert row.actor_id == admin_user.id


def test_unit_update_creates_audit_log(client, admin_user):
    from app.audit.models import AuditLog
    from app.extensions import db
    from app.properties.models import Property, Unit

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(organization_id=admin_user.organization_id, name="Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    response = client.post(
        f"/admin/units/{unit.id}/edit",
        data={"name": "102", "unit_type": "suite"},
    )
    assert response.status_code == 302

    row = AuditLog.query.filter_by(action="unit_updated", target_id=unit.id).first()
    assert row is not None
    assert row.target_type == "unit"
    assert row.actor_id == admin_user.id


def test_admin_can_cancel_reservation_through_ui(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="UI Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 3),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = client.post(
        f"/admin/reservations/{res.id}/cancel",
        data={"confirm_cancel": "yes"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    refreshed = Reservation.query.get(res.id)
    assert refreshed is not None
    assert refreshed.status == "cancelled"


def test_admin_can_create_reservation_through_ui(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="UI Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    response = client.post(
        "/admin/reservations/new",
        data={
            "unit_id": str(unit.id),
            "guest_id": str(admin_user.id),
            "start_date": "2026-07-01",
            "end_date": "2026-07-03",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    row = Reservation.query.filter_by(unit_id=unit.id, guest_id=admin_user.id).first()
    assert row is not None
    assert row.status == "confirmed"


def test_reservation_creation_through_ui_creates_audit_log(client, admin_user):
    from app.audit.models import AuditLog
    from app.extensions import db
    from app.properties.models import Property, Unit

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="UI Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.commit()

    create_response = client.post(
        "/admin/reservations/new",
        data={
            "unit_id": str(unit.id),
            "guest_id": str(admin_user.id),
            "start_date": "2026-07-01",
            "end_date": "2026-07-03",
        },
    )
    assert create_response.status_code == 302

    row = AuditLog.query.filter_by(action="reservation_created").first()
    assert row is not None
    assert row.target_type == "reservation"
    assert row.actor_id == admin_user.id


def test_overlapping_reservation_through_ui_is_rejected(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="UI Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_id=admin_user.id,
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 3),
            status="confirmed",
        )
    )
    db.session.commit()

    response = client.post(
        "/admin/reservations/new",
        data={
            "unit_id": str(unit.id),
            "guest_id": str(admin_user.id),
            "start_date": "2026-07-02",
            "end_date": "2026-07-04",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"overlapping reservation" in response.data


def test_superadmin_2fa_is_not_bypassed_for_pms_pages(client, superadmin):
    _login(client, email=superadmin.email, password=superadmin.password_plain)

    response = client.get("/admin/properties", follow_redirects=False)
    assert response.status_code == 302
    assert "/2fa/verify" in response.headers["Location"]


def test_dashboard_shows_correct_counts_for_admin_organization(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit1 = Unit(property_id=prop.id, name="101", unit_type="double")
    unit2 = Unit(property_id=prop.id, name="102", unit_type="double")
    db.session.add(unit1)
    db.session.add(unit2)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=unit1.id,
            guest_id=admin_user.id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            status="confirmed",
        )
    )
    db.session.add(
        Reservation(
            unit_id=unit2.id,
            guest_id=admin_user.id,
            start_date=date(2026, 9, 4),
            end_date=date(2026, 9, 6),
            status="cancelled",
        )
    )
    db.session.commit()

    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Total properties" in response.data
    assert b">1<" in response.data
    assert b"Total units" in response.data
    assert b">2<" in response.data
    assert b"Active reservations" in response.data
    assert b"Cancelled reservations" in response.data


def test_dashboard_occupancy_percent_matches_nightly_logic(client, admin_user):
    from unittest.mock import patch

    from app.admin import services as admin_services
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit_booked = Unit(property_id=prop.id, name="101", unit_type="double")
    unit_free = Unit(property_id=prop.id, name="102", unit_type="double")
    db.session.add(unit_booked)
    db.session.add(unit_free)
    db.session.flush()
    fixed_today = date(2026, 4, 26)
    db.session.add(
        Reservation(
            unit_id=unit_booked.id,
            guest_id=admin_user.id,
            start_date=fixed_today,
            end_date=fixed_today + timedelta(days=2),
            status="confirmed",
        )
    )
    db.session.commit()

    with patch("app.admin.services.date") as mock_date:
        mock_date.today.return_value = fixed_today
        stats = admin_services.get_dashboard_stats(organization_id=admin_user.organization_id)

    assert stats["occupancy_percent"] == 50.0
    assert stats["occupancy_percent"] == stats["occupancy_percentage"]
    assert stats["current_guests"] == 1
    assert stats["arrivals_today"] == 1
    assert stats["departures_today"] == 0
    assert stats["upcoming_reservations"] == 0

    with patch("app.admin.services.date") as mock_date:
        mock_date.today.return_value = fixed_today
        page = client.get("/admin")
    assert page.status_code == 200
    assert b"50.0" in page.data


def test_dashboard_latest_audit_events_appear(client, admin_user):
    from app.audit import record as audit_record
    from app.audit.models import AuditStatus

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    audit_record(
        "dashboard.test.event",
        status=AuditStatus.SUCCESS,
        organization_id=admin_user.organization_id,
        target_type="test",
        target_id=1,
        commit=True,
    )

    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Latest audit events" in response.data
    assert b"dashboard.test.event" in response.data


def test_dashboard_respects_tenant_isolation(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    own_prop = Property(organization_id=admin_user.organization_id, name="Own Hotel", address=None)
    db.session.add(own_prop)
    db.session.flush()
    own_unit = Unit(property_id=own_prop.id, name="101", unit_type="double")
    db.session.add(own_unit)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=own_unit.id,
            guest_id=admin_user.id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            status="confirmed",
        )
    )

    other_org = Organization(name="Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_user = User(
        email="other-dashboard@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_prop = Property(organization_id=other_org.id, name="Other Hotel", address=None)
    db.session.add(other_prop)
    db.session.flush()
    other_unit = Unit(property_id=other_prop.id, name="201", unit_type="single")
    db.session.add(other_unit)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=other_unit.id,
            guest_id=other_user.id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            status="confirmed",
        )
    )
    db.session.commit()

    response = client.get("/admin")
    assert response.status_code == 200
    assert b"Other Hotel" not in response.data


def test_admin_can_access_reports_index(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.get("/admin/reports")
    assert response.status_code == 200
    assert b"Reports" in response.data


def test_normal_user_cannot_access_reports(client, regular_user):
    _login(client, email=regular_user.email, password=regular_user.password_plain)

    response = client.get("/admin/reports", follow_redirects=False)
    assert response.status_code == 403


def test_occupancy_report_calculates_correctly(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit1 = Unit(property_id=prop.id, name="101", unit_type="double")
    unit2 = Unit(property_id=prop.id, name="102", unit_type="double")
    db.session.add(unit1)
    db.session.add(unit2)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=unit1.id,
            guest_id=admin_user.id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 3),
            status="confirmed",
        )
    )
    db.session.commit()

    response = client.get("/admin/reports/occupancy?start_date=2026-08-01&end_date=2026-08-04")
    assert response.status_code == 200
    assert b"Total units" in response.data
    assert b">2<" in response.data
    assert b"Reserved units" in response.data
    assert b">1<" in response.data
    assert b">50.0<" in response.data


def test_reservation_report_calculates_confirmed_and_cancelled(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_id=admin_user.id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 3),
            status="confirmed",
        )
    )
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_id=admin_user.id,
            start_date=date(2026, 8, 5),
            end_date=date(2026, 8, 7),
            status="cancelled",
        )
    )
    db.session.commit()

    response = client.get("/admin/reports/reservations")
    assert response.status_code == 200
    assert b"Total reservations" in response.data
    assert b">2<" in response.data
    assert b"Confirmed reservations" in response.data
    assert b">1<" in response.data
    assert b"Cancelled reservations" in response.data
    assert b">1<" in response.data


def test_reports_respect_tenant_isolation(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    own_prop = Property(organization_id=admin_user.organization_id, name="Own Hotel", address=None)
    db.session.add(own_prop)
    db.session.flush()
    own_unit = Unit(property_id=own_prop.id, name="101", unit_type="double")
    db.session.add(own_unit)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=own_unit.id,
            guest_id=admin_user.id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 3),
            status="confirmed",
        )
    )

    other_org = Organization(name="Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_user = User(
        email="other-report@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_prop = Property(organization_id=other_org.id, name="Other Hotel", address=None)
    db.session.add(other_prop)
    db.session.flush()
    other_unit = Unit(property_id=other_prop.id, name="201", unit_type="single")
    db.session.add(other_unit)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=other_unit.id,
            guest_id=other_user.id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 3),
            status="confirmed",
        )
    )
    db.session.commit()

    occupancy = client.get("/admin/reports/occupancy?start_date=2026-08-01&end_date=2026-08-04")
    reservation_report = client.get("/admin/reports/reservations")

    assert occupancy.status_code == 200
    assert b">1<" in occupancy.data
    assert reservation_report.status_code == 200
    assert b"Total reservations" in reservation_report.data
    assert b">1<" in reservation_report.data


def test_occupancy_invalid_date_range_is_rejected(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.get("/admin/reports/occupancy?start_date=2026-08-05&end_date=2026-08-01")
    assert response.status_code == 200
    assert b"Start date must be before end date." in response.data


def test_admin_can_access_calendar(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.get("/admin/calendar")
    assert response.status_code == 200
    assert b"Reservation calendar" in response.data
    assert b"fullcalendar" in response.data.lower()


def test_normal_user_cannot_access_calendar(client, regular_user):
    _login(client, email=regular_user.email, password=regular_user.password_plain)

    response = client.get("/admin/calendar", follow_redirects=False)
    assert response.status_code == 403


def test_calendar_events_returns_only_same_organization(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    own_prop = Property(organization_id=admin_user.organization_id, name="Own Hotel", address=None)
    db.session.add(own_prop)
    db.session.flush()
    own_unit = Unit(property_id=own_prop.id, name="101", unit_type="double")
    db.session.add(own_unit)
    db.session.flush()
    own_res = Reservation(
        unit_id=own_unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 5, 10),
        end_date=date(2026, 5, 14),
        status="confirmed",
    )
    db.session.add(own_res)

    other_org = Organization(name="Other Org Cal")
    db.session.add(other_org)
    db.session.flush()
    other_user = User(
        email="other-cal@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_prop = Property(organization_id=other_org.id, name="Other Hotel", address=None)
    db.session.add(other_prop)
    db.session.flush()
    other_unit = Unit(property_id=other_prop.id, name="201", unit_type="single")
    db.session.add(other_unit)
    db.session.flush()
    other_res = Reservation(
        unit_id=other_unit.id,
        guest_id=other_user.id,
        start_date=date(2026, 5, 10),
        end_date=date(2026, 5, 14),
        status="confirmed",
    )
    db.session.add(other_res)
    db.session.commit()

    response = client.get("/admin/calendar/events?start=2026-05-01&end=2026-05-31")
    assert response.status_code == 200
    data = response.get_json()
    assert isinstance(data, list)
    ids = {item["id"] for item in data}
    assert own_res.id in ids
    assert other_res.id not in ids


def test_calendar_events_json_shape_and_cancelled_status(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="303", unit_type="suite")
    db.session.add(unit)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_id=admin_user.id,
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 4),
            status="confirmed",
        )
    )
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_id=admin_user.id,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 12),
            status="cancelled",
        )
    )
    db.session.commit()

    response = client.get("/admin/calendar/events?start=2026-06-01&end=2026-06-30")
    assert response.status_code == 200
    data = response.get_json()
    assert len(data) == 2
    required = {"id", "title", "start", "end", "status", "unit_id", "property_id", "url"}
    statuses = []
    starts = set()
    for item in data:
        assert set(item.keys()) == required
        starts.add(item["start"])
        assert item["property_id"] == prop.id
        statuses.append(item["status"])
    assert starts == {"2026-06-01", "2026-06-10"}
    assert "confirmed" in statuses
    assert "cancelled" in statuses


def test_calendar_event_includes_edit_url(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="URL Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 8, 10),
        end_date=date(2026, 8, 12),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = client.get("/admin/calendar/events?start=2026-08-01&end=2026-08-31")
    assert response.status_code == 200
    items = response.get_json()
    match = next(x for x in items if x["id"] == res.id)
    assert match["url"] == f"/admin/reservations/{res.id}/edit"


def test_calendar_events_invalid_start_returns_400(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.get("/admin/calendar/events?start=not-a-date")
    assert response.status_code == 400


def test_admin_can_open_reservation_edit_page(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Edit Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="E1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 5),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = client.get(f"/admin/reservations/{res.id}/edit")
    assert response.status_code == 200
    assert b"Edit reservation" in response.data
    assert b"Guest name" in response.data


def test_admin_can_update_reservation_via_edit_form(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Edit Hotel 2", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="E2", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 11, 1),
        end_date=date(2026, 11, 4),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = client.post(
        f"/admin/reservations/{res.id}/edit",
        data={
            "guest_name": admin_user.email,
            "property_id": str(prop.id),
            "unit_id": str(unit.id),
            "start_date": "2026-11-02",
            "end_date": "2026-11-06",
            "status": "confirmed",
            "return_to": "detail",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    refreshed = Reservation.query.get(res.id)
    assert refreshed is not None
    assert refreshed.start_date == date(2026, 11, 2)
    assert refreshed.end_date == date(2026, 11, 6)


def test_normal_user_cannot_open_reservation_edit(client, regular_user):
    _login(client, email=regular_user.email, password=regular_user.password_plain)

    response = client.get("/admin/reservations/1/edit", follow_redirects=False)
    assert response.status_code == 403


def test_admin_cannot_edit_other_organizations_reservation(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    other_org = Organization(name="Edit Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_user = User(
        email="other-edit@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_prop = Property(organization_id=other_org.id, name="Foreign", address=None)
    db.session.add(other_prop)
    db.session.flush()
    other_unit = Unit(property_id=other_prop.id, name="X1", unit_type="single")
    db.session.add(other_unit)
    db.session.flush()
    other_res = Reservation(
        unit_id=other_unit.id,
        guest_id=other_user.id,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 5),
        status="confirmed",
    )
    db.session.add(other_res)
    db.session.commit()

    get_resp = client.get(f"/admin/reservations/{other_res.id}/edit", follow_redirects=False)
    assert get_resp.status_code == 404

    post_resp = client.post(
        f"/admin/reservations/{other_res.id}/edit",
        data={
            "guest_name": admin_user.email,
            "property_id": "1",
            "unit_id": "1",
            "start_date": "2026-12-01",
            "end_date": "2026-12-05",
            "status": "confirmed",
            "return_to": "calendar",
        },
        follow_redirects=False,
    )
    assert post_resp.status_code == 404


def test_reservation_edit_rejects_start_not_before_end(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Bad Dates", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="B1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 10, 10),
        end_date=date(2026, 10, 15),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = client.post(
        f"/admin/reservations/{res.id}/edit",
        data={
            "guest_name": admin_user.email,
            "property_id": str(prop.id),
            "unit_id": str(unit.id),
            "start_date": "2026-10-20",
            "end_date": "2026-10-18",
            "status": "confirmed",
            "return_to": "calendar",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"must be before" in response.data


def test_reservation_edit_rejects_overlapping_dates(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Overlap Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="O1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    first = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        status="confirmed",
    )
    second = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 14),
        status="confirmed",
    )
    db.session.add(first)
    db.session.add(second)
    db.session.commit()

    response = client.post(
        f"/admin/reservations/{second.id}/edit",
        data={
            "guest_name": admin_user.email,
            "property_id": str(prop.id),
            "unit_id": str(unit.id),
            "start_date": "2026-09-02",
            "end_date": "2026-09-12",
            "status": "confirmed",
            "return_to": "calendar",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"overlapping reservation" in response.data


def test_reservation_edit_same_dates_succeeds_without_self_overlap(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Self Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="S1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 8, 20),
        end_date=date(2026, 8, 25),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = client.post(
        f"/admin/reservations/{res.id}/edit",
        data={
            "guest_name": admin_user.email,
            "property_id": str(prop.id),
            "unit_id": str(unit.id),
            "start_date": "2026-08-20",
            "end_date": "2026-08-25",
            "status": "confirmed",
            "return_to": "calendar",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302


def test_reservation_edit_creates_audit_log(client, admin_user):
    from app.audit.models import AuditLog
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Audit Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 5),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = client.post(
        f"/admin/reservations/{res.id}/edit",
        data={
            "guest_name": admin_user.email,
            "property_id": str(prop.id),
            "unit_id": str(unit.id),
            "start_date": "2026-07-01",
            "end_date": "2026-07-06",
            "status": "confirmed",
            "return_to": "detail",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    row = AuditLog.query.filter_by(action="reservation_updated", target_id=res.id).first()
    assert row is not None
    assert row.target_type == "reservation"
    assert row.actor_id == admin_user.id


def test_calendar_events_start_end_filter_excludes_outside_range(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Filter Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    inside = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 7, 5),
        end_date=date(2026, 7, 10),
        status="confirmed",
    )
    before_window = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 5),
        status="confirmed",
    )
    after_window = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        status="confirmed",
    )
    db.session.add(inside)
    db.session.add(before_window)
    db.session.add(after_window)
    db.session.commit()

    response = client.get("/admin/calendar/events?start=2026-07-01&end=2026-07-31")
    assert response.status_code == 200
    ids = {item["id"] for item in response.get_json()}
    assert inside.id in ids
    assert before_window.id not in ids
    assert after_window.id not in ids
