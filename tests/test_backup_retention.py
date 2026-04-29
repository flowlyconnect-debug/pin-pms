"""Spec section 8 — varmuuskopioiden retention-prune."""

from __future__ import annotations

import os
import time


def test_prune_removes_old_files(app, tmp_path):
    """Files older than BACKUP_RETENTION_DAYS are pruned, fresh ones kept."""

    from app.backups.services import prune_old_backups

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()

    old_file = backup_dir / "old.sql.gz"
    fresh_file = backup_dir / "fresh.sql.gz"
    old_file.write_bytes(b"")
    fresh_file.write_bytes(b"")

    # Push old_file's mtime to 60 days ago.
    sixty_days = 60 * 86400
    now = time.time()
    os.utime(old_file, (now - sixty_days, now - sixty_days))

    app.config["BACKUP_DIR"] = str(backup_dir)
    app.config["BACKUP_RETENTION_DAYS"] = 30

    removed = prune_old_backups()

    assert removed == 1
    assert not old_file.exists()
    assert fresh_file.exists()


def test_prune_skips_when_retention_disabled(app, tmp_path):
    from app.backups.services import prune_old_backups

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "anything.sql.gz").write_bytes(b"")

    app.config["BACKUP_DIR"] = str(backup_dir)
    app.config["BACKUP_RETENTION_DAYS"] = 0

    assert prune_old_backups() == 0
