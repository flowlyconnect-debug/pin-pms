"""Shared JSON response helpers for the public API.

Every response from ``/api/v1/*`` follows the contract defined in the project
brief (section 6):

    success:  {"success": true,  "data": <...>, "error": null}
    error:    {"success": false, "data": null,  "error": {"code": "...", "message": "..."}}

Route handlers should return the values produced by :func:`json_ok` and
:func:`json_error` — never a bare ``jsonify`` — so the shape stays consistent.
"""
from typing import Any

from flask import jsonify


def json_ok(data: Any = None, status: int = 200, meta: Any = None):
    """Return a uniform success response."""

    payload = {"success": True, "data": data, "error": None}
    if meta is not None:
        payload["meta"] = meta
    return jsonify(payload), status


def json_error(
    code: str,
    message: str,
    status: int = 400,
    data: Any = None,
):
    """Return a uniform error response.

    ``code`` is the machine-readable error key (snake_case). ``message`` is a
    short, human-readable description safe to show to API consumers — it must
    not leak internal state, stack traces, or SQL.
    """

    payload = {
        "success": False,
        "data": data,
        "error": {"code": code, "message": message},
    }
    return jsonify(payload), status
