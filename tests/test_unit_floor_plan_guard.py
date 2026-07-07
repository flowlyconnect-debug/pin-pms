from __future__ import annotations


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def test_unit_edit_preserves_floor_plan_image_id_when_field_empty(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, PropertyImage, Unit
    from app.storage import get_url as storage_get_url

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Floor Plan Prop")
    db.session.add(prop)
    db.session.flush()
    key = f"org-{admin_user.organization_id}/property-{prop.id}/plan.jpg"
    image = PropertyImage(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        url=storage_get_url(key),
        thumbnail_url=storage_get_url(f"{key[:-4]}-thumb.jpg"),
        storage_key=key,
        thumbnail_storage_key=f"{key[:-4]}-thumb.jpg",
        alt_text="Plan",
        sort_order=1,
        file_size=100,
        content_type="image/jpeg",
        uploaded_by=None,
    )
    db.session.add(image)
    db.session.flush()
    unit = Unit(
        property_id=prop.id,
        name="101",
        unit_type="studio",
        floor_plan_image_id=image.id,
    )
    db.session.add(unit)
    db.session.commit()

    response = client.post(
        f"/admin/units/{unit.id}/edit",
        data={"name": "101 updated", "unit_type": "studio"},
        follow_redirects=True,
    )
    assert response.status_code == 200

    refreshed = Unit.query.get(unit.id)
    assert refreshed is not None
    assert refreshed.name == "101 updated"
    assert refreshed.floor_plan_image_id == image.id


def test_unit_edit_can_clear_floor_plan_image_id_with_checkbox(client, admin_user):
    from app.extensions import db
    from app.properties.models import Property, PropertyImage, Unit
    from app.storage import get_url as storage_get_url

    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Clear Plan Prop")
    db.session.add(prop)
    db.session.flush()
    key = f"org-{admin_user.organization_id}/property-{prop.id}/clear.jpg"
    image = PropertyImage(
        organization_id=admin_user.organization_id,
        property_id=prop.id,
        url=storage_get_url(key),
        thumbnail_url=storage_get_url(f"{key[:-4]}-thumb.jpg"),
        storage_key=key,
        thumbnail_storage_key=f"{key[:-4]}-thumb.jpg",
        alt_text="Clear",
        sort_order=1,
        file_size=100,
        content_type="image/jpeg",
        uploaded_by=None,
    )
    db.session.add(image)
    db.session.flush()
    unit = Unit(
        property_id=prop.id,
        name="102",
        unit_type="studio",
        floor_plan_image_id=image.id,
    )
    db.session.add(unit)
    db.session.commit()

    response = client.post(
        f"/admin/units/{unit.id}/edit",
        data={
            "name": "102",
            "unit_type": "studio",
            "clear_floor_plan_image": "y",
        },
        follow_redirects=True,
    )
    assert response.status_code == 200

    refreshed = Unit.query.get(unit.id)
    assert refreshed is not None
    assert refreshed.floor_plan_image_id is None
