from __future__ import annotations

from pindora_pms import PMSClient


def test_client_exposes_resources():
    client = PMSClient("pms_test")
    assert client.reservations is not None
    assert client.invoices is not None
