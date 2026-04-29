from __future__ import annotations

from datetime import datetime, timedelta, timezone


def test_status_component_uptime_percent_30d_window(app):
    from app.admin.services import status_uptime_percent
    from app.extensions import db
    from app.status.models import StatusCheck

    now = datetime.now(timezone.utc)
    rows = [
        StatusCheck(
            component_key="api", checked_at=now - timedelta(days=1), ok=True, latency_ms=10
        ),
        StatusCheck(
            component_key="api", checked_at=now - timedelta(days=2), ok=True, latency_ms=10
        ),
        StatusCheck(
            component_key="api", checked_at=now - timedelta(days=3), ok=False, latency_ms=10
        ),
        StatusCheck(
            component_key="api", checked_at=now - timedelta(days=31), ok=False, latency_ms=10
        ),
    ]
    db.session.add_all(rows)
    db.session.commit()

    uptime = status_uptime_percent(component_key="api", window_days=30)
    assert uptime == 66.67
