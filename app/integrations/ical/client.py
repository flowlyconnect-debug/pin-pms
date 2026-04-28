from __future__ import annotations

import requests
from flask import current_app


class IcalClient:
    def __init__(self, *, timeout_seconds: int = 10):
        self.timeout_seconds = timeout_seconds

    @classmethod
    def from_config(cls) -> "IcalClient":
        return cls(
            timeout_seconds=int(current_app.config.get("ICAL_HTTP_TIMEOUT_SECONDS", 10)),
        )

    def fetch_calendar(self, *, source_url: str) -> bytes:
        response = requests.get(
            source_url,
            timeout=self.timeout_seconds,
            headers={"Accept": "text/calendar,text/plain;q=0.9,*/*;q=0.1"},
        )
        response.raise_for_status()
        return response.content

