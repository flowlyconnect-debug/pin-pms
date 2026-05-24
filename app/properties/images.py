from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from io import BytesIO

from urllib.parse import quote

from flask import current_app
from PIL import Image

from app.extensions import db
from app.properties.models import Property, PropertyImage
from app.storage import delete as storage_delete
from app.storage import get_url as storage_get_url
from app.storage import upload as storage_upload

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp"})
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_WIDTH = 800
MAX_HEIGHT = 600
THUMB_WIDTH = 400
THUMB_HEIGHT = 300


@dataclass
class PropertyImageError(Exception):
    code: str
    message: str
    status: int


def _assert_property_for_org(*, organization_id: int, property_id: int) -> Property:
    row = Property.query.filter_by(id=property_id, organization_id=organization_id).first()
    if row is None:
        raise PropertyImageError("not_found", "Property not found.", 404)
    return row


def _validate_filename_extension(filename: str | None) -> None:
    if not filename:
        return
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise PropertyImageError(
            "validation_error",
            "Only JPG, JPEG, PNG and WebP files are allowed.",
            400,
        )


def _process_image(raw: bytes, content_type: str) -> tuple[bytes, bytes, str]:
    if content_type not in ALLOWED_CONTENT_TYPES:
        if content_type == "image/svg+xml":
            raise PropertyImageError("validation_error", "SVG uploads are not allowed.", 400)
        raise PropertyImageError("validation_error", "Only WebP, JPEG and PNG are supported.", 400)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PropertyImageError("validation_error", "Image exceeds 10 MB limit.", 400)

    try:
        img = Image.open(BytesIO(raw))
        img.verify()
        img = Image.open(BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        raise PropertyImageError("validation_error", "Invalid image file.", 400) from exc

    if img.mode not in {"RGB", "RGBA"}:
        img = img.convert("RGB")

    base = img.copy()
    base.thumbnail((MAX_WIDTH, MAX_HEIGHT))
    thumb = img.copy()
    thumb.thumbnail((THUMB_WIDTH, THUMB_HEIGHT))

    ext = (
        "webp"
        if content_type == "image/webp"
        else ("png" if content_type == "image/png" else "jpg")
    )
    save_format = "WEBP" if ext == "webp" else ("PNG" if ext == "png" else "JPEG")

    base_bytes = BytesIO()
    thumb_bytes = BytesIO()
    save_kwargs = {"optimize": True}
    if save_format in {"JPEG", "WEBP"}:
        save_kwargs["quality"] = 82
    base.save(base_bytes, format=save_format, **save_kwargs)
    thumb.save(thumb_bytes, format=save_format, **save_kwargs)

    if base_bytes.tell() > MAX_UPLOAD_BYTES:
        raise PropertyImageError("validation_error", "Optimized image still exceeds 10 MB.", 400)

    return base_bytes.getvalue(), thumb_bytes.getvalue(), ext


def _cdn_invalidate(urls: list[str]) -> None:
    if not current_app.config.get("CDN_ENABLED"):
        return
    # Placeholder hook; provider-specific purge API is environment-dependent.
    current_app.logger.info("cdn_invalidate_requested", extra={"count": len(urls), "urls": urls})


def uses_admin_image_proxy() -> bool:
    """Local storage without a public base URL must be served via admin session."""

    backend = (current_app.config.get("STORAGE_BACKEND") or "local").strip().lower()
    if backend != "local":
        return False
    return not (current_app.config.get("STORAGE_PUBLIC_BASE_URL") or "").strip()


def browser_image_url(*, storage_key: str) -> str:
    """URL suitable for ``<img src>`` in logged-in admin HTML."""

    if uses_admin_image_proxy():
        return f"/admin/property-images/{quote(storage_key.lstrip('/'), safe='/')}"
    return storage_get_url(storage_key)


def serialize_cover_image(row: PropertyImage) -> dict:
    return serialize_property_image_for_admin(row)


def serialize_property_image_for_admin(row: PropertyImage) -> dict:
    return {
        "id": row.id,
        "property_id": row.property_id,
        "url": row.url,
        "thumbnail_url": row.thumbnail_url,
        "url_src": browser_image_url(storage_key=row.storage_key),
        "thumbnail_src": browser_image_url(storage_key=row.thumbnail_storage_key),
        "alt_text": row.alt_text,
        "sort_order": row.sort_order,
        "content_type": row.content_type,
        "file_size": row.file_size,
    }


def pick_cover_image(rows: list[PropertyImage]) -> PropertyImage | None:
    if not rows:
        return None
    return min(rows, key=lambda row: (row.sort_order, row.id))


def get_cover_image(*, organization_id: int, property_id: int) -> dict | None:
    rows = list_property_images(organization_id=organization_id, property_id=property_id)
    cover = pick_cover_image(rows)
    return serialize_cover_image(cover) if cover is not None else None


def get_cover_images_for_properties(
    *, organization_id: int, property_ids: list[int]
) -> dict[int, dict]:
    """Return cover image payloads keyed by property_id (one DB query)."""

    if not property_ids:
        return {}
    rows = (
        PropertyImage.query.filter(
            PropertyImage.organization_id == organization_id,
            PropertyImage.property_id.in_(property_ids),
        )
        .order_by(
            PropertyImage.property_id.asc(),
            PropertyImage.sort_order.asc(),
            PropertyImage.id.asc(),
        )
        .all()
    )
    covers: dict[int, dict] = {}
    for row in rows:
        if row.property_id not in covers:
            covers[row.property_id] = serialize_cover_image(row)
    return covers


def set_cover_image(*, organization_id: int, property_id: int, image_id: int) -> None:
    rows = list_property_images(organization_id=organization_id, property_id=property_id)
    by_id = {row.id: row for row in rows}
    if image_id not in by_id:
        raise PropertyImageError("not_found", "Image not found.", 404)
    ids = [image_id] + [row.id for row in rows if row.id != image_id]
    reorder_property_images(organization_id=organization_id, property_id=property_id, ids=ids)


def move_property_image(
    *,
    organization_id: int,
    property_id: int,
    image_id: int,
    direction: str,
) -> None:
    rows = list_property_images(organization_id=organization_id, property_id=property_id)
    ids = [row.id for row in rows]
    if image_id not in ids:
        raise PropertyImageError("not_found", "Image not found.", 404)
    idx = ids.index(image_id)
    if direction == "up" and idx > 0:
        ids[idx - 1], ids[idx] = ids[idx], ids[idx - 1]
    elif direction == "down" and idx < len(ids) - 1:
        ids[idx + 1], ids[idx] = ids[idx], ids[idx + 1]
    else:
        return
    reorder_property_images(organization_id=organization_id, property_id=property_id, ids=ids)


def list_property_images(*, organization_id: int, property_id: int) -> list[PropertyImage]:
    _assert_property_for_org(organization_id=organization_id, property_id=property_id)
    return (
        PropertyImage.query.filter_by(organization_id=organization_id, property_id=property_id)
        .order_by(PropertyImage.sort_order.asc(), PropertyImage.id.asc())
        .all()
    )


def upload_property_image(
    *,
    organization_id: int,
    property_id: int,
    raw: bytes,
    content_type: str,
    alt_text: str,
    uploaded_by: int | None,
    filename: str | None = None,
) -> PropertyImage:
    _assert_property_for_org(organization_id=organization_id, property_id=property_id)
    _validate_filename_extension(filename)
    alt_clean = (alt_text or "").strip()
    if not alt_clean:
        raise PropertyImageError("validation_error", "alt_text is required.", 400)
    processed, thumb, ext = _process_image(raw, content_type)
    next_order = (
        db.session.query(db.func.max(PropertyImage.sort_order))
        .filter_by(organization_id=organization_id, property_id=property_id)
        .scalar()
        or 0
    )
    token = secrets.token_hex(12)
    key = f"org-{organization_id}/property-{property_id}/{token}.{ext}"
    thumb_key = f"org-{organization_id}/property-{property_id}/{token}-thumb.{ext}"
    storage_upload(file_bytes=processed, key=key, content_type=content_type)
    storage_upload(file_bytes=thumb, key=thumb_key, content_type=content_type)
    row = PropertyImage(
        organization_id=organization_id,
        property_id=property_id,
        url=storage_get_url(key),
        thumbnail_url=storage_get_url(thumb_key),
        storage_key=key,
        thumbnail_storage_key=thumb_key,
        alt_text=alt_clean,
        sort_order=next_order + 1,
        file_size=len(processed),
        content_type=content_type,
        uploaded_by=uploaded_by,
    )
    db.session.add(row)
    db.session.commit()
    _cdn_invalidate([row.url, row.thumbnail_url])
    return row


def delete_property_image(*, organization_id: int, property_id: int, image_id: int) -> bool:
    _assert_property_for_org(organization_id=organization_id, property_id=property_id)
    row = PropertyImage.query.filter_by(
        id=image_id, organization_id=organization_id, property_id=property_id
    ).first()
    if row is None:
        raise PropertyImageError("not_found", "Image not found.", 404)
    storage_delete(row.storage_key)
    storage_delete(row.thumbnail_storage_key)
    urls = [row.url, row.thumbnail_url]
    db.session.delete(row)
    db.session.commit()
    _cdn_invalidate(urls)
    return True


def reorder_property_images(*, organization_id: int, property_id: int, ids: list[int]) -> None:
    rows = list_property_images(organization_id=organization_id, property_id=property_id)
    by_id = {row.id: row for row in rows}
    if set(ids) != set(by_id.keys()):
        raise PropertyImageError("validation_error", "Image sort payload is invalid.", 400)
    for idx, image_id in enumerate(ids, start=1):
        by_id[image_id].sort_order = idx
    db.session.commit()
