from __future__ import annotations

from pathlib import Path

from flask import current_app


class LocalStorage:
    def _root(self) -> Path:
        custom = (current_app.config.get("STORAGE_LOCAL_ROOT") or "").strip()
        if custom:
            return Path(custom)
        return Path(current_app.instance_path) / "uploads" / "property_images"

    def upload(self, *, file_bytes: bytes, key: str, content_type: str) -> str:
        _ = content_type
        root = self._root()
        path = root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(file_bytes)
        return key

    def delete(self, *, key: str) -> None:
        path = self._root() / key
        if path.exists():
            path.unlink()

    def path_for_key(self, *, key: str) -> Path:
        return self._root() / key

    def get_url(self, *, key: str) -> str:
        base = (current_app.config.get("STORAGE_PUBLIC_BASE_URL") or "").strip()
        if base:
            return f"{base.rstrip('/')}/{key.lstrip('/')}"
        return f"/api/v1/property-images/{key.lstrip('/')}"
