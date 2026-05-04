"""Daily pruning of expired idempotency key rows (APScheduler, UTC cron)."""

from __future__ import annotations

import atexit
import logging
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask

from app.idempotency.services import prune_expired

logger = logging.getLogger(__name__)


def _build_trigger(cron_expr: str) -> CronTrigger:
    parts = cron_expr.split()
    if len(parts) != 5:
        raise ValueError(
            "IDEMPOTENCY_PRUNE_SCHEDULE_CRON must have five space-separated fields, got "
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


def _scheduled_prune_job(app: Flask) -> None:
    with app.app_context():
        n = prune_expired()
        if n:
            logger.info("Pruned %s expired idempotency key row(s).", n)


def init_scheduler(app: Flask) -> Any:
    if app.config.get("TESTING"):
        return None
    if not app.config.get("IDEMPOTENCY_PRUNE_SCHEDULER_ENABLED", True):
        return None

    cron_expr = app.config.get("IDEMPOTENCY_PRUNE_SCHEDULE_CRON", "0 4 * * *")
    try:
        trigger = _build_trigger(cron_expr)
    except ValueError as err:
        logger.error("Invalid IDEMPOTENCY_PRUNE_SCHEDULE_CRON: %s", err)
        return None

    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _scheduled_prune_job,
        trigger=trigger,
        args=[app],
        id="pindora_idempotency_prune",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    if getattr(init_scheduler, "_started", False):
        return scheduler
    init_scheduler._started = True  # type: ignore[attr-defined]

    scheduler.start()
    logger.info("Idempotency prune scheduler started (cron=%r).", cron_expr)
    atexit.register(_shutdown_scheduler, scheduler)
    return scheduler


def _shutdown_scheduler(scheduler) -> None:  # pragma: no cover
    try:
        scheduler.shutdown(wait=False)
    except Exception:  # noqa: BLE001
        logger.exception("Idempotency scheduler shutdown failed")
