from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

from app.audit.models import AuditLog
from app.billing.models import Invoice, Lease
from app.extensions import db
from app.gdpr.services import (
    GdprPermissionError,
    anonymize_user_data,
    delete_user_data,
    export_json_safe,
    export_user_data,
)
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.users.models import User, UserRole
from app.users.services import UserServiceError


def _shadow_guest_exists(user_id: int) -> bool:
    from app.guests.models import Guest

    return db.session.get(Guest, user_id) is not None


def _property_unit(*, organization_id: int) -> tuple[Property, Unit]:
    prop = Property(organization_id=organization_id, name="GDPR Prop", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U1", unit_type="double")
    db.session.add(unit)
    db.session.commit()
    return prop, unit


def _invoice_for_user(*, user: User) -> Invoice:
    _prop, unit = _property_unit(organization_id=user.organization_id)
    assert _shadow_guest_exists(user.id)
    lease = Lease(
        organization_id=user.organization_id,
        unit_id=unit.id,
        guest_id=user.id,
        reservation_id=None,
        start_date=date(2026, 6, 1),
        end_date=None,
        rent_amount=Decimal("80.00"),
        deposit_amount=Decimal("0.00"),
        billing_cycle="monthly",
        status="draft",
        notes=None,
        created_by_id=user.id,
    )
    db.session.add(lease)
    db.session.flush()
    inv = Invoice(
        organization_id=user.organization_id,
        lease_id=lease.id,
        reservation_id=None,
        guest_id=user.id,
        invoice_number=None,
        amount=Decimal("40.00"),
        vat_rate=Decimal("0.00"),
        vat_amount=Decimal("0.00"),
        subtotal_excl_vat=Decimal("40.00"),
        total_incl_vat=Decimal("40.00"),
        currency="EUR",
        due_date=date(2026, 6, 10),
        paid_at=None,
        status="draft",
        description=None,
        metadata_json={"token": "secret-should-not-appear-in-export"},
        created_by_id=user.id,
    )
    db.session.add(inv)
    db.session.flush()
    inv.invoice_number = f"GDPR-{user.organization_id}-{inv.id:08d}"
    db.session.commit()
    return inv


def test_export_user_data_returns_complete_json(app, organization, regular_user):
    _prop, unit = _property_unit(organization_id=organization.id)
    assert _shadow_guest_exists(regular_user.id)
    db.session.add(
        Reservation(
            unit_id=unit.id,
            guest_id=regular_user.id,
            guest_name="Test Guest",
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 5),
            status="confirmed",
        )
    )
    db.session.commit()
    _invoice_for_user(user=regular_user)

    data = export_user_data(regular_user.id)
    assert set(data.keys()) == {"audit_log", "guests", "invoices", "reservations", "users"}
    assert data["users"]["id"] == regular_user.id
    assert len(data["reservations"]) >= 1
    assert len(data["invoices"]) >= 1
    assert isinstance(data["guests"], list)
    assert isinstance(data["audit_log"], list)

    row = AuditLog.query.filter_by(action="gdpr.export", target_id=regular_user.id).first()
    assert row is not None


def test_export_does_not_leak_password_hash(app, organization, regular_user):
    raw = export_json_safe(export_user_data(regular_user.id))
    assert "password_hash" not in raw
    assert '"password_hash"' not in raw


def test_export_does_not_leak_totp_secret(app, organization, regular_user):
    regular_user.totp_secret = "JBSWY3DPEHPK3PXP"
    db.session.commit()
    raw = export_json_safe(export_user_data(regular_user.id))
    assert "totp_secret" not in raw
    assert "JBSWY3DPEHPK3PXP" not in raw


def test_export_does_not_leak_backup_codes_or_api_key_hash(app, organization, regular_user):
    from app.api.models import ApiKey

    regular_user.backup_codes = ["hashed1", "hashed2"]
    db.session.commit()
    key, _raw = ApiKey.issue(
        name="gdpr-key",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes="",
    )
    db.session.add(key)
    db.session.commit()

    raw = export_json_safe(export_user_data(regular_user.id))
    assert "backup_codes" not in raw
    assert "key_hash" not in raw
    assert key.key_hash not in raw


def test_anonymize_replaces_pii(app, organization, regular_user):
    regular_user.first_name = "Matti"
    regular_user.last_name = "Meikäläinen"
    regular_user.phone = "+358401"
    regular_user.address = "Katu 1"
    db.session.commit()

    anonymize_user_data(regular_user.id)
    db.session.expire_all()
    u = db.session.get(User, regular_user.id)
    assert u.email == f"anonymized-{u.id}@deleted.local"
    assert u.first_name == "Anonyymi"
    assert u.last_name == "Käyttäjä"
    assert u.phone is None
    assert u.address is None
    assert u.is_active is False
    assert u.anonymized_at is not None
    assert u.organization_id == organization.id

    row = AuditLog.query.filter_by(action="gdpr.anonymize", target_id=regular_user.id).first()
    assert row is not None


def test_anonymize_preserves_invoices_and_audit_log(app, organization, regular_user):
    inv = _invoice_for_user(user=regular_user)
    from app.audit import record as audit_record

    audit_record(
        "test.action",
        target_type="user",
        target_id=regular_user.id,
        actor_id=regular_user.id,
        commit=True,
    )
    before_audit_count = AuditLog.query.filter(AuditLog.actor_id == regular_user.id).count()

    anonymize_user_data(regular_user.id)

    assert db.session.get(Invoice, inv.id) is not None
    assert AuditLog.query.filter(AuditLog.actor_id == regular_user.id).count() >= before_audit_count


def test_delete_calls_anonymize_first(app, organization, regular_user):
    other = User(
        email="other-gdpr@test.local",
        password_hash=generate_password_hash("OtherPass123!"),
        organization_id=organization.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other)
    db.session.commit()

    state = {"anonymize": False}
    from app.gdpr import services as gdpr_services

    real_anonymize = gdpr_services.anonymize_user_data

    def wrap_anon(uid: int) -> None:
        state["anonymize"] = True
        real_anonymize(uid)

    orig_delete = db.session.delete

    def wrap_delete(obj):
        if isinstance(obj, User) and obj.id == regular_user.id:
            assert state["anonymize"] is True
        return orig_delete(obj)

    with patch.object(gdpr_services, "anonymize_user_data", wrap_anon):
        with patch.object(db.session, "delete", wrap_delete):
            delete_user_data(regular_user.id, from_cli=True)

    assert db.session.get(User, regular_user.id) is None


def test_delete_creates_audit_log_before_deletion(app, organization, regular_user):
    other = User(
        email="other2-gdpr@test.local",
        password_hash=generate_password_hash("OtherPass123!"),
        organization_id=organization.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other)
    db.session.commit()
    uid = regular_user.id

    delete_user_data(uid, from_cli=True)

    row = AuditLog.query.filter_by(action="gdpr.delete", target_id=uid).first()
    assert row is not None
    assert db.session.get(User, uid) is None


def test_delete_requires_superadmin_when_not_cli(app, organization, regular_user, superadmin):
    other = User(
        email="other3-gdpr@test.local",
        password_hash=generate_password_hash("OtherPass123!"),
        organization_id=organization.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other)
    db.session.commit()

    from flask_login import login_user

    with app.test_request_context("/"):
        login_user(regular_user)
        with pytest.raises(GdprPermissionError):
            delete_user_data(superadmin.id, from_cli=False)


def test_cli_gdpr_commands_work(app, organization, regular_user):

    other = User(
        email="cli-peer@test.local",
        password_hash=generate_password_hash("OtherPass123!"),
        organization_id=organization.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other)
    db.session.commit()

    runner = app.test_cli_runner()

    r_export = runner.invoke(args=["gdpr-export-user", "--email", regular_user.email])
    assert r_export.exit_code == 0
    assert "users" in r_export.output

    r_bad = runner.invoke(args=["gdpr-export-user", "--email", "nope@missing.invalid"])
    assert r_bad.exit_code != 0

    r_anon = runner.invoke(args=["gdpr-anonymize-user", "--email", other.email, "--yes"])
    assert r_anon.exit_code == 0
    db.session.expire_all()
    o = db.session.get(User, other.id)
    assert o is not None
    assert o.email.startswith("anonymized-")

    victim = User(
        email="cli-delete@test.local",
        password_hash=generate_password_hash("DelPass123!"),
        organization_id=organization.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(victim)
    db.session.commit()
    vid = victim.id

    r_del = runner.invoke(args=["gdpr-delete-user", "--email", "cli-delete@test.local", "--yes"])
    assert r_del.exit_code == 0
    assert db.session.get(User, vid) is None

    r_del_missing = runner.invoke(
        args=["gdpr-delete-user", "--email", "gone@missing.invalid", "--yes"]
    )
    assert r_del_missing.exit_code != 0


def test_export_audit_action_recorded(app, organization, regular_user):
    export_user_data(regular_user.id)
    assert AuditLog.query.filter_by(action="gdpr.export").first() is not None


def test_anonymize_audit_action_recorded(app, organization, regular_user):
    anonymize_user_data(regular_user.id)
    assert AuditLog.query.filter_by(action="gdpr.anonymize").first() is not None


def test_delete_audit_action_recorded(app, organization, regular_user):
    other = User(
        email="audit-peer@test.local",
        password_hash=generate_password_hash("OtherPass123!"),
        organization_id=organization.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other)
    db.session.commit()
    delete_user_data(regular_user.id, from_cli=True)
    assert (
        AuditLog.query.filter_by(action="gdpr.delete", target_id=regular_user.id).first()
        is not None
    )


def test_delete_user_not_found_raises(app, organization):
    with pytest.raises(UserServiceError):
        delete_user_data(999_999, from_cli=True)
