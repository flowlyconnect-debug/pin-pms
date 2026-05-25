from __future__ import annotations

from datetime import date

from app.extensions import db
from app.properties.models import Property, Unit
from app.reservations import services as reservation_service
from app.reservations.models import Reservation
from app.guests.models import Guest


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _seed_property_unit(admin_user):
    prop = Property(
        organization_id=admin_user.organization_id,
        name="Wizard Hotel",
        address=None,
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="201", unit_type="double")
    db.session.add(unit)
    db.session.commit()
    return prop, unit


def _wizard_state(client):
    with client.session_transaction() as sess:
        return sess.get(reservation_service.RESERVATION_WIZARD_SESSION_KEY)


def test_wizard_step1_saves_property_to_session(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, _unit = _seed_property_unit(admin_user)

    response = client.post(
        f"/admin/reservations/new/step/1",
        data={"property_id": str(prop.id), "csrf_token": _csrf(client)},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/step/2" in response.headers["Location"]

    state = _wizard_state(client)
    assert state is not None
    assert state["property_id"] == prop.id


def _csrf(client) -> str:
    response = client.get("/admin/reservations/new/step/1")
    text = response.get_data(as_text=True)
    marker = 'name="csrf_token" value="'
    start = text.index(marker) + len(marker)
    end = text.index('"', start)
    return text[start:end]


def test_wizard_step2_saves_unit_and_dates_when_free(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, unit = _seed_property_unit(admin_user)
    token = _csrf(client)

    client.post(
        "/admin/reservations/new/step/1",
        data={"property_id": str(prop.id), "csrf_token": token},
    )
    response = client.post(
        "/admin/reservations/new/step/2",
        data={
            "unit_id": str(unit.id),
            "check_in": "2026-08-01",
            "check_out": "2026-08-05",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/step/3" in response.headers["Location"]

    state = _wizard_state(client)
    assert state["unit_id"] == unit.id
    assert state["check_in"] == "2026-08-01"
    assert state["check_out"] == "2026-08-05"


def test_wizard_step2_blocks_overlap(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, unit = _seed_property_unit(admin_user)
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_id=admin_user.id,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 5),
            status="confirmed",
        )
    )
    db.session.commit()
    token = _csrf(client)

    client.post(
        "/admin/reservations/new/step/1",
        data={"property_id": str(prop.id), "csrf_token": token},
    )
    response = client.post(
        "/admin/reservations/new/step/2",
        data={
            "unit_id": str(unit.id),
            "check_in": "2026-08-02",
            "check_out": "2026-08-06",
            "csrf_token": token,
        },
    )
    assert response.status_code == 200
    assert "päällekkäinen" in response.get_data(as_text=True)


def test_wizard_step3_selects_existing_guest(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, unit = _seed_property_unit(admin_user)
    guest = Guest(
        organization_id=admin_user.organization_id,
        first_name="Ada",
        last_name="Lovelace",
        email="ada@example.com",
    )
    db.session.add(guest)
    db.session.commit()
    token = _csrf(client)

    client.post(
        "/admin/reservations/new/step/1",
        data={"property_id": str(prop.id), "csrf_token": token},
    )
    client.post(
        "/admin/reservations/new/step/2",
        data={
            "unit_id": str(unit.id),
            "check_in": "2026-09-01",
            "check_out": "2026-09-04",
            "csrf_token": token,
        },
    )
    response = client.post(
        "/admin/reservations/new/step/3",
        data={
            "guest_mode": "existing",
            "guest_id": str(guest.id),
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert "/step/4" in response.headers["Location"]

    state = _wizard_state(client)
    assert state["guest_id"] == guest.id


def test_wizard_step3_creates_new_guest(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, unit = _seed_property_unit(admin_user)
    token = _csrf(client)

    client.post(
        "/admin/reservations/new/step/1",
        data={"property_id": str(prop.id), "csrf_token": token},
    )
    client.post(
        "/admin/reservations/new/step/2",
        data={
            "unit_id": str(unit.id),
            "check_in": "2026-10-01",
            "check_out": "2026-10-03",
            "csrf_token": token,
        },
    )
    response = client.post(
        "/admin/reservations/new/step/3",
        data={
            "guest_mode": "new",
            "first_name": "Uusi",
            "last_name": "Vieras",
            "email": "uusi@example.com",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    state = _wizard_state(client)
    assert state["guest_id"] is not None
    created = Guest.query.get(state["guest_id"])
    assert created is not None
    assert created.first_name == "Uusi"


def test_wizard_step4_creates_reservation_and_clears_session(client, admin_user):
    from app.audit.models import AuditLog

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, unit = _seed_property_unit(admin_user)
    guest = Guest(
        organization_id=admin_user.organization_id,
        first_name="Confirm",
        last_name="Guest",
        email="confirm@example.com",
    )
    db.session.add(guest)
    db.session.commit()
    token = _csrf(client)

    client.post(
        "/admin/reservations/new/step/1",
        data={"property_id": str(prop.id), "csrf_token": token},
    )
    client.post(
        "/admin/reservations/new/step/2",
        data={
            "unit_id": str(unit.id),
            "check_in": "2026-11-01",
            "check_out": "2026-11-04",
            "csrf_token": token,
        },
    )
    client.post(
        "/admin/reservations/new/step/3",
        data={
            "guest_mode": "existing",
            "guest_id": str(guest.id),
            "csrf_token": token,
        },
    )
    response = client.post(
        "/admin/reservations/new/step/4",
        data={
            "amount": "150.00",
            "currency": "EUR",
            "csrf_token": token,
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    row = Reservation.query.filter_by(unit_id=unit.id, guest_id=guest.id).first()
    assert row is not None
    assert row.start_date == date(2026, 11, 1)
    assert str(row.amount) == "150.00"

    audit = AuditLog.query.filter_by(action="reservation_created", target_id=row.id).first()
    assert audit is not None

    assert _wizard_state(client) is None


def test_wizard_cancel_clears_session(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, _unit = _seed_property_unit(admin_user)
    token = _csrf(client)

    client.post(
        "/admin/reservations/new/step/1",
        data={"property_id": str(prop.id), "csrf_token": token},
    )
    assert _wizard_state(client) is not None

    response = client.post(
        "/admin/reservations/new/cancel",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert _wizard_state(client) is None
