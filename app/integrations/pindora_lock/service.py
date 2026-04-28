from __future__ import annotations

from app.integrations.pindora_lock import adapter
from app.integrations.pindora_lock.client import PindoraLockClient


class PindoraLockService:
    def __init__(self, client: PindoraLockClient | None = None):
        self.client = client or PindoraLockClient.from_config()

    def provision_access_code(
        self,
        *,
        provider_device_id: str,
        code: str,
        valid_from_iso: str,
        valid_until_iso: str,
    ) -> dict:
        payload = self.client.create_access_code(
            provider_device_id=provider_device_id,
            code=code,
            valid_from_iso=valid_from_iso,
            valid_until_iso=valid_until_iso,
        )
        return adapter.normalize_code_create(payload)

    def revoke_access_code(self, *, provider_device_id: str, provider_code_id: str) -> None:
        self.client.revoke_access_code(
            provider_device_id=provider_device_id,
            provider_code_id=provider_code_id,
        )
