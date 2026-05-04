from __future__ import annotations

from typing import Any

import requests
from flask import current_app

from app.core.telemetry import trace_http_call
from app.webhooks.signature import verify_hmac_sha256_hex


class PindoraLockClient:
    def __init__(self, *, base_url: str, api_key: str, timeout_seconds: int = 10):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls) -> "PindoraLockClient":
        return cls(
            base_url=current_app.config.get("PINDORA_LOCK_BASE_URL", ""),
            api_key=current_app.config.get("PINDORA_LOCK_API_KEY", ""),
            timeout_seconds=int(current_app.config.get("PINDORA_LOCK_TIMEOUT_SECONDS", 10)),
        )

    def create_access_code(
        self,
        *,
        provider_device_id: str,
        code: str,
        valid_from_iso: str,
        valid_until_iso: str,
    ) -> dict[str, Any]:
        self._ensure_enabled()
        # Placeholder endpoint path; replace once vendor docs are confirmed.
        return self._request(
            "POST",
            f"/devices/{provider_device_id}/codes",
            json_payload={
                "code": code,
                "valid_from": valid_from_iso,
                "valid_until": valid_until_iso,
            },
        )

    def revoke_access_code(
        self, *, provider_device_id: str, provider_code_id: str
    ) -> dict[str, Any]:
        self._ensure_enabled()
        # Placeholder endpoint path; replace once vendor docs are confirmed.
        return self._request("DELETE", f"/devices/{provider_device_id}/codes/{provider_code_id}")

    def verify_webhook_signature(self, *, payload: bytes, signature: str) -> bool:
        secret = (current_app.config.get("PINDORA_LOCK_WEBHOOK_SECRET") or "").strip()
        if not secret:
            try:
                from app.webhooks.services import get_inbound_webhook_secret

                secret = get_inbound_webhook_secret("pindora_lock")
            except Exception:  # noqa: BLE001
                secret = ""
        return verify_hmac_sha256_hex(
            secret=secret,
            payload_bytes=payload,
            signature_header=signature or "",
        )

    def _request(
        self, method: str, path: str, json_payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = trace_http_call(
            "pindora_lock.request",
            requests.request,
            method=method,
            url=f"{self.base_url}{path}",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json=json_payload,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        body = response.json() if response.content else {}
        return body if isinstance(body, dict) else {"data": body}

    def _ensure_enabled(self) -> None:
        if not self.base_url or not self.api_key:
            raise RuntimeError("Pindora lock integration is not configured.")
