"""Tests for :mod:`app.portal.services` portal auth helpers."""

from __future__ import annotations

from app.extensions import db
from app.portal import services as portal_service


def test_portal_login_with_audit_failure(app, regular_user):
    with app.app_context():
        user = portal_service.portal_login_with_audit(
            email=regular_user.email,
            password="wrong-password",
        )
        assert user is None


def test_portal_login_with_audit_success(app, regular_user):
    with app.app_context():
        user = portal_service.portal_login_with_audit(
            email=regular_user.email,
            password=regular_user.password_plain,
        )
        assert user is not None and user.id == regular_user.id
