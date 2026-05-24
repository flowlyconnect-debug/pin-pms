from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image
from sqlalchemy import event

from app.extensions import db
from app.properties import images as image_service
from app.properties.models import Property, PropertyImage, Unit
from app.storage import get_url as storage_get_url


@pytest.fixture
def query_counter():
    counter = {"count": 0, "statements": []}

    def _on_execute(conn, cursor, statement, parameters, context, executemany):
        if statement.strip().lower().startswith(("select", "with")):
            counter["count"] += 1
            counter["statements"].append(statement)

    def _attach():
        event.listen(db.engine, "before_cursor_execute", _on_execute)
        return db.engine

    yield counter, _attach

    try:
        event.remove(db.engine, "before_cursor_execute", _on_execute)
    except Exception:
        pass


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def _jpeg_bytes(*, size: tuple[int, int] = (600, 400)) -> bytes:
    img = Image.new("RGB", size, color=(90, 140, 210))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _configure_local_storage(app) -> None:
    app.config["STORAGE_BACKEND"] = "local"
    root = str(app.instance_path) + "/test_property_cover_images"
    app.config["STORAGE_LOCAL_ROOT"] = root
    app.config["STORAGE_PUBLIC_BASE_URL"] = "https://cdn.test.example/media"


def _seed_image(
    *,
    organization_id: int,
    property_id: int,
    sort_order: int,
    alt_text: str,
) -> PropertyImage:
    key = f"org-{organization_id}/property-{property_id}/img-{sort_order}.jpg"
    thumb_key = f"{key[:-4]}-thumb.jpg"
    row = PropertyImage(
        organization_id=organization_id,
        property_id=property_id,
        url=storage_get_url(key),
        thumbnail_url=storage_get_url(thumb_key),
        storage_key=key,
        thumbnail_storage_key=thumb_key,
        alt_text=alt_text,
        sort_order=sort_order,
        file_size=1024,
        content_type="image/jpeg",
        uploaded_by=None,
    )
    db.session.add(row)
    db.session.commit()
    return row


def test_pick_cover_image_uses_lowest_sort_order(app, admin_user):
    prop = Property(organization_id=admin_user.organization_id, name="Cover Sort", address=None)
    db.session.add(prop)
    db.session.commit()
    _seed_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        sort_order=3,
        alt_text="Kolmas",
    )
    cover_row = _seed_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        sort_order=1,
        alt_text="Ensimmäinen",
    )
    _seed_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        sort_order=2,
        alt_text="Toinen",
    )

    cover = image_service.get_cover_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
    )
    assert cover is not None
    assert cover["id"] == cover_row.id
    assert cover["alt_text"] == "Ensimmäinen"


def test_get_cover_image_returns_none_without_images(app, admin_user):
    prop = Property(organization_id=admin_user.organization_id, name="No Images", address=None)
    db.session.add(prop)
    db.session.commit()

    assert (
        image_service.get_cover_image(
            organization_id=admin_user.organization_id,
            property_id=prop.id,
        )
        is None
    )


def test_set_cover_image_moves_image_first(app, admin_user):
    prop = Property(organization_id=admin_user.organization_id, name="Set Cover", address=None)
    db.session.add(prop)
    db.session.commit()
    first = _seed_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        sort_order=1,
        alt_text="A",
    )
    second = _seed_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        sort_order=2,
        alt_text="B",
    )

    image_service.set_cover_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        image_id=second.id,
    )
    cover = image_service.get_cover_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
    )
    assert cover is not None
    assert cover["id"] == second.id

    rows = image_service.list_property_images(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
    )
    assert [row.id for row in rows] == [second.id, first.id]


def test_get_cover_images_for_properties_returns_first_per_property(app, admin_user):
    org_id = admin_user.organization_id
    props = [
        Property(organization_id=org_id, name=f"P{i}", address=None) for i in range(2)
    ]
    db.session.add_all(props)
    db.session.commit()
    for prop in props:
        _seed_image(
            organization_id=org_id,
            property_id=prop.id,
            sort_order=2,
            alt_text="Toinen",
        )
        _seed_image(
            organization_id=org_id,
            property_id=prop.id,
            sort_order=1,
            alt_text=f"Kansi {prop.id}",
        )

    covers = image_service.get_cover_images_for_properties(
        organization_id=org_id,
        property_ids=[p.id for p in props],
    )
    assert len(covers) == 2
    for prop in props:
        assert covers[prop.id]["alt_text"] == f"Kansi {prop.id}"


def test_cover_thumbnail_url_uses_storage_public_base(app, admin_user):
    _configure_local_storage(app)
    prop = Property(organization_id=admin_user.organization_id, name="URL Prop", address=None)
    db.session.add(prop)
    db.session.commit()
    row = _seed_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        sort_order=1,
        alt_text="URL",
    )

    cover = image_service.get_cover_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
    )
    assert cover is not None
    assert cover["thumbnail_url"].startswith("https://cdn.test.example/media/")
    assert row.thumbnail_storage_key.split("/")[-1] in cover["thumbnail_url"]


def test_properties_list_renders_cover_and_placeholder(client, app, admin_user):
    _configure_local_storage(app)
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    org_id = admin_user.organization_id

    with_cover = Property(organization_id=org_id, name="Kuvallinen", address="Katu 1")
    without = Property(organization_id=org_id, name="Kuvaton", address="Katu 2")
    db.session.add_all([with_cover, without])
    db.session.commit()
    _seed_image(
        organization_id=org_id,
        property_id=with_cover.id,
        sort_order=1,
        alt_text="Julkisivu",
    )

    page = client.get("/admin/properties")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "Kuvallinen" in html
    assert "Kuvaton" in html
    assert "Julkisivu" in html
    assert 'loading="lazy"' in html
    assert "property-card__placeholder" in html or "properties-list-table__placeholder" in html

    cards = client.get("/admin/properties?view=cards")
    assert cards.status_code == 200
    cards_html = cards.get_data(as_text=True)
    assert "property-card" in cards_html
    assert "Kuvallinen" in cards_html


def test_properties_detail_renders_gallery(client, app, admin_user):
    _configure_local_storage(app)
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(organization_id=admin_user.organization_id, name="Galleria", address=None)
    db.session.add(prop)
    db.session.commit()
    _seed_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        sort_order=1,
        alt_text="Iso kuva",
    )
    _seed_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        sort_order=2,
        alt_text="Pikkukuva",
    )

    page = client.get(f"/admin/properties/{prop.id}")
    assert page.status_code == 200
    html = page.get_data(as_text=True)
    assert "property-gallery" in html
    assert "Iso kuva" in html
    assert "data-gallery-url" in html
    assert "admin-property-gallery.js" in html
    assert "data-gallery-prev" in html
    assert "data-gallery-next" in html


def test_properties_list_cover_fetch_bounded_queries(app, admin_user, client, query_counter):
    _configure_local_storage(app)
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    org_id = admin_user.organization_id
    props = [
        Property(organization_id=org_id, name=f"List {i}", address=f"Osoite {i}") for i in range(5)
    ]
    db.session.add_all(props)
    db.session.commit()
    for prop in props:
        _seed_image(
            organization_id=org_id,
            property_id=prop.id,
            sort_order=1,
            alt_text=f"Alt {prop.id}",
        )
        db.session.add(
            Unit(property_id=prop.id, name=f"Huone {prop.id}", unit_type=None, max_guests=2)
        )
    db.session.commit()

    counter, attach = query_counter
    attach()
    counter["count"] = 0
    counter["statements"] = []
    response = client.get("/admin/properties")
    assert response.status_code == 200
    # Paginated list + cover batch + unit summary (bounded, not per-property N+1 for images).
    assert counter["count"] <= 12


def test_upload_generates_400px_thumbnail(client, app, api_key, regular_user):
    from app.storage.local import LocalStorage

    _configure_local_storage(app)
    prop = Property(
        organization_id=regular_user.organization_id, name="Thumb 400", address=None
    )
    db.session.add(prop)
    db.session.commit()

    response = client.post(
        f"/api/v1/properties/{prop.id}/images",
        headers={"X-API-Key": api_key.raw},
        data={
            "alt_text": "Leveä",
            "image": (BytesIO(_jpeg_bytes(size=(1200, 900))), "wide.jpg", "image/jpeg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 201

    row = PropertyImage.query.filter_by(property_id=prop.id).first()
    assert row is not None
    thumb = Image.open(LocalStorage().path_for_key(key=row.thumbnail_storage_key))
    assert thumb.width <= 400
    assert thumb.height <= 300
