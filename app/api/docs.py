from __future__ import annotations

from apispec import APISpec
from flask import current_app, jsonify, render_template_string

from app.api import api_bp
from app.api.auth import require_api_key, scope_required


def _build_openapi_spec() -> dict:
    spec = APISpec(
        title="Pin PMS API",
        version="1.0.0",
        openapi_version="3.0.3",
        info={
            "description": (
                "Auto-generated OpenAPI description for `/api/v1` routes. "
                "Tenant data is never embedded in this document.\n\n"
                "**Idempotency:** Send `Idempotency-Key: <unique-string>` (or the "
                "equivalent `X-Idempotency-Key`) on duplicate-sensitive POST requests "
                "(including payment webhooks) so retries do not double-apply side effects. "
                "The same key with the same JSON body returns the cached HTTP status and body; "
                "the same key with a different JSON body returns **409 Conflict**. "
                "If a duplicate request arrives before the first has finished, the server may "
                "respond with **503** (`idempotency_request_in_progress`) — retry after a short backoff.\n\n"
                "**Inbound webhooks** (`POST /api/v1/webhooks/{provider}` for `stripe`, `vismapay`, "
                "`pindora_lock`): these endpoints **do not** use an API key. Authenticate with the "
                "provider-specific signature header (`Stripe-Signature`, `X-VismaPay-Signature`, "
                "or `X-Signature`). An invalid or missing signature yields **401 Unauthorized**. "
                "A valid signature always yields **200 OK** once the event is accepted (including "
                "duplicate `external_id` / provider replays).\n\n"
                "**Outbound webhook subscriptions** (`GET`/`POST`/`DELETE /api/v1/webhooks/subscriptions`): "
                "require API-key scopes `webhooks:read` and `webhooks:write`. On `POST`, the signing "
                "secret is returned once in `data.secret`.\n\n"
                "**Verifying outbound deliveries (receiver side):** read the raw HTTP body bytes, "
                "compute `payload_sha256 = SHA256(JSON)` where JSON uses sorted object keys and "
                "no insignificant whitespace (same canonicalization as the sender), then compute "
                "`HMAC_SHA256(signing_secret, raw_body_bytes)` and compare hex digests to the "
                "`X-Pindora-Signature` header using a constant-time comparison.\n\n"
                "**Webhook events:** `reservation.created`, `reservation.cancelled`, "
                "`reservation.updated`, `invoice.created`, `invoice.paid`, `invoice.refunded`, "
                "`guest.checked_in`, `guest.checked_out`, `maintenance.requested`.\n\n"
                "**Example payload (`reservation.created`):** "
                "```json\n"
                '{"event":"reservation.created","occurred_at":"2026-05-05T08:00:00+00:00",'
                '"organization_id":1,"data":{"reservation_id":101,"unit_id":12,'
                '"start_date":"2026-06-01","end_date":"2026-06-03",'
                '"status":"confirmed","guest_id":77}}\n'
                "```\n\n"
                "**Example payload (`invoice.created`):** "
                "```json\n"
                '{"event":"invoice.created","occurred_at":"2026-05-05T08:00:00+00:00",'
                '"organization_id":1,"data":{"invoice_id":501,"invoice_number":"BIL-1-00000501",'
                '"guest_id":77,"reservation_id":101,"lease_id":null,'
                '"amount":"149.00","currency":"EUR","status":"open",'
                '"due_date":"2026-06-15"}}\n'
                "```\n\n"
                "**Example payload (`guest.checked_in`):** "
                "```json\n"
                '{"event":"guest.checked_in","occurred_at":"2026-05-05T08:00:00+00:00",'
                '"organization_id":1,"data":{"reservation_id":101,"check_in_id":88,'
                '"guest_id":77,"checked_in_at":"2026-05-05T08:00:00+00:00"}}\n'
                "```\n\n"
                "**Example payload (`maintenance.requested`):** "
                "```json\n"
                '{"event":"maintenance.requested","occurred_at":"2026-05-05T08:00:00+00:00",'
                '"organization_id":1,"data":{"request_id":9001,"property_id":3,"unit_id":12,'
                '"reservation_id":101,"guest_id":77,"status":"new","priority":"normal"}}\n'
                "```\n\n"
                "Use the same HMAC-SHA256 verification mechanism for outbound signatures as inbound. "
                "The secret is returned once when creating the webhook subscription."
            )
        },
    )

    spec.components.security_scheme(
        "ApiKeyAuth",
        {
            "type": "apiKey",
            "in": "header",
            "name": "X-API-Key",
            "description": ("You may also use `Authorization: Bearer pms_<key>`."),
        },
    )

    spec.components.schema(
        "WebhookSubscription",
        {
            "type": "object",
            "properties": {
                "id": {"type": "integer"},
                "organization_id": {"type": "integer"},
                "url": {"type": "string"},
                "events": {"type": "array", "items": {"type": "string"}},
                "is_active": {"type": "boolean"},
                "failure_count": {"type": "integer"},
                "last_delivery_status": {"type": "integer", "nullable": True},
                "created_at": {"type": "string", "format": "date-time"},
                "updated_at": {"type": "string", "format": "date-time"},
                "secret": {
                    "type": "string",
                    "description": "Returned only once on POST /webhooks/subscriptions.",
                    "nullable": True,
                },
            },
        },
    )

    # Flask stores dynamic params as `<int:id>`; OpenAPI expects `{id}` with schema.
    for rule in sorted(current_app.url_map.iter_rules(), key=lambda r: r.rule):
        if not rule.rule.startswith("/api/v1/"):
            continue
        if rule.endpoint == "static":
            continue

        path = rule.rule
        for argument in rule.arguments:
            path = path.replace(f"<int:{argument}>", f"{{{argument}}}")
            path = path.replace(f"<{argument}>", f"{{{argument}}}")

        parameters = [
            {
                "name": arg,
                "in": "path",
                "required": True,
                "schema": {"type": "integer" if f"<int:{arg}>" in rule.rule else "string"},
            }
            for arg in sorted(rule.arguments)
        ]

        operations: dict[str, dict] = {}
        for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
            operation = {
                "operationId": f"{rule.endpoint}.{method.lower()}",
                "responses": {
                    "200": {"description": "Successful response"},
                    "400": {"description": "Validation error"},
                    "401": {"description": "Unauthorized"},
                    "403": {"description": "Forbidden"},
                },
            }
            if parameters:
                operation["parameters"] = parameters
            if method in {"POST", "PATCH", "PUT"}:
                operation["requestBody"] = {
                    "required": False,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                }
            if rule.endpoint not in {"api.api_health", "webhooks.inbound_webhook"}:
                operation["security"] = [{"ApiKeyAuth": []}]
            operations[method.lower()] = operation

        spec.path(path=path, operations=operations)

    return spec.to_dict()


@api_bp.get("/openapi.json")
@require_api_key
@scope_required("reports:read")
def openapi_spec():
    return jsonify(_build_openapi_spec())


@api_bp.get("/docs")
@require_api_key
@scope_required("reports:read")
def swagger_ui():
    return render_template_string("""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Pin PMS API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css" />
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.ui = SwaggerUIBundle({
        url: "/api/v1/openapi.json",
        dom_id: "#swagger-ui",
        deepLinking: true,
        persistAuthorization: true,
      });
    </script>
  </body>
</html>
        """)
