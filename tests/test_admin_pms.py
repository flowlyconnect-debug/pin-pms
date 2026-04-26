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


def test_admin_can_see_reservation_detail_with_labels(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Detail Prop", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U9", unit_type="suite")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 5, 10),
        end_date=date(2026, 5, 14),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    page = client.get(f"/admin/reservations/{res.id}")
    assert page.status_code == 200
    assert admin_user.email.encode() in page.data
    assert b"Detail Prop" in page.data
    assert b"U9" in page.data
    assert b"2026-05-10" in page.data
    assert b"confirmed" in page.data
    assert b"Edit reservation" in page.data


def test_admin_cancel_reservation_creates_audit_log(client, admin_user):
    from app.audit.models import AuditLog
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Audit Cancel Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="AC1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 5, 20),
        end_date=date(2026, 5, 22),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = client.post(
        f"/admin/reservations/{res.id}/cancel",
        data={"confirm_cancel": "yes"},
        follow_redirects=False,
    )
    assert response.status_code == 302

    log = AuditLog.query.filter_by(action="reservation_cancelled", target_id=res.id).first()
    assert log is not None
    assert log.target_type == "reservation"
    assert log.actor_id == admin_user.id


def test_admin_cannot_cancel_other_organization_reservation(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    other_org = Organization(name="Cancel Foreign Org")
    db.session.add(other_org)
    db.session.flush()
    other_user = User(
        email="foreign-cancel@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_prop = Property(organization_id=other_org.id, name="Foreign Prop", address=None)
    db.session.add(other_prop)
    db.session.flush()
    other_unit = Unit(property_id=other_prop.id, name="FX", unit_type="single")
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

    response = client.post(
        f"/admin/reservations/{other_res.id}/cancel",
        data={"confirm_cancel": "yes"},
        follow_redirects=False,
    )
    assert response.status_code == 404


def test_cancel_reservation_idempotent_no_duplicate_audit(app, admin_user):
    from app.audit.models import AuditLog
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations import services as reservation_services
    from app.reservations.models import Reservation

    with app.app_context():
        prop = Property(organization_id=admin_user.organization_id, name="Idem Hotel", address=None)
        db.session.add(prop)
        db.session.flush()
        unit = Unit(property_id=prop.id, name="I1", unit_type="double")
        db.session.add(unit)
        db.session.flush()
        res = Reservation(
            unit_id=unit.id,
            guest_id=admin_user.id,
            start_date=date(2026, 6, 10),
            end_date=date(2026, 6, 12),
            status="confirmed",
        )
        db.session.add(res)
        db.session.commit()

        reservation_services.cancel_reservation(
            organization_id=admin_user.organization_id,
            reservation_id=res.id,
            actor_user_id=admin_user.id,
        )
        count_after_first = AuditLog.query.filter_by(
            action="reservation_cancelled",
            target_id=res.id,
        ).count()
        assert count_after_first == 1

        reservation_services.cancel_reservation(
            organization_id=admin_user.organization_id,
            reservation_id=res.id,
            actor_user_id=admin_user.id,
        )
        count_after_second = AuditLog.query.filter_by(
            action="reservation_cancelled",
            target_id=res.id,
        ).count()
        assert count_after_second == 1
        assert Reservation.query.get(res.id).status == "cancelled"


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
    assert b"All properties" in response.data
    assert b"All units" in response.data


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
    required = {
        "id",
        "title",
        "start",
        "end",
        "status",
        "unit_id",
        "property_id",
        "color",
        "extendedProps",
        "url",
        "editable",
    }
    statuses = []
    starts = set()
    titles = set()
    colors_by_status = {}
    for item in data:
        assert set(item.keys()) == required
        assert item["editable"] == (item["status"] != "cancelled")
        starts.add(item["start"])
        assert item["property_id"] == prop.id
        titles.add(item["title"])
        colors_by_status[item["status"]] = item["color"]
        assert set(item["extendedProps"].keys()) == {
            "guest_name",
            "guest_id",
            "property_name",
            "unit_name",
            "status",
            "unit_id",
        }
        assert item["extendedProps"]["guest_name"] == admin_user.email
        assert item["extendedProps"]["property_name"] == "Hotel"
        assert item["extendedProps"]["unit_name"] == "303"
        assert item["extendedProps"]["status"] == item["status"]
        assert item["extendedProps"]["unit_id"] == unit.id
        statuses.append(item["status"])
    assert starts == {"2026-06-01", "2026-06-10"}
    assert "confirmed" in statuses
    assert "cancelled" in statuses
    assert f"{admin_user.email.split('@', 1)[0]} – 303" in titles
    assert colors_by_status["confirmed"] == "#10b981"
    assert colors_by_status["cancelled"] == "#9ca3af"


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


def test_calendar_events_property_filter(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop_a = Property(organization_id=admin_user.organization_id, name="Cal Prop A", address=None)
    prop_b = Property(organization_id=admin_user.organization_id, name="Cal Prop B", address=None)
    db.session.add_all([prop_a, prop_b])
    db.session.flush()
    unit_a = Unit(property_id=prop_a.id, name="A1", unit_type="double")
    unit_b = Unit(property_id=prop_b.id, name="B1", unit_type="double")
    db.session.add_all([unit_a, unit_b])
    db.session.flush()
    res_a = Reservation(
        unit_id=unit_a.id,
        guest_id=admin_user.id,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 5),
        status="confirmed",
    )
    res_b = Reservation(
        unit_id=unit_b.id,
        guest_id=admin_user.id,
        start_date=date(2026, 3, 10),
        end_date=date(2026, 3, 14),
        status="confirmed",
    )
    db.session.add_all([res_a, res_b])
    db.session.commit()

    base = "/admin/calendar/events?start=2026-03-01&end=2026-03-31"
    all_ids = {item["id"] for item in client.get(base).get_json()}
    assert all_ids == {res_a.id, res_b.id}

    filtered = client.get(f"{base}&property_id={prop_a.id}").get_json()
    assert {item["id"] for item in filtered} == {res_a.id}
    for item in filtered:
        assert item["property_id"] == prop_a.id


def test_calendar_events_unit_filter(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Cal One Prop", address=None)
    db.session.add(prop)
    db.session.flush()
    unit_1 = Unit(property_id=prop.id, name="U1", unit_type="double")
    unit_2 = Unit(property_id=prop.id, name="U2", unit_type="double")
    db.session.add_all([unit_1, unit_2])
    db.session.flush()
    r1 = Reservation(
        unit_id=unit_1.id,
        guest_id=admin_user.id,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 4),
        status="confirmed",
    )
    r2 = Reservation(
        unit_id=unit_2.id,
        guest_id=admin_user.id,
        start_date=date(2026, 4, 10),
        end_date=date(2026, 4, 14),
        status="confirmed",
    )
    db.session.add_all([r1, r2])
    db.session.commit()

    base = "/admin/calendar/events?start=2026-04-01&end=2026-04-30"
    filtered = client.get(f"{base}&unit_id={unit_2.id}").get_json()
    assert {item["id"] for item in filtered} == {r2.id}


def test_calendar_events_combined_property_and_unit_filter(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop_x = Property(organization_id=admin_user.organization_id, name="Cal X", address=None)
    prop_y = Property(organization_id=admin_user.organization_id, name="Cal Y", address=None)
    db.session.add_all([prop_x, prop_y])
    db.session.flush()
    ux1 = Unit(property_id=prop_x.id, name="X1", unit_type="double")
    ux2 = Unit(property_id=prop_x.id, name="X2", unit_type="double")
    uy1 = Unit(property_id=prop_y.id, name="Y1", unit_type="double")
    db.session.add_all([ux1, ux2, uy1])
    db.session.flush()
    rx = Reservation(
        unit_id=ux1.id,
        guest_id=admin_user.id,
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 5),
        status="confirmed",
    )
    ry = Reservation(
        unit_id=uy1.id,
        guest_id=admin_user.id,
        start_date=date(2026, 2, 10),
        end_date=date(2026, 2, 14),
        status="confirmed",
    )
    db.session.add_all([rx, ry])
    db.session.commit()

    base = "/admin/calendar/events?start=2026-02-01&end=2026-02-28"
    filtered = client.get(
        f"{base}&property_id={prop_x.id}&unit_id={ux1.id}"
    ).get_json()
    assert {item["id"] for item in filtered} == {rx.id}


def test_calendar_events_rejects_unit_not_on_selected_property(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop_x = Property(organization_id=admin_user.organization_id, name="Cal PX", address=None)
    prop_y = Property(organization_id=admin_user.organization_id, name="Cal PY", address=None)
    db.session.add_all([prop_x, prop_y])
    db.session.flush()
    ux = Unit(property_id=prop_x.id, name="Only X", unit_type="double")
    uy = Unit(property_id=prop_y.id, name="Only Y", unit_type="double")
    db.session.add_all([ux, uy])
    db.session.commit()

    response = client.get(
        "/admin/calendar/events?start=2026-01-01&end=2026-01-31"
        f"&property_id={prop_x.id}&unit_id={uy.id}"
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["code"] == "validation_error"


def test_calendar_events_rejects_other_organization_property_id(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    other_org = Organization(name="Cal Filter Other Org")
    db.session.add(other_org)
    db.session.flush()
    foreign_prop = Property(organization_id=other_org.id, name="Foreign Cal", address=None)
    db.session.add(foreign_prop)
    db.session.commit()

    response = client.get(
        "/admin/calendar/events?start=2026-05-01&end=2026-05-31"
        f"&property_id={foreign_prop.id}"
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["message"] == "Invalid property filter."


def test_calendar_events_rejects_other_organization_unit_id(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    other_org = Organization(name="Cal Unit Other Org")
    db.session.add(other_org)
    db.session.flush()
    foreign_prop = Property(organization_id=other_org.id, name="Foreign Unit Prop", address=None)
    db.session.add(foreign_prop)
    db.session.flush()
    foreign_unit = Unit(property_id=foreign_prop.id, name="FU", unit_type="single")
    db.session.add(foreign_unit)
    db.session.commit()

    response = client.get(
        "/admin/calendar/events?start=2026-05-01&end=2026-05-31"
        f"&unit_id={foreign_unit.id}"
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["error"]["message"] == "Invalid unit filter."


def test_calendar_events_invalid_property_id_param_returns_400(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.get("/admin/calendar/events?start=2026-05-01&end=2026-05-31&property_id=abc")
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


def _move_patch(client, *, reservation_id: int, payload: dict):
    return client.patch(
        f"/admin/reservations/{reservation_id}/move",
        json=payload,
        headers={"Content-Type": "application/json"},
    )


def _resize_patch(client, *, reservation_id: int, payload: dict):
    return client.patch(
        f"/admin/reservations/{reservation_id}/resize",
        json=payload,
        headers={"Content-Type": "application/json"},
    )


def test_admin_can_move_reservation(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Move Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="M1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _move_patch(
        client,
        reservation_id=res.id,
        payload={
            "start_date": "2026-08-03",
            "end_date": "2026-08-08",
            "unit_id": unit.id,
        },
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["id"] == res.id
    assert body["data"]["start_date"] == "2026-08-03"
    assert body["data"]["end_date"] == "2026-08-08"
    assert body["data"]["unit_id"] == unit.id

    refreshed = Reservation.query.get(res.id)
    assert refreshed.start_date == date(2026, 8, 3)
    assert refreshed.end_date == date(2026, 8, 8)


def test_move_reservation_success_json_shape(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Shape Move", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="S1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 3, 1),
        end_date=date(2026, 3, 4),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _move_patch(
        client,
        reservation_id=res.id,
        payload={"start_date": "2026-03-02", "end_date": "2026-03-05", "unit_id": unit.id},
    )
    body = response.get_json()
    assert set(body.keys()) == {"success", "data", "error"}
    assert body["success"] is True
    assert body["data"] is not None
    assert set(body["data"].keys()) == {"id", "start_date", "end_date", "unit_id"}


def test_move_reservation_overlap_json_shape(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Overlap Move", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="O1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    first = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 6),
        status="confirmed",
    )
    second = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 4, 10),
        end_date=date(2026, 4, 14),
        status="confirmed",
    )
    db.session.add(first)
    db.session.add(second)
    db.session.commit()

    response = _move_patch(
        client,
        reservation_id=second.id,
        payload={
            "start_date": "2026-04-02",
            "end_date": "2026-04-12",
            "unit_id": unit.id,
        },
    )
    assert response.status_code == 409
    body = response.get_json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "reservation_overlap"
    assert "overlap" in body["error"]["message"].lower()


def test_regular_user_cannot_move_reservation(client, regular_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=regular_user.email, password=regular_user.password_plain)

    prop = Property(organization_id=regular_user.organization_id, name="User Move", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=regular_user.id,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 4),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _move_patch(
        client,
        reservation_id=res.id,
        payload={"start_date": "2026-05-02", "end_date": "2026-05-05", "unit_id": unit.id},
    )
    assert response.status_code == 403


def test_cannot_move_other_organization_reservation(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    own_prop = Property(organization_id=admin_user.organization_id, name="Admin Move Org", address=None)
    db.session.add(own_prop)
    db.session.flush()
    own_unit = Unit(property_id=own_prop.id, name="Admin U", unit_type="double")
    db.session.add(own_unit)

    other_org = Organization(name="Move Foreign Org")
    db.session.add(other_org)
    db.session.flush()
    other_user = User(
        email="move-foreign@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_prop = Property(organization_id=other_org.id, name="FProp", address=None)
    db.session.add(other_prop)
    db.session.flush()
    other_unit = Unit(property_id=other_prop.id, name="FU", unit_type="single")
    db.session.add(other_unit)
    db.session.flush()
    other_res = Reservation(
        unit_id=other_unit.id,
        guest_id=other_user.id,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 5),
        status="confirmed",
    )
    db.session.add(other_res)
    db.session.commit()

    # Valid unit in admin org, but reservation belongs to another tenant → 404.
    response = _move_patch(
        client,
        reservation_id=other_res.id,
        payload={
            "start_date": "2026-06-02",
            "end_date": "2026-06-06",
            "unit_id": own_unit.id,
        },
    )
    assert response.status_code == 404


def test_move_rejects_unit_from_other_organization(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    own_prop = Property(organization_id=admin_user.organization_id, name="Own Move", address=None)
    db.session.add(own_prop)
    db.session.flush()
    own_unit = Unit(property_id=own_prop.id, name="OU", unit_type="double")
    db.session.add(own_unit)
    db.session.flush()
    res = Reservation(
        unit_id=own_unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 14),
        status="confirmed",
    )
    db.session.add(res)

    other_org = Organization(name="Unit Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_user = User(
        email="unit-other@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_prop = Property(organization_id=other_org.id, name="OP", address=None)
    db.session.add(other_prop)
    db.session.flush()
    foreign_unit = Unit(property_id=other_prop.id, name="FX", unit_type="single")
    db.session.add(foreign_unit)
    db.session.commit()

    response = _move_patch(
        client,
        reservation_id=res.id,
        payload={
            "start_date": "2026-07-10",
            "end_date": "2026-07-14",
            "unit_id": foreign_unit.id,
        },
    )
    assert response.status_code == 400
    body = response.get_json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "validation_error"


def test_move_rejects_start_not_before_end(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Bad Move", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="B1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _move_patch(
        client,
        reservation_id=res.id,
        payload={
            "start_date": "2026-09-10",
            "end_date": "2026-09-08",
            "unit_id": unit.id,
        },
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


def test_move_same_dates_no_self_overlap(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Self Move", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="SM", unit_type="double")
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

    response = _move_patch(
        client,
        reservation_id=res.id,
        payload={
            "start_date": "2026-10-10",
            "end_date": "2026-10-15",
            "unit_id": unit.id,
        },
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_move_creates_reservation_moved_audit(client, admin_user):
    from app.audit.models import AuditLog
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Audit Move", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="AM", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 11, 20),
        end_date=date(2026, 11, 25),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _move_patch(
        client,
        reservation_id=res.id,
        payload={
            "start_date": "2026-11-21",
            "end_date": "2026-11-26",
            "unit_id": unit.id,
        },
    )
    assert response.status_code == 200

    log = AuditLog.query.filter_by(action="reservation_moved", target_id=res.id).first()
    assert log is not None
    assert log.target_type == "reservation"
    assert log.actor_id == admin_user.id


def test_admin_can_resize_reservation(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Resize Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="R1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 5),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _resize_patch(
        client,
        reservation_id=res.id,
        payload={"start_date": "2026-12-01", "end_date": "2026-12-07"},
    )
    assert response.status_code == 200
    body = response.get_json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["data"]["id"] == res.id
    assert body["data"]["start_date"] == "2026-12-01"
    assert body["data"]["end_date"] == "2026-12-07"
    assert body["data"]["unit_id"] == unit.id


def test_resize_reservation_success_json_shape(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Resize Shape", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="RS", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 12),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _resize_patch(
        client,
        reservation_id=res.id,
        payload={"start_date": "2026-12-10", "end_date": "2026-12-13"},
    )
    body = response.get_json()
    assert set(body.keys()) == {"success", "data", "error"}
    assert body["success"] is True
    assert body["data"] is not None
    assert set(body["data"].keys()) == {"id", "start_date", "end_date", "unit_id"}


def test_resize_reservation_error_json_shape(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Resize Error", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="RE", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 12, 15),
        end_date=date(2026, 12, 18),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _resize_patch(
        client,
        reservation_id=res.id,
        payload={"start_date": "2026-12-19", "end_date": "2026-12-18"},
    )
    assert response.status_code == 400
    body = response.get_json()
    assert set(body.keys()) == {"success", "data", "error"}
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "validation_error"


def test_regular_user_cannot_resize_reservation(client, regular_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=regular_user.email, password=regular_user.password_plain)

    prop = Property(organization_id=regular_user.organization_id, name="Resize User", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="RU", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=regular_user.id,
        start_date=date(2026, 12, 20),
        end_date=date(2026, 12, 24),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _resize_patch(
        client,
        reservation_id=res.id,
        payload={"start_date": "2026-12-20", "end_date": "2026-12-25"},
    )
    assert response.status_code == 403


def test_cannot_resize_other_organization_reservation(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole
    from werkzeug.security import generate_password_hash

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    other_org = Organization(name="Resize Foreign Org")
    db.session.add(other_org)
    db.session.flush()
    other_user = User(
        email="resize-foreign@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=other_org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_prop = Property(organization_id=other_org.id, name="Resize FProp", address=None)
    db.session.add(other_prop)
    db.session.flush()
    other_unit = Unit(property_id=other_prop.id, name="RFU", unit_type="single")
    db.session.add(other_unit)
    db.session.flush()
    other_res = Reservation(
        unit_id=other_unit.id,
        guest_id=other_user.id,
        start_date=date(2026, 12, 5),
        end_date=date(2026, 12, 10),
        status="confirmed",
    )
    db.session.add(other_res)
    db.session.commit()

    response = _resize_patch(
        client,
        reservation_id=other_res.id,
        payload={"start_date": "2026-12-05", "end_date": "2026-12-11"},
    )
    assert response.status_code == 404


def test_resize_rejects_start_not_before_end(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Resize Bad", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="RB", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 3),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _resize_patch(
        client,
        reservation_id=res.id,
        payload={"start_date": "2026-12-04", "end_date": "2026-12-04"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


def test_resize_rejects_overlap(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Resize Overlap", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="RO", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    first = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 12, 1),
        end_date=date(2026, 12, 5),
        status="confirmed",
    )
    second = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 12, 10),
        end_date=date(2026, 12, 12),
        status="confirmed",
    )
    db.session.add(first)
    db.session.add(second)
    db.session.commit()

    response = _resize_patch(
        client,
        reservation_id=second.id,
        payload={"start_date": "2026-12-03", "end_date": "2026-12-11"},
    )
    assert response.status_code == 409
    body = response.get_json()
    assert body["error"]["code"] == "reservation_overlap"


def test_resize_same_dates_no_self_overlap(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Resize Self", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="RSF", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 12, 21),
        end_date=date(2026, 12, 24),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _resize_patch(
        client,
        reservation_id=res.id,
        payload={"start_date": "2026-12-21", "end_date": "2026-12-24"},
    )
    assert response.status_code == 200
    assert response.get_json()["success"] is True


def test_resize_creates_reservation_resized_audit(client, admin_user):
    from app.audit.models import AuditLog
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Resize Audit", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="RA", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    res = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        start_date=date(2026, 12, 26),
        end_date=date(2026, 12, 29),
        status="confirmed",
    )
    db.session.add(res)
    db.session.commit()

    response = _resize_patch(
        client,
        reservation_id=res.id,
        payload={"start_date": "2026-12-26", "end_date": "2026-12-30"},
    )
    assert response.status_code == 200

    log = AuditLog.query.filter_by(action="reservation_resized", target_id=res.id).first()
    assert log is not None
    assert log.target_type == "reservation"
    assert log.actor_id == admin_user.id
