"""APScheduler jobs for payment lifecycle (pending expiry, etc.)."""

from __future__ import annotations

import atexit
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

from app.extensions import db

logger = logging.getLogger(__name__)


def _expire_job(app: Flask) -> None:
    with app.app_context():
        try:
            from app.payments.services import expire_pending_payments

            n = expire_pending_payments()
            if n:
                logger.info("Payment expiry job marked %s payment(s) as expired.", n)
        except Exception:  # noqa: BLE001
            logger.exception("Payment expiry job failed")
        finally:
            db.session.remove()


def init_scheduler(app: Flask):
    if app.config.get("TESTING"):
        return None
    if not app.config.get("PAYMENT_EXPIRY_SCHEDULER_ENABLED", False):
        return None

    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _expire_job,
        trigger=IntervalTrigger(hours=1),
        args=[app],
        id="payment_pending_expiry",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    if getattr(init_scheduler, "_started", False):
        return scheduler
    init_scheduler._started = True  # type: ignore[attr-defined]
    scheduler.start()
    atexit.register(_shutdown_scheduler, scheduler)
    logger.info("Payment pending-expiry scheduler started (hourly).")
    return scheduler


def _shutdown_scheduler(scheduler) -> None:  # pragma: no cover
    try:
        scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        logger.exception("Payment scheduler shutdown failed")
