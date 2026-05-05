from __future__ import annotations

from werkzeug.security import generate_password_hash

from app.audit.models import AuditLog
from app.extensions import db
from app.notifications.models import Notification
from app.notifications import services as notification_service
from app.organizations.models import Organization
from app.users.models import User, UserRole


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _seed_org_and_admin(*, name: str, email: str, password: str) -> tuple[Organization, User]:
    org = Organization(name=name)
    db.session.add(org)
    db.session.flush()
    user = User(
        email=email,
        password_hash=generate_password_hash(password),
        organization_id=org.id,
        role=UserRole.ADMIN.value,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    user.password_plain = password
    return org, user


def test_notification_only_visible_to_own_org(app):
    with app.app_context():
        org_a, user_a = _seed_org_and_admin(name="Org A", email="orga@test.local", password="Pass123!")
        org_b, _ = _seed_org_and_admin(name="Org B", email="orgb@test.local", password="Pass123!")
        notification_service.create(org_a.id, "reservation.created", "A event")
        notification_service.create(org_b.id, "reservation.created", "B event")
        db.session.commit()

        rows = notification_service.list_all_for_user(
            user_id=user_a.id,
            organization_id=user_a.organization_id,
        )
        assert len(rows) == 1
        assert rows[0].organization_id == org_a.id


def test_notification_mark_read_requires_owner(app):
    with app.app_context():
        org_a, user_a = _seed_org_and_admin(name="Org A", email="orga-owner@test.local", password="Pass123!")
        org_b, _ = _seed_org_and_admin(name="Org B", email="orgb-owner@test.local", password="Pass123!")
        foreign = notification_service.create(org_b.id, "maintenance.requested", "B only")
        db.session.commit()
        assert foreign is not None

        try:
            notification_service.mark_read(notification_id=foreign.id, user_id=user_a.id)
            assert False, "Expected forbidden error"
        except notification_service.NotificationServiceError as err:
            assert err.status == 403

        reloaded = Notification.query.get(foreign.id)
        assert reloaded is not None
        assert reloaded.is_read is False


def test_unread_count_excludes_read(app):
    with app.app_context():
        org, user = _seed_org_and_admin(name="Org A", email="count@test.local", password="Pass123!")
        first = notification_service.create(org.id, "reservation.created", "first")
        second = notification_service.create(org.id, "reservation.created", "second")
        db.session.commit()
        assert first is not None
        assert second is not None

        notification_service.mark_read(notification_id=first.id, user_id=user.id)
        db.session.commit()

        count = notification_service.unread_count(user_id=user.id, organization_id=org.id)
        assert count == 1


def test_create_notification_audits(app):
    with app.app_context():
        org, _ = _seed_org_and_admin(name="Org A", email="audit@test.local", password="Pass123!")
        row = notification_service.create(
            organization_id=org.id,
            type="invoice.overdue",
            title="Overdue",
            severity="warning",
        )
        db.session.commit()
        assert row is not None

        audit = AuditLog.query.filter_by(action="notification.created", target_id=row.id).first()
        assert audit is not None
        assert audit.target_type == "notification"
        assert (audit.context or {}).get("type") == "invoice.overdue"


def test_notification_bell_renders_in_admin(client, app):
    with app.app_context():
        _, user = _seed_org_and_admin(name="Org A", email="bell@test.local", password="Pass123!")
        email = user.email
        password = user.password_plain
    _login(client, email=email, password=password)
    response = client.get("/admin")
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "data-admin-notifications" in html


def test_mark_all_read_marks_only_own_org(app):
    with app.app_context():
        org_a, user_a = _seed_org_and_admin(name="Org A", email="readall-a@test.local", password="Pass123!")
        org_b, _ = _seed_org_and_admin(name="Org B", email="readall-b@test.local", password="Pass123!")

        a_row = notification_service.create(org_a.id, "reservation.created", "A")
        b_row = notification_service.create(org_b.id, "reservation.created", "B")
        db.session.commit()
        assert a_row is not None
        assert b_row is not None

        marked = notification_service.mark_all_read(
            user_id=user_a.id,
            organization_id=user_a.organization_id,
        )
        db.session.commit()

        assert marked == 1
        assert Notification.query.get(a_row.id).is_read is True
        assert Notification.query.get(b_row.id).is_read is False

