"""Spec section 16 — varmuuskopion luonti."""

from __future__ import annotations

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
