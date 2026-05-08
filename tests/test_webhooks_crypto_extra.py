from __future__ import annotations

from cryptography.fernet import Fernet

from app.webhooks.crypto import decrypt_signing_secret, encrypt_signing_secret, webhook_fernet


def test_webhook_crypto_encrypt_decrypt_with_fallback(app):
    with app.app_context():
        app.config["CHECKIN_FERNET_KEY"] = ""
        token = encrypt_signing_secret("secret-value")
        assert decrypt_signing_secret(token) == "secret-value"
        assert webhook_fernet() is not None


def test_webhook_crypto_uses_configured_key(app):
    with app.app_context():
        app.config["CHECKIN_FERNET_KEY"] = Fernet.generate_key().decode("utf-8")
        token = encrypt_signing_secret("another-secret")
        assert decrypt_signing_secret(token) == "another-secret"
