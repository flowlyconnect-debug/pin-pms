from __future__ import annotations


def test_payments_scheduler_returns_background_scheduler(app):
    from app.payments.scheduler import init_scheduler

    with app.app_context():
        scheduler = init_scheduler(app)
        assert scheduler is not None
        assert scheduler.timezone is not None

