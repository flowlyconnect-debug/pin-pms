from __future__ import annotations

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask


def init_scheduler(app: Flask):
    _ = app
    scheduler = BackgroundScheduler(timezone="UTC")
    return scheduler

