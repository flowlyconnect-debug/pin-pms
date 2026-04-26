from __future__ import annotations

from datetime import date


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _seed_guest(*, db, organization_id: int, first_name: str = "Jane", last_name: str = "Doe", email: str | None = "jane@example.com"):
    from app.guests.models import Guest

    row = Guest(
        organization_id=organization_id,
        first_name=first_name,
        last_name=last_name,
        email=email,
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_admin_can_list_guests(client, admin_user):
    from app.extensions import db

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    _seed_guest(db=db, organization_id=admin_user.organization_id, first_name="Aino", last_name="Guest", email="aino@test.local")

    response = client.get("/admin/guests")
    assert response.status_code == 200
    assert b"Aino Guest" in response.data


def test_admin_can_create_guest(client, admin_user):
    from app.guests.models import Guest

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.post(
        "/admin/guests/new",
        data={
            "first_name": "Matti",
            "last_name": "Meikalainen",
            "email": "matti@test.local",
            "phone": "123",
            "notes": "VIP",
            "preferences": "Late checkout",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    row = Guest.query.filter_by(organization_id=admin_user.organization_id, email="matti@test.local").first()
    assert row is not None


def test_admin_can_edit_guest(client, admin_user):
    from app.extensions import db
    from app.guests.models import Guest

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    row = _seed_guest(db=db, organization_id=admin_user.organization_id, first_name="Old", last_name="Name", email="old@test.local")
    response = client.post(
        f"/admin/guests/{row.id}/edit",
        data={
            "first_name": "New",
            "last_name": "Name",
            "email": "new@test.local",
            "phone": "",
            "notes": "",
            "preferences": "",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200
    refreshed = Guest.query.get(row.id)
    assert refreshed.email == "new@test.local"


def test_user_cannot_manage_guests(client, regular_user):
    _login(client, email=regular_user.email, password=regular_user.password_plain)
    assert client.get("/admin/guests", follow_redirects=False).status_code == 403
    assert client.get("/admin/guests/new", follow_redirects=False).status_code == 403


def test_other_organization_guest_not_visible(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    own = _seed_guest(db=db, organization_id=admin_user.organization_id, first_name="Own", last_name="Guest", email="own@test.local")
    other_org = Organization(name="Other Guest Org")
    db.session.add(other_org)
    db.session.commit()
    _seed_guest(db=db, organization_id=other_org.id, first_name="Foreign", last_name="Guest", email="foreign@test.local")

    page = client.get("/admin/guests")
    assert f"/admin/guests/{own.id}".encode() in page.data
    assert b"Foreign Guest" not in page.data


def test_same_email_blocked_in_same_organization(client, admin_user):
    from app.extensions import db

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    _seed_guest(db=db, organization_id=admin_user.organization_id, first_name="A", last_name="One", email="dup@test.local")

    response = client.post(
        "/admin/guests/new",
        data={"first_name": "B", "last_name": "Two", "email": "dup@test.local"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"already exists in your organization" in response.data


def test_same_email_allowed_in_different_organizations(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    _seed_guest(db=db, organization_id=admin_user.organization_id, first_name="A", last_name="One", email="same@test.local")
    other_org = Organization(name="Other Email Org")
    db.session.add(other_org)
    db.session.commit()
    _seed_guest(db=db, organization_id=other_org.id, first_name="B", last_name="Two", email="same@test.local")


def test_reservation_can_link_guest_and_detail_shows_history(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    guest = _seed_guest(db=db, organization_id=admin_user.organization_id, first_name="Link", last_name="Guest", email="link@test.local")
    prop = Property(organization_id=admin_user.organization_id, name="Guest Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="101", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    reservation = Reservation(
        unit_id=unit.id,
        guest_id=guest.id,
        guest_name="Link Guest",
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 3),
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()

    detail = client.get(f"/admin/guests/{guest.id}")
    assert detail.status_code == 200
    assert f"/admin/reservations/{reservation.id}".encode() in detail.data


def test_guest_audit_logs_created(client, admin_user):
    from app.audit.models import AuditLog

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    create = client.post(
        "/admin/guests/new",
        data={"first_name": "Audit", "last_name": "Guest", "email": "audit@test.local"},
        follow_redirects=False,
    )
    assert create.status_code == 302
    created = AuditLog.query.filter_by(action="guest_created").first()
    assert created is not None

    guest_id = int(create.headers["Location"].rstrip("/").split("/")[-1])
    update = client.post(
        f"/admin/guests/{guest_id}/edit",
        data={"first_name": "Audit2", "last_name": "Guest", "email": "audit2@test.local", "phone": "", "notes": "", "preferences": ""},
        follow_redirects=False,
    )
    assert update.status_code == 302
    updated = AuditLog.query.filter_by(action="guest_updated", target_id=guest_id).first()
    assert updated is not None


def test_calendar_title_uses_guest_full_name_when_linked(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    guest = _seed_guest(db=db, organization_id=admin_user.organization_id, first_name="Full", last_name="Name", email="full@test.local")
    prop = Property(organization_id=admin_user.organization_id, name="Cal Guest Hotel", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="303", unit_type="suite")
    db.session.add(unit)
    db.session.flush()
    reservation = Reservation(
        unit_id=unit.id,
        guest_id=guest.id,
        guest_name="Legacy Name",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 4),
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()

    events = client.get("/admin/calendar/events?start=2026-06-01&end=2026-06-30").get_json()
    item = next(x for x in events if x["id"] == reservation.id)
    assert item["title"] == "Full Name – 303"
    assert item["extendedProps"]["guest_id"] == guest.id
