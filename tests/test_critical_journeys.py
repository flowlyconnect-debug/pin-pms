"""Critical user-journey tests (synkronointiketjut) at the HTTP level.

These complement the unit/route tests by walking whole chains the way the
product is used:

* admin luo varauksen → lista → kalenteri-API → tietokanta
* päällekkäinen varaus estyy HTTP-tasolla
* peruutus vapauttaa ajan ja sama slotti voidaan varata uudelleen
* varausvahvistus- ja peruutussähköpostit muodostuvat oikealla sisällöllä
* Paytrail: epäonnistunut callback EI merkitse laskua maksetuksi,
  väärä allekirjoitus hylätään
* Pindora-lukkovirhe ei kaada varauksen peruutusta eikä check-in-sivua
* virhetilanteet: puuttuva lomakedata, kirjautumaton käyttäjä, API ilman avainta

External services are never called: Mailgun is disabled by ``TestConfig``
(``MAIL_DEV_LOG_ONLY``), Paytrail signature/network and Pindora client calls
are monkeypatched per test.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.extensions import db

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

CHECK_IN = date.today() + timedelta(days=40)
CHECK_OUT = date.today() + timedelta(days=43)


def login(client, user) -> None:
    resp = client.post(
        "/login",
        data={"email": user.email, "password": user.password_plain},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.data


@pytest.fixture()
def unit(organization):
    from app.properties.models import Property, Unit

    prop = Property(organization_id=organization.id, name="Journey Kohde", city="Espoo")
    db.session.add(prop)
    db.session.commit()
    row = Unit(property_id=prop.id, name="Journey 1A")
    db.session.add(row)
    db.session.commit()
    return row


@pytest.fixture()
def guest(organization):
    from app.guests.models import Guest

    row = Guest(
        organization_id=organization.id,
        first_name="Jenni",
        last_name="Journey",
        email="jenni.journey@example.com",
        phone="+358401112222",
    )
    db.session.add(row)
    db.session.commit()
    return row


def _create_reservation_http(client, unit, guest, *, start=CHECK_IN, end=CHECK_OUT):
    return client.post(
        "/admin/reservations/new",
        data={
            "unit_id": str(unit.id),
            "guest_id": str(guest.id),
            "guest_name": "",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "amount": "150.00",
            "currency": "EUR",
        },
        follow_redirects=False,
    )


def _reservation_rows(unit):
    from app.reservations.models import Reservation

    return Reservation.query.filter_by(unit_id=unit.id).all()


# ---------------------------------------------------------------------------
# 1. Varaus syntyy ja näkyy kaikkialla
# ---------------------------------------------------------------------------


def test_admin_reservation_syncs_to_list_calendar_and_db(client, admin_user, unit, guest):
    login(client, admin_user)

    resp = _create_reservation_http(client, unit, guest)
    assert resp.status_code in (302, 303), resp.data

    rows = _reservation_rows(unit)
    assert len(rows) == 1
    assert rows[0].status == "confirmed"
    assert rows[0].start_date == CHECK_IN

    listing = client.get("/admin/reservations")
    assert listing.status_code == 200
    assert b"Jenni" in listing.data or b"Journey" in listing.data

    events = client.get(
        "/admin/calendar/events",
        query_string={
            "start": (CHECK_IN - timedelta(days=7)).isoformat(),
            "end": (CHECK_OUT + timedelta(days=7)).isoformat(),
        },
    )
    assert events.status_code == 200
    payload = events.get_json()
    assert any(CHECK_IN.isoformat() in str(ev.get("start", "")) for ev in payload), payload


def test_double_booking_is_rejected_over_http(client, admin_user, unit, guest):
    login(client, admin_user)
    assert _create_reservation_http(client, unit, guest).status_code in (302, 303)

    resp = _create_reservation_http(client, unit, guest)
    # Form is re-rendered with an error instead of redirecting to detail.
    assert resp.status_code == 200
    assert len(_reservation_rows(unit)) == 1

    # Partial overlap must also be rejected.
    resp = _create_reservation_http(
        client, unit, guest, start=CHECK_IN + timedelta(days=1), end=CHECK_OUT + timedelta(days=1)
    )
    assert resp.status_code == 200
    assert len(_reservation_rows(unit)) == 1


def test_cancelling_frees_the_slot_for_rebooking(client, admin_user, unit, guest):
    login(client, admin_user)
    assert _create_reservation_http(client, unit, guest).status_code in (302, 303)
    row_id = _reservation_rows(unit)[0].id

    resp = client.post(
        f"/admin/reservations/{row_id}/cancel",
        data={"confirm_cancel": "yes"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), resp.data

    from app.reservations.models import Reservation

    db.session.expire_all()
    assert db.session.get(Reservation, row_id).status == "cancelled"

    # Cancelled reservation no longer blocks the calendar slot.
    assert _create_reservation_http(client, unit, guest).status_code in (302, 303)
    active = [r for r in _reservation_rows(unit) if r.status != "cancelled"]
    assert len(active) == 1


# ---------------------------------------------------------------------------
# 2. Sähköpostit muodostuvat oikealla sisällöllä (Mailgun mockattu/dev-log)
# ---------------------------------------------------------------------------


def test_reservation_confirmation_email_has_correct_content(
    client, admin_user, unit, guest, monkeypatch
):
    from app.email.services import ensure_seed_templates

    ensure_seed_templates()  # db_isolation wipes seed rows between tests

    sent: list[tuple[str, str, dict]] = []

    def _spy(key, *, to, context=None):
        sent.append((key, to, dict(context or {})))
        return True

    monkeypatch.setattr("app.reservations.services.send_template", _spy)

    login(client, admin_user)
    assert _create_reservation_http(client, unit, guest).status_code in (302, 303)

    assert sent, "reservation confirmation email was never sent"
    key, to, context = sent[0]
    assert key == "reservation_confirmation"
    assert to == guest.email
    assert context["unit_name"] == unit.name
    assert context["start_date"] == CHECK_IN.isoformat()
    assert context["end_date"] == CHECK_OUT.isoformat()

    # The stored template renders with that context and mentions the reservation.
    from app.email.templates import render_template_for

    rendered = render_template_for("reservation_confirmation", context | {"reservation_id": 1})
    assert "1" in rendered.subject or "1" in rendered.text
    assert context["start_date"] in rendered.text or context["start_date"] in rendered.html


def test_cancellation_email_is_sent_with_correct_template(
    client, admin_user, unit, guest, monkeypatch
):
    sent: list[str] = []
    monkeypatch.setattr(
        "app.reservations.services.send_template",
        lambda key, *, to, context=None: sent.append(key) or True,
    )

    login(client, admin_user)
    assert _create_reservation_http(client, unit, guest).status_code in (302, 303)
    row_id = _reservation_rows(unit)[0].id

    client.post(f"/admin/reservations/{row_id}/cancel", data={"confirm_cancel": "yes"})
    assert "reservation_cancelled" in sent


# ---------------------------------------------------------------------------
# 3. Maksut: epäonnistunut maksu ei vahvista, väärä signeeraus hylätään
# ---------------------------------------------------------------------------


def _open_invoice_with_pending_payment(organization, actor):
    from app.billing.models import Invoice
    from app.payments.models import Payment

    invoice = Invoice(
        organization_id=organization.id,
        invoice_number="INV-JOURNEY-1",
        amount=Decimal("124.00"),
        vat_rate=Decimal("24.00"),
        vat_amount=Decimal("24.00"),
        subtotal_excl_vat=Decimal("100.00"),
        total_incl_vat=Decimal("124.00"),
        currency="EUR",
        due_date=date.today(),
        status="open",
        created_by_id=actor.id,
    )
    db.session.add(invoice)
    db.session.commit()

    payment = Payment(
        organization_id=organization.id,
        invoice_id=invoice.id,
        provider="paytrail",
        provider_payment_id="pt-journey-1",
        provider_session_id="pt-journey-1",
        amount=Decimal("124.00"),
        currency="EUR",
        status="pending",
    )
    db.session.add(payment)
    db.session.commit()
    return invoice, payment


_PAYTRAIL_QUERY = {
    "checkout-account": "375917",
    "checkout-algorithm": "sha256",
    "checkout-method": "GET",
    "checkout-nonce": "journey-nonce",
    "checkout-timestamp": "2026-07-06T10:00:00Z",
    "checkout-transaction-id": "pt-journey-1",
    "signature": "test-signature",
}


def test_failed_paytrail_callback_does_not_mark_invoice_paid(
    app, client, organization, regular_user, monkeypatch
):
    invoice, payment = _open_invoice_with_pending_payment(organization, regular_user)
    monkeypatch.setattr(
        "app.payments.providers.paytrail.PaytrailProvider.verify_query_signature",
        lambda *a, **k: True,
    )

    resp = client.get(
        "/api/v1/webhooks/paytrail",
        query_string=_PAYTRAIL_QUERY | {"checkout-status": "fail"},
    )
    assert resp.status_code == 200

    db.session.expire_all()
    from app.billing.models import Invoice
    from app.payments.models import Payment

    assert db.session.get(Payment, payment.id).status != "succeeded"
    assert db.session.get(Invoice, invoice.id).status == "open"


def test_paytrail_callback_with_bad_signature_is_rejected(client, organization, regular_user):
    invoice, payment = _open_invoice_with_pending_payment(organization, regular_user)

    resp = client.get(
        "/api/v1/webhooks/paytrail",
        query_string=_PAYTRAIL_QUERY | {"checkout-status": "ok"},
    )
    assert resp.status_code == 401

    db.session.expire_all()
    from app.payments.models import Payment

    assert db.session.get(Payment, payment.id).status == "pending"


# ---------------------------------------------------------------------------
# 4. Pindora-lukkovirhe ei kaada järjestelmää
# ---------------------------------------------------------------------------


def test_pindora_revoke_failure_does_not_break_cancellation(
    client, admin_user, unit, guest, monkeypatch
):
    login(client, admin_user)
    assert _create_reservation_http(client, unit, guest).status_code in (302, 303)
    row_id = _reservation_rows(unit)[0].id

    monkeypatch.setattr(
        "app.portal.services.revoke_access_codes_for_reservation",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("Pindora API down")),
    )

    resp = client.post(
        f"/admin/reservations/{row_id}/cancel",
        data={"confirm_cancel": "yes"},
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303), "lock failure must not break cancellation"

    from app.reservations.models import Reservation

    db.session.expire_all()
    assert db.session.get(Reservation, row_id).status == "cancelled"


def test_pindora_provision_failure_returns_handled_error_on_checkin(
    client, admin_user, unit, guest, monkeypatch
):
    """Online check-in must not 500 when the lock vendor API errors out."""

    from io import BytesIO

    login(client, admin_user)
    assert _create_reservation_http(client, unit, guest).status_code in (302, 303)
    reservation = _reservation_rows(unit)[0]

    from app.portal.models import LockDevice
    from app.portal.services import issue_checkin_token

    db.session.add(
        LockDevice(
            organization_id=admin_user.organization_id,
            unit_id=unit.id,
            provider="pindora",
            provider_device_id="pindora-journey-lock",
            name="Journey Lock",
        )
    )
    db.session.commit()

    monkeypatch.setattr(
        "app.integrations.pindora_lock.service.PindoraLockService.provision_access_code",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("Pindora API down")),
    )

    token = issue_checkin_token(reservation_id=reservation.id)
    resp = client.post(
        f"/portal/check-in/{token}",
        data={
            "full_name": "Jenni Journey",
            "date_of_birth": "1990-01-01",
            "rules_signature": "Jenni Journey",
            "id_document": (BytesIO(b"fake-image-bytes"), "id.jpg"),
        },
        content_type="multipart/form-data",
    )
    # Handled error: the check-in page re-renders with a retryable message
    # (503), instead of the generic unhandled 500 page.
    assert (
        resp.status_code == 503
    ), f"Pindora failure during check-in must be handled, got {resp.status_code}"
    assert "tilapäisen häiriön".encode() in resp.data


# ---------------------------------------------------------------------------
# 5. Virhetilanteet
# ---------------------------------------------------------------------------


def test_reservation_form_with_missing_fields_is_rejected(client, admin_user, unit):
    login(client, admin_user)
    resp = client.post(
        "/admin/reservations/new",
        data={"unit_id": "", "start_date": "", "end_date": ""},
    )
    assert resp.status_code == 200
    assert len(_reservation_rows(unit)) == 0


def test_reservation_with_invalid_dates_is_rejected(client, admin_user, unit, guest):
    login(client, admin_user)
    # checkout before checkin
    resp = _create_reservation_http(client, unit, guest, start=CHECK_OUT, end=CHECK_IN)
    assert resp.status_code == 200
    assert len(_reservation_rows(unit)) == 0


def test_admin_routes_require_login_and_role(client, regular_user):
    resp = client.get("/admin/reservations", follow_redirects=False)
    # Anonymous: redirect to login or explicit 401 — never the reservation list.
    assert resp.status_code in (302, 303, 401)

    login(client, regular_user)  # role=user, not admin
    resp = client.get("/admin/reservations", follow_redirects=False)
    assert resp.status_code in (302, 303, 403)


def test_api_requires_key_and_uses_error_envelope(client):
    resp = client.get("/api/v1/me")
    assert resp.status_code == 401
    body = resp.get_json()
    assert body["success"] is False
    assert body["error"]["code"]


def test_api_health_is_public_and_ok(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.get_json().get("success") is True
