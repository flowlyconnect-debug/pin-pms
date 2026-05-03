"""Tests for :mod:`app.backups.services` admin/operator helpers."""

from __future__ import annotations


def test_verify_backup_restore_credentials_password_stage(app, superadmin):
    from app.backups.services import verify_backup_restore_credentials

    with app.app_context():
        assert (
            verify_backup_restore_credentials(
                user=superadmin,
                password="wrong-password",
                totp_code="123456",
                backup_id=1,
            )
            == "password"
        )


def test_verify_backup_restore_credentials_totp_stage(app, superadmin):
    from app.backups.services import verify_backup_restore_credentials

    with app.app_context():
        assert (
            verify_backup_restore_credentials(
                user=superadmin,
                password=superadmin.password_plain,
                totp_code="000000",
                backup_id=1,
            )
            == "totp"
        )


def test_verify_backup_restore_credentials_ok(app, superadmin):
    import pyotp

    from app.backups.services import verify_backup_restore_credentials

    with app.app_context():
        code = pyotp.TOTP(superadmin.totp_secret).now()
        assert (
            verify_backup_restore_credentials(
                user=superadmin,
                password=superadmin.password_plain,
                totp_code=code,
                backup_id=1,
            )
            == "ok"
        )
