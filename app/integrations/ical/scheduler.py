from __future__ import annotations

import atexit
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

logger = logging.getLogger(__name__)


def _sync_job(app: Flask) -> None:
    from app.integrations.ical.service import IcalService

    with app.app_context():
        count = IcalService().sync_all_feeds()
        if count:
            logger.info("Imported %s iCal event(s).", count)


def init_scheduler(app: Flask):
    if app.config.get("TESTING"):
        return None
    if not app.config.get("ICAL_SYNC_ENABLED", True):
        return None
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _sync_job,
        trigger=IntervalTrigger(minutes=int(app.config.get("ICAL_SYNC_INTERVAL_MINUTES", 15))),
        args=[app],
        id="ical_sync",
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
        logger.exception("iCal scheduler shutdown failed")
