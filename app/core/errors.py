"""Centralised error copy + handler registration — project brief section 15.

The actual handlers are wired up in :mod:`app.__init__` because they need
the Flask app instance. This module owns the human-readable copy table so
all status codes have a single source of truth.
"""

from __future__ import annotations

# Human-facing copy for each error code. Keep messages short and avoid
# exposing internal details; if Werkzeug gives us a more specific
# description (e.g. from a custom ``abort(403, "You are not the owner")``)
# we prefer it.
ERROR_COPY: dict[int, tuple[str, str]] = {
    400: ("Bad Request", "Your request could not be understood."),
    401: ("Unauthorized", "You must sign in to access this page."),
    403: ("Forbidden", "You do not have permission to access this page."),
    404: ("Not Found", "The page you requested does not exist."),
    405: (
        "Method Not Allowed",
        "This resource does not support that kind of request.",
    ),
    413: ("Payload Too Large", "The data you submitted is too large."),
    429: (
        "Too Many Requests",
        "You are making requests too quickly. Please wait and try again.",
    ),
    500: (
        "Internal Server Error",
        "Something went wrong on our side. The error has been recorded.",
    ),
}


def copy_for(code: int) -> tuple[str, str]:
    """Return ``(title, default_message)`` for the given status code."""

    return ERROR_COPY.get(code, ("HTTP Error", "An unexpected error occurred."))
