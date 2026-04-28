from __future__ import annotations

import gzip
import io
from types import SimpleNamespace
from pathlib import Path

import pyotp


def _force_superadmin_session(client, superadmin):
    with client.session_transaction() as session:
        session["_user_id"] = str(superadmin.id)
        session["_fresh"] = True
        session["2fa_verified"] = True


def _login(client, *, email: str, password: str):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _login_superadmin_2fa(client, superadmin):
    _ = _login(client, email=superadmin.email, password=superadmin.password_plain)
    code = pyotp.TOTP(superadmin.totp_secret).now()
    _ = client.post("/2fa/verify", data={"code": code}, follow_redirects=False)


def test_auth_login_logout_and_login_failed_audit(client, regular_user):
    from app.audit.models import AuditLog

    _ = _login(client, email=regular_user.email, password=regular_user.password_plain)
    _ = client.get("/logout", follow_redirects=False)
    _ = _login(client, email=regular_user.email, password="wrong-password")

    assert AuditLog.query.filter_by(action="login").first() is not None
    assert AuditLog.query.filter_by(action="logout").first() is not None
    assert AuditLog.query.filter_by(action="login_failed").first() is not None


def test_auth_2fa_enabled_and_disabled_audit(client, superadmin):
    from app.audit.models import AuditLog
    from app.auth import services as auth_service
    from app.extensions import db

    superadmin.is_2fa_enabled = False
    superadmin.totp_secret = pyotp.random_base32()
    db.session.commit()

    _ = _login(client, email=superadmin.email, password=superadmin.password_plain)
    code = pyotp.TOTP(superadmin.totp_secret).now()
    _ = client.post("/2fa/setup", data={"code": code}, follow_redirects=False)

    db.session.refresh(superadmin)
    auth_service.disable_2fa(superadmin, reason="test")

    assert AuditLog.query.filter_by(action="2fa_enabled").first() is not None
    assert AuditLog.query.filter_by(action="2fa_disabled").first() is not None


def test_user_and_setting_audit_actions(organization):
    from app.audit.models import AuditLog
    from app.settings.services import set_value
    from app.users import services as user_service
    from app.users.models import UserRole

    user = user_service.create_user(
        email="audit-user@example.com",
        password="StrongPassword123!",
        role=UserRole.USER.value,
        organization_id=organization.id,
    )
    _ = user_service.change_password(
        user_id=user.id,
        new_password="AnotherStrongPassword123!",
        commit=True,
    )
    _ = user_service.update_user_role(user_id=user.id, new_role=UserRole.ADMIN.value, commit=True)
    _ = user_service.deactivate_user(user_id=user.id, commit=True)
    _ = set_value("audit.coverage.example", "on", type_="string", actor_user_id=user.id)

    assert AuditLog.query.filter_by(action="user.created").first() is not None
    assert AuditLog.query.filter_by(action="password_changed").first() is not None
    assert AuditLog.query.filter_by(action="role_changed").first() is not None
    assert AuditLog.query.filter_by(action="user.deleted").first() is not None
    assert AuditLog.query.filter_by(action="setting.updated").first() is not None


def test_apikey_and_email_template_audit_actions(client, superadmin, regular_user):
    from app.api.models import ApiKey
    from app.audit.models import AuditLog
    from app.email.models import EmailTemplate
    from app.extensions import db

    runner = client.application.test_cli_runner()
    create_result = runner.invoke(
        args=["create-api-key"],
        input=f"Coverage key\n{regular_user.email}\nreservations:read\n",
    )
    assert create_result.exit_code == 0
    created = AuditLog.query.filter_by(action="apikey.created").order_by(AuditLog.id.desc()).first()
    assert created is not None

    _login_superadmin_2fa(client, superadmin)
    key_row = ApiKey.query.filter_by(id=created.target_id).first()
    assert key_row is not None

    delete_response = client.post(
        f"/admin/api-keys/{key_row.id}/delete",
        follow_redirects=False,
    )
    assert delete_response.status_code == 302
    assert AuditLog.query.filter_by(action="apikey.deleted").first() is not None

    if EmailTemplate.query.filter_by(key="welcome_email").first() is None:
        db.session.add(
            EmailTemplate(
                key="welcome_email",
                subject="Welcome {{ organization_name }}",
                body_text="Hi {{ user_email }}",
                body_html="<p>Hi {{ user_email }}</p>",
                description="Coverage template",
                available_variables=["organization_name", "user_email"],
            )
        )
        db.session.commit()

    edit_response = client.post(
        "/admin/email-templates/welcome_email",
        data={
            "action": "save",
            "subject": "Welcome {{ organization_name }}",
            "body_text": "Hi {{ user_email }}",
            "body_html": "<p>Hi {{ user_email }}</p>",
        },
        follow_redirects=False,
    )
    assert edit_response.status_code == 302
    db.session.rollback()
    assert AuditLog.query.filter_by(action="email_template.updated").first() is not None


def test_apikey_rotated_cli_audit(app, regular_user):
    from app.api.models import ApiKey
    from app.audit.models import AuditLog
    from app.extensions import db

    key, _raw = ApiKey.issue(
        name="Rotate me",
        organization_id=regular_user.organization_id,
        user_id=regular_user.id,
        scopes="reservations:read",
    )
    db.session.add(key)
    db.session.commit()

    runner = app.test_cli_runner()
    result = runner.invoke(args=["rotate-api-key"], input=f"{key.key_prefix}\n")
    assert result.exit_code == 0
    assert AuditLog.query.filter_by(action="apikey.rotated").first() is not None


class _FakeCreateBackupPopen:
    def __init__(self, *args, **kwargs):
        self.stdout = io.BytesIO(b"select 1;\n")
        self.stderr = io.BytesIO(b"")
        self.returncode = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def communicate(self, timeout=None):
        _ = timeout
        return b"", b""


class _FakeRestoreBackupPopen:
    def __init__(self, *args, **kwargs):
        self.stdin = io.BytesIO()
        self.stdout = io.BytesIO(b"")
        self.stderr = io.BytesIO(b"")
        self.returncode = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def communicate(self, timeout=None):
        _ = timeout
        return b"", b""


def test_backup_created_and_restored_audit(app, monkeypatch, tmp_path):
    from app.audit.models import AuditLog
    from app.backups.models import Backup, BackupStatus, BackupTrigger
    from app.backups.services import create_backup, restore_backup
    from app.extensions import db

    backup_dir = Path(tmp_path)
    app.config["BACKUP_DIR"] = str(backup_dir)
    app.config["UPLOADS_DIR"] = ""

    monkeypatch.setattr("app.backups.services.subprocess.Popen", _FakeCreateBackupPopen)
    backup = create_backup(trigger=BackupTrigger.MANUAL)
    assert backup.status == BackupStatus.SUCCESS
    assert AuditLog.query.filter_by(action="backup.created").first() is not None

    restore_file = backup_dir / "restore-input.sql.gz"
    with gzip.open(restore_file, "wb") as fp:
        fp.write(b"select 1;\n")

    monkeypatch.setattr(
        "app.backups.services.create_backup",
        lambda **kwargs: SimpleNamespace(filename="safe-copy.sql.gz"),
    )
    monkeypatch.setattr("app.backups.services.subprocess.Popen", _FakeRestoreBackupPopen)
    monkeypatch.setattr("app.backups.services._notify_superadmins_of_restore", lambda **kwargs: None)

    _ = restore_backup(filename=restore_file.name, actor_user_id=None)
    assert AuditLog.query.filter_by(action="backup.restored").first() is not None


def test_admin_audit_page_has_no_edit_or_delete_buttons(client, superadmin):
    _login_superadmin_2fa(client, superadmin)
    response = client.get("/admin/audit")
    assert response.status_code == 200
    assert b">Edit<" not in response.data
    assert b">Delete<" not in response.data
