from __future__ import annotations

from types import SimpleNamespace


def test_webhook_scheduler_disabled_in_testing(app):
    from app.webhooks import scheduler as webhook_scheduler

    with app.app_context():
        app.config["TESTING"] = True
        assert webhook_scheduler.init_scheduler(app) is None


def test_webhook_scheduler_disabled_by_flag(app):
    from app.webhooks import scheduler as webhook_scheduler

    with app.app_context():
        app.config["TESTING"] = False
        app.config["WEBHOOK_DELIVERY_SCHEDULER_ENABLED"] = False
        app.config["WEBHOOK_INBOUND_HANDLER_SCHEDULER_ENABLED"] = False
        assert webhook_scheduler.init_scheduler(app) is None


def test_webhook_scheduler_runs_job_and_shutdown(app, monkeypatch):
    from app.webhooks import scheduler as webhook_scheduler

    calls = {"started": False, "shutdown": False, "jobs": 0}

    class FakeScheduler:
        def add_job(self, *args, **kwargs):
            _ = (args, kwargs)
            calls["jobs"] += 1

        def start(self):
            calls["started"] = True

        def shutdown(self, wait=False):
            _ = wait
            calls["shutdown"] = True

    monkeypatch.setattr(webhook_scheduler, "BackgroundScheduler", lambda **kwargs: FakeScheduler())
    monkeypatch.setattr(webhook_scheduler, "IntervalTrigger", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(webhook_scheduler, "retry_pending_deliveries", lambda: 1, raising=False)
    monkeypatch.setattr(webhook_scheduler.db.session, "remove", lambda: None)
    with app.app_context():
        app.config["TESTING"] = False
        app.config["WEBHOOK_DELIVERY_SCHEDULER_ENABLED"] = True
        app.config["WEBHOOK_DELIVERY_RETRY_INTERVAL_SECONDS"] = 1
        if hasattr(webhook_scheduler.init_scheduler, "_started"):
            delattr(webhook_scheduler.init_scheduler, "_started")
        sched = webhook_scheduler.init_scheduler(app)
        assert sched is not None
        assert calls["jobs"] == 1
        assert calls["started"] is True
        webhook_scheduler._shutdown_scheduler(sched)
        assert calls["shutdown"] is True


def test_webhook_scheduler_job_exception_path(app, monkeypatch):
    from app.webhooks import scheduler as webhook_scheduler

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(webhook_scheduler, "retry_pending_deliveries", boom, raising=False)
    removed = {"ok": False}
    monkeypatch.setattr(webhook_scheduler.db.session, "remove", lambda: removed.update(ok=True))
    webhook_scheduler._delivery_job(app)
    assert removed["ok"] is True


def test_webhook_inbound_handler_job_runs_processor(app, monkeypatch):
    from app.webhooks import scheduler as webhook_scheduler

    called = {"n": 0}

    def fake_process():
        called["n"] += 1
        return 0

    monkeypatch.setattr(
        "app.webhooks.services.process_stale_inbound_webhook_events",
        fake_process,
        raising=False,
    )
    monkeypatch.setattr(webhook_scheduler.db.session, "remove", lambda: None)
    webhook_scheduler._inbound_handler_job(app)
    assert called["n"] == 1


def test_webhook_scheduler_registers_both_jobs_when_enabled(app, monkeypatch):
    from app.webhooks import scheduler as webhook_scheduler
    from types import SimpleNamespace

    calls = {"jobs": 0}

    class FakeScheduler:
        def add_job(self, *args, **kwargs):
            _ = (args, kwargs)
            calls["jobs"] += 1

        def start(self):
            return None

        def shutdown(self, wait=False):
            _ = wait

    monkeypatch.setattr(webhook_scheduler, "BackgroundScheduler", lambda **kwargs: FakeScheduler())
    monkeypatch.setattr(webhook_scheduler, "IntervalTrigger", lambda **kwargs: SimpleNamespace(**kwargs))
    monkeypatch.setattr(webhook_scheduler.db.session, "remove", lambda: None)
    with app.app_context():
        app.config["TESTING"] = False
        app.config["WEBHOOK_DELIVERY_SCHEDULER_ENABLED"] = True
        app.config["WEBHOOK_INBOUND_HANDLER_SCHEDULER_ENABLED"] = True
        if hasattr(webhook_scheduler.init_scheduler, "_started"):
            delattr(webhook_scheduler.init_scheduler, "_started")
        sched = webhook_scheduler.init_scheduler(app)
        assert sched is not None
        assert calls["jobs"] == 2
        webhook_scheduler._shutdown_scheduler(sched)

