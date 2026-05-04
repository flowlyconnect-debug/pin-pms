"""Webhook infrastructure (inbound provider endpoints + outbound subscriptions)."""

from flask import Blueprint

webhooks_bp = Blueprint("webhooks", __name__)

from . import routes  # noqa: E402,F401
