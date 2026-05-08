from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from html.parser import HTMLParser

from app.billing.models import Invoice, Lease
from app.core.i18n import priority_label, status_label
from app.extensions import db
from app.guests.models import Guest
from app.maintenance.models import MaintenanceRequest
from app.payments.models import Payment
from app.properties.models import Property, Unit
from app.reservations.models import Reservation


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _seed_property_and_unit(admin_user):
    prop = Property(organization_id=admin_user.organization_id, name="Kielitesti", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A1", unit_type="double")
    db.session.add(unit)
    db.session.commit()
    return prop, unit


def _seed_guest(admin_user):
    guest = Guest(
        organization_id=admin_user.organization_id,
        first_name="Pekka",
        last_name="Testaaja",
        email="pekka@example.com",
    )
    db.session.add(guest)
    db.session.flush()
    return guest


def _visible_text(html: str) -> str:
    class _VisibleTextParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self._skip_stack: list[str] = []
            self._parts: list[str] = []

        def handle_starttag(self, tag, attrs):
            _ = attrs
            if tag in {"script", "style"}:
                self._skip_stack.append(tag)

        def handle_endtag(self, tag):
            if self._skip_stack and self._skip_stack[-1] == tag:
                self._skip_stack.pop()

        def handle_data(self, data):
            if self._skip_stack:
                return
            cleaned = (data or "").strip()
            if cleaned:
                self._parts.append(cleaned)

    parser = _VisibleTextParser()
    parser.feed(html)
    return " ".join(parser._parts)


def _seed_ui_rows(admin_user):
    prop, unit = _seed_property_and_unit(admin_user)
    guest = _seed_guest(admin_user)
    today = date.today()

    reservation = Reservation(
        unit_id=unit.id,
        guest_id=guest.id,
        guest_name=guest.full_name,
        start_date=today,
        end_date=today + timedelta(days=2),
        status="active",
        amount=Decimal("120.00"),
        currency="EUR",
        payment_status="pending",
    )
    db.session.add(reservation)
    db.session.flush()

    lease = Lease(
        organization_id=admin_user.organization_id,
        unit_id=unit.id,
        guest_id=guest.id,
        reservation_id=reservation.id,
        start_date=today,
        end_date=today + timedelta(days=30),
        rent_amount=Decimal("950.00"),
        deposit_amount=Decimal("200.00"),
        billing_cycle="monthly",
        status="draft",
        created_by_id=admin_user.id,
    )
    db.session.add(lease)
    db.session.flush()

    invoice = Invoice(
        organization_id=admin_user.organization_id,
        lease_id=lease.id,
        reservation_id=reservation.id,
        guest_id=guest.id,
        amount=Decimal("124.00"),
        vat_rate=Decimal("24.00"),
        vat_amount=Decimal("24.00"),
        subtotal_excl_vat=Decimal("100.00"),
        total_incl_vat=Decimal("124.00"),
        currency="EUR",
        due_date=today + timedelta(days=7),
        status="overdue",
        created_by_id=admin_user.id,
    )
    db.session.add(invoice)
    db.session.flush()

    payment = Payment(
        organization_id=admin_user.organization_id,
        invoice_id=invoice.id,
        reservation_id=reservation.id,
        provider="stripe",
        amount=Decimal("124.00"),
        currency="EUR",
        status="paid",
    )
    db.session.add(payment)

    maintenance = MaintenanceRequest(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=guest.id,
        reservation_id=reservation.id,
        title="Vuotava hana",
        description="Kylpyhuoneessa vuotaa.",
        status="in_progress",
        priority="urgent",
        assigned_to_id=None,
        due_date=None,
        resolved_at=None,
        created_by_id=admin_user.id,
    )
    db.session.add(maintenance)
    db.session.commit()


def test_admin_pages_have_finnish_buttons(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop, unit = _seed_property_and_unit(admin_user)

    row = MaintenanceRequest(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        unit_id=unit.id,
        guest_id=None,
        reservation_id=None,
        title="Vuotava hana",
        description="Kylpyhuoneessa vuotaa.",
        status="new",
        priority="normal",
        assigned_to_id=None,
        due_date=None,
        resolved_at=None,
        created_by_id=admin_user.id,
    )
    db.session.add(row)
    db.session.commit()

    urls = [
        "/admin/maintenance-requests",
        "/admin/maintenance-requests/new",
        f"/admin/maintenance-requests/{row.id}",
        f"/admin/maintenance-requests/{row.id}/edit",
    ]
    for url in urls:
        response = client.get(url)
        assert response.status_code == 200
        html = response.get_data(as_text=True)
        assert "Save" not in html
        assert "Cancel" not in html
        assert "Delete" not in html
        assert "Edit" not in html
        assert "Create" not in html
        assert "Submit" not in html


def test_maintenance_priority_dropdown_in_finnish(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    _seed_property_and_unit(admin_user)

    response = client.get("/admin/maintenance-requests/new")
    assert response.status_code == 200
    html = response.get_data(as_text=True)

    assert '<option value="low"' in html and ">Matala</option>" in html
    assert '<option value="normal"' in html and ">Normaali</option>" in html
    assert '<option value="high"' in html and ">Korkea</option>" in html
    assert '<option value="urgent"' in html and ">Kiireellinen</option>" in html
    assert "value=\"Matala\"" not in html


def test_calendar_sync_page_does_not_500(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/calendar-sync/conflicts")
    assert response.status_code == 200


def test_list_views_do_not_render_raw_enum_labels(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    _seed_ui_rows(admin_user)

    routes = [
        "/admin/reservations",
        "/admin/leases",
        "/admin/invoices",
        "/admin/maintenance-requests",
        "/admin/payments",
    ]
    expected_finnish = {"Aktiivinen", "Luonnos", "Erääntynyt", "Työn alla", "Kiireellinen", "Maksettu"}
    raw_values = {"active", "draft", "overdue", "in_progress", "urgent", "paid"}

    for route in routes:
        response = client.get(route)
        if response.status_code == 404:
            continue
        assert response.status_code == 200
        text = _visible_text(response.get_data(as_text=True))
        lowered = text.lower()
        for raw in raw_values:
            assert raw not in lowered
        assert any(label in text for label in expected_finnish)


def test_filter_dropdown_labels_are_finnish(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    _seed_ui_rows(admin_user)

    response = client.get("/admin/invoices")
    assert response.status_code == 200
    options = {}
    for value in ("active", "paid", "high", "urgent"):
        marker = f'<option value="{value}"'
        html = response.get_data(as_text=True)
        if marker not in html:
            continue
        segment = html.split(marker, 1)[1]
        text = segment.split(">", 1)[1].split("</option>", 1)[0].strip()
        options[value] = text

    assert options.get("active") == "Aktiivinen"
    assert options.get("paid") == "Maksettu"
    assert options.get("high") is None  # this view does not expose priority options

    response_maintenance = client.get("/admin/maintenance-requests")
    assert response_maintenance.status_code == 200
    html_maintenance = response_maintenance.get_data(as_text=True)
    options_maintenance = {}
    for value in ("high", "urgent"):
        marker = f'<option value="{value}"'
        segment = html_maintenance.split(marker, 1)[1]
        options_maintenance[value] = segment.split(">", 1)[1].split("</option>", 1)[0].strip()
    assert options_maintenance.get("high") == "Korkea"
    assert options_maintenance.get("urgent") == "Kiireellinen"


def test_status_label_filter():
    assert status_label("active") == "Aktiivinen"
    assert status_label("paid") == "Maksettu"
    assert status_label(None) == "-"


def test_priority_label_filter():
    assert priority_label("high") == "Korkea"
    assert priority_label("urgent") == "Kiireellinen"
    assert priority_label("unknown") == "-"
