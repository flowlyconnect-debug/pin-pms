"""Tests for :mod:`app.api.services` helpers used by API and admin flows."""

from __future__ import annotations

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.organizations.models import Organization
from app.properties.models import Property, Unit
from app.users.models import User, UserRole


def test_get_unit_for_org_calendar_export_scoped_to_org(app, organization):
    from app.api.services import get_unit_for_org_calendar_export

    with app.app_context():
        prop = Property(organization_id=organization.id, name="Cal Prop", address=None)
        db.session.add(prop)
        db.session.flush()
        unit = Unit(property_id=prop.id, name="U1", unit_type="studio")
        db.session.add(unit)
        db.session.commit()

        found = get_unit_for_org_calendar_export(
            organization_id=organization.id,
            unit_id=unit.id,
        )
        assert found is not None and found.id == unit.id
        assert (
            get_unit_for_org_calendar_export(
                organization_id=organization.id,
                unit_id=unit.id + 999_999,
            )
            is None
        )


def test_create_api_key_admin_rejects_cross_org_user(app, organization, superadmin):
    from app.api.services import ApiKeyAdminError, create_api_key_admin

    with app.app_context():
        other_org = Organization(name="Other Org For Api Test")
        db.session.add(other_org)
        db.session.flush()
        foreign_user = User(
            email="foreign@test.local",
            password_hash=generate_password_hash("ForeignPass123!"),
            organization_id=other_org.id,
            role=UserRole.USER.value,
            is_active=True,
        )
        db.session.add(foreign_user)
        db.session.commit()

        with pytest.raises(ApiKeyAdminError) as excinfo:
            create_api_key_admin(
                name="bad",
                organization_id=organization.id,
                user_id=foreign_user.id,
                scopes=["properties:read"],
                expires_at=None,
                actor_id=superadmin.id,
                actor_email=superadmin.email,
                actor_is_superadmin=True,
            )
        assert "organisaatioon" in excinfo.value.message.lower()
