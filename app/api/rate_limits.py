from __future__ import annotations

from flask import g
from sqlalchemy.orm.exc import DetachedInstanceError

DEFAULT_API_RATE_LIMIT = "100/hour"


def resolve_api_rate_limit() -> str:
    """Resolve per-request API rate limit from API key organization plan."""

    api_key = getattr(g, "api_key", None)
    if api_key is None:
        return DEFAULT_API_RATE_LIMIT
    try:
        if api_key.organization_id is None:
            return DEFAULT_API_RATE_LIMIT
    except DetachedInstanceError:
        return DEFAULT_API_RATE_LIMIT

    try:
        organization = getattr(api_key, "organization", None)
    except DetachedInstanceError:
        return DEFAULT_API_RATE_LIMIT
    if organization is None:
        return DEFAULT_API_RATE_LIMIT
    plan = getattr(organization, "subscription_plan", None)
    if plan is None:
        return DEFAULT_API_RATE_LIMIT
    limits = plan.limits_json or {}
    value = str(limits.get("api_rate_limit") or "").strip()
    return value or DEFAULT_API_RATE_LIMIT
