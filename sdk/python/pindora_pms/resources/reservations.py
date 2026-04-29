from __future__ import annotations


class ReservationsResource:
    def __init__(self, client):
        self.client = client

    def list(self, *, page: int = 1, per_page: int = 20):
        return self.client._request(
            "GET",
            "/reservations",
            params={"page": page, "per_page": per_page},
        )

    def create(self, **payload):
        return self.client._request("POST", "/reservations", json=payload)

    def get(self, reservation_id: int):
        return self.client._request("GET", f"/reservations/{reservation_id}")

    def cancel(self, reservation_id: int):
        return self.client._request("PATCH", f"/reservations/{reservation_id}/cancel")
