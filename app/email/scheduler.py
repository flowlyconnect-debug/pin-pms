from __future__ import annotations

import atexit
import logging
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

from app.email.models import OutgoingEmail, OutgoingEmailStatus
from app.email.services import send_template_sync
from app.extensions import db

logger = logging.getLogger(__name__)


def run_email_queue_cycle(*, batch_size: int = 50) -> int:
    now = datetime.now(timezone.utc)
    rows = (
        OutgoingEmail.query.filter(
            OutgoingEmail.status == OutgoingEmailStatus.PENDING,
            OutgoingEmail.scheduled_at <= now,
        )
        .order_by(OutgoingEmail.scheduled_at.asc(), OutgoingEmail.id.asc())
        .limit(batch_size)
        .all()
    )
    processed = 0
    for row in rows:
        _deliver_row(row)
        processed += 1
    return processed


def _deliver_row(row: OutgoingEmail) -> None:
    try:
        ok = send_template_sync(
            row.template_key,
            to=row.to,
            context=dict(row.context_json or {}),
        )
    except Exception as err:  # noqa: BLE001
        ok = False
        row.attempts += 1
        row.last_error = str(err)
    else:
        if ok:
            row.status = OutgoingEmailStatus.SENT
            row.sent_at = datetime.now(timezone.utc)
            row.last_error = None
        else:
            row.attempts += 1
            row.last_error = "Mailgun send returned false."

    if row.status != OutgoingEmailStatus.SENT and row.attempts >= 5:
        row.status = OutgoingEmailStatus.FAILED

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
