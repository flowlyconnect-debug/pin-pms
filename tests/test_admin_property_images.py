from __future__ import annotations

import re
from io import BytesIO

import pytest
from PIL import Image

from app.extensions import db
from app.properties.models import Property, PropertyImage


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _extract_csrf(html: str) -> str:
    match = re.search(r'name="csrf_token"\s+value="([^"]+)"', html)
    if not match:
        raise AssertionError("CSRF token not found in form")
    return match.group(1)


def _jpeg_bytes() -> bytes:
    img = Image.new("RGB", (400, 300), color=(80, 120, 200))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _seed_property(admin_user) -> Property:
    prop = Property(organization_id=admin_user.organization_id, name="Gallery Prop", address=None)
    db.session.add(prop)
    db.session.commit()
    return prop


def test_property_images_upload_with_csrf(client, app, admin_user):
    app.config["STORAGE_BACKEND"] = "local"
    app.config["STORAGE_LOCAL_ROOT"] = str(app.instance_path) + "/test_admin_property_images"

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = _seed_property(admin_user)

    app.config["WTF_CSRF_ENABLED"] = True
    page = client.get(f"/admin/properties/{prop.id}/images")
    assert page.status_code == 200
    page_html = page.get_data(as_text=True)
    assert 'enctype="multipart/form-data"' in page_html
    assert 'name="csrf_token"' in page_html
    assert 'name="image"' in page_html
    csrf = _extract_csrf(page_html)

    response = client.post(
        f"/admin/properties/{prop.id}/images",
        data={
            "csrf_token": csrf,
            "alt_text": "Parveke",
            "image": (BytesIO(_jpeg_bytes()), "balcony.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"CSRF token is missing" not in response.data

    row = PropertyImage.query.filter_by(property_id=prop.id).first()
    assert row is not None
    assert row.alt_text == "Parveke"


def test_property_images_page_shows_10mb_limit(client, app, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = _seed_property(admin_user)

    page = client.get(f"/admin/properties/{prop.id}/images")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "max 10 MB" in html
    assert 'accept="image/jpeg,image/png,image/webp"' in html


def test_property_images_upload_jpeg_extension(client, app, admin_user):
    app.config["STORAGE_BACKEND"] = "local"
    app.config["STORAGE_LOCAL_ROOT"] = str(app.instance_path) + "/test_admin_property_images"

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = _seed_property(admin_user)

    app.config["WTF_CSRF_ENABLED"] = True
    page = client.get(f"/admin/properties/{prop.id}/images")
    csrf = _extract_csrf(page.get_data(as_text=True))

    response = client.post(
        f"/admin/properties/{prop.id}/images",
        data={
            "csrf_token": csrf,
            "alt_text": "Terassi",
            "image": (BytesIO(_jpeg_bytes()), "terrace.jpeg", "image/jpeg"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    row = PropertyImage.query.filter_by(property_id=prop.id).first()
    assert row is not None
    assert row.alt_text == "Terassi"


def test_property_images_upload_rejects_over_10mb(client, app, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = _seed_property(admin_user)

    app.config["WTF_CSRF_ENABLED"] = True
    page = client.get(f"/admin/properties/{prop.id}/images")
    csrf = _extract_csrf(page.get_data(as_text=True))

    oversized = b"\xff\xd8\xff" + (b"\x00" * (10 * 1024 * 1024 + 1))
    response = client.post(
        f"/admin/properties/{prop.id}/images",
        data={
            "csrf_token": csrf,
            "alt_text": "Liian iso",
            "image": (BytesIO(oversized), "huge.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
        follow_redirects=True,
    )
    assert response.status_code == 200
    assert b"Image exceeds 10 MB limit." in response.data
    assert PropertyImage.query.filter_by(property_id=prop.id).count() == 0


def test_property_images_upload_rejected_without_csrf(client, app, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = _seed_property(admin_user)

    app.config["WTF_CSRF_ENABLED"] = True
    response = client.post(
        f"/admin/properties/{prop.id}/images",
        data={
            "alt_text": "Ei tokenia",
            "image": (BytesIO(_jpeg_bytes()), "skip.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code in (400, 403)
