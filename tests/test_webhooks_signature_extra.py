from __future__ import annotations

from app.webhooks.signature import hmac_sha256_hex_digest, verify_hmac_sha256_hex


def test_signature_helper_accepts_plain_and_v1_headers():
    body = b'{"ok":true}'
    secret = "sig-secret"
    sig = hmac_sha256_hex_digest(secret=secret, payload_bytes=body)
    assert verify_hmac_sha256_hex(secret=secret, payload_bytes=body, signature_header=sig) is True
    assert verify_hmac_sha256_hex(secret=secret, payload_bytes=body, signature_header=f"t=1,v1={sig}") is True
    assert verify_hmac_sha256_hex(secret=secret, payload_bytes=body, signature_header="bad") is False
    assert verify_hmac_sha256_hex(secret="", payload_bytes=body, signature_header=sig) is False

