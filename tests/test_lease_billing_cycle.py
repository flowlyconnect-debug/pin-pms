from __future__ import annotations

from datetime import date


def _make_active_lease(admin_user, *, billing_cycle: str, status: str = "active"):
    from app.billing import services as billing_service
    from app.extensions import db
    from app.properties.models import Property, Unit

    prop = Property(
        organization_id=admin_user.organization_id, name=f"Cycle {billing_cycle}", address="x"
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U1", unit_type="double")
    db.session.add(unit)
    db.session.commit()
    lease = billing_service.create_lease(
        organization_id=admin_user.organization_id,
        unit_id=unit.id,
        guest_id=admin_user.id,
        reservation_id=None,
        start_date_raw="2026-01-01",
        end_date_raw=None,
        rent_amount_raw="150.00",
        deposit_amount_raw="0",
        billing_cycle=billing_cycle,
        notes=None,
        actor_user_id=admin_user.id,
    )
    if status != "draft":
        from app.billing.models import Lease
        from app.extensions import db as _db

        row = Lease.query.get(lease["id"])
        row.status = status
        _db.session.commit()
    return lease


def test_monthly_active_lease_creates_invoice_on_first_day(admin_user):
    from app.billing import services as billing_service

    _ = _make_active_lease(admin_user, billing_cycle="monthly", status="active")
    summary = billing_service.generate_due_lease_invoices(run_date=date(2026, 2, 1))
    assert summary["created"] >= 1


def test_ended_lease_does_not_create_invoice(admin_user):
    from app.billing import services as billing_service

    _ = _make_active_lease(admin_user, billing_cycle="monthly", status="ended")
    summary = billing_service.generate_due_lease_invoices(run_date=date(2026, 2, 1))
    assert summary["created"] == 0


def test_pending_signature_lease_does_not_create_invoice(admin_user):
    from app.billing import services as billing_service

    _ = _make_active_lease(admin_user, billing_cycle="monthly", status="pending_signature")
    summary = billing_service.generate_due_lease_invoices(run_date=date(2026, 2, 1))
    assert summary["created"] == 0


def test_same_period_no_duplicate_invoice(admin_user):
    from app.billing import services as billing_service

    _ = _make_active_lease(admin_user, billing_cycle="monthly", status="active")
    summary_1 = billing_service.generate_due_lease_invoices(run_date=date(2026, 3, 1))
    summary_2 = billing_service.generate_due_lease_invoices(run_date=date(2026, 3, 1))
    assert summary_1["created"] >= 1
    assert summary_2["created"] == 0
