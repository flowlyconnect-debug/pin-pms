"""Project brief section 8 — guarded restore flow.

Verifies the restore path:

* a pre-restore safe-copy row is written before the destructive load
* the safe-copy carries ``trigger == PRE_RESTORE`` so retention pruning skips it
* ``backup.restored`` lands in the audit log, with the safe-copy filename in
  the audit context

The actual ``psql`` and ``pg_dump`` calls are stubbed so the test does not
require a live PostgreSQL instance.
"""

from __future__ import annotations

import gzip
import io
from pathlib import Path


class _FakePopen:
    """Minimal Popen stand-in for both pg_dump (create_backup) and psql (restore)."""

    def __init__(self, *args, **kwargs):
        self.stdin = io.BytesIO()
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


def test_restore_creates_pre_restore_safe_copy_and_audits(app, monkeypatch, tmp_path):
    from app.audit.models import AuditLog
    from app.backups.models import Backup, BackupTrigger
    from app.backups.services import restore_backup

    backup_dir = Path(tmp_path)
    app.config["BACKUP_DIR"] = str(backup_dir)
    app.config["UPLOADS_DIR"] = ""

    # Place a fake gzipped SQL dump to restore.
    restore_file = backup_dir / "input.sql.gz"
    with gzip.open(restore_file, "wb") as fp:
        fp.write(b"select 1;\n")

    monkeypatch.setattr("app.backups.services.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(
        "app.backups.services._notify_superadmins_of_restore",
        lambda **kwargs: None,
    )

    safe_copy_name, _size = restore_backup(filename=restore_file.name, actor_user_id=None)
    assert safe_copy_name

    # A PRE_RESTORE-tagged safe-copy row was inserted before the load.
    safe_copy = Backup.query.filter_by(filename=safe_copy_name).first()
    assert safe_copy is not None
    assert safe_copy.trigger == BackupTrigger.PRE_RESTORE

    # The audit log entry exists and points at the loaded file.
    audit = AuditLog.query.filter_by(action="backup.restored").order_by(AuditLog.id.desc()).first()
    assert audit is not None
    ctx = audit.context or {}
    assert ctx.get("restored_from") == restore_file.name
    assert ctx.get("safe_copy") == safe_copy_name


def test_restore_aborts_when_safe_copy_fails(app, monkeypatch, tmp_path):
    """If the safe-copy step fails, the destructive psql load must not run."""

    from app.audit.models import AuditLog
    from app.backups.services import BackupError, restore_backup

    backup_dir = Path(tmp_path)
    app.config["BACKUP_DIR"] = str(backup_dir)
    app.config["UPLOADS_DIR"] = ""

    restore_file = backup_dir / "input.sql.gz"
    with gzip.open(restore_file, "wb") as fp:
        fp.write(b"select 1;\n")

    def _fail_safe_copy(**kwargs):
        raise BackupError("simulated dump failure")

    monkeypatch.setattr("app.backups.services.create_backup", _fail_safe_copy)

    # psql must never be invoked once the safe-copy step has raised.
    def _explode_popen(*args, **kwargs):
        raise AssertionError("restore must not run psql when safe-copy failed")

    monkeypatch.setattr("app.backups.services.subprocess.Popen", _explode_popen)

    try:
        restore_backup(filename=restore_file.name, actor_user_id=None)
    except BackupError:
        pass
    else:
        raise AssertionError("expected BackupError when safe-copy fails")

    audit = (
        AuditLog.query.filter_by(action="backup.restored.failed")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert audit is not None
    assert (audit.context or {}).get("stage") == "safe_copy"


# ---------------------------------------------------------------------------
# Init template §8 — selective JSON-export restore
# ---------------------------------------------------------------------------


def _seed_json_export_pair(backup_dir, *, sql_filename: str):
    """Place a fake SQL dump + paired JSON exports inside ``backup_dir``.

    Returns ``(email_templates_filename, settings_filename)``. The SQL dump
    body is a no-op statement so the stub psql consumer can read it.
    """

    import gzip
    import json
    from pathlib import Path

    backup_dir = Path(backup_dir)
    sql_path = backup_dir / sql_filename
    with gzip.open(sql_path, "wb") as fp:
        fp.write(b"select 1;\n")

    stem = sql_filename[: -len(".sql.gz")]
    email_filename = f"{stem}.email_templates.json"
    settings_filename = f"{stem}.settings.json"

    (backup_dir / email_filename).write_text(
        json.dumps(
            {
                "export_type": "email_templates",
                "created_at": "2026-05-07T00:00:00+00:00",
                "rows": [
                    {
                        "key": "welcome_email",
                        "subject": "Restored subject",
                        "body_text": "Restored plain body",
                        "body_html": "<p>Restored HTML body</p>",
                        "text_content": "Restored plain body",
                        "html_content": "<p>Restored HTML body</p>",
                        "description": "Restored welcome",
                        "available_variables": ["user_email"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    (backup_dir / settings_filename).write_text(
        json.dumps(
            {
                "export_type": "settings",
                "created_at": "2026-05-07T00:00:00+00:00",
                "rows": [
                    {
                        "key": "company_name",
                        "value": "Restored Pin PMS",
                        "type": "string",
                        "description": "Display name",
                        "is_secret": False,
                    },
                    {
                        "key": "json_restore_secret",
                        "value": "<redacted>",
                        "type": "string",
                        "description": "Secret used in restore test",
                        "is_secret": True,
                    },
                ],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    return email_filename, settings_filename


def test_restore_json_exports_upserts_and_audits(app, monkeypatch, tmp_path):
    """JSON-export restore upserts templates/settings and audits the action.

    Crucially, the redacted secret value must NOT overwrite the live DB value
    — operators must be able to safely promote a JSON export back without
    nuking the configured secret.
    """

    from app.audit.models import AuditLog
    from app.backups.models import Backup, BackupStatus, BackupTrigger
    from app.backups.services import restore_backup
    from app.email.models import EmailTemplate
    from app.extensions import db
    from app.settings.models import Setting, SettingType

    backup_dir = Path(tmp_path)
    app.config["BACKUP_DIR"] = str(backup_dir)
    app.config["UPLOADS_DIR"] = ""

    sql_filename = "pindora-20260507T120000Z.sql.gz"
    email_filename, settings_filename = _seed_json_export_pair(
        backup_dir, sql_filename=sql_filename
    )

    db.session.add(
        Backup(
            filename=sql_filename,
            location=str(backup_dir / sql_filename),
            status=BackupStatus.SUCCESS,
            trigger=BackupTrigger.MANUAL,
            email_templates_filename=email_filename,
            settings_filename=settings_filename,
        )
    )

    welcome = EmailTemplate.query.filter_by(key="welcome_email").first()
    if welcome is None:
        welcome = EmailTemplate(
            key="welcome_email",
            subject="Local edit subject",
            body_text="Local edit plain",
            body_html="<p>Local edit HTML</p>",
            text_content="Local edit plain",
            html_content="<p>Local edit HTML</p>",
            description="Local",
            available_variables=["user_email"],
        )
        db.session.add(welcome)
    else:
        welcome.subject = "Local edit subject"
        welcome.body_html = "<p>Local edit HTML</p>"

    company = Setting.query.filter_by(key="company_name").first()
    if company is None:
        company = Setting(
            key="company_name",
            value="Local Edit Co",
            type=SettingType.STRING,
            description="Display name",
            is_secret=False,
        )
        db.session.add(company)
    else:
        company.value = "Local Edit Co"

    secret_db_value = "live-secret-do-not-overwrite"
    db.session.add(
        Setting(
            key="json_restore_secret",
            value=secret_db_value,
            type=SettingType.STRING,
            description="Secret used in restore test",
            is_secret=True,
        )
    )
    db.session.commit()

    monkeypatch.setattr("app.backups.services.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(
        "app.backups.services._notify_superadmins_of_restore",
        lambda **kwargs: None,
    )

    safe_copy_name, _size = restore_backup(
        filename=sql_filename,
        actor_user_id=None,
        restore_json_exports=True,
    )
    assert safe_copy_name

    refreshed_template = EmailTemplate.query.filter_by(key="welcome_email").first()
    assert refreshed_template is not None
    assert refreshed_template.subject == "Restored subject"
    assert refreshed_template.body_html == "<p>Restored HTML body</p>"

    refreshed_company = Setting.query.filter_by(key="company_name").first()
    assert refreshed_company is not None
    assert refreshed_company.value == "Restored Pin PMS"

    refreshed_secret = Setting.query.filter_by(key="json_restore_secret").first()
    assert refreshed_secret is not None
    assert refreshed_secret.is_secret is True
    assert refreshed_secret.value == secret_db_value

    json_audit = (
        AuditLog.query.filter_by(action="backup.restore_json_exports")
        .order_by(AuditLog.id.desc())
        .first()
    )
    assert json_audit is not None
    ctx = json_audit.context or {}
    assert ctx.get("email_templates_filename") == email_filename
    assert ctx.get("settings_filename") == settings_filename
    summary = ctx.get("summary") or {}
    assert summary.get("email_templates", {}).get("updated", 0) >= 1
    assert summary.get("settings", {}).get("redacted_preserved", 0) >= 1


def test_restore_without_json_exports_does_not_audit_json_action(app, monkeypatch, tmp_path):
    """Default ``restore_json_exports=False`` must not write the JSON audit row."""

    import gzip

    from app.audit.models import AuditLog
    from app.backups.services import restore_backup

    backup_dir = Path(tmp_path)
    app.config["BACKUP_DIR"] = str(backup_dir)
    app.config["UPLOADS_DIR"] = ""

    restore_file = backup_dir / "no-json-restore.sql.gz"
    with gzip.open(restore_file, "wb") as fp:
        fp.write(b"select 1;\n")

    monkeypatch.setattr("app.backups.services.subprocess.Popen", _FakePopen)
    monkeypatch.setattr(
        "app.backups.services._notify_superadmins_of_restore",
        lambda **kwargs: None,
    )

    _ = restore_backup(filename=restore_file.name, actor_user_id=None)

    json_audit = AuditLog.query.filter_by(action="backup.restore_json_exports").first()
    assert json_audit is None
