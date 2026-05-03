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
                "Tenant data is never embedded in this document."
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
            if rule.endpoint not in {"api.api_health"}:
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
