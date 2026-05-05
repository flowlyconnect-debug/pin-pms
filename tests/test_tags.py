from __future__ import annotations

from app.audit.models import AuditLog
from app.extensions import db
from app.guests.models import Guest
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.tags.services import TagService, TagServiceError
from app.users.models import Organization


def _seed_guest(org_id: int) -> Guest:
    guest = Guest(organization_id=org_id, first_name="Vip", last_name="Guest", email="vip@test.local")
    db.session.add(guest)
    db.session.flush()
    return guest


def _seed_property_and_reservation(org_id: int):
    prop = Property(organization_id=org_id, name="HQ")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A1")
    db.session.add(unit)
    db.session.flush()
    guest = _seed_guest(org_id)
    reservation = Reservation(
        unit_id=unit.id,
        guest_id=guest.id,
        guest_name=guest.full_name,
        start_date="2026-01-01",
        end_date="2026-01-02",
    )
    db.session.add(reservation)
    db.session.flush()
    return prop, guest, reservation


def test_create_tag(organization, regular_user):
    row = TagService.create(organization.id, "VIP", "green", regular_user.id)
    db.session.commit()
    assert row.name == "VIP"
    assert row.color == "green"
    assert row.organization_id == organization.id
    assert AuditLog.query.filter_by(action="tag.created", target_id=row.id).first() is not None


def test_tag_limit_100_per_org(organization, regular_user):
    for idx in range(100):
        TagService.create(organization.id, f"tag-{idx}", "blue", regular_user.id)
    db.session.commit()
    try:
        TagService.create(organization.id, "tag-101", "blue", regular_user.id)
        assert False
    except TagServiceError as err:
        assert err.code == "validation_error"


def test_attach_detach_tag_to_guest(organization, regular_user):
    guest = _seed_guest(organization.id)
    tag = TagService.create(organization.id, "VIP", "yellow", regular_user.id)
    TagService.attach(organization.id, "guest", guest.id, tag.id, regular_user.id)
    db.session.commit()
    rows = TagService.list_for_target(organization.id, "guest", guest.id)
    assert [r.id for r in rows] == [tag.id]
    assert AuditLog.query.filter_by(action="tag.attached").first() is not None

    TagService.detach(organization.id, "guest", guest.id, tag.id, regular_user.id)
    db.session.commit()
    assert TagService.list_for_target(organization.id, "guest", guest.id) == []
    assert AuditLog.query.filter_by(action="tag.detached").first() is not None


def test_tag_tenant_isolation(regular_user):
    org_a = Organization(name="A")
    org_b = Organization(name="B")
    db.session.add_all([org_a, org_b])
    db.session.flush()
    guest_b = _seed_guest(org_b.id)
    tag_a = TagService.create(org_a.id, "A-Tag", "red", regular_user.id)
    db.session.commit()
    try:
        TagService.attach(org_b.id, "guest", guest_b.id, tag_a.id, regular_user.id)
        assert False
    except TagServiceError as err:
        assert err.status in (404, 403)


def test_api_tags_require_scope(client, regular_user):
    from app.api.models import ApiKey

    key, raw = ApiKey.issue(
        name="No tags scope",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes="guests:read",
    )
    db.session.add(key)
    db.session.commit()
    no_scope = client.get("/api/v1/tags", headers={"X-API-Key": raw})
    assert no_scope.status_code == 403
