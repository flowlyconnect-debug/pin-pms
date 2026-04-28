from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.api.models import ApiKeyUsage
from app.extensions import db


def record_api_key_usage(
    *,
    api_key_id: int,
    endpoint: str,
    status_code: int,
    ip: str | None,
    user_agent: str | None,
) -> None:
    row = ApiKeyUsage(
        api_key_id=api_key_id,
        endpoint=(endpoint or "")[:255] or "-",
        status_code=int(status_code),
        ip=(ip or None),
        user_agent=((user_agent or "")[:512] or None),
    )
    db.session.add(row)


def prune_api_key_usage(*, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    deleted = (
        db.session.query(ApiKeyUsage)
        .filter(ApiKeyUsage.created_at < cutoff)
        .delete(synchronize_session=False)
    )
    db.session.commit()
    return int(deleted or 0)
