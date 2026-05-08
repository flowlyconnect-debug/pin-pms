from __future__ import annotations

import secrets
from dataclasses import dataclass
from io import BytesIO

from flask import current_app
from PIL import Image

from app.extensions import db
from app.properties.models import Property, PropertyImage
from app.storage import delete as storage_delete
from app.storage import get_url as storage_get_url
from app.storage import upload as storage_upload

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024
MAX_WIDTH = 800
MAX_HEIGHT = 600
THUMB_WIDTH = 200
THUMB_HEIGHT = 150


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


def _process_image(raw: bytes, content_type: str) -> tuple[bytes, bytes, str]:
    if content_type not in ALLOWED_CONTENT_TYPES:
        if content_type == "image/svg+xml":
            raise PropertyImageError("validation_error", "SVG uploads are not allowed.", 400)
        raise PropertyImageError("validation_error", "Only WebP, JPEG and PNG are supported.", 400)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise PropertyImageError("validation_error", "Image exceeds 2 MB limit.", 400)

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
        raise PropertyImageError("validation_error", "Optimized image still exceeds 2 MB.", 400)

    return base_bytes.getvalue(), thumb_bytes.getvalue(), ext


def _cdn_invalidate(urls: list[str]) -> None:
    if not current_app.config.get("CDN_ENABLED"):
        return
    # Placeholder hook; provider-specific purge API is environment-dependent.
    current_app.logger.info("cdn_invalidate_requested", extra={"count": len(urls), "urls": urls})


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
) -> PropertyImage:
    _assert_property_for_org(organization_id=organization_id, property_id=property_id)
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
