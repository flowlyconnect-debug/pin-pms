from __future__ import annotations

import atexit
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from flask import Flask

logger = logging.getLogger(__name__)


def _revoke_job(app: Flask) -> None:
    from app.portal import services as portal_services

    with app.app_context():
        count = portal_services.auto_revoke_expired_access_codes()
        if count:
            logger.info("Auto-revoked %s expired access code(s).", count)


def init_scheduler(app: Flask):
    if app.config.get("TESTING"):
        return None
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _revoke_job,
        trigger=IntervalTrigger(minutes=15),
        args=[app],
        id="portal_lock_revoke",
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
        logger.exception("Portal scheduler shutdown failed")
