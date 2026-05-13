"""Testit asiakaspalautteen korjauksille:

1. Yläpalkin iso otsikko vaihtuu sivun mukaan; pientä "Hallinta · …"
   -breadcrumb-riviä ei enää renderöidä.
2. Kohteet → Huoneet → Muokkaa -näkymä ei enää palauta 500-virhettä myöskään
   silloin kun huoneella on Decimal-arvo (esim. ``area_sqm``).
"""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.properties.models import Property, Unit


def _login(client, *, email: str, password: str):
    return client.post("/login", data={"email": email, "password": password})


# ---------------------------------------------------------------------------
# 1. Yläpalkin otsikkologiikka
# ---------------------------------------------------------------------------


def test_topbar_breadcrumb_does_not_duplicate_hallinta_on_dashboard(client, admin_user):
    """Etusivulla otsikko on 'Hallintapaneeli'; ylimääräistä murupolku-riviä ei ole."""

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/dashboard", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert "Hallintapaneeli" in html
    assert 'class="admin-topbar-breadcrumb"' not in html


def test_topbar_title_changes_on_properties_list(client, admin_user):
    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/properties", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Page title -block renderöityy topbarin title-paikalle
    assert 'class="admin-topbar-title">Kohteet<' in html
    assert 'class="admin-topbar-breadcrumb"' not in html


def test_topbar_title_changes_on_units_edit(client, admin_user):
    """Huoneen muokkausnäkymässä yläpalkki näyttää 'Muokkaa huonetta'."""

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(
        organization_id=admin_user.organization_id, name="Topbar-koti", address=None
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="TB-1", unit_type="std")
    db.session.add(unit)
    db.session.commit()

    response = client.get(f"/admin/units/{unit.id}/edit", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'class="admin-topbar-title">Muokkaa huonetta<' in html
    assert 'class="admin-topbar-breadcrumb"' not in html


def test_topbar_title_for_dashboard_does_not_duplicate(client, admin_user):
    """Sanity check: dashboard ei renderöi vanhaa murupolku-elementtiä."""

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    response = client.get("/admin/dashboard", follow_redirects=False)
    html = response.get_data(as_text=True)
    assert 'class="admin-topbar-breadcrumb"' not in html


# ---------------------------------------------------------------------------
# 2. Huoneen muokkausnäkymän 500-virhe Decimaalisilla arvoilla
# ---------------------------------------------------------------------------


def test_unit_edit_page_loads_when_area_sqm_is_set(client, admin_user):
    """Aiemmin: ``str(Decimal('12.50'))`` virtasi WTForms DecimalFieldin
    ``_value()``-koodipolulle, jossa ``'%.2f' % '12.50'`` heitti TypeErrorin
    ja sivu palautti 500. Nyt service-kerroksen Decimal-stringit muunnetaan
    takaisin Decimaleiksi ennen lomakkeen alustusta."""

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(
        organization_id=admin_user.organization_id, name="Decimal Hotel", address=None
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(
        property_id=prop.id,
        name="D-1",
        unit_type="suite",
        area_sqm=Decimal("12.50"),
        floor=3,
        bedrooms=2,
        max_guests=4,
    )
    db.session.add(unit)
    db.session.commit()

    response = client.get(f"/admin/units/{unit.id}/edit", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    # Lomake renderöityy ja sisältää nykyisen pinta-alan
    assert 'name="area_sqm"' in html
    assert "12.50" in html
    assert "Muokkaa huonetta" in html


def test_unit_edit_page_loads_when_area_sqm_is_none(client, admin_user):
    """Tyhjälläkin pinta-alalla muokkaussivun tulee latautua ilman 500-virhettä."""

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(
        organization_id=admin_user.organization_id, name="None Hotel", address=None
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="N-1", unit_type=None, area_sqm=None)
    db.session.add(unit)
    db.session.commit()

    response = client.get(f"/admin/units/{unit.id}/edit", follow_redirects=False)
    assert response.status_code == 200


def test_property_edit_page_loads_when_latitude_longitude_are_set(client, admin_user):
    """Sama bugi piili PropertyForm.latitude/longitude-kentissä. Tämä testi
    suojaa regressiolta."""

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(
        organization_id=admin_user.organization_id,
        name="GPS-koti",
        address=None,
        latitude=Decimal("60.1234567"),
        longitude=Decimal("24.7654321"),
    )
    db.session.add(prop)
    db.session.commit()

    response = client.get(f"/admin/properties/{prop.id}/edit", follow_redirects=False)
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'name="latitude"' in html
    assert 'name="longitude"' in html


def test_unit_edit_post_still_persists_changes(client, admin_user):
    """Korjaus ei saa rikkoa POST-tallennusta."""

    _login(client, email=admin_user.email, password=admin_user.password_plain)
    prop = Property(
        organization_id=admin_user.organization_id, name="Post Hotel", address=None
    )
    db.session.add(prop)
    db.session.flush()
    unit = Unit(property_id=prop.id, name="P-1", area_sqm=Decimal("10.00"))
    db.session.add(unit)
    db.session.commit()

    response = client.post(
        f"/admin/units/{unit.id}/edit",
        data={
            "name": "P-1 päivitetty",
            "area_sqm": "20.25",
            "unit_type": "suite",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    refreshed = Unit.query.get(unit.id)
    assert refreshed is not None
    assert refreshed.name == "P-1 päivitetty"
    assert refreshed.area_sqm == Decimal("20.25")
