from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.properties.models import Property, Unit


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


def test_admin_create_property_with_all_descriptive_fields(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    response = client.post(
        "/admin/properties/new",
        data={
            "name": "Katajanokka Suites",
            "address": "Kanavakatu 1",
            "street_address": "Kanavakatu 1 A",
            "postal_code": "00160",
            "city": "Helsinki",
            "latitude": "60.1675000",
            "longitude": "24.9631000",
            "year_built": "2002",
            "has_elevator": "y",
            "has_parking": "y",
            "has_sauna": "y",
            "has_courtyard": "",
            "has_air_conditioning": "y",
            "description": "Merellinen kohde keskustan tuntumassa.",
            "url": "https://example.com/katajanokka",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    row = Property.query.filter_by(
        organization_id=admin_user.organization_id,
        name="Katajanokka Suites",
    ).first()
    assert row is not None
    assert row.street_address == "Kanavakatu 1 A"
    assert row.postal_code == "00160"
    assert row.city == "Helsinki"
    assert row.latitude == Decimal("60.1675000")
    assert row.longitude == Decimal("24.9631000")
    assert row.year_built == 2002
    assert row.has_elevator is True
    assert row.has_parking is True
    assert row.has_sauna is True
    assert row.has_courtyard is False
    assert row.has_air_conditioning is True
    assert row.description == "Merellinen kohde keskustan tuntumassa."
    assert row.url == "https://example.com/katajanokka"


def test_admin_property_and_unit_edit_views_show_all_fields(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Kenttatesti", address="A")
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="A1", unit_type="studio")
    db.session.add(unit)
    db.session.commit()

    prop_edit = client.get(f"/admin/properties/{prop.id}/edit")
    unit_edit = client.get(f"/admin/units/{unit.id}/edit")
    assert prop_edit.status_code == 200
    assert unit_edit.status_code == 200

    prop_html = prop_edit.get_data(as_text=True)
    unit_html = unit_edit.get_data(as_text=True)

    for field_name in [
        "street_address",
        "postal_code",
        "city",
        "latitude",
        "longitude",
        "year_built",
        "has_elevator",
        "has_parking",
        "has_sauna",
        "has_courtyard",
        "has_air_conditioning",
        "description",
        "url",
    ]:
        assert f'name="{field_name}"' in prop_html

    for field_name in [
        "area_sqm",
        "floor",
        "bedrooms",
        "max_guests",
        "unit_type",
        "has_kitchen",
        "has_bathroom",
        "has_balcony",
        "has_terrace",
        "has_dishwasher",
        "has_washing_machine",
        "has_tv",
        "has_wifi",
        "description",
        "floor_plan_image_id",
    ]:
        assert f'name="{field_name}"' in unit_html


def test_admin_unit_area_sqm_validation(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(organization_id=admin_user.organization_id, name="Validointikohde", address=None)
    db.session.add(prop)
    db.session.commit()

    response = client.post(
        f"/admin/properties/{prop.id}/units/new",
        data={
            "name": "B2",
            "unit_type": "studio",
            "area_sqm": "10001",
            "floor": "2",
            "bedrooms": "1",
            "max_guests": "2",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Anna arvo väliltä 0–10000." in html
    row = Unit.query.filter_by(property_id=prop.id, name="B2").first()
    assert row is None


def test_admin_detail_booleans_render_as_kylla_ei(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)

    prop = Property(
        organization_id=admin_user.organization_id,
        name="Bool Kohde",
        has_elevator=True,
        has_parking=False,
        has_sauna=True,
        has_courtyard=False,
        has_air_conditioning=True,
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(
        property_id=prop.id,
        name="Bool Unit",
        has_kitchen=True,
        has_bathroom=False,
        has_balcony=True,
        has_terrace=False,
        has_dishwasher=True,
        has_washing_machine=False,
        has_tv=True,
        has_wifi=False,
    )
    db.session.add(unit)
    db.session.commit()

    prop_detail = client.get(f"/admin/properties/{prop.id}")
    unit_detail = client.get(f"/admin/units/{unit.id}")
    assert prop_detail.status_code == 200
    assert unit_detail.status_code == 200

    prop_html = prop_detail.get_data(as_text=True)
    unit_html = unit_detail.get_data(as_text=True)
    assert "Kyllä" in prop_html
    assert "Ei" in prop_html
    assert "Kyllä" in unit_html
    assert "Ei" in unit_html
    assert "True" not in prop_html
    assert "False" not in prop_html
    assert "True" not in unit_html
    assert "False" not in unit_html
