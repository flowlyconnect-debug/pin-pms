"""Spec section 16 — varmuuskopion luonti."""

from __future__ import annotations

import io
import json
import shutil
from pathlib import Path

import pytest


@pytest.mark.skipif(
    not shutil.which("pg_dump"),
    reason="pg_dump must be on PATH (install PostgreSQL client tools, or run tests in Linux/Docker).",
)
def test_create_backup_writes_gzipped_file_and_db_row(app, tmp_path, monkeypatch):
    """``create_backup`` produces a non-empty ``.sql.gz`` and a SUCCESS row.

    ``BACKUP_DIR`` is overridden to a pytest-managed temp directory so the
    test is hermetic — no risk of polluting the real volume mount.
    """

    from app.backups.models import Backup, BackupStatus, BackupTrigger
    from app.backups.services import create_backup

    monkeypatch.setitem(app.config, "BACKUP_DIR", str(tmp_path))

    backup = create_backup(trigger=BackupTrigger.MANUAL)

    # Row reflects success.
    assert backup.status == BackupStatus.SUCCESS
    assert backup.size_bytes is not None
    assert backup.size_bytes > 0
    assert backup.error_message is None
    assert backup.completed_at is not None

    # File exists, lives inside our tmp_path, and matches the recorded size.
    location = Path(backup.location)
    assert location.parent == tmp_path
    assert location.exists()
    assert location.stat().st_size == backup.size_bytes
    assert location.suffix == ".gz"

    # The row is queryable through the public ``Backup`` interface.
    persisted = Backup.query.filter_by(id=backup.id).first()
    assert persisted is not None
    assert persisted.filename == backup.filename


# ---------------------------------------------------------------------------
# Init template §8 — JSON exports paired with the SQL dump
# ---------------------------------------------------------------------------


class _FakePgDumpPopen:
    """Stub ``pg_dump`` so the JSON-export tests do not need a live cluster."""

    def __init__(self, *args, **kwargs):
        self.stdout = io.BytesIO(b"-- dump\n")
        self.stderr = io.BytesIO(b"")
        self.returncode = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def communicate(self, timeout=None):
        _ = timeout
        return b"", b""


def test_create_backup_writes_email_templates_and_settings_json(app, tmp_path, monkeypatch):
    """create_backup writes JSON exports next to the SQL dump and records them."""

    from app.backups.models import BackupTrigger
    from app.backups.services import create_backup
    from app.email.models import EmailTemplate
    from app.extensions import db
    from app.settings.models import Setting, SettingType

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setitem(app.config, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setitem(app.config, "UPLOADS_DIR", "")

    template = EmailTemplate(
        key="json_export_test_template",
        subject="Hello {{ name }}",
        body_text="Plain body for {{ name }}",
        body_html="<p>HTML body for {{ name }}</p>",
        text_content="Plain body for {{ name }}",
        html_content="<p>HTML body for {{ name }}</p>",
        description="Used by JSON export test",
        available_variables=["name"],
    )
    db.session.add(template)

    setting = Setting(
        key="json_export_test_setting",
        value="visible-value",
        type=SettingType.STRING,
        description="Plain setting used by export test",
        is_secret=False,
    )
    db.session.add(setting)
    db.session.commit()

    monkeypatch.setattr("app.backups.services.subprocess.Popen", _FakePgDumpPopen)
    backup = create_backup(trigger=BackupTrigger.MANUAL)

    assert backup.email_templates_filename
    assert backup.settings_filename

    email_path = backup_dir / backup.email_templates_filename
    settings_path = backup_dir / backup.settings_filename
    assert email_path.exists()
    assert settings_path.exists()

    email_payload = json.loads(email_path.read_text(encoding="utf-8"))
    settings_payload = json.loads(settings_path.read_text(encoding="utf-8"))

    assert email_payload["export_type"] == "email_templates"
    assert settings_payload["export_type"] == "settings"

    email_keys = {row["key"] for row in email_payload["rows"]}
    settings_keys = {row["key"] for row in settings_payload["rows"]}
    assert "json_export_test_template" in email_keys
    assert "json_export_test_setting" in settings_keys


def test_settings_json_export_redacts_secret_values(app, tmp_path, monkeypatch):
    """``is_secret`` rows must be redacted; the plaintext must not appear at all."""

    from app.backups.models import BackupTrigger
    from app.backups.services import SECRET_REDACTED, create_backup
    from app.extensions import db
    from app.settings.models import Setting, SettingType

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    monkeypatch.setitem(app.config, "BACKUP_DIR", str(backup_dir))
    monkeypatch.setitem(app.config, "UPLOADS_DIR", "")

    secret_value = "super-secret-value"
    db.session.add(
        Setting(
            key="json_export_secret_key",
            value=secret_value,
            type=SettingType.STRING,
            description="Secret used by redaction test",
            is_secret=True,
        )
    )
    db.session.commit()

    monkeypatch.setattr("app.backups.services.subprocess.Popen", _FakePgDumpPopen)
    backup = create_backup(trigger=BackupTrigger.MANUAL)

    settings_path = backup_dir / backup.settings_filename
    raw_text = settings_path.read_text(encoding="utf-8")

    payload = json.loads(raw_text)
    by_key = {row["key"]: row for row in payload["rows"]}
    assert "json_export_secret_key" in by_key
    assert by_key["json_export_secret_key"]["value"] == SECRET_REDACTED
    assert by_key["json_export_secret_key"]["is_secret"] is True

    assert secret_value not in raw_text
