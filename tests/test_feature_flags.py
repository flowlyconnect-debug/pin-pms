from __future__ import annotations

from app import create_app
from app.config import TestConfig


def _has_owner_portal_routes(app) -> bool:
    return any(rule.endpoint.startswith("owner_portal.") for rule in app.url_map.iter_rules())


def test_owner_portal_blueprint_not_registered_when_flag_disabled():
    class OwnerPortalOffConfig(TestConfig):
        OWNER_PORTAL_ENABLED = False

    app = create_app(OwnerPortalOffConfig)
    try:
        assert _has_owner_portal_routes(app) is False
    finally:
        ext = app.extensions.get("apscheduler_instances", {})
        for scheduler in ext.values():
            scheduler.shutdown(wait=False)


def test_owner_portal_blueprint_registered_when_flag_enabled():
    class OwnerPortalOnConfig(TestConfig):
        OWNER_PORTAL_ENABLED = True

    app = create_app(OwnerPortalOnConfig)
    try:
        assert _has_owner_portal_routes(app) is True
    finally:
        ext = app.extensions.get("apscheduler_instances", {})
        for scheduler in ext.values():
            scheduler.shutdown(wait=False)
