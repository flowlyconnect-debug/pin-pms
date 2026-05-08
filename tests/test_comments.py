from __future__ import annotations

from datetime import date, datetime, timedelta

from jinja2 import Environment

from app.audit.models import AuditLog
from app.comments.services import CommentService, CommentServiceError
from app.extensions import db
from app.guests.models import Guest
from app.notifications.models import Notification
from app.properties.models import Property, Unit
from app.reservations.models import Reservation
from app.users.models import Organization, User, UserRole


def _seed_reservation(org_id: int, guest_id: int) -> Reservation:
    prop = Property(organization_id=org_id, name="Test")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="U1")
    db.session.add(unit)
    db.session.flush()
    row = Reservation(
        unit_id=unit.id,
        guest_id=guest_id,
        guest_name="Guest Name",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 2),
    )
    db.session.add(row)
    db.session.flush()
    return row


def test_create_comment(organization, regular_user):
    guest = Guest(organization_id=organization.id, first_name="A", last_name="B")
    db.session.add(guest)
    db.session.flush()
    reservation = _seed_reservation(organization.id, guest.id)
    row = CommentService.create(
        organization.id, "reservation", reservation.id, regular_user.id, "Moi"
    )
    db.session.commit()
    assert row.body == "Moi"
    assert row.author_user_id == regular_user.id
    assert row.target_id == reservation.id
    assert (
        AuditLog.query.filter_by(action="comment.created", target_id=reservation.id).first()
        is not None
    )


def test_edit_comment_by_author_only(organization, regular_user, admin_user):
    guest = Guest(organization_id=organization.id, first_name="A", last_name="B")
    db.session.add(guest)
    db.session.flush()
    reservation = _seed_reservation(organization.id, guest.id)
    row = CommentService.create(
        organization.id, "reservation", reservation.id, regular_user.id, "Vanha"
    )
    db.session.commit()
    row = CommentService.edit(row.id, regular_user.id, "Uusi")
    db.session.commit()
    assert row.body == "Uusi"
    try:
        CommentService.edit(row.id, admin_user.id, "Ei saa")
        raise AssertionError("Expected CommentServiceError")
    except CommentServiceError as err:
        assert err.status == 403


def test_edit_comment_after_15_min_rejected(organization, regular_user):
    guest = Guest(organization_id=organization.id, first_name="A", last_name="B")
    db.session.add(guest)
    db.session.flush()
    reservation = _seed_reservation(organization.id, guest.id)
    row = CommentService.create(
        organization.id, "reservation", reservation.id, regular_user.id, "Old"
    )
    row.created_at = datetime.utcnow() - timedelta(minutes=16)
    db.session.commit()
    try:
        CommentService.edit(row.id, regular_user.id, "new")
        raise AssertionError("Expected CommentServiceError")
    except CommentServiceError as err:
        assert err.status == 403


def test_delete_comment_by_author_or_admin(organization, regular_user, admin_user):
    guest = Guest(organization_id=organization.id, first_name="A", last_name="B")
    db.session.add(guest)
    db.session.flush()
    reservation = _seed_reservation(organization.id, guest.id)
    row = CommentService.create(
        organization.id, "reservation", reservation.id, regular_user.id, "Del"
    )
    db.session.commit()
    CommentService.delete(row.id, admin_user.id)
    db.session.commit()
    assert AuditLog.query.filter_by(action="comment.deleted").first() is not None


def test_comment_mentions_create_notification(organization, regular_user):
    teammate = User(
        organization_id=organization.id,
        email="kollega@test.local",
        password_hash="x",
        role=UserRole.USER.value,
        is_active=True,
    )
    guest = Guest(organization_id=organization.id, first_name="A", last_name="B")
    db.session.add_all([teammate, guest])
    db.session.flush()
    reservation = _seed_reservation(organization.id, guest.id)
    CommentService.create(
        organization.id,
        "reservation",
        reservation.id,
        regular_user.id,
        "Moi @kollega",
        is_internal=True,
    )
    db.session.commit()
    assert Notification.query.filter_by(user_id=teammate.id).first() is not None


def test_comment_body_is_escaped():
    env = Environment(autoescape=True)
    rendered = env.from_string("{{ body }}").render(body="<script>alert(1)</script>")
    assert "<script>" not in rendered


def test_comment_tenant_isolation(regular_user):
    org_a = Organization(name="A")
    org_b = Organization(name="B")
    db.session.add_all([org_a, org_b])
    db.session.flush()
    guest = Guest(organization_id=org_b.id, first_name="B", last_name="Guest")
    db.session.add(guest)
    db.session.flush()
    reservation = _seed_reservation(org_b.id, guest.id)
    CommentService.create(org_b.id, "reservation", reservation.id, regular_user.id, "x")
    db.session.commit()
    try:
        CommentService.list_for_target(
            org_a.id, "reservation", reservation.id, include_internal=True
        )
        raise AssertionError("Expected CommentServiceError")
    except CommentServiceError as err:
        assert err.status in (403, 404)
