"""APScheduler jobs for outbound webhook delivery and stale inbound handler dispatch."""

from __future__ import annotations

import atexit
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

from app.extensions import db

logger = logging.getLogger(__name__)


def _delivery_job(app: Flask) -> None:
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


def _inbound_handler_job(app: Flask) -> None:
    with app.app_context():
        try:
            from app.webhooks.services import process_stale_inbound_webhook_events

            n = process_stale_inbound_webhook_events()
            if n:
                logger.info("Inbound webhook handler job processed %s event(s).", n)
        except Exception:  # noqa: BLE001
            logger.exception("Inbound webhook handler job failed")
        finally:
            db.session.remove()


def init_scheduler(app: Flask):
    if app.config.get("TESTING"):
        return None

    delivery_on = bool(app.config.get("WEBHOOK_DELIVERY_SCHEDULER_ENABLED", False))
    inbound_on = bool(app.config.get("WEBHOOK_INBOUND_HANDLER_SCHEDULER_ENABLED", False))
    if not delivery_on and not inbound_on:
        return None

    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")

    if delivery_on:
        interval = int(app.config.get("WEBHOOK_DELIVERY_RETRY_INTERVAL_SECONDS", 60))
        interval = max(15, interval)
        scheduler.add_job(
            _delivery_job,
            trigger=IntervalTrigger(seconds=interval),
            args=[app],
            id="webhook_delivery_retry",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )

    if inbound_on:
        interval_in = int(app.config.get("WEBHOOK_INBOUND_HANDLER_INTERVAL_SECONDS", 60))
        interval_in = max(15, interval_in)
        scheduler.add_job(
            _inbound_handler_job,
            trigger=IntervalTrigger(seconds=interval_in),
            args=[app],
            id="webhook_inbound_handler_retry",
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
