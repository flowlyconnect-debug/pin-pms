"""APScheduler job for outbound webhook delivery retries."""

from __future__ import annotations

import atexit
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

from app.extensions import db

logger = logging.getLogger(__name__)


def _job(app: Flask) -> None:
    with app.app_context():
        try:
            from app.webhooks.services import retry_pending_deliveries

            n = retry_pending_deliveries()
            if n:
                logger.info("Webhook retry job processed %s delivery row(s).", n)
        except Exception:  # noqa: BLE001
            logger.exception("Webhook retry job failed")
        finally:
            db.session.remove()


def init_scheduler(app: Flask):
    if app.config.get("TESTING"):
        return None
    if not app.config.get("WEBHOOK_DELIVERY_SCHEDULER_ENABLED", False):
        return None

    interval = int(app.config.get("WEBHOOK_DELIVERY_RETRY_INTERVAL_SECONDS", 60))
    interval = max(15, interval)

    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(seconds=interval),
        args=[app],
        id="webhook_delivery_retry",
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
        logger.exception("Webhook scheduler shutdown failed")
