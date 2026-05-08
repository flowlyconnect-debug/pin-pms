from __future__ import annotations

from io import BytesIO

from PIL import Image


def _image_bytes(
    *, fmt: str = "JPEG", size: tuple[int, int] = (1600, 1200), with_exif: bool = False
) -> bytes:
    img = Image.new("RGB", size, color=(120, 60, 200))
    buf = BytesIO()
    kwargs = {}
    if with_exif:
        exif = Image.Exif()
        exif[274] = 1
        kwargs["exif"] = exif
    img.save(buf, format=fmt, **kwargs)
    return buf.getvalue()


def _upload(
    client,
    api_key_raw: str,
    property_id: int,
    raw: bytes,
    filename: str,
    mimetype: str,
    alt_text: str,
):
    return client.post(
        f"/api/v1/properties/{property_id}/images",
        headers={"X-API-Key": api_key_raw},
        data={"alt_text": alt_text, "image": (BytesIO(raw), filename, mimetype)},
        content_type="multipart/form-data",
    )


def test_image_upload_strips_exif(client, app, api_key, regular_user):
    from app.extensions import db
    from app.properties.models import Property, PropertyImage
    from app.storage.local import LocalStorage

    app.config["STORAGE_BACKEND"] = "local"
    app.config["STORAGE_LOCAL_ROOT"] = str(app.instance_path) + "/test_property_images"
    prop = Property(
        organization_id=regular_user.organization_id, name="Exif Property", address=None
    )
    db.session.add(prop)
    db.session.commit()

    response = _upload(
        client,
        api_key.raw,
        prop.id,
        _image_bytes(with_exif=True),
        "sample.jpg",
        "image/jpeg",
        "Parvekkeen nakyma",
    )
    assert response.status_code == 201

    row = PropertyImage.query.filter_by(property_id=prop.id).first()
    assert row is not None
    path = LocalStorage().path_for_key(key=row.storage_key)
    saved = Image.open(path)
    assert len(saved.getexif()) == 0


def test_image_resize_max_dimensions(client, app, api_key, regular_user):
    from app.extensions import db
    from app.properties.models import Property, PropertyImage
    from app.storage.local import LocalStorage

    app.config["STORAGE_BACKEND"] = "local"
    app.config["STORAGE_LOCAL_ROOT"] = str(app.instance_path) + "/test_property_images_resize"
    prop = Property(
        organization_id=regular_user.organization_id, name="Resize Property", address=None
    )
    db.session.add(prop)
    db.session.commit()

    response = _upload(
        client,
        api_key.raw,
        prop.id,
        _image_bytes(size=(2800, 2100)),
        "large.jpg",
        "image/jpeg",
        "Iso olohuone",
    )
    assert response.status_code == 201

    row = PropertyImage.query.filter_by(property_id=prop.id).first()
    assert row is not None
    saved = Image.open(LocalStorage().path_for_key(key=row.storage_key))
    thumb = Image.open(LocalStorage().path_for_key(key=row.thumbnail_storage_key))
    assert saved.width <= 800
    assert saved.height <= 600
    assert thumb.width <= 200
    assert thumb.height <= 150


def test_image_only_org_can_upload(client, app, regular_user, api_key):
    from app.api.models import ApiKey
    from app.extensions import db
    from app.organizations.models import Organization
    from app.properties.models import Property
    from app.users.models import User, UserRole

    app.config["STORAGE_BACKEND"] = "local"
    other_org = Organization(name="Other Org")
    db.session.add(other_org)
    db.session.flush()
    other_user = User(
        email="other@test.local",
        password_hash=regular_user.password_hash,
        organization_id=other_org.id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_key, raw = ApiKey.issue(
        name="Other key",
        organization_id=other_org.id,
        user_id=other_user.id,
        scopes="properties:write,properties:read",
    )
    db.session.add(other_key)
    prop = Property(organization_id=regular_user.organization_id, name="Protected", address=None)
    db.session.add(prop)
    db.session.commit()
    _ = api_key

    response = _upload(client, raw, prop.id, _image_bytes(), "a.jpg", "image/jpeg", "Ei oikeuksia")
    assert response.status_code == 404


def test_image_delete_removes_from_storage(client, app, api_key, regular_user):
    from app.extensions import db
    from app.properties.models import Property, PropertyImage
    from app.storage.local import LocalStorage

    app.config["STORAGE_BACKEND"] = "local"
    app.config["STORAGE_LOCAL_ROOT"] = str(app.instance_path) + "/test_property_images_delete"
    prop = Property(
        organization_id=regular_user.organization_id, name="Delete Property", address=None
    )
    db.session.add(prop)
    db.session.commit()

    upload_resp = _upload(
        client, api_key.raw, prop.id, _image_bytes(), "del.jpg", "image/jpeg", "Poistettava kuva"
    )
    assert upload_resp.status_code == 201
    row = PropertyImage.query.filter_by(property_id=prop.id).first()
    assert row is not None
    storage = LocalStorage()
    main_path = storage.path_for_key(key=row.storage_key)
    thumb_path = storage.path_for_key(key=row.thumbnail_storage_key)
    assert main_path.exists()
    assert thumb_path.exists()

    delete_resp = client.delete(
        f"/api/v1/properties/{prop.id}/images/{row.id}",
        headers={"X-API-Key": api_key.raw},
    )
    assert delete_resp.status_code == 200
    assert not main_path.exists()
    assert not thumb_path.exists()


def test_svg_upload_rejected(client, app, api_key, regular_user):
    from app.extensions import db
    from app.properties.models import Property

    app.config["STORAGE_BACKEND"] = "local"
    prop = Property(organization_id=regular_user.organization_id, name="SVG Property", address=None)
    db.session.add(prop)
    db.session.commit()

    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><script>alert(1)</script></svg>"
    response = _upload(client, api_key.raw, prop.id, svg, "x.svg", "image/svg+xml", "SVG")
    assert response.status_code == 400
