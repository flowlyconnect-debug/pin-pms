"""E2E: varauswizard, kalenteri, tuplavarauksen esto, muokkaus ja peruutus."""

from __future__ import annotations

from datetime import date, timedelta

from e2e.conftest import SeedData


def create_reservation_via_wizard(
    page,
    base_url: str,
    seed: SeedData,
    *,
    check_in: date | None = None,
    check_out: date | None = None,
    expect_success: bool = True,
) -> None:
    """Drive the four wizard steps in the browser (existing guest, EUR 100)."""

    check_in = check_in or seed.check_in
    check_out = check_out or seed.check_out

    # Step 1 — property
    page.goto(f"{base_url}/admin/reservations/new/step/1")
    page.select_option("select[name=property_id]", str(seed.property_id))
    page.click("button[name=action][value=next]")

    # Step 2 — unit + dates
    page.wait_for_url("**/reservations/new/step/2")
    page.select_option("select[name=unit_id]", str(seed.unit_id))
    page.fill("input[name=check_in]", check_in.isoformat())
    page.fill("input[name=check_out]", check_out.isoformat())
    page.click("button[name=action][value=next]")

    if not expect_success:
        page.wait_for_url("**/reservations/new/step/2")
        assert "päällekkäinen" in page.locator("body").inner_text()
        return

    # Step 3 — guest (pick the seeded existing guest)
    page.wait_for_url("**/reservations/new/step/3")
    page.check("input[name=guest_mode][value=existing]")
    page.select_option("select[name=guest_id]", str(seed.guest_id))
    page.click("button[name=action][value=next]")

    # Step 4 — confirm
    page.wait_for_url("**/reservations/new/step/4")
    page.fill("input[name=amount]", "100.00")
    page.click("button[name=action][value=confirm]")


def test_admin_creates_reservation_and_it_is_listed(admin_page, live_server, seed):
    create_reservation_via_wizard(admin_page, live_server, seed)

    admin_page.goto(f"{live_server}/admin/reservations")
    body = admin_page.locator("body")
    assert seed.guest_name.split()[0] in body.inner_text() or "Erkki" in body.inner_text()


def test_reservation_appears_in_calendar_events(admin_page, live_server, seed):
    create_reservation_via_wizard(admin_page, live_server, seed)

    start = (seed.check_in - timedelta(days=7)).isoformat()
    end = (seed.check_out + timedelta(days=7)).isoformat()
    resp = admin_page.request.get(
        f"{live_server}/admin/calendar/events?start={start}&end={end}"
    )
    assert resp.ok
    events = resp.json()
    assert any(seed.check_in.isoformat() in str(ev.get("start", "")) for ev in events), events

    # The calendar page itself renders without errors.
    admin_page.goto(f"{live_server}/admin/calendar")
    assert admin_page.locator("body").inner_text()


def test_overlapping_reservation_is_rejected(admin_page, live_server, seed):
    from app.reservations.models import Reservation

    create_reservation_via_wizard(admin_page, live_server, seed)
    create_reservation_via_wizard(
        admin_page,
        live_server,
        seed,
        expect_success=False,
    )

    active = (
        Reservation.query.filter_by(unit_id=seed.unit_id)
        .filter(Reservation.status != "cancelled")
        .count()
    )
    assert active == 1, "duplicate overlapping reservation created"


def test_admin_can_edit_reservation_dates(admin_page, live_server, seed):
    create_reservation_via_wizard(admin_page, live_server, seed)

    admin_page.goto(f"{live_server}/admin/reservations")
    admin_page.click("a:has-text('Muokkaa')")
    new_end = (seed.check_out + timedelta(days=2)).isoformat()
    admin_page.fill("input[name=end_date]", new_end)
    admin_page.click("button[type=submit]:has-text('Tallenna')")

    from app.reservations.models import Reservation

    row = Reservation.query.filter_by(unit_id=seed.unit_id).one()
    assert row.end_date.isoformat() == new_end


def test_cancelling_reservation_frees_the_slot(admin_page, live_server, seed):
    create_reservation_via_wizard(admin_page, live_server, seed)

    from app.reservations.models import Reservation

    row = Reservation.query.filter_by(unit_id=seed.unit_id).one()

    admin_page.goto(f"{live_server}/admin/reservations/{row.id}")
    admin_page.check("input[name=confirm_cancel]")
    admin_page.click("button:has-text('Peruuta varaus')")
    admin_page.wait_for_load_state()

    from app.extensions import db

    db.session.expire_all()
    row = db.session.get(Reservation, row.id)
    assert row.status == "cancelled"

    # The same dates can now be booked again.
    create_reservation_via_wizard(admin_page, live_server, seed)
    active = (
        Reservation.query.filter_by(unit_id=seed.unit_id)
        .filter(Reservation.status != "cancelled")
        .count()
    )
    assert active == 1
