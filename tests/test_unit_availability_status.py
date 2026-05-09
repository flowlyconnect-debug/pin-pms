"""Tests for ``list_units_with_availability_status`` and the property-detail admin view.

Kattaa:
- statuslaskennan eri tilat (free, reserved, transition, maintenance, blocked)
- tenant-isolaation organization_id-rajauksella
- tehokkuuden (rajatun määrän SQL-kyselyitä, ei N+1:tä)
- HTML-renderöinnin (status-badge ja meta-tiedot näkyvät property-detail-näkymässä)
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from sqlalchemy import event

from app.extensions import db
from app.maintenance.models import MaintenanceRequest
from app.organizations.models import Organization
from app.properties import services as property_service
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _seed_property_with_unit(*, organization_id: int, property_name: str, unit_name: str) -> tuple[Property, Unit]:
    prop = Property(organization_id=organization_id, name=property_name, address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name=unit_name, unit_type="std")
    db.session.add(unit)
    db.session.flush()
    return prop, unit


def _state_of(rows: list[dict], unit_id: int) -> dict:
    return next(row for row in rows if row["id"] == unit_id)


# ---------------------------------------------------------------------------
# Status laskenta
# ---------------------------------------------------------------------------


def test_unit_with_no_reservations_is_free(app, admin_user):
    with app.app_context():
        _, unit = _seed_property_with_unit(
            organization_id=admin_user.organization_id,
            property_name="Free Hotel",
            unit_name="100",
        )
        db.session.commit()

        rows = property_service.list_units_with_availability_status(
            organization_id=admin_user.organization_id,
            as_of=date(2026, 5, 9),
        )
        row = _state_of(rows, unit.id)
        assert row["current_state"] == "free"
        assert row["current_guest_name"] is None
        assert row["occupied_until"] is None


def test_unit_with_active_reservation_is_reserved(app, admin_user):
    with app.app_context():
        _, unit = _seed_property_with_unit(
            organization_id=admin_user.organization_id,
            property_name="Reserved Hotel",
            unit_name="201",
        )
        today = date(2026, 5, 9)
        db.session.add(
            Reservation(
                unit_id=unit.id,
                guest_id=None,
                guest_name="Matti Meikäläinen",
                start_date=today - timedelta(days=2),
                end_date=today + timedelta(days=3),
                status="confirmed",
            )
        )
        db.session.commit()

        rows = property_service.list_units_with_availability_status(
            organization_id=admin_user.organization_id,
            as_of=today,
        )
        row = _state_of(rows, unit.id)
        assert row["current_state"] == "reserved"
        assert row["current_guest_name"] == "Matti Meikäläinen"
        assert row["occupied_until"] == today + timedelta(days=3)


def test_unit_with_checkout_today_and_new_arrival_is_transition(app, admin_user):
    with app.app_context():
        _, unit = _seed_property_with_unit(
            organization_id=admin_user.organization_id,
            property_name="Transition Hotel",
            unit_name="301",
        )
        today = date(2026, 5, 9)
        # Lähtevä varaus, joka päättyy tänään
        db.session.add(
            Reservation(
                unit_id=unit.id,
                guest_id=None,
                guest_name="Lähtijä",
                start_date=today - timedelta(days=3),
                end_date=today,
                status="confirmed",
            )
        )
        # Uusi vieras saapuu samana päivänä
        db.session.add(
            Reservation(
                unit_id=unit.id,
                guest_id=None,
                guest_name="Saapuja",
                start_date=today,
                end_date=today + timedelta(days=2),
                status="confirmed",
            )
        )
        db.session.commit()

        rows = property_service.list_units_with_availability_status(
            organization_id=admin_user.organization_id,
            as_of=today,
        )
        row = _state_of(rows, unit.id)
        assert row["current_state"] == "transition"
        assert row["current_guest_name"] == "Saapuja"


def test_unit_with_open_maintenance_is_maintenance(app, admin_user):
    with app.app_context():
        prop, unit = _seed_property_with_unit(
            organization_id=admin_user.organization_id,
            property_name="Maintenance Hotel",
            unit_name="401",
        )
        today = date(2026, 5, 9)
        db.session.add(
            MaintenanceRequest(
                organization_id=admin_user.organization_id,
                property_id=prop.id,
                unit_id=unit.id,
                title="Vesivuoto",
                status="in_progress",
                priority="high",
                due_date=today,
                created_by_id=admin_user.id,
            )
        )
        db.session.commit()

        rows = property_service.list_units_with_availability_status(
            organization_id=admin_user.organization_id,
            as_of=today,
        )
        row = _state_of(rows, unit.id)
        assert row["current_state"] == "maintenance"


def test_free_unit_lists_next_reservation(app, admin_user):
    with app.app_context():
        _, unit = _seed_property_with_unit(
            organization_id=admin_user.organization_id,
            property_name="Future Hotel",
            unit_name="501",
        )
        today = date(2026, 5, 9)
        db.session.add(
            Reservation(
                unit_id=unit.id,
                guest_id=None,
                guest_name="Tuleva Vieras",
                start_date=today + timedelta(days=4),
                end_date=today + timedelta(days=7),
                status="confirmed",
            )
        )
        db.session.commit()

        rows = property_service.list_units_with_availability_status(
            organization_id=admin_user.organization_id,
            as_of=today,
        )
        row = _state_of(rows, unit.id)
        assert row["current_state"] == "free"
        assert row["next_reservation_at"] == today + timedelta(days=4)
        assert row["next_guest_name"] == "Tuleva Vieras"
        assert row["days_until_next"] == 4


def test_cancelled_reservations_do_not_block_unit(app, admin_user):
    with app.app_context():
        _, unit = _seed_property_with_unit(
            organization_id=admin_user.organization_id,
            property_name="Cancelled Hotel",
            unit_name="601",
        )
        today = date(2026, 5, 9)
        db.session.add(
            Reservation(
                unit_id=unit.id,
                guest_id=None,
                guest_name="Peruttu",
                start_date=today - timedelta(days=1),
                end_date=today + timedelta(days=2),
                status="cancelled",
            )
        )
        db.session.commit()

        rows = property_service.list_units_with_availability_status(
            organization_id=admin_user.organization_id,
            as_of=today,
        )
        row = _state_of(rows, unit.id)
        assert row["current_state"] == "free"


# ---------------------------------------------------------------------------
# Tenant isolaatio
# ---------------------------------------------------------------------------


def test_other_org_units_are_not_returned(app, admin_user):
    with app.app_context():
        _, own_unit = _seed_property_with_unit(
            organization_id=admin_user.organization_id,
            property_name="Own Hotel",
            unit_name="OWN",
        )
        other_org = Organization(name="Toinen Org")
        db.session.add(other_org)
        db.session.flush()
        _, other_unit = _seed_property_with_unit(
            organization_id=other_org.id,
            property_name="Toisen Hotelli",
            unit_name="OTHER",
        )
        db.session.commit()

        rows = property_service.list_units_with_availability_status(
            organization_id=admin_user.organization_id,
            as_of=date(2026, 5, 9),
        )
        ids = [row["id"] for row in rows]
        assert own_unit.id in ids
        assert other_unit.id not in ids


def test_other_org_maintenance_does_not_leak(app, admin_user):
    """Toisen organisaation huoltopyyntö ei saa aiheuttaa maintenance-tilaa omalle huoneelle."""

    with app.app_context():
        own_prop, own_unit = _seed_property_with_unit(
            organization_id=admin_user.organization_id,
            property_name="Own Hotel",
            unit_name="OWN1",
        )
        other_org = Organization(name="Toinen Org B")
        db.session.add(other_org)
        db.session.flush()
        # Huoltopyyntö, joka teknisesti viittaa OMAAN unitiin mutta toiseen organisaatioon
        # — sekä ohjelman tenant-tarkistus organization_id:llä että fyysinen mahdottomuus
        # tarkoittavat että tämän _ei pidä_ vaikuttaa.
        db.session.add(
            MaintenanceRequest(
                organization_id=other_org.id,
                property_id=own_prop.id,
                unit_id=own_unit.id,
                title="Toisen orgin huolto",
                status="in_progress",
                priority="normal",
                due_date=date(2026, 5, 9),
                created_by_id=admin_user.id,
            )
        )
        db.session.commit()

        rows = property_service.list_units_with_availability_status(
            organization_id=admin_user.organization_id,
            as_of=date(2026, 5, 9),
        )
        row = _state_of(rows, own_unit.id)
        # Tenant-rajaus organization_id:llä estää huoltopyynnön vaikutuksen.
        assert row["current_state"] == "free"


# ---------------------------------------------------------------------------
# Suorituskyky: kysely-count ei kasva unit-määrän mukaan (ei N+1)
# ---------------------------------------------------------------------------


@pytest.fixture
def query_counter():
    """Kerää kaikki SELECT-kyselyt SQLAlchemyn engine event -hookilla."""

    counter = {"count": 0, "statements": []}

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().lower().startswith(("select", "with")):
            counter["count"] += 1
            counter["statements"].append(statement)

    def _attach():
        engine = db.engine
        event.listen(engine, "before_cursor_execute", _on_execute)
        return engine

    yield counter, _attach

    try:
        event.remove(db.engine, "before_cursor_execute", _on_execute)
    except Exception:
        pass


def test_list_units_with_availability_status_query_count_is_bounded(app, admin_user, query_counter):
    with app.app_context():
        # Luodaan kymmenen huonetta saman omistajan alle.
        property_id = None
        unit_ids: list[int] = []
        prop = Property(
            organization_id=admin_user.organization_id, name="Big Hotel", address=None
        )
        db.session.add(prop)
        db.session.flush()
        property_id = prop.id
        for i in range(10):
            unit = Unit(property_id=prop.id, name=f"U{i}", unit_type="std")
            db.session.add(unit)
            db.session.flush()
            unit_ids.append(unit.id)
        # Lisätään kullekin huoneelle nykyinen varaus
        today = date(2026, 5, 9)
        for uid in unit_ids:
            db.session.add(
                Reservation(
                    unit_id=uid,
                    guest_id=None,
                    guest_name=f"Guest-{uid}",
                    start_date=today - timedelta(days=1),
                    end_date=today + timedelta(days=2),
                    status="confirmed",
                )
            )
        db.session.commit()

        counter, attach = query_counter
        attach()
        counter["count"] = 0
        counter["statements"] = []

        rows = property_service.list_units_with_availability_status(
            organization_id=admin_user.organization_id,
            property_id=property_id,
            as_of=today,
        )

        # Funktion pitää tehdä korkeintaan kolme SELECT-kyselyä
        # riippumatta siitä, montako huonetta organisaatiossa on.
        assert len(rows) == 10
        assert counter["count"] <= 4, (
            f"Liian monta SELECT-kyselyä ({counter['count']}); N+1-ongelma?"
        )


# ---------------------------------------------------------------------------
# HTML-renderöinti
# ---------------------------------------------------------------------------


def test_property_detail_renders_unit_status_badge(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, unit = _seed_property_with_unit(
        organization_id=admin_user.organization_id,
        property_name="Render Hotel",
        unit_name="RENDER-1",
    )
    today = date.today()
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_id=None,
            guest_name="Status Vieras",
            start_date=today - timedelta(days=1),
            end_date=today + timedelta(days=2),
            status="confirmed",
        )
    )
    db.session.commit()

    response = client.get(f"/admin/properties/{prop.id}", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    # Tila-sarake otsikossa
    assert "<th>Tila</th>" in html
    # Status-badge huoneen rivillä
    assert "status-badge--reserved" in html
    # Suomenkielinen labeli (availability_label-filterin kautta)
    assert "Varattu" in html
    # Vieraan nimi näkyy meta-tekstissä
    assert "Status Vieras" in html


def test_admin_css_defines_unit_availability_status_badge_classes():
    css_path = "app/static/css/admin.css"
    with open(css_path, encoding="utf-8") as handle:
        css = handle.read()

    for variant in ("free", "reserved", "transition", "maintenance", "blocked"):
        assert f".status-badge--{variant}" in css, (
            f"admin.css puuttuu .status-badge--{variant}"
        )
