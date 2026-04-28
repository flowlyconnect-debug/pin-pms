from __future__ import annotations

import atexit
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask

from app.api.services import prune_api_key_usage

logger = logging.getLogger(__name__)


def _daily_prune_job(app: Flask) -> None:
    with app.app_context():
        retention_days = int(app.config.get("API_USAGE_RETENTION_DAYS", 90))
        deleted = prune_api_key_usage(retention_days=retention_days)
        if deleted:
            logger.info("Pruned %s api_key_usage rows older than %s days.", deleted, retention_days)


def init_scheduler(app: Flask):
    if app.config.get("TESTING"):
        return None
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _daily_prune_job,
        trigger=CronTrigger(hour=4, minute=15),
        args=[app],
        id="api_key_usage_prune",
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
        logger.exception("API usage scheduler shutdown failed")
