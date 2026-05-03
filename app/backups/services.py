"""Backup creation service.

The single public entry point :func:`create_backup` runs ``pg_dump`` against
the configured database, gzips the output, writes it to ``BACKUP_DIR``, and
records the result in both the ``backups`` table and the audit log.

It is intentionally **synchronous**. Backups for a SaaS PMS are small enough
(megabytes-to-gigabytes) that running them inside the request that triggered
them, or inside a cron-fired thread, is fine — and removing the queue layer
makes failures visible immediately. If a deployment ever needs a long-running
backup, swap the implementation for a Celery task; the call site does not
change.

Security
--------

* The DB password is passed via ``PGPASSWORD`` in the child environment so it
  never appears in the process list.
* The dump is *not* placed inside the application working directory (which is
  bind-mounted to the host); ``BACKUP_DIR`` is its own volume.
"""
from __future__ import annotations

import gzip
import logging
import os
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional
from urllib.parse import urlparse

import boto3
from flask import current_app

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.backups.models import Backup, BackupStatus, BackupTrigger
from app.email.models import TemplateKey
from app.email.services import send_template
from app.extensions import db

logger = logging.getLogger(__name__)


class BackupError(RuntimeError):
    """Raised when a backup attempt fails for an expected reason.

    The caller is responsible for surfacing the message to the user; the audit
    row is already written by :func:`create_backup` before the exception is
    re-raised.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_database_url(url: str) -> dict[str, str]:
    """Pull ``pg_dump`` connection parameters out of a SQLAlchemy URL.

    Accepts ``postgresql+psycopg2://user:password@host:port/dbname``.
    """

    parsed = urlparse(url)
    if not parsed.hostname or not parsed.path:
        raise BackupError(f"DATABASE_URL does not look usable for pg_dump: {url!r}")

    return {
        "host": parsed.hostname,
        "port": str(parsed.port or 5432),
        "user": parsed.username or "",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/"),
    }


def _ensure_backup_dir(path: str) -> Path:
    backup_dir = Path(path)
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise BackupError(f"Cannot create backup directory {path!r}: {err}") from err
    return backup_dir


def _build_filename(prefix: str = "pindora") -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{prefix}-{stamp}.sql.gz"


def _build_uploads_filename(sql_filename: str) -> str:
    """Sibling tarball name for the uploaded-files archive."""

    if sql_filename.endswith(".sql.gz"):
        stem = sql_filename[: -len(".sql.gz")]
    else:
        stem = sql_filename
    return f"{stem}.uploads.tar.gz"


def _archive_uploads(uploads_dir: Path, target: Path) -> bool:
    """Tar.gz ``uploads_dir`` into ``target``.

    Returns True if the archive was created (directory existed and was
    not empty), False if the step was skipped. Caller is responsible for
    cleaning up ``target`` on a later failure.
    """

    if not uploads_dir.exists() or not uploads_dir.is_dir():
        return False
    # Skip if directory is empty so we do not write 1KB tarballs nightly.
    if not any(uploads_dir.iterdir()):
        return False

    with tarfile.open(target, "w:gz") as tar:
        tar.add(uploads_dir, arcname=uploads_dir.name)
    return True


def _send_notification(*, ok: bool, backup: Backup, error_message: str | None) -> None:
    """Best-effort backup_completed / backup_failed email."""

    notify_to = current_app.config.get("BACKUP_NOTIFY_EMAIL") or ""
    if not notify_to:
        return

    template = TemplateKey.BACKUP_COMPLETED if ok else TemplateKey.BACKUP_FAILED
    timestamp = (backup.completed_at or backup.created_at).isoformat(timespec="seconds")
    context = {
        "backup_name": backup.filename,
        "completed_at" if ok else "failed_at": timestamp,
        "size_human": backup.size_human,
        "location": backup.location,
        "error_message": error_message or "",
    }
    try:
        send_template(template, to=notify_to, context=context)
    except Exception:  # noqa: BLE001 — notification failure must not mask the backup result
        logger.exception("Failed to send %s notification to %s", template, notify_to)


def _s3_prefix(prefix: str) -> str:
    normalized = (prefix or "").strip()
    if not normalized:
        return ""
    return normalized if normalized.endswith("/") else f"{normalized}/"


def _s3_uri(bucket: str, key: str) -> str:
    return f"s3://{bucket}/{key}"


def _upload_offsite_to_s3(
    *,
    backup: Backup,
    sql_path: Path,
    uploads_filename: str | None,
) -> tuple[str, str | None]:
    cfg = current_app.config
    bucket = (cfg.get("BACKUP_S3_BUCKET") or "").strip()
    access_key = (cfg.get("BACKUP_S3_ACCESS_KEY") or "").strip()
    secret_key = (cfg.get("BACKUP_S3_SECRET_KEY") or "").strip()
    endpoint_url = (cfg.get("BACKUP_S3_ENDPOINT_URL") or "").strip() or None
    if not bucket:
        raise BackupError("BACKUP_S3_BUCKET is required when BACKUP_S3_ENABLED=1")
    if not access_key or not secret_key:
        raise BackupError("BACKUP_S3_ACCESS_KEY and BACKUP_S3_SECRET_KEY are required when BACKUP_S3_ENABLED=1")

    prefix = _s3_prefix(cfg.get("BACKUP_S3_PREFIX", "pindora-pms/"))
    sql_key = f"{prefix}{backup.filename}"
    uploads_key = f"{prefix}{uploads_filename}" if uploads_filename else None

    client = boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    client.upload_file(str(sql_path), bucket, sql_key)

    uploads_uri: str | None = None
    if uploads_filename:
        uploads_path = sql_path.parent / uploads_filename
        if uploads_path.exists():
            client.upload_file(str(uploads_path), bucket, uploads_key)
            uploads_uri = _s3_uri(bucket, uploads_key)
    return _s3_uri(bucket, sql_key), uploads_uri


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def create_backup(
    *,
    actor_user_id: Optional[int] = None,
    trigger: str = BackupTrigger.MANUAL,
) -> Backup:
    """Run ``pg_dump`` and persist the result.

    Returns the persisted :class:`Backup` row. On failure, raises
    :class:`BackupError` *after* recording the failed row + audit event so the
    operator can see the attempt in the admin UI.
    """

    cfg = current_app.config
    backup_dir = _ensure_backup_dir(cfg.get("BACKUP_DIR", "/var/backups/pindora"))
    filename = _build_filename()
    location = backup_dir / filename

    db_params = _parse_database_url(cfg.get("SQLALCHEMY_DATABASE_URI", ""))

    # Insert the pending row up front so a process crash mid-dump still leaves
    # a trace. The same row is updated to success/failed below.
    backup = Backup(
        filename=filename,
        location=str(location),
        status=BackupStatus.PENDING,
        trigger=trigger if trigger in BackupTrigger.ALL else BackupTrigger.MANUAL,
        created_by_id=actor_user_id,
    )
    db.session.add(backup)
    db.session.commit()

    # ``--clean --if-exists`` makes the dump self-cleaning: it inserts
    # ``DROP ... IF EXISTS`` statements at the top so the same file can be
    # safely loaded onto a populated database (this is what the restore flow
    # relies on). ``--no-password`` forces pg_dump to read the password from
    # ``PGPASSWORD`` and never prompt — critical for unattended cron runs.
    cmd = [
        "pg_dump",
        "--host",
        db_params["host"],
        "--port",
        db_params["port"],
        "--username",
        db_params["user"],
        "--dbname",
        db_params["dbname"],
        "--no-password",
        "--format=plain",
        "--clean",
        "--if-exists",
    ]
    env = os.environ.copy()
    if db_params["password"]:
        env["PGPASSWORD"] = db_params["password"]

    logger.info(f"Starting pg_dump -> {location}")

    try:
        with gzip.open(location, "wb") as gz, subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        ) as proc:
            assert proc.stdout is not None  # for type-checkers
            shutil.copyfileobj(proc.stdout, gz)
            _, stderr = proc.communicate(timeout=cfg.get("BACKUP_TIMEOUT_SEC", 1800))
            returncode = proc.returncode

        if returncode != 0:
            err_text = (stderr or b"").decode("utf-8", errors="replace").strip()
            raise BackupError(f"pg_dump exited with code {returncode}: {err_text}")

        size_bytes = location.stat().st_size
    except BackupError:
        # Already a tidy message; just record + re-raise.
        backup.status = BackupStatus.FAILED
        backup.completed_at = datetime.now(timezone.utc)
        backup.error_message = str(_truncate_error(_pop_exc()))
        db.session.commit()
        audit_record(
            "backup.created.failed",
            status=AuditStatus.FAILURE,
            actor_id=actor_user_id,
            target_type="backup",
            target_id=backup.id,
            context={
                "filename": backup.filename,
                "trigger": backup.trigger,
                "error": backup.error_message,
            },
            commit=True,
        )
        _safe_unlink(location)
        _send_notification(ok=False, backup=backup, error_message=backup.error_message)
        raise
    except Exception as err:  # noqa: BLE001 — turn unexpected failures into BackupError
        logger.exception("Unexpected error during pg_dump")
        backup.status = BackupStatus.FAILED
        backup.completed_at = datetime.now(timezone.utc)
        backup.error_message = _truncate_error(str(err))
        db.session.commit()
        audit_record(
            "backup.created.failed",
            status=AuditStatus.FAILURE,
            actor_id=actor_user_id,
            target_type="backup",
            target_id=backup.id,
            context={
                "filename": backup.filename,
                "trigger": backup.trigger,
                "error": backup.error_message,
            },
            commit=True,
        )
        _safe_unlink(location)
        _send_notification(ok=False, backup=backup, error_message=backup.error_message)
        raise BackupError(str(err)) from err

    # Success path. Pair an optional uploads tarball alongside the SQL dump
    # so the brief's "ladatut tiedostot" requirement is covered. The step is
    # silent if no uploads directory exists.
    uploads_filename: str | None = None
    uploads_dir_setting = cfg.get("UPLOADS_DIR")
    if uploads_dir_setting:
        uploads_target_name = _build_uploads_filename(filename)
        uploads_target_path = backup_dir / uploads_target_name
        try:
            if _archive_uploads(Path(uploads_dir_setting), uploads_target_path):
                uploads_filename = uploads_target_name
                size_bytes += uploads_target_path.stat().st_size
        except Exception:  # noqa: BLE001 — uploads archive is best-effort
            logger.exception("Failed to archive uploads directory")
            _safe_unlink(uploads_target_path)

    backup.status = BackupStatus.SUCCESS
    backup.size_bytes = size_bytes
    backup.completed_at = datetime.now(timezone.utc)
    backup.uploads_filename = uploads_filename
    db.session.commit()

    audit_record(
        "backup.created",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        target_type="backup",
        target_id=backup.id,
        context={
            "filename": backup.filename,
            "trigger": backup.trigger,
            "size_bytes": size_bytes,
            "location": backup.location,
        },
        commit=True,
    )
    logger.info(f"Backup complete: {filename} ({size_bytes} bytes)")

    if cfg.get("BACKUP_S3_ENABLED"):
        try:
            sql_s3_uri, uploads_s3_uri = _upload_offsite_to_s3(
                backup=backup,
                sql_path=location,
                uploads_filename=uploads_filename,
            )
            backup.s3_uri = sql_s3_uri
            db.session.commit()
            audit_record(
                "backup.uploaded_offsite",
                status=AuditStatus.SUCCESS,
                actor_id=actor_user_id,
                target_type="backup",
                target_id=backup.id,
                context={
                    "filename": backup.filename,
                    "sql_s3_uri": sql_s3_uri,
                    "uploads_s3_uri": uploads_s3_uri,
                },
                commit=True,
            )
        except Exception as err:  # noqa: BLE001 — off-site copy must not fail local backup
            logger.exception("Off-site S3 upload failed for %s", backup.filename)
            audit_record(
                "backup.uploaded_offsite",
                status=AuditStatus.FAILURE,
                actor_id=actor_user_id,
                target_type="backup",
                target_id=backup.id,
                context={
                    "filename": backup.filename,
                    "error": _truncate_error(str(err)),
                },
                commit=True,
            )

    _send_notification(ok=True, backup=backup, error_message=None)

    # Brief, section 8: keep only the last N days. Run after every successful
    # backup so a long-running deployment cannot fill up disk. Failures here
    # are logged but never break the surrounding backup result.
    try:
        prune_old_backups()
    except Exception:  # noqa: BLE001 — pruning is best-effort
        logger.exception("Backup retention prune failed")

    return backup


def prune_old_backups() -> int:
    """Delete backup files (and their DB rows) older than the retention window.

    Returns the number of files removed. ``BACKUP_RETENTION_DAYS=0`` disables
    pruning entirely. ``pre_restore`` safe-copies are kept regardless of age
    so a botched restore can always be reverted.
    """

    cfg = current_app.config
    retention_days = int(cfg.get("BACKUP_RETENTION_DAYS", 0) or 0)
    if retention_days <= 0:
        return 0

    cutoff = datetime.now(timezone.utc).timestamp() - retention_days * 86400
    backup_dir = Path(cfg.get("BACKUP_DIR", "/var/backups/pindora"))
    if not backup_dir.exists():
        return 0

    removed = 0
    for path in backup_dir.glob("*.sql.gz"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= cutoff:
            continue

        row = Backup.query.filter_by(filename=path.name).first()
        if row is not None and row.trigger == BackupTrigger.PRE_RESTORE:
            # Pre-restore safe-copies are protected — they are the operator's
            # last line of defence against a botched restore.
            continue

        try:
            path.unlink()
        except OSError:
            logger.exception("Failed to remove old backup file %s", path)
            continue
        removed += 1

        # Remove the paired uploads tarball as well, if one exists.
        uploads_sibling = backup_dir / _build_uploads_filename(path.name)
        if uploads_sibling.exists():
            try:
                uploads_sibling.unlink()
            except OSError:
                logger.exception(
                    "Failed to remove old uploads archive %s", uploads_sibling
                )

        if row is not None:
            db.session.delete(row)

    if removed:
        db.session.commit()
        audit_record(
            "backup.pruned",
            status=AuditStatus.SUCCESS,
            target_type="backup",
            context={"removed_count": removed, "retention_days": retention_days},
            commit=True,
        )
        logger.info(f"Pruned {removed} backup file(s) older than {retention_days} days.")
    return removed


# ---------------------------------------------------------------------------
# Internal utilities
# ---------------------------------------------------------------------------


def _truncate_error(err: str | BaseException, limit: int = 2000) -> str:
    text = str(err) if not isinstance(err, str) else err
    return text if len(text) <= limit else text[:limit] + "…[truncated]"


def _pop_exc() -> BaseException:
    """Return the most recent exception or empty string."""
    import sys

    exc = sys.exc_info()[1]
    return exc if exc is not None else RuntimeError("unknown error")


def _safe_unlink(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        logger.exception("Failed to remove partial backup file %s", path)


# ---------------------------------------------------------------------------
# Restore
# ---------------------------------------------------------------------------


def restore_backup(*, filename: str, actor_user_id: Optional[int] = None) -> tuple[str, str]:
    """Restore the database from ``filename`` (located inside ``BACKUP_DIR``).

    Caller is expected to have **already verified** the operator's password
    and 2FA code (see :func:`app.admin.routes.backup_restore`). This function
    performs the destructive part:

    1. Take a fresh "pre-restore" safe-copy of the current database so a
       botched restore can be reverted by loading this file.
    2. Pipe ``gunzip < filename | psql --single-transaction -v ON_ERROR_STOP=1``
       so any error rolls the entire restore back atomically.
    3. Audit ``backup.restored`` and email every superadmin via the
       ``admin_notification`` template.

    Returns ``(safe_copy_filename, safe_copy_size_human)``. On any failure
    raises :class:`BackupError`; the audit row + notification are written first.
    """

    cfg = current_app.config
    backup_dir = _ensure_backup_dir(cfg.get("BACKUP_DIR", "/var/backups/pindora"))
    target_file = backup_dir / filename

    if not target_file.exists() or target_file.is_dir():
        raise BackupError(f"Backup file not found: {filename}")

    # ``filename`` is unique in the table so we can resolve the row up front.
    target_row = Backup.query.filter_by(filename=filename).first()
    target_row_id = target_row.id if target_row is not None else None
    if target_row is None:
        # Allow restoring files that were placed in BACKUP_DIR out-of-band
        # (e.g. copied from another environment), but make that visible.
        logger.warning(
            "Restoring %s without a matching backups row — file is on disk but "
            "was not created by this app.",
            filename,
        )

    # 1) Safe-copy.
    logger.info(f"Taking pre-restore safe-copy before loading {filename}")
    try:
        safe_copy = create_backup(
            actor_user_id=actor_user_id,
            trigger=BackupTrigger.PRE_RESTORE,
        )
    except BackupError as err:
        # Refuse to restore if we cannot first protect the current state.
        audit_record(
            "backup.restored.failed",
            status=AuditStatus.FAILURE,
            actor_id=actor_user_id,
            target_type="backup",
            target_id=target_row.id if target_row else None,
            context={
                "filename": filename,
                "stage": "safe_copy",
                "error": str(err),
            },
            commit=True,
        )
        raise BackupError(f"Pre-restore safe-copy failed; aborting: {err}") from err

    safe_copy_filename = safe_copy.filename
    safe_copy_size_human = getattr(safe_copy, "size_human", "unknown size")
    safe_copy_id = getattr(safe_copy, "id", None)

    # 2) Run psql with the gunzipped dump piped in.
    db_params = _parse_database_url(cfg.get("SQLALCHEMY_DATABASE_URI", ""))
    env = os.environ.copy()
    if db_params["password"]:
        env["PGPASSWORD"] = db_params["password"]

    psql_cmd = [
        "psql",
        "--host",
        db_params["host"],
        "--port",
        db_params["port"],
        "--username",
        db_params["user"],
        "--dbname",
        db_params["dbname"],
        "--no-password",
        "--single-transaction",
        "--quiet",
        "-v",
        "ON_ERROR_STOP=1",
    ]

    # The application's own SQLAlchemy connections must be released before
    # running ``DROP TABLE``s, otherwise psql blocks waiting for the locks
    # we hold ourselves.
    db.session.commit()
    db.session.close()
    db.engine.dispose()

    logger.info(f"Loading {target_file} into the database via psql")

    try:
        with gzip.open(target_file, "rt", encoding="utf-8", errors="replace") as gz, subprocess.Popen(
            psql_cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
        ) as proc:
            assert proc.stdin is not None  # for type-checkers
            try:
                for line in gz:
                    if line.startswith("SET transaction_timeout"):
                        # pg_dump from newer client versions can emit this GUC,
                        # but PostgreSQL 16 does not recognize it.
                        continue
                    try:
                        proc.stdin.write(line)
                    except TypeError:
                        proc.stdin.write(line.encode("utf-8"))
            except BrokenPipeError:
                # psql exited early (usually due SQL error). Continue to read stderr
                # so the caller gets the real root cause.
                pass
            finally:
                try:
                    proc.stdin.close()
                    proc.stdin = None
                except Exception:
                    pass
            stdout, stderr = proc.communicate(timeout=cfg.get("RESTORE_TIMEOUT_SEC", 1800))
            returncode = proc.returncode
    except Exception as err:  # noqa: BLE001
        logger.exception("Unexpected error during psql restore")
        _record_restore_failure(
            actor_user_id=actor_user_id,
                target_row_id=target_row_id,
            filename=filename,
                safe_copy_filename=safe_copy_filename,
            error=str(err),
        )
        raise BackupError(str(err)) from err

    if returncode != 0:
        if isinstance(stderr, bytes):
            err_text = stderr.decode("utf-8", errors="replace").strip()
        else:
            err_text = (stderr or "").strip()
        _record_restore_failure(
            actor_user_id=actor_user_id,
            target_row_id=target_row_id,
            filename=filename,
            safe_copy_filename=safe_copy_filename,
            error=f"psql exited with code {returncode}: {err_text}",
        )
        raise BackupError(f"psql exited with code {returncode}: {err_text}")

    # 4) Restore uploads tarball if a sibling was produced at backup time.
    #    Skipped silently when the deployment has no uploads directory.
    uploads_restored = False
    uploads_sibling = backup_dir / _build_uploads_filename(filename)
    uploads_dir_setting = cfg.get("UPLOADS_DIR")
    if uploads_sibling.exists() and uploads_dir_setting:
        try:
            uploads_dir = Path(uploads_dir_setting)
            uploads_dir.parent.mkdir(parents=True, exist_ok=True)
            with tarfile.open(uploads_sibling, "r:gz") as tar:
                # Extract into the parent so the archive's own root directory
                # name lands at uploads_dir's path. ``filter`` arg is required
                # on Python 3.12+; ``data`` is the safe default policy.
                try:
                    tar.extractall(path=uploads_dir.parent, filter="data")
                except TypeError:  # Python < 3.12
                    tar.extractall(path=uploads_dir.parent)
            uploads_restored = True
        except Exception:  # noqa: BLE001 — uploads restore is best-effort
            logger.exception(
                "Failed to restore uploads archive %s", uploads_sibling
            )

    # 5) Audit + notify. The audit row is written into the *restored* DB so
    #    that an observer of the restored database sees that a restore was
    #    performed bringing it to the current state.
    audit_record(
        "backup.restored",
        status=AuditStatus.SUCCESS,
        actor_id=actor_user_id,
        target_type="backup",
        target_id=target_row_id,
        context={
            "restored_from": filename,
            "safe_copy": safe_copy_filename,
            "uploads_restored": uploads_restored,
        },
        commit=True,
    )
    _notify_superadmins_of_restore(
        restored_filename=filename,
        safe_copy_filename=safe_copy_filename,
    )
    logger.info(f"Restore complete: loaded {filename} (safe-copy: {safe_copy_filename})")
    refreshed_safe_copy = Backup.query.get(safe_copy_id) if safe_copy_id is not None else None
    if refreshed_safe_copy is not None:
        return refreshed_safe_copy.filename, refreshed_safe_copy.size_human
    return safe_copy_filename, safe_copy_size_human


def _record_restore_failure(
    *,
    actor_user_id: Optional[int],
    target_row_id: Optional[int],
    filename: str,
    safe_copy_filename: str,
    error: str,
) -> None:
    """Write the audit row + email notification for a failed restore.

    Called from ``restore_backup`` *after* the engine has been disposed and
    psql has failed. The audit row goes into whatever state the database is
    currently in — which after a single-transaction failure is the original
    pre-restore state, so the row is preserved correctly.
    """

    try:
        audit_record(
            "backup.restored.failed",
            status=AuditStatus.FAILURE,
            actor_id=actor_user_id,
            target_type="backup",
            target_id=target_row_id,
            context={
                "filename": filename,
                "safe_copy": safe_copy_filename,
                "error": _truncate_error(error),
            },
            commit=True,
        )
    except Exception:  # noqa: BLE001 — observability must not mask the user error
        logger.exception("Failed to record backup.restored.failed audit row")


def _notify_superadmins_of_restore(
    *,
    restored_filename: str,
    safe_copy_filename: str,
) -> None:
    """Email every active superadmin that a restore happened."""

    from app.users.models import User, UserRole  # local to avoid cycles

    superadmins = (
        User.query.filter_by(role=UserRole.SUPERADMIN.value, is_active=True).all()
    )
    if not superadmins:
        return

    subject_line = "Database restored from backup"
    message = (
        f"A database restore was performed from backup {restored_filename!r}. "
        f"A safe-copy of the previous state was saved as {safe_copy_filename!r} "
        f"and can be loaded to revert this change."
    )

    for sa in superadmins:
        try:
            send_template(
                TemplateKey.ADMIN_NOTIFICATION,
                to=sa.email,
                context={
                    "subject_line": subject_line,
                    "message": message,
                },
            )
        except Exception:  # noqa: BLE001 — one bounce must not block the others
            logger.exception("Failed to notify %s about restore", sa.email)


def list_backups_for_admin(*, limit: int = 100) -> list[Backup]:
    return Backup.query.order_by(Backup.created_at.desc()).limit(limit).all()


def record_backup_download_audit(*, backup: Backup) -> None:
    audit_record(
        "backup.downloaded",
        status=AuditStatus.SUCCESS,
        target_type="backup",
        target_id=backup.id,
        context={"filename": backup.filename},
        commit=True,
    )


def verify_backup_restore_credentials(
    *,
    user,
    password: str,
    totp_code: str,
    backup_id: int,
) -> Literal["password", "totp", "ok"]:
    """Validate operator password + TOTP before running a destructive restore."""

    import pyotp

    normalized_totp = (totp_code or "").replace(" ", "").strip()
    if not user or not user.check_password(password):
        audit_record(
            "backup.restore.auth_failed",
            status=AuditStatus.FAILURE,
            target_type="backup",
            target_id=backup_id,
            context={"stage": "password"},
            commit=True,
        )
        return "password"
    if not user.totp_secret or not pyotp.TOTP(user.totp_secret).verify(
        normalized_totp, valid_window=1
    ):
        audit_record(
            "backup.restore.auth_failed",
            status=AuditStatus.FAILURE,
            target_type="backup",
            target_id=backup_id,
            context={"stage": "2fa"},
            commit=True,
        )
        return "totp"
    return "ok"
