from __future__ import annotations

from datetime import date
from io import BytesIO

from PIL import Image


def _portal_login(client, *, email: str, password: str):
    return client.post(
        "/portal/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def _jpeg_bytes() -> bytes:
    img = Image.new("RGB", (120, 90), color=(40, 120, 200))
    buf = BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_portal_reservation_uses_portal_image_src_not_api(client, app, admin_user, regular_user):
    from app.extensions import db
    from app.properties import images as image_service
    from app.properties.models import Property, PropertyImage, Unit
    from app.reservations.models import Reservation
    from app.storage.local import LocalStorage

    app.config["STORAGE_BACKEND"] = "local"
    app.config["STORAGE_PUBLIC_BASE_URL"] = ""
    root = str(app.instance_path) + "/test_portal_property_images"
    app.config["STORAGE_LOCAL_ROOT"] = root

    prop = Property(organization_id=admin_user.organization_id, name="Portal Image Prop")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="P1", unit_type="double")
    db.session.add(unit)
    db.session.flush()
    reservation = Reservation(
        unit_id=unit.id,
        guest_id=regular_user.id,
        guest_name=regular_user.email,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 4),
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()

    image_service.upload_property_image(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        raw=_jpeg_bytes(),
        content_type="image/jpeg",
        alt_text="Nakyma",
        uploaded_by=admin_user.id,
        filename="view.jpg",
    )

    image_row = PropertyImage.query.filter_by(property_id=prop.id).first()
    assert image_row is not None

    _portal_login(client, email=regular_user.email, password=regular_user.password_plain)
    detail = client.get(f"/portal/reservations/{reservation.id}")
    assert detail.status_code == 200
    html = detail.get_data(as_text=True)
    assert "/portal/property-images/" in html
    assert f"reservation={reservation.id}" in html
    assert "/api/v1/property-images/" not in html

    thumb_name = image_row.thumbnail_storage_key.split("/")[-1]
    img_response = client.get(
        f"/portal/property-images/{image_row.thumbnail_storage_key}"
        f"?reservation={reservation.id}"
    )
    assert img_response.status_code == 200
    assert img_response.mimetype == "image/jpeg"
    assert len(img_response.data) > 0
    assert LocalStorage().path_for_key(key=image_row.thumbnail_storage_key).exists()
    assert thumb_name in html


def test_portal_property_image_requires_login(client, app, admin_user, regular_user):
    from app.extensions import db
    from app.properties.models import Property, PropertyImage, Unit
    from app.reservations.models import Reservation
    from app.storage import get_url as storage_get_url

    app.config["STORAGE_BACKEND"] = "local"
    app.config["STORAGE_PUBLIC_BASE_URL"] = ""
    app.config["STORAGE_LOCAL_ROOT"] = str(app.instance_path) + "/test_portal_image_auth"

    prop = Property(organization_id=admin_user.organization_id, name="Auth Prop")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A1")
    db.session.add(unit)
    db.session.flush()
    key = f"org-{admin_user.organization_id}/property-{prop.id}/auth-thumb.jpg"
    db.session.add(
        PropertyImage(
            organization_id=admin_user.organization_id,
            property_id=prop.id,
            url=storage_get_url(key.replace("-thumb", "")),
            thumbnail_url=storage_get_url(key),
            storage_key=key.replace("-thumb", ""),
            thumbnail_storage_key=key,
            alt_text="Auth",
            sort_order=1,
            file_size=100,
            content_type="image/jpeg",
            uploaded_by=None,
        )
    )
    reservation = Reservation(
        unit_id=unit.id,
        guest_id=regular_user.id,
        guest_name=regular_user.email,
        start_date=date(2026, 9, 5),
        end_date=date(2026, 9, 7),
        status="confirmed",
    )
    db.session.add(reservation)
    db.session.commit()

    response = client.get(f"/portal/property-images/{key}?reservation={reservation.id}")
    assert response.status_code == 302
    assert "/portal/login" in response.headers["Location"]


def test_portal_property_image_denied_for_other_guest_reservation(client, app, regular_user):
    from werkzeug.security import generate_password_hash

    from app.extensions import db
    from app.properties.models import Property, PropertyImage, Unit
    from app.reservations.models import Reservation
    from app.storage import get_url as storage_get_url
    from app.users.models import User, UserRole

    app.config["STORAGE_BACKEND"] = "local"
    app.config["STORAGE_PUBLIC_BASE_URL"] = ""

    _portal_login(client, email=regular_user.email, password=regular_user.password_plain)

    prop = Property(organization_id=regular_user.organization_id, name="Denied Prop")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="D1")
    db.session.add(unit)
    db.session.flush()
    key = f"org-{regular_user.organization_id}/property-{prop.id}/denied-thumb.jpg"
    db.session.add(
        PropertyImage(
            organization_id=regular_user.organization_id,
            property_id=prop.id,
            url=storage_get_url(key.replace("-thumb", "")),
            thumbnail_url=storage_get_url(key),
            storage_key=key.replace("-thumb", ""),
            thumbnail_storage_key=key,
            alt_text="Denied",
            sort_order=1,
            file_size=100,
            content_type="image/jpeg",
            uploaded_by=None,
        )
    )
    other_user = User(
        email="other-portal-image@test.local",
        password_hash=generate_password_hash("UserPass123!"),
        organization_id=regular_user.organization_id,
        role=UserRole.USER.value,
        is_active=True,
    )
    db.session.add(other_user)
    db.session.flush()
    other_res = Reservation(
        unit_id=unit.id,
        guest_id=other_user.id,
        guest_name=other_user.email,
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        status="confirmed",
    )
    db.session.add(other_res)
    db.session.commit()

    response = client.get(f"/portal/property-images/{key}?reservation={other_res.id}")
    assert response.status_code == 404
