from __future__ import annotations

import atexit
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

from app.status.service import run_synthetic_checks

logger = logging.getLogger(__name__)


def _job(app: Flask) -> None:
    with app.app_context():
        run_synthetic_checks()


def init_scheduler(app: Flask):
    if app.config.get("TESTING"):
        return None
    if not app.config.get("STATUS_SCHEDULER_ENABLED", True):
        return None
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _job,
        trigger=IntervalTrigger(minutes=1),
        args=[app],
        id="status_synthetic_checks",
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
        logger.exception("Status scheduler shutdown failed")
