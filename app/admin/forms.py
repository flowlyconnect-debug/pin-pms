from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, TextAreaField
from wtforms.fields import DateTimeLocalField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional

from app.settings.models import SettingType
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
    scopes = StringField("Scopes", validators=[Optional(), Length(max=512)])
    expires_at = DateTimeLocalField("Expires at", validators=[Optional()], format="%Y-%m-%dT%H:%M")


class EmailTemplateForm(FlaskForm):
    subject = StringField("Subject", validators=[DataRequired(), Length(min=1, max=255)])
    body_text = TextAreaField("Plain-text body", validators=[DataRequired(), Length(min=1)])
    body_html = TextAreaField("HTML body", validators=[Optional()])


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
