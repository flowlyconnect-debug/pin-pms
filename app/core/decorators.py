"""Reusable view decorators (tenant scoping, etc.)."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Any

from flask import abort, g
from flask_login import current_user

from app.api.schemas import json_error


def _resolve_model_class(model_name: str | type[Any]) -> type[Any]:
    """Resolve a model class from a short string name or return class as-is."""
    if not isinstance(model_name, str):
        return model_name

    normalized_name = model_name.strip().lower()
    model_registry: dict[str, Callable[[], type[Any]]] = {
        "invoice": lambda: __import__("app.billing.models", fromlist=["Invoice"]).Invoice,
        "payment": lambda: __import__("app.payments.models", fromlist=["Payment"]).Payment,
        "webhook_subscription": lambda: __import__(
            "app.webhooks.models", fromlist=["WebhookSubscription"]
        ).WebhookSubscription,
        "imported_calendar_feed": lambda: __import__(
            "app.integrations.ical.models", fromlist=["ImportedCalendarFeed"]
        ).ImportedCalendarFeed,
    }
    resolver = model_registry.get(normalized_name)
    if resolver is None:
        raise ValueError(f"Unknown tenant model '{model_name}'")
    return resolver()


def _load_entity(model_class: type[Any], entity_id: Any) -> Any | None:
    if entity_id is None:
        return None
    return model_class.query.get(entity_id)


def require_tenant_access(
    model_name: str | type[Any],
    id_arg: str = "id",
    *,
    id_param: str | None = None,
    allow_superadmin_all_tenants: bool = False,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator that fetches model by id and verifies organization match.

    Usage: ``@require_tenant_access("invoice", id_arg="invoice_id")``.
    """
    if id_param:
        # Backward-compatible alias used by existing routes.
        id_arg = id_param
    model_class = _resolve_model_class(model_name)

    def decorator(view_func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view_func)
        def wrapped(*args: Any, **kwargs: Any):
            entity = _load_entity(model_class, kwargs.get(id_arg))
            if entity is None:
                abort(404)
            if allow_superadmin_all_tenants and getattr(current_user, "is_superadmin", False):
                g.scoped_entity = entity
                return view_func(*args, **kwargs)
            if getattr(entity, "organization_id", None) != getattr(
                current_user, "organization_id", None
            ):
                abort(404)
            g.scoped_entity = entity
            return view_func(*args, **kwargs)

        return wrapped

    return decorator


def require_api_tenant_entity(
    model_class: type[Any],
    *,
    id_param: str,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Load a row by id and ensure ``organization_id`` matches the API key's organization."""

    def decorator(view_func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view_func)
        def wrapped(*args: Any, **kwargs: Any):
            from flask import g as flask_g

            entity = _load_entity(model_class, kwargs.get(id_param))
            if entity is None:
                return json_error("not_found", "Resource not found.", status=404)
            api_key = getattr(flask_g, "api_key", None)
            org_id = getattr(api_key, "organization_id", None)
            if org_id is None or getattr(entity, "organization_id", None) != org_id:
                return json_error("forbidden", "Invoice not found.", status=403)
            flask_g.scoped_entity = entity
            return view_func(*args, **kwargs)

        return wrapped

    return decorator
