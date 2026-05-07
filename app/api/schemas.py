"""Shared JSON response helpers for the public API.

Every response from ``/api/v1/*`` follows the contract defined in the project
brief (section 6):

    success:  {"success": true,  "data": <...>, "error": null}
    error:    {"success": false, "data": null,  "error": {"code": "...", "message": "..."}}

Route handlers should return the values produced by :func:`json_ok` and
:func:`json_error` — never a bare ``jsonify`` — so the shape stays consistent.
"""

from typing import Any, TypedDict

from flask import jsonify


class InvoiceSchema(TypedDict, total=False):
    """JSON shape returned for invoice resources under ``/api/v1/invoices``."""

    id: int
    organization_id: int
    lease_id: int | None
    reservation_id: int | None
    guest_id: int | None
    invoice_number: str | None
    amount: str
    vat_rate: str
    vat_amount: str
    subtotal_excl_vat: str
    total_incl_vat: str
    total: str
    currency: str
    due_date: str
    paid_at: str | None
    status: str
    description: str | None
    metadata_json: Any
    created_by_id: int
    updated_by_id: int | None
    created_at: str | None
    updated_at: str | None


class PropertySchema(TypedDict, total=False):
    id: int
    organization_id: int
    name: str
    address: str | None
    city: str | None
    postal_code: str | None
    street_address: str | None
    latitude: str | None
    longitude: str | None
    year_built: int | None
    has_elevator: bool
    has_parking: bool
    has_sauna: bool
    has_courtyard: bool
    has_air_conditioning: bool
    description: str | None
    url: str | None
    created_at: str | None
    updated_at: str | None


class UnitSchema(TypedDict, total=False):
    id: int
    property_id: int
    name: str
    unit_type: str | None
    floor: int | None
    area_sqm: str | None
    bedrooms: int
    has_kitchen: bool
    has_bathroom: bool
    has_balcony: bool
    has_terrace: bool
    has_dishwasher: bool
    has_washing_machine: bool
    has_tv: bool
    has_wifi: bool
    max_guests: int
    description: str | None
    floor_plan_image_id: int | None
    created_at: str | None
    updated_at: str | None


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
