from __future__ import annotations


def test_payments_scheduler_disabled_in_testing(app):
    from app.payments.scheduler import init_scheduler

    with app.app_context():
        assert init_scheduler(app) is None


def test_payments_scheduler_disabled_by_flag(app):
    from app.payments.scheduler import init_scheduler

    with app.app_context():
        app.config["TESTING"] = False
        app.config["PAYMENT_EXPIRY_SCHEDULER_ENABLED"] = False
        assert init_scheduler(app) is None


def test_payment_expiry_job_calls_service(app, monkeypatch):
    from app.payments import scheduler as ps

    called = {"n": 0}

    def fake_expire():
        called["n"] += 1
        return 0

    monkeypatch.setattr("app.payments.services.expire_pending_payments", fake_expire)
    monkeypatch.setattr(ps.db.session, "remove", lambda: None)
    ps._expire_job(app)
    assert called["n"] == 1


def test_payments_scheduler_starts_when_enabled(app, monkeypatch):
    from types import SimpleNamespace

    from app.payments import scheduler as ps

    calls = {"jobs": 0, "started": False}

    class FakeScheduler:
        def add_job(self, *args, **kwargs):
            _ = (args, kwargs)
            calls["jobs"] += 1

        def start(self):
            calls["started"] = True

        def shutdown(self, wait=False):
            _ = wait

    monkeypatch.setattr(ps, "BackgroundScheduler", lambda **kwargs: FakeScheduler())
    monkeypatch.setattr(ps, "IntervalTrigger", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(ps.db.session, "remove", lambda: None)
    with app.app_context():
        app.config["TESTING"] = False
        app.config["PAYMENT_EXPIRY_SCHEDULER_ENABLED"] = True
        if hasattr(ps.init_scheduler, "_started"):
            delattr(ps.init_scheduler, "_started")
        sched = ps.init_scheduler(app)
        assert sched is not None
        assert calls["jobs"] == 1
        assert calls["started"] is True
        ps._shutdown_scheduler(sched)
