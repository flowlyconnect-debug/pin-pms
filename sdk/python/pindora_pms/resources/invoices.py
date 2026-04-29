from __future__ import annotations


class InvoicesResource:
    def __init__(self, client):
        self.client = client

    def list(self, *, page: int = 1, per_page: int = 20):
        return self.client._request(
            "GET",
            "/invoices",
            params={"page": page, "per_page": per_page},
        )

    def create(self, **payload):
        return self.client._request("POST", "/invoices", json=payload)

    def get(self, invoice_id: int):
        return self.client._request("GET", f"/invoices/{invoice_id}")
