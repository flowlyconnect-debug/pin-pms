from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import (
    BooleanField,
    DecimalField,
    IntegerField,
    PasswordField,
    SelectField,
    SelectMultipleField,
    StringField,
    TextAreaField,
)
from wtforms.fields import DateTimeLocalField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional, URL

from app.settings.models import SettingType
from app.api.models import ALLOWED_API_KEY_SCOPES
from app.users.models import UserRole


class UserCreateForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[DataRequired(), Email(), Length(max=255)],
    )
    role = SelectField(
        "Role",
        validators=[DataRequired()],
        choices=[(role.value, role.value) for role in UserRole],
    )
    organization_id = SelectField(
        "Organization",
        validators=[DataRequired(), NumberRange(min=1)],
        coerce=int,
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(), Length(min=12, max=255)],
    )


class UserEditForm(FlaskForm):
    role = SelectField(
        "Role",
        validators=[DataRequired()],
        choices=[(role.value, role.value) for role in UserRole],
    )
    organization_id = SelectField(
        "Organization",
        validators=[DataRequired(), NumberRange(min=1)],
        coerce=int,
    )
    password = PasswordField(
        "Password",
        validators=[Optional(), Length(min=12, max=255)],
    )
    is_active = BooleanField("Active")


class OrganizationForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(min=1, max=255)])


class ApiKeyForm(FlaskForm):
    name = StringField("Name", validators=[DataRequired(), Length(min=1, max=255)])
    organization_id = SelectField(
        "Organization",
        validators=[DataRequired(), NumberRange(min=1)],
        coerce=int,
    )
    user_id = SelectField("User", validators=[Optional()], coerce=int)
    scopes = SelectMultipleField(
        "Scopes",
        validators=[Optional()],
        choices=[(scope, scope) for scope in ALLOWED_API_KEY_SCOPES],
    )
    expires_at = DateTimeLocalField("Expires at", validators=[Optional()], format="%Y-%m-%dT%H:%M")


class EmailTemplateForm(FlaskForm):
    subject = StringField("Subject", validators=[DataRequired(), Length(min=1, max=255)])
    body_text = TextAreaField("Plain-text body", validators=[DataRequired(), Length(min=1)])
    body_html = TextAreaField("HTML body", validators=[Optional()])


class EmailTemplateTestSendForm(FlaskForm):
    to = StringField("Vastaanottajan sahkoposti", validators=[DataRequired(), Length(max=255)])


class SettingForm(FlaskForm):
    key = StringField("Key", validators=[DataRequired(), Length(min=1, max=128)])
    value = TextAreaField("Value", validators=[Optional()])
    type = SelectField(
        "Type",
        validators=[DataRequired()],
        choices=[(t, t) for t in SettingType.ALL],
    )
    description = StringField("Description", validators=[Optional(), Length(max=255)])
    is_secret = BooleanField("Treat as secret")


class PropertyForm(FlaskForm):
    name = StringField("Nimi", validators=[DataRequired(), Length(max=255)])
    address = StringField("Osoite", validators=[Optional(), Length(max=512)])
    city = StringField("Kaupunki", validators=[Optional(), Length(max=100)])
    postal_code = StringField("Postinumero", validators=[Optional(), Length(max=10)])
    street_address = StringField("Katuosoite", validators=[Optional(), Length(max=200)])
    latitude = DecimalField("Leveysaste", validators=[Optional()], places=7)
    longitude = DecimalField("Pituusaste", validators=[Optional()], places=7)
    year_built = IntegerField("Rakennusvuosi", validators=[Optional(), NumberRange(min=0, max=9999)])
    has_elevator = BooleanField("Hissi")
    has_parking = BooleanField("Pysäköinti")
    has_sauna = BooleanField("Sauna")
    has_courtyard = BooleanField("Sisäpiha")
    has_air_conditioning = BooleanField("Ilmastointi")
    description = TextAreaField("Kuvaus", validators=[Optional()])
    url = StringField("Verkko-osoite", validators=[Optional(), Length(max=500), URL(require_tld=False)])


class UnitForm(FlaskForm):
    name = StringField("Nimi", validators=[DataRequired(), Length(max=255)])
    unit_type = StringField("Tyyppi", validators=[Optional(), Length(max=100)])
    floor = IntegerField("Kerros", validators=[Optional()])
    area_sqm = DecimalField("Pinta-ala (m²)", validators=[Optional(), NumberRange(min=0)], places=2)
    bedrooms = IntegerField("Makuuhuoneet", validators=[Optional(), NumberRange(min=0)], default=0)
    has_kitchen = BooleanField("Keittiö")
    has_bathroom = BooleanField("Kylpyhuone", default=True)
    has_balcony = BooleanField("Parveke")
    has_terrace = BooleanField("Terassi")
    has_dishwasher = BooleanField("Astianpesukone")
    has_washing_machine = BooleanField("Pyykinpesukone")
    has_tv = BooleanField("TV")
    has_wifi = BooleanField("WiFi", default=True)
    max_guests = IntegerField("Maksimivieraat", validators=[Optional(), NumberRange(min=1)], default=2)
    description = TextAreaField("Kuvaus", validators=[Optional()])
    floor_plan_image_id = IntegerField("Pohjapiirroskuvan ID", validators=[Optional(), NumberRange(min=1)])
