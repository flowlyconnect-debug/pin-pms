from __future__ import annotations

from datetime import date

from app.integrations.ical import adapter
from app.integrations.ical.client import IcalClient
from app.integrations.ical.service import IcalService


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def test_ical_adapter_parses_events_with_ical_library():
    payload = (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:airbnb-1\r\n"
        "DTSTART;VALUE=DATE:20260510\r\n"
        "DTEND;VALUE=DATE:20260512\r\n"
        "SUMMARY:Airbnb blocked\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    ).encode("utf-8")
    out = adapter.parse_ical_events(payload)
    assert len(out) == 1
    assert out[0]["uid"] == "airbnb-1"
    assert out[0]["start_date"].isoformat() == "2026-05-10"
    assert out[0]["end_date"].isoformat() == "2026-05-12"


def test_ical_client_fetches_calendar(monkeypatch):
    calls = {}

    class FakeResponse:
        content = b"BEGIN:VCALENDAR\r\nEND:VCALENDAR\r\n"

        def raise_for_status(self):
            return None

    def fake_get(url, timeout, headers):
        calls["url"] = url
        calls["timeout"] = timeout
        calls["headers"] = headers
        return FakeResponse()

    monkeypatch.setattr("app.integrations.ical.client.requests.get", fake_get)
    payload = IcalClient(timeout_seconds=7).fetch_calendar(
        source_url="https://example.test/unit.ics"
    )
    assert payload.startswith(b"BEGIN:VCALENDAR")
    assert calls["url"] == "https://example.test/unit.ics"
    assert calls["timeout"] == 7
    assert "text/calendar" in calls["headers"]["Accept"]


def test_export_unit_calendar_requires_signed_token(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    org = Organization(name="Org iCal")
    db.session.add(org)
    db.session.flush()
    prop = Property(organization_id=org.id, name="P", address="A")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U1", unit_type="studio")
    db.session.add(unit)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_name="Guest",
            start_date=date(2026, 5, 15),
            end_date=date(2026, 5, 18),
            status="confirmed",
            currency="EUR",
            payment_status="pending",
        )
    )
    db.session.commit()

    blocked = client.get(f"/api/v1/units/{unit.id}/calendar.ics?token=bad")
    assert blocked.status_code == 403

    with client.application.app_context():
        token = IcalService().sign_unit_token(unit_id=unit.id)
    ok = client.get(f"/api/v1/units/{unit.id}/calendar.ics?token={token}")
    assert ok.status_code == 200
    assert b"BEGIN:VCALENDAR" in ok.data
    assert b"reservation-" in ok.data


def test_admin_calendar_sync_page_and_import_conflict(client, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    org = Organization.query.get(admin_user.organization_id)
    if org is None:
        org = Organization(name="Admin Org")
        db.session.add(org)
        db.session.flush()
        admin_user.organization_id = org.id
        db.session.flush()
    prop = Property(organization_id=org.id, name="Sync property", address="")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="Sync unit", unit_type="")
    db.session.add(unit)
    db.session.flush()
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_name="Internal guest",
            start_date=date(2026, 6, 1),
            end_date=date(2026, 6, 5),
            status="confirmed",
            currency="EUR",
            payment_status="pending",
        )
    )
    db.session.commit()

    page = client.get(f"/admin/units/{unit.id}/calendar-sync")
    assert page.status_code == 200
    assert b"Kalenterisynkronointi" in page.data

    posted = client.post(
        f"/admin/units/{unit.id}/calendar-sync",
        data={"name": "Airbnb", "source_url": "https://example.test/u1.ics"},
        follow_redirects=False,
    )
    assert posted.status_code == 302
