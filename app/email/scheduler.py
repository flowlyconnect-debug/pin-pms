from __future__ import annotations

import atexit
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask
from sqlalchemy import or_

from app.audit import record as audit_record
from app.audit.models import AuditStatus
from app.email.models import EmailQueueItem, OutgoingEmailStatus
from app.email.services import send_template_now
from app.extensions import db

logger = logging.getLogger(__name__)


MAX_ATTEMPTS = 5
RETRY_BACKOFF = (
    timedelta(minutes=1),
    timedelta(minutes=5),
    timedelta(minutes=30),
    timedelta(hours=2),
    timedelta(hours=12),
)


def _safe_error_text(err: object) -> str:
    return str(err or "")[:240]


def _compute_next_attempt(now: datetime, attempt_count: int) -> datetime:
    idx = max(0, min(attempt_count - 1, len(RETRY_BACKOFF) - 1))
    return now + RETRY_BACKOFF[idx]


def process_email_queue(limit: int = 50) -> int:
    now = datetime.now(timezone.utc)
    rows = (
        EmailQueueItem.query.filter(
            EmailQueueItem.status == OutgoingEmailStatus.PENDING,
            or_(
                EmailQueueItem.next_attempt_at.is_(None),
                EmailQueueItem.next_attempt_at <= now,
            ),
        )
        .order_by(EmailQueueItem.next_attempt_at.asc().nullsfirst(), EmailQueueItem.id.asc())
        .limit(limit)
        .all()
    )
    processed = 0
    for row in rows:
        _deliver_row(row, now=now)
        processed += 1
    return processed


def run_email_queue_cycle(*, batch_size: int = 50) -> int:
    return process_email_queue(limit=batch_size)


def _deliver_row(row: EmailQueueItem, *, now: datetime) -> None:
    row.sync_compat_fields()
    row.status = OutgoingEmailStatus.SENDING
    db.session.add(row)
    db.session.commit()
    try:
        ok = send_template_now(
            row.template_key,
            to=row.effective_recipient_email,
            context=dict(row.context_json or {}),
        )
    except Exception as err:  # noqa: BLE001
        ok = False
        row.attempt_count = min(MAX_ATTEMPTS, row.effective_attempt_count + 1)
        row.last_error = _safe_error_text(err)
    else:
        if ok:
            row.status = OutgoingEmailStatus.SENT
            row.sent_at = now
            row.last_error = None
            row.next_attempt_at = None
            audit_record(
                "email.sent",
                status=AuditStatus.SUCCESS,
                organization_id=row.organization_id,
                target_type="email_queue",
                target_id=row.id,
                metadata={"template_key": row.template_key, "status": row.status},
            )
        else:
            row.attempt_count = min(MAX_ATTEMPTS, row.effective_attempt_count + 1)
            row.last_error = "Mailgun send returned false."

    if row.status != OutgoingEmailStatus.SENT:
        attempts = row.effective_attempt_count
        if attempts >= MAX_ATTEMPTS:
            row.status = OutgoingEmailStatus.FAILED
            row.next_attempt_at = None
            audit_record(
                "email.failed",
                status=AuditStatus.FAILURE,
                organization_id=row.organization_id,
                target_type="email_queue",
                target_id=row.id,
                metadata={
                    "template_key": row.template_key,
                    "attempt_count": attempts,
                    "status": row.status,
                    "error": _safe_error_text(row.last_error),
                },
            )
        else:
            row.status = OutgoingEmailStatus.PENDING
            row.next_attempt_at = _compute_next_attempt(now, attempts)
            audit_record(
                "email.retried",
                status=AuditStatus.FAILURE,
                organization_id=row.organization_id,
                target_type="email_queue",
                target_id=row.id,
                metadata={
                    "template_key": row.template_key,
                    "attempt_count": attempts,
                    "status": row.status,
                    "error": _safe_error_text(row.last_error),
                },
            )

    row.sync_compat_fields()
    db.session.add(row)
    db.session.commit()


def _scheduler_job(app: Flask) -> None:
    with app.app_context():
        count = run_email_queue_cycle()
        if count:
            logger.info("Processed %s queued email(s).", count)


def init_scheduler(app: Flask):
    if app.config.get("TESTING"):
        return None
    if not app.config.get("EMAIL_SCHEDULER_ENABLED", True):
        return None
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _scheduler_job,
        trigger=IntervalTrigger(seconds=30),
        args=[app],
        id="email_queue_dispatch",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    if getattr(init_scheduler, "_started", False):
        return scheduler
    init_scheduler._started = True  # type: ignore[attr-defined]
    scheduler.start()
    atexit.register(_shutdown_scheduler, scheduler)
    return scheduler


def _shutdown_scheduler(scheduler) -> None:  # pragma: no cover
    try:
        scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        logger.exception("Email scheduler shutdown failed")
