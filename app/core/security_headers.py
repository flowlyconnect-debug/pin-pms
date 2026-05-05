"""Baseline security headers — project brief section 10.

Centralised so :mod:`app.__init__` stays small and the policy lives in one
place. CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy and
Permissions-Policy are sent on every response. HSTS is sent only over
HTTPS (``request.is_secure`` or ``X-Forwarded-Proto: https``).

Authenticated HTML routes under ``/admin`` and ``/portal`` are pinned to
``Cache-Control: no-store`` so a shared proxy or a browser back button
cannot expose another user's screen.
"""

from __future__ import annotations

from secrets import token_urlsafe

from flask import Flask, g, request


def _build_csp(nonce: str) -> str:
    return (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        f"script-src 'self' 'nonce-{nonce}' https://cdn.jsdelivr.net; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )


def register_security_headers(app: Flask) -> None:
    """Attach the after_request hook that emits the headers."""

    @app.before_request
    def _generate_csp_nonce():
        g.csp_nonce = token_urlsafe(16)

    @app.after_request
    def _apply(response):
        nonce = getattr(g, "csp_nonce", "")
        csp = app.config.get("CONTENT_SECURITY_POLICY") or _build_csp(nonce)

        response.headers.setdefault("Content-Security-Policy", csp)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), microphone=(), camera=()",
        )

        forwarded_proto = (request.headers.get("X-Forwarded-Proto") or "").lower()
        if request.is_secure or forwarded_proto == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=63072000; includeSubDomains",
            )

        if response.mimetype == "text/html" and request.path.startswith(("/admin", "/portal")):
            response.headers.setdefault(
                "Cache-Control",
                "no-store, no-cache, must-revalidate, private",
            )

        return response
