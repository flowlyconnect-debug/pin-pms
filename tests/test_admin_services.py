"""Tests for :mod:`app.admin.services` helpers moved out of admin routes."""

from __future__ import annotations


def test_create_organization_superadmin_rejects_duplicate_name(app, organization, superadmin):
    from app.admin.services import create_organization_superadmin

    with app.app_context():
        org, err = create_organization_superadmin(
            name=organization.name,
            actor_id=superadmin.id,
            actor_email=superadmin.email,
        )
        assert org is None
        assert err is not None


def test_verify_fresh_2fa_code_accepts_totp(app, superadmin):
    import pyotp

    from app.admin.services import verify_fresh_2fa_code

    with app.app_context():
        code = pyotp.TOTP(superadmin.totp_secret).now()
        assert verify_fresh_2fa_code(user=superadmin, code=code) is True
