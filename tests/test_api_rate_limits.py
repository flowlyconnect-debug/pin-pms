from __future__ import annotations


def test_resolve_api_rate_limit_defaults_to_free(app):
    from app.api.rate_limits import resolve_api_rate_limit

    with app.test_request_context("/api/v1/health"):
        assert resolve_api_rate_limit() == "100/hour"


def test_resolve_api_rate_limit_uses_plan_from_api_key(app, organization, regular_user):
    from flask import g

    from app.api.models import ApiKey
    from app.api.rate_limits import resolve_api_rate_limit
    from app.extensions import db
    from app.subscriptions.models import SubscriptionPlan

    free = SubscriptionPlan(code="free", name="Free", limits_json={"api_rate_limit": "100/hour"})
    pro = SubscriptionPlan(code="pro", name="Pro", limits_json={"api_rate_limit": "1000/hour"})
    db.session.add_all([free, pro])
    db.session.flush()
    organization.subscription_plan_id = pro.id

    key, _raw = ApiKey.issue(
        name="Pro key",
        organization_id=organization.id,
        user_id=regular_user.id,
        scopes="reservations:read",
    )
    db.session.add(key)
    db.session.commit()

    with app.test_request_context("/api/v1/reservations"):
        g.api_key = key
        assert resolve_api_rate_limit() == "1000/hour"
