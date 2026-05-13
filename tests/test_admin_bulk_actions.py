from __future__ import annotations

from datetime import date, timedelta


def _login_admin(client, admin_user):
    client.post("/login", data={"email": admin_user.email, "password": admin_user.password_plain})


def _seed_reservations(app, organization, count: int = 3):
    from app.extensions import db
    from app.guests.models import Guest
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    guest = Guest(organization_id=organization.id, first_name="Bulk", last_name="Guest")
    prop = Property(organization_id=organization.id, name="Bulk Property")
    db.session.add_all([guest, prop])
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U1")
    db.session.add(unit)
    db.session.flush()
    rows = []
    for i in range(count):
        row = Reservation(
            unit_id=unit.id,
            guest_id=guest.id,
            guest_name=f"G{i}",
            start_date=date.today() + timedelta(days=i),
            end_date=date.today() + timedelta(days=i + 1),
            status="confirmed",
        )
        db.session.add(row)
        rows.append(row)
    db.session.commit()
    return rows


def test_bulk_cancel_reservations_audits_each(app, client, organization, admin_user):
    from app.audit.models import AuditLog
    from app.reservations.models import Reservation

    rows = _seed_reservations(app, organization, 3)
    _login_admin(client, admin_user)
    rv = client.post(
        "/admin/reservations/bulk",
        data={"action": "cancel", "ids": [r.id for r in rows], "idempotency_key": "bulk-1"},
        headers={"Accept": "application/json"},
    )
    assert rv.status_code == 200
    for row in rows:
        refreshed = Reservation.query.get(row.id)
        assert refreshed.status == "cancelled"
        assert AuditLog.query.filter_by(
            action="reservation.bulk_cancelled", target_id=row.id
        ).first()


def test_bulk_action_rejects_other_org_ids(app, client, organization, admin_user):
    from app.extensions import db
    from app.organizations.models import Organization
    from app.reservations.models import Reservation

    own = _seed_reservations(app, organization, 1)[0]
    org_b = Organization(name="B")
    db.session.add(org_b)
    db.session.commit()
    other = _seed_reservations(app, org_b, 1)[0]
    _login_admin(client, admin_user)
    rv = client.post(
        "/admin/reservations/bulk",
        data={"action": "cancel", "ids": [own.id, other.id], "idempotency_key": "bulk-2"},
    )
    assert rv.status_code == 403
    assert Reservation.query.get(other.id).status == "confirmed"


def test_bulk_action_idempotent_with_key(app, client, organization, admin_user):
    from app.audit.models import AuditLog

    rows = _seed_reservations(app, organization, 1)
    _login_admin(client, admin_user)
    payload = {"action": "cancel", "ids": [rows[0].id], "idempotency_key": "bulk-3"}
    headers = {"Accept": "application/json"}
    assert client.post("/admin/reservations/bulk", data=payload, headers=headers).status_code == 200
    assert client.post("/admin/reservations/bulk", data=payload, headers=headers).status_code == 200
    count = AuditLog.query.filter_by(
        action="reservation.bulk_cancelled", target_id=rows[0].id
    ).count()
    assert count == 1


def test_bulk_action_requires_csrf(app, client, organization, admin_user):
    app.config["WTF_CSRF_ENABLED"] = True
    rows = _seed_reservations(app, organization, 1)
    _login_admin(client, admin_user)
    rv = client.post("/admin/reservations/bulk", data={"action": "cancel", "ids": [rows[0].id]})
    assert rv.status_code in (400, 403)
    app.config["WTF_CSRF_ENABLED"] = False


def test_bulk_action_rejects_more_than_1000_sync(app, client, organization, admin_user):
    _login_admin(client, admin_user)
    rv = client.post(
        "/admin/reservations/bulk",
        data={"action": "cancel", "ids": list(range(1, 1002)), "idempotency_key": "bulk-4"},
        headers={"Accept": "application/json"},
    )
    assert rv.status_code == 422
