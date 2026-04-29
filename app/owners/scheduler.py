from __future__ import annotations

import atexit
import logging
from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.owners.models import OwnerPayout, OwnerPayoutStatus, PropertyOwner
from app.owners.services import generate_monthly_payout, send_payout_email

logger = logging.getLogger(__name__)


def _previous_month(today: date) -> str:
    year = today.year
    month = today.month - 1
    if month == 0:
        month = 12
        year -= 1
    return f"{year:04d}-{month:02d}"


def run_monthly_owner_payout_job() -> int:
    period = _previous_month(date.today())
    owners = PropertyOwner.query.filter_by(is_active=True).all()
    count = 0
    for owner in owners:
        generate_monthly_payout(owner_id=owner.id, period_month=period)
        payout = OwnerPayout.query.filter_by(owner_id=owner.id, period_month=period).first()
        if payout is not None and payout.status == OwnerPayoutStatus.DRAFT:
            send_payout_email(payout=payout)
        count += 1
    return count


def _job(app):
    with app.app_context():
        processed = run_monthly_owner_payout_job()
        if processed:
            logger.info("Processed owner payouts for %s owner(s).", processed)


def init_scheduler(app):
    if app.config.get("TESTING"):
        return None
    scheduler = BackgroundScheduler(daemon=True, timezone="UTC")
    scheduler.add_job(
        _job,
        trigger=CronTrigger(day=5, hour=3, minute=0),
        args=[app],
        id="owners_monthly_payouts",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )
    if getattr(init_scheduler, "_started", False):
        return scheduler
    init_scheduler._started = True  # type: ignore[attr-defined]
    scheduler.start()
    atexit.register(_shutdown, scheduler)
    return scheduler


def _shutdown(scheduler):  # pragma: no cover
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        logger.exception("Owner scheduler shutdown failed")
