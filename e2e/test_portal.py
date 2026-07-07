"""E2E: portaalikirjautuminen ja omien varausten näkyminen (eristys)."""

from __future__ import annotations

import pytest

from e2e.conftest import PORTAL_PASSWORD


@pytest.fixture()
def portal_reservation(flask_app, seed):
    """A confirmed reservation owned by the portal user (project convention:
    ``Reservation.guest_id`` stores the portal ``User.id``, see tests/test_portal.py)."""

    from app.extensions import db
    from app.reservations.models import Reservation

    row = Reservation(
        unit_id=seed.unit_id,
        guest_id=seed.portal_user_id,
        guest_name="Portal E2E Guest",
        start_date=seed.check_in,
        end_date=seed.check_out,
        status="confirmed",
    )
    db.session.add(row)
    db.session.commit()
    return row


def portal_login(page, base_url: str, email: str, password: str) -> None:
    page.goto(f"{base_url}/portal/login")
    page.fill("#email", email)
    page.fill("#password", password)
    page.click("form:has(#password) button[type=submit]")


def test_portal_user_logs_in_and_sees_own_reservation(page, live_server, seed, portal_reservation):
    portal_login(page, live_server, seed.portal_email, PORTAL_PASSWORD)
    page.wait_for_url("**/portal/**")

    page.goto(f"{live_server}/portal/reservations")
    body = page.locator("body").inner_text()
    assert seed.check_in.isoformat()[:4] in body  # year visible somewhere
    assert (
        seed.unit_name in body or "Portal E2E Guest" in body or seed.check_in.strftime("%d") in body
    )


def test_portal_wrong_password_rejected(page, live_server, seed):
    portal_login(page, live_server, seed.portal_email, "VaaraSalasana123!")
    page.wait_for_selector("form")
    assert "/portal/dashboard" not in page.url


def test_portal_user_cannot_open_foreign_reservation(
    page, live_server, seed, portal_reservation, flask_app
):
    from werkzeug.security import generate_password_hash

    from app.extensions import db
    from app.reservations.models import Reservation
    from app.users.models import User, UserRole

    other = User(
        email="e2e-other-guest@example.com",
        password_hash=generate_password_hash(PORTAL_PASSWORD),
        organization_id=seed.org_id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other)
    db.session.commit()

    foreign = Reservation(
        unit_id=seed.unit_id,
        guest_id=other.id,
        guest_name="Other Guest",
        start_date=seed.check_out,
        end_date=seed.check_out.replace(day=seed.check_out.day),
        status="confirmed",
    )
    # Non-overlapping window right after the first reservation.
    from datetime import timedelta

    foreign.start_date = seed.check_out + timedelta(days=1)
    foreign.end_date = seed.check_out + timedelta(days=3)
    db.session.add(foreign)
    db.session.commit()

    portal_login(page, live_server, seed.portal_email, PORTAL_PASSWORD)
    page.wait_for_url("**/portal/**")

    resp = page.request.get(f"{live_server}/portal/reservations/{foreign.id}", max_redirects=0)
    assert resp.status in (302, 303, 403, 404)
