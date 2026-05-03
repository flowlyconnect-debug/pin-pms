"""Unit coverage for :mod:`app.auth.services` route-facing helpers."""

from __future__ import annotations

import pyotp


def test_verify_superadmin_two_factor_code_accepts_totp(app, superadmin):
    from app.auth.services import verify_superadmin_two_factor_code

    with app.app_context():
        code = pyotp.TOTP(superadmin.totp_secret).now()
        assert verify_superadmin_two_factor_code(user=superadmin, code=code) == "totp"


def test_verify_superadmin_two_factor_code_rejects_invalid(app, superadmin):
    from app.auth.services import verify_superadmin_two_factor_code

    with app.app_context():
        assert verify_superadmin_two_factor_code(user=superadmin, code="000000") == "failed"


def test_authenticate_user_for_login_returns_user_on_success(app, superadmin):
    from app.auth.services import authenticate_user_for_login

    with app.app_context():
        user, err, infra = authenticate_user_for_login(
            email=superadmin.email,
            password=superadmin.password_plain,
        )
        assert user is not None and user.id == superadmin.id
        assert err is None and infra is False
