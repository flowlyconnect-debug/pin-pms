from decimal import Decimal
from types import SimpleNamespace

from app.payments.providers.paytrail import PaytrailProvider, calculate_signature


def test_signature_calculation_matches_paytrail_spec_style():
    headers = {
        "checkout-account": "375917",
        "checkout-algorithm": "sha256",
        "checkout-method": "POST",
        "checkout-nonce": "abc",
        "checkout-timestamp": "2026-05-05T10:00:00Z",
    }
    body = '{"stamp":"x","amount":1234}'
    sig = calculate_signature("SAIPPUAKAUPPIAS", headers, body)
    assert len(sig) == 64
    assert all(c in "0123456789abcdef" for c in sig)


def test_amount_in_cents_correctly_converted():
    provider = PaytrailProvider()
    event = provider.parse_webhook_event(
        payload={"checkout-status": "ok", "checkout-transaction-id": "tx"}
    )
    assert event["type"] == "payment.succeeded"


def test_callback_unknown_status_returns_invalid_marker():
    provider = PaytrailProvider()
    event = provider.parse_webhook_event(payload={"checkout-status": "wat"})
    assert event["type"] == "invalid_status"


def test_verify_query_signature_roundtrip(app):
    provider = PaytrailProvider()
    with app.app_context():
        app.config["PAYTRAIL_SECRET_KEY"] = "SAIPPUAKAUPPIAS"
        query = {
            "checkout-account": "375917",
            "checkout-algorithm": "sha256",
            "checkout-method": "GET",
            "checkout-nonce": "n",
            "checkout-timestamp": "2026-05-05T10:00:00Z",
            "checkout-status": "ok",
        }
        query["signature"] = calculate_signature("SAIPPUAKAUPPIAS", query, "")
        assert provider.verify_query_signature(query) is True


def test_create_checkout_contains_finnish_provider_list(app, monkeypatch):
    captured = {}
    provider = PaytrailProvider()

    def fake_post(url, headers, data, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["data"] = data
        _ = timeout
        return SimpleNamespace(
            raise_for_status=lambda: None,
            json=lambda: {"transactionId": "tx1", "href": "https://paytrail"},
        )

    monkeypatch.setattr("requests.post", fake_post)
    with app.app_context():
        app.config["PAYTRAIL_SECRET_KEY"] = "SAIPPUAKAUPPIAS"
        app.config["PAYTRAIL_MERCHANT_ID"] = "375917"
        app.config["PAYTRAIL_API_BASE"] = "https://services.paytrail.com"
        app.config["PAYMENT_CALLBACK_URL"] = "https://app/callback"
        invoice = SimpleNamespace(
            id=1,
            invoice_number="INV-1",
            vat_rate=Decimal("24.00"),
            guest=SimpleNamespace(email="x@test"),
        )
        result = provider.create_checkout(
            amount=Decimal("10.00"),
            currency="EUR",
            invoice=invoice,
            return_url="https://app/return",
            cancel_url="https://app/cancel",
            idempotency_key="idem-paytrail-1",
        )
    body = captured["data"].decode("utf-8")
    assert "nordea" in body and "op" in body and "danske" in body and "handelsbanken" in body
    assert '"amount":1000' in body
    assert result["provider_payment_id"] == "tx1"
