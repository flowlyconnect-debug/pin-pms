"""Tests for :mod:`app.owner_portal.services`."""

from __future__ import annotations

import pytest
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.owner_portal import services as owner_portal_service
from app.owners.models import OwnerUser, PropertyOwner
from app.properties.models import Property


def test_list_owner_property_reservations_raises_without_assignment(app, organization):
    with app.app_context():
        owner = PropertyOwner(
            organization_id=organization.id,
            name="O",
            email="o@test.local",
            is_active=True,
        )
        db.session.add(owner)
        db.session.flush()
        user = OwnerUser(
            owner_id=owner.id,
            email="ou@test.local",
            password_hash=generate_password_hash("pw"),
            is_active=True,
        )
        db.session.add(user)
        prop = Property(organization_id=organization.id, name="P", address=None)
        db.session.add(prop)
        db.session.commit()

        with pytest.raises(ValueError, match="assignment_not_found"):
            owner_portal_service.list_owner_property_reservations(
                owner_id=owner.id,
                property_id=prop.id,
            )
