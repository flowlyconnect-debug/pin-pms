from __future__ import annotations

from datetime import date, datetime, timezone
from io import BytesIO

from app.core.security import hash_token


def test_portal_checkin_issues_access_code_and_hashes_db(client, regular_user, monkeypatch):
    from app.extensions import db
    from app.portal.models import AccessCode, LockDevice
    from app.portal.services import issue_checkin_token
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation

    monkeypatch.setattr(
        "app.integrations.pindora_lock.service.PindoraLockService.provision_access_code",
        lambda self, **kwargs: {"provider_code_id": "vendor-code-1", "status": "created"},
    )

    prop = Property(organization_id=regular_user.organization_id, name="Checkin Prop", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A1", unit_type="studio")
    db.session.add(unit)
    db.session.flush()
    lock = LockDevice(
        organization_id=regular_user.organization_id,
        unit_id=unit.id,
        provider="pindora",
        provider_device_id="dev-1",
        name="Front door",
        status="online",
    )
    db.session.add(lock)
    reservation = Reservation(
        unit_id=unit.id,
        guest_id=regular_user.id,
        guest_name=regular_user.email,
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 5),
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()

    token = issue_checkin_token(reservation_id=reservation.id)
    response = client.post(
        f"/portal/check-in/{token}",
        data={
            "full_name": "Portal Guest",
            "date_of_birth": "1990-01-01",
            "rules_signature": "Portal Guest",
            "id_document": (BytesIO(b"fake-image-bytes"), "id.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 200
    assert b"Ovikoodisi:" in response.data

    row = AccessCode.query.filter_by(reservation_id=reservation.id).first()
    assert row is not None
    assert row.code_hash
    assert row.code_hash != hash_token("000000")
    assert b"code_hash" not in response.data


def test_cancel_reservation_revokes_existing_access_codes(client, admin_user, monkeypatch):
    from app.extensions import db
    from app.portal.models import AccessCode, LockDevice
    from app.properties.models import Property, Unit
    from app.reservations.models import Reservation
    from app.reservations.services import cancel_reservation

    monkeypatch.setattr(
        "app.integrations.pindora_lock.service.PindoraLockService.revoke_access_code",
        lambda self, **kwargs: None,
    )

    prop = Property(organization_id=admin_user.organization_id, name="Cancel Prop", address=None)
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="C1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    lock = LockDevice(
        organization_id=admin_user.organization_id,
        unit_id=unit.id,
        provider="pindora",
        provider_device_id="dev-cancel",
        name="Cancel lock",
        status="online",
    )
    db.session.add(lock)
    reservation = Reservation(
        unit_id=unit.id,
        guest_id=admin_user.id,
        guest_name=admin_user.email,
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 3),
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.flush()
    code = AccessCode(
        reservation_id=reservation.id,
        lock_device_id=lock.id,
        code_hash=hash_token("123456"),
        provider_code_id="provider-code-77",
        valid_from=datetime(2026, 6, 1, tzinfo=timezone.utc),
        valid_until=datetime(2026, 6, 3, tzinfo=timezone.utc),
        is_active=True,
    )
    db.session.add(code)
    db.session.commit()

    cancel_reservation(
        organization_id=admin_user.organization_id,
        reservation_id=reservation.id,
        actor_user_id=admin_user.id,
    )
    db.session.refresh(code)
    assert code.is_active is False
    assert code.revoked_at is not None
