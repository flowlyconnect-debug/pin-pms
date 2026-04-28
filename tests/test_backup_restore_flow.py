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
from types import SimpleNamespace


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
    from app.extensions import db

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
    audit = (
        AuditLog.query.filter_by(action="backup.restored")
        .order_by(AuditLog.id.desc())
        .first()
    )
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
