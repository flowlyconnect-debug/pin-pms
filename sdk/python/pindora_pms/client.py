from __future__ import annotations

from typing import Any

import requests

from .exceptions import PMSAPIError
from .resources.invoices import InvoicesResource
from .resources.reservations import ReservationsResource

DEFAULT_BASE_URL = "http://127.0.0.1:5000"


class PMSClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.reservations = ReservationsResource(self)
        self.invoices = InvoicesResource(self)

    def _request(self, method: str, path: str, *, params=None, json=None) -> Any:
        response = requests.request(
            method,
            f"{self.base_url}/api/v1{path}",
            headers={"Authorization": f"Bearer {self.api_key}"},
            params=params,
            json=json,
            timeout=20,
        )
        payload = response.json()
        if not response.ok:
            error = payload.get("error") or {}
            raise PMSAPIError(response.status_code, error.get("code", "api_error"), error.get("message", ""))
        return payload.get("data")
