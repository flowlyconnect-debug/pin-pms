from __future__ import annotations

from flask import current_app


class StorageError(Exception):
    pass


def _backend():
    name = (current_app.config.get("STORAGE_BACKEND") or "local").strip().lower()
    if name == "s3":
        from app.storage.s3 import S3Storage

        return S3Storage()
    from app.storage.local import LocalStorage

    return LocalStorage()


def upload(file_bytes: bytes, key: str, content_type: str) -> str:
    return _backend().upload(file_bytes=file_bytes, key=key, content_type=content_type)


def delete(key: str) -> None:
    _backend().delete(key=key)


def get_url(key: str) -> str:
    return _backend().get_url(key=key)
