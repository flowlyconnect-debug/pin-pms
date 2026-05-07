"""Backup metadata model.

The actual dump files live on disk under ``BACKUP_DIR``; this table is the
authoritative ledger of every attempt — successful, failed, scheduled, or
manual — so superadmins can answer "did last night's backup run?" without
shelling into the host.

Status lifecycle
----------------

::

    pending  ──►  success
              └►  failed

A row is inserted with ``status="pending"`` the moment the dump starts so a
crash mid-run is still observable. The row is then updated in place with the
final status, byte count, and (on failure) ``error_message``.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.extensions import db


class BackupStatus:
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"

    ALL = (PENDING, SUCCESS, FAILED)


class BackupTrigger:
    SCHEDULED = "scheduled"
    MANUAL = "manual"
    # Created automatically as the safe-copy step before a restore. Stored as
    # a normal Backup row so the operator can revert a botched restore by
    # re-loading this file.
    PRE_RESTORE = "pre_restore"

    ALL = (SCHEDULED, MANUAL, PRE_RESTORE)


class Backup(db.Model):
    __tablename__ = "backups"

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False, unique=True, index=True)
    # ``location`` is the absolute path the dump was written to. Logged so
    # superadmins can copy it manually from the volume if needed.
    location = db.Column(db.String(512), nullable=False)
    size_bytes = db.Column(db.BigInteger, nullable=True)
    status = db.Column(db.String(16), nullable=False, default=BackupStatus.PENDING, index=True)
    trigger = db.Column(db.String(16), nullable=False, default=BackupTrigger.SCHEDULED)
    created_at = db.Column(
        db.DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    completed_at = db.Column(db.DateTime(timezone=True), nullable=True)
    created_by_id = db.Column(
        db.Integer,
        db.ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    error_message = db.Column(db.Text, nullable=True)
    # Brief, section 8: backup also includes uploaded files. ``uploads_filename``
    # is the sibling tar.gz next to the SQL dump; NULL when the deployment has
    # no uploads directory or it was empty at backup time.
    uploads_filename = db.Column(db.String(255), nullable=True)
    # Init template §8: human-readable JSON exports of the email templates and
    # the settings table are written next to the SQL dump so an operator can
    # audit them without restoring the whole database. NULL on rows created
    # before this column existed or when the export step was skipped.
    email_templates_filename = db.Column(db.String(255), nullable=True)
    settings_filename = db.Column(db.String(255), nullable=True)
    # Optional S3 URI for the off-site uploaded SQL dump.
    s3_uri = db.Column(db.String(1024), nullable=True)

    @property
    def size_human(self) -> str:
        """Format ``size_bytes`` as a short human string (KB / MB / GB)."""

        if self.size_bytes is None:
            return "—"
        n = float(self.size_bytes)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} PB"
