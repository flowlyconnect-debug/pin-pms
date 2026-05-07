"""Background backup scheduler.

Runs ``create_backup`` on the schedule defined by ``BACKUP_SCHEDULE_CRON``.

Multi-worker safety
-------------------

When the app is served by multiple Gunicorn workers, every worker boots a
``BackgroundScheduler`` and every cron tick fires in every worker. Without
coordination that would mean N parallel ``pg_dump`` runs writing N files on
the same minute.

We use a Postgres advisory lock to serialise the actual dump: each scheduled
invocation tries ``pg_try_advisory_lock(LOCK_KEY)`` and silently skips if
another worker already holds it. The lock is released as soon as the call
returns, so a 24h cron tomorrow is unaffected by today's worker that held it.

Process lifecycle
-----------------

The scheduler is started lazily on the first request (``before_first_request``
is gone in modern Flask, so we use ``app.before_request`` with a one-shot
flag). Stopping cleanly relies on the OS sending the worker a signal — ``atexit``
handles that for us.
"""
from __future__ import annotations

import atexit
import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask

from app.backups.services import BackupError, create_backup
from app.backups.models import BackupTrigger

logger = logging.getLogger(__name__)

# Arbitrary 64-bit integer used as the advisory-lock key. Keep it stable —
# changing it would let an old worker run alongside a new worker.
_ADVISORY_LOCK_KEY = 728110424711


def _build_trigger(cron_expr: str) -> CronTrigger:
    """Parse ``"minute hour day month day_of_week"`` into a CronTrigger."""

    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(
            "BACKUP_SCHEDULE_CRON must have five space-separated fields, got "
            f"{cron_expr!r}"
        )
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(
        minute=minute,
        hour=hour,
        day=day,
        month=month,
        day_of_week=day_of_week,
    )


def _invoice_overdue_scheduled_job(app: Flask) -> None:
    """Mark open invoices overdue when due date has passed (all tenants)."""

    from app.billing import services as billing_services

    with app.app_context():
        n = billing_services.mark_overdue_invoices(organization_id=None)
        logger.info("Scheduled invoice overdue pass marked %s invoice(s).", n)


def _scheduled_backup_job(app: Flask) -> None:
    """The cron-fired job. Acquires the advisory lock or no-ops."""

    from app.extensions import db

    with app.app_context():
        # ``pg_try_advisory_lock`` returns true if the lock was acquired.
        # ``False`` means another worker is already running this tick, which
        # is the entire point of the coordination.
        result = db.session.execute(
            db.text("SELECT pg_try_advisory_lock(:key)"),
            {"key": _ADVISORY_LOCK_KEY},
        ).scalar()
        if not result:
            logger.info(
                "Backup tick skipped — another worker holds the advisory lock."
            )
            return

        try:
            create_backup(trigger=BackupTrigger.SCHEDULED)
        except BackupError:
            # ``create_backup`` already wrote the audit row + email. We just
            # need to make sure the lock is released.
            logger.error("Scheduled backup failed; see audit log for details.")
        finally:
            db.session.execute(
                db.text("SELECT pg_advisory_unlock(:key)"),
                {"key": _ADVISORY_LOCK_KEY},
            )
            db.session.commit()


def init_scheduler(app: Flask) -> Any:
    """Start the BackgroundScheduler if enabled in config.

    Returns the scheduler instance (or ``None`` when disabled) so callers and
    tests can introspect it. The scheduler is registered with ``atexit`` to
    shut down cleanly on worker exit.
    """

    if app.config.get("TESTING"):
        return None

    backup_on = app.config.get("BACKUP_SCHEDULER_ENABLED")
    invoice_on = app.config.get("INVOICE_OVERDUE_SCHEDULER_ENABLED")

    if not backup_on and not invoice_on:
        logger.info(
            "Background scheduler idle — BACKUP_SCHEDULER_ENABLED and "
            "INVOICE_OVERDUE_SCHEDULER_ENABLED are both off."
        )
        return None

    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    cron_expr = ""
    if backup_on:
        cron_expr = app.config.get("BACKUP_SCHEDULE_CRON", "0 3 * * *")
        try:
            trigger = _build_trigger(cron_expr)
        except ValueError as err:
            logger.error("Invalid BACKUP_SCHEDULE_CRON: %s", err)
        else:
            scheduler.add_job(
                _scheduled_backup_job,
                trigger=trigger,
                args=[app],
                id="pindora_backup",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
    else:
        logger.info("BACKUP_SCHEDULER_ENABLED is off — automatic backups disabled.")

    if invoice_on:
        cron_inv = app.config.get("INVOICE_OVERDUE_SCHEDULE_CRON", "30 6 * * *")
        try:
            trigger_inv = _build_trigger(cron_inv)
        except ValueError as err:
            logger.error("Invalid INVOICE_OVERDUE_SCHEDULE_CRON: %s", err)
        else:
            scheduler.add_job(
                _invoice_overdue_scheduled_job,
                trigger=trigger_inv,
                args=[app],
                id="pindora_invoice_overdue",
                max_instances=1,
                coalesce=True,
                replace_existing=True,
            )
            logger.info("Invoice overdue job registered (cron=%r).", cron_inv)

    if not scheduler.get_jobs():
        logger.error("Scheduler had no valid jobs — not starting.")
        return None

    # Guard against double-start when Flask's debug auto-reloader spawns a
    # child process — that child re-imports ``create_app`` and would otherwise
    # boot a second scheduler in the same container.
    if getattr(init_scheduler, "_started", False):
        return scheduler
    init_scheduler._started = True  # type: ignore[attr-defined]

    scheduler.start()
    if backup_on and cron_expr:
        logger.info(
            "Background scheduler started (backup cron=%r, dir=%r).",
            cron_expr,
            app.config.get("BACKUP_DIR"),
        )
    else:
        logger.info("Background scheduler started (backup job disabled).")

    # Stop scheduler when the worker is shutting down.
    atexit.register(_shutdown_scheduler, scheduler)
    return scheduler


def _shutdown_scheduler(scheduler) -> None:  # pragma: no cover - exit-time only
    try:
        scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        logger.exception("Scheduler shutdown raised")
