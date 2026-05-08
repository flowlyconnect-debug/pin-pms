"""Init template §11 — audit coverage for security-relevant actions."""

from __future__ import annotations

import gzip
import io
from pathlib import Path
from types import SimpleNamespace

import pyotp

_ENV = {"REMOTE_ADDR": "203.0.113.44", "HTTP_USER_AGENT": "pytest-section11/1.0"}


def _assert_request_audit_fields(entry) -> None:
    assert entry is not None
    assert entry.action
    assert entry.ip_address, "ip_address must be populated (request or override)"
    assert entry.user_agent, "user_agent must be populated (request or override)"
    assert entry.context is not None


def _login_superadmin_2fa(client, superadmin):
    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
        environ_overrides=_ENV,
    )
    code = pyotp.TOTP(superadmin.totp_secret).now()
    client.post("/2fa/verify", data={"code": code}, environ_overrides=_ENV)


def test_audit_login_success(client, regular_user):
    from app.audit.models import AuditLog

    client.post(
        "/login",
        data={"email": regular_user.email, "password": regular_user.password_plain},
        environ_overrides=_ENV,
    )
    row = AuditLog.query.filter_by(action="login", target_id=regular_user.id).first()
    assert row is not None
    _assert_request_audit_fields(row)


def test_audit_login_failed_user_not_found(client):
    from app.audit.models import AuditLog

    client.post(
        "/login",
        data={"email": "nobody@example.invalid", "password": "x"},
        environ_overrides=_ENV,
    )
    row = AuditLog.query.filter_by(action="auth.login_failed").first()
    assert row is not None
    assert row.target_type == "auth"
    assert row.target_id is None
    _assert_request_audit_fields(row)
    assert row.context.get("reason") == "user_not_found"


def test_audit_login_failed_wrong_password(client, regular_user):
    from app.audit.models import AuditLog

    client.post(
        "/login",
        data={"email": regular_user.email, "password": "WrongPassword!!!"},
        environ_overrides=_ENV,
    )
    row = AuditLog.query.filter_by(action="auth.login_failed").order_by(AuditLog.id.desc()).first()
    assert row is not None
    assert row.target_type == "user"
    assert row.target_id == regular_user.id
    _assert_request_audit_fields(row)
    assert row.context.get("reason") == "invalid_password"


def test_audit_login_failed_bad_2fa(client, superadmin):
    from app.audit.models import AuditLog

    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
        environ_overrides=_ENV,
    )
    client.post("/2fa/verify", data={"code": "000000"}, environ_overrides=_ENV)
    row = AuditLog.query.filter_by(action="auth.login_failed").order_by(AuditLog.id.desc()).first()
    assert row is not None
    assert row.target_id == superadmin.id
    _assert_request_audit_fields(row)
    assert row.context.get("reason") == "invalid_2fa_code"


def test_audit_logout(client, regular_user):
    from app.audit.models import AuditLog

    client.post(
        "/login",
        data={"email": regular_user.email, "password": regular_user.password_plain},
        environ_overrides=_ENV,
    )
    client.get("/logout", environ_overrides=_ENV)
    row = AuditLog.query.filter_by(action="auth.logout").first()
    assert row is not None
    assert row.target_id == regular_user.id
    _assert_request_audit_fields(row)


def test_audit_password_change(app, organization):
    from app.audit.models import AuditLog
    from app.users import services as user_service
    from app.users.models import UserRole

    with app.test_request_context("/", environ_overrides=_ENV):
        user = user_service.create_user(
            email="pwchg-audit@test.local",
            password="InitialPass123!",
            role=UserRole.USER.value,
            organization_id=organization.id,
        )
        _ = user_service.change_password(
            user_id=user.id,
            new_password="NewStrongPass123!",
            commit=True,
        )
    row = AuditLog.query.filter_by(action="password_changed", target_id=user.id).first()
    assert row is not None
    _assert_request_audit_fields(row)
    assert "password" not in (row.context or {})


def test_audit_2fa_enable(client, superadmin):
    from app.audit.models import AuditLog
    from app.extensions import db

    superadmin.is_2fa_enabled = False
    superadmin.totp_secret = pyotp.random_base32()
    db.session.commit()

    client.post(
        "/login",
        data={"email": superadmin.email, "password": superadmin.password_plain},
        environ_overrides=_ENV,
    )
    code = pyotp.TOTP(superadmin.totp_secret).now()
    client.post("/2fa/setup", data={"code": code}, environ_overrides=_ENV)
    row = AuditLog.query.filter_by(action="2fa_enabled", target_id=superadmin.id).first()
    assert row is not None
    _assert_request_audit_fields(row)


def test_audit_api_key_create_delete_rotate(client, superadmin, regular_user):
    from app.api.models import ApiKey
    from app.audit.models import AuditLog
    from app.extensions import db

    runner = client.application.test_cli_runner()
    create = runner.invoke(
        args=["create-api-key"],
        input=f"section11-key\n{regular_user.email}\nreservations:read\n",
    )
    assert create.exit_code == 0
    created = AuditLog.query.filter_by(action="apikey.created").order_by(AuditLog.id.desc()).first()
    assert created is not None
    key_row = db.session.get(ApiKey, created.target_id)
    assert key_row is not None

    rot = runner.invoke(
        args=["rotate-api-key", "--key-id", str(key_row.id), "--reason", "section11"],
    )
    assert rot.exit_code == 0
    rotated = (
        AuditLog.query.filter_by(action="api_key.rotated").order_by(AuditLog.id.desc()).first()
    )
    assert rotated is not None
    assert "hash" not in str(rotated.context).lower()

    _login_superadmin_2fa(client, superadmin)
    del_resp = client.post(
        f"/admin/api-keys/{key_row.id}/delete",
        environ_overrides=_ENV,
        follow_redirects=False,
    )
    assert del_resp.status_code == 302
    deleted = AuditLog.query.filter_by(action="apikey.deleted").order_by(AuditLog.id.desc()).first()
    assert deleted is not None
    _assert_request_audit_fields(deleted)
    assert deleted.context.get("prefix")


def test_audit_settings_update_non_secret_and_secret(superadmin):
    from app.audit.models import AuditLog
    from app.settings import services as settings_service

    settings_service.set_value(
        "company_name",
        "AuditCo",
        type_="string",
        actor_user_id=superadmin.id,
    )
    pub = AuditLog.query.filter_by(action="settings.update").order_by(AuditLog.id.desc()).first()
    assert pub is not None
    ctx = pub.context or {}
    assert ctx.get("old_value_redacted") is False
    assert ctx.get("new_value_redacted") is False
    assert "old_value" not in ctx and "new_value" not in ctx

    settings_service.set_value(
        "smtp_password",
        "s3cr3t-one",
        type_="string",
        is_secret=True,
        actor_user_id=superadmin.id,
    )
    settings_service.set_value(
        "smtp_password",
        "s3cr3t-two",
        actor_user_id=superadmin.id,
    )
    sec = AuditLog.query.filter_by(action="settings.update").order_by(AuditLog.id.desc()).first()
    assert sec is not None
    sctx = sec.context or {}
    assert sctx.get("new_value_redacted") is True
    assert "s3cr3t" not in str(sctx)


def test_audit_user_created_deleted_role_changed(app, organization):
    from app.audit.models import ActorType, AuditLog
    from app.users import services as user_service
    from app.users.models import UserRole

    with app.test_request_context("/", environ_overrides=_ENV):
        user = user_service.create_user(
            email="lifecycle-audit@test.local",
            password="LifecyclePass123!",
            role=UserRole.USER.value,
            organization_id=organization.id,
        )
        _ = user_service.update_user_role(
            user_id=user.id,
            new_role=UserRole.ADMIN.value,
            actor_type=ActorType.USER,
            actor_id=user.id,
            commit=True,
        )
        _ = user_service.deactivate_user(user_id=user.id, commit=True)

    assert AuditLog.query.filter_by(action="user.created", target_id=user.id).first()
    role = AuditLog.query.filter_by(action="user.role_changed", target_id=user.id).first()
    assert role is not None
    assert role.context.get("old_role") == UserRole.USER.value
    assert role.context.get("new_role") == UserRole.ADMIN.value
    assert AuditLog.query.filter_by(action="user.deleted", target_id=user.id).first()


def test_audit_email_template_update(client, superadmin):
    from app.audit.models import AuditLog
    from app.email.models import EmailTemplate
    from app.extensions import db

    if EmailTemplate.query.filter_by(key="welcome_email").first() is None:
        db.session.add(
            EmailTemplate(
                key="welcome_email",
                subject="Welcome {{ organization_name }}",
                body_text="Hi {{ user_email }}",
                body_html="<p>Hi {{ user_email }}</p>",
                description="audit test",
                available_variables=["organization_name", "user_email"],
            )
        )
        db.session.commit()

    _login_superadmin_2fa(client, superadmin)
    resp = client.post(
        "/admin/email-templates/welcome_email",
        data={
            "action": "save",
            "subject": "Welcome {{ organization_name }}",
            "body_text": "Hi {{ user_email }}",
            "body_html": "<p>Hi {{ user_email }}</p>",
        },
        environ_overrides=_ENV,
        follow_redirects=False,
    )
    assert resp.status_code == 302
    row = (
        AuditLog.query.filter_by(action="email_template.update")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert row is not None
    _assert_request_audit_fields(row)
    assert row.context.get("template_key") == "welcome_email"


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


def test_audit_backup_created_and_restored(app, monkeypatch, tmp_path):
    from app.audit.models import AuditLog
    from app.backups.models import BackupStatus, BackupTrigger
    from app.backups.services import create_backup, restore_backup

    backup_dir = Path(tmp_path)
    app.config["BACKUP_DIR"] = str(backup_dir)
    app.config["UPLOADS_DIR"] = ""

    with app.test_request_context("/", environ_overrides=_ENV):
        monkeypatch.setattr("app.backups.services.subprocess.Popen", _FakeCreateBackupPopen)
        backup = create_backup(trigger=BackupTrigger.MANUAL, actor_user_id=None)
    assert backup.status == BackupStatus.SUCCESS
    created = AuditLog.query.filter_by(action="backup.created").order_by(AuditLog.id.desc()).first()
    assert created is not None
    _assert_request_audit_fields(created)

    restore_file = backup_dir / "restore-input.sql.gz"
    with gzip.open(restore_file, "wb") as fp:
        fp.write(b"select 1;\n")

    monkeypatch.setattr(
        "app.backups.services.create_backup",
        lambda **kwargs: SimpleNamespace(filename="safe-copy.sql.gz", id=999, size_human="1 B"),
    )
    monkeypatch.setattr("app.backups.services.subprocess.Popen", _FakeRestoreBackupPopen)
    monkeypatch.setattr(
        "app.backups.services._notify_superadmins_of_restore", lambda **kwargs: None
    )

    with app.test_request_context("/", environ_overrides=_ENV):
        _ = restore_backup(filename=restore_file.name, actor_user_id=None)
    restored = (
        AuditLog.query.filter_by(action="backup.restored").order_by(AuditLog.id.desc()).first()
    )
    assert restored is not None
    _assert_request_audit_fields(restored)
