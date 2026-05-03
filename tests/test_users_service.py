from __future__ import annotations

import pytest
from werkzeug.security import generate_password_hash

from app.audit.models import ActorType, AuditLog
from app.extensions import db
from app.users import services as user_services
from app.users.models import User, UserRole


def test_create_user_success_and_audit(app, organization):
    with app.app_context():
        user = user_services.create_user(
            email="newuser@test.local",
            password="NewUserPass123!",
            role=UserRole.USER.value,
            organization_id=organization.id,
        )
        assert user.id is not None
        assert user.email == "newuser@test.local"
        assert user.organization_id == organization.id
        assert user.is_active is True

        row = AuditLog.query.filter_by(
            action="user.created",
            target_type="user",
            target_id=user.id,
        ).first()
        assert row is not None
        assert row.context.get("email") == "newuser@test.local"
        assert row.context.get("role") == UserRole.USER.value


def test_create_superadmin_audit_action(app, organization):
    with app.app_context():
        user = user_services.create_user(
            email="sa_new@test.local",
            password="SuperAdminPass123!",
            role=UserRole.SUPERADMIN.value,
            organization_id=organization.id,
        )
        row = AuditLog.query.filter_by(
            action="superadmin.created",
            target_id=user.id,
        ).first()
        assert row is not None


def test_create_user_duplicate_email(app, organization):
    with app.app_context():
        user_services.create_user(
            email="dup@test.local",
            password="DupUserPass123!",
            role=UserRole.USER.value,
            organization_id=organization.id,
        )
        with pytest.raises(user_services.UserServiceError, match="already exists"):
            user_services.create_user(
                email="dup@test.local",
                password="AnotherPass123!",
                role=UserRole.ADMIN.value,
                organization_id=organization.id,
            )


def test_create_user_invalid_role(app, organization):
    with app.app_context():
        with pytest.raises(user_services.UserServiceError, match="Invalid role"):
            user_services.create_user(
                email="badrole@test.local",
                password="BadRolePass123!",
                role="not_a_real_role",
                organization_id=organization.id,
            )


def test_create_user_get_or_create_organization_by_name(app):
    with app.app_context():
        user = user_services.create_user(
            email="byname@test.local",
            password="ByNamePass123!",
            role=UserRole.USER.value,
            organization_name="  Fresh Org Name  ",
        )
        from app.organizations.models import Organization

        org = Organization.query.filter_by(name="Fresh Org Name").first()
        assert org is not None
        assert user.organization_id == org.id


def test_update_user_role_writes_audit(app, organization):
    with app.app_context():
        user = user_services.create_user(
            email="rolechg@test.local",
            password="RoleChgPass123!",
            role=UserRole.USER.value,
            organization_id=organization.id,
        )
        user_services.update_user_role(
            user_id=user.id,
            new_role=UserRole.ADMIN.value,
            actor_type=ActorType.USER,
            actor_id=999,
            actor_email="actor@test.local",
            commit=True,
        )
        db.session.refresh(user)
        assert user.role == UserRole.ADMIN.value
        row = AuditLog.query.filter_by(
            action="user.role_changed",
            target_id=user.id,
        ).first()
        assert row is not None
        assert row.context.get("old_role") == UserRole.USER.value
        assert row.context.get("new_role") == UserRole.ADMIN.value


def test_deactivate_user_writes_audit(app, organization):
    with app.app_context():
        user = user_services.create_user(
            email="deact@test.local",
            password="DeactPass123!",
            role=UserRole.USER.value,
            organization_id=organization.id,
        )
        user_services.deactivate_user(
            user_id=user.id,
            actor_type=ActorType.USER,
            actor_id=1,
            actor_email="admin@test.local",
            commit=True,
        )
        db.session.refresh(user)
        assert user.is_active is False
        row = AuditLog.query.filter_by(
            action="user.deleted",
            target_id=user.id,
        ).first()
        assert row is not None


def test_reactivate_user_writes_audit(app, organization):
    with app.app_context():
        user = User(
            email="react@test.local",
            password_hash=generate_password_hash("ReactivatePass123!"),
            organization_id=organization.id,
            role=UserRole.USER.value,
            is_active=False,
        )
        db.session.add(user)
        db.session.commit()

        user_services.reactivate_user(
            user_id=user.id,
            actor_type=ActorType.USER,
            actor_id=1,
            commit=True,
        )
        db.session.refresh(user)
        assert user.is_active is True
        assert (
            AuditLog.query.filter_by(
                action="user.reactivated",
                target_id=user.id,
            ).first()
            is not None
        )


def test_change_password_writes_audit(app, organization):
    with app.app_context():
        user = user_services.create_user(
            email="pwd@test.local",
            password="InitialPass123!",
            role=UserRole.USER.value,
            organization_id=organization.id,
        )
        user_services.change_password(
            user_id=user.id,
            new_password="UpdatedPass123!",
            actor_type=ActorType.USER,
            actor_id=1,
            commit=True,
        )
        db.session.refresh(user)
        assert user.check_password("UpdatedPass123!")
        row = AuditLog.query.filter_by(
            action="password_changed",
            target_id=user.id,
        ).first()
        assert row is not None


def test_deactivate_forbids_self(app, organization):
    with app.app_context():
        user = user_services.create_user(
            email="self@test.local",
            password="SelfDeactPass123!",
            role=UserRole.USER.value,
            organization_id=organization.id,
        )
        with pytest.raises(user_services.UserServiceError, match="cannot deactivate yourself"):
            user_services.deactivate_user(
                user_id=user.id,
                actor_type=ActorType.USER,
                actor_id=user.id,
                commit=True,
            )
