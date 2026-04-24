import click
from flask import Flask
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.organizations.models import Organization
from app.users.models import User, UserRole


def register_cli_commands(app: Flask) -> None:
    @app.cli.command("create-user")
    @click.option("--email", prompt=True, help="User email address")
    @click.option(
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="User password",
    )
    @click.option(
        "--role",
        prompt=True,
        type=click.Choice([role.value for role in UserRole], case_sensitive=False),
        default=UserRole.USER.value,
        show_default=True,
        help="User role",
    )
    @click.option("--organization-name", prompt=True, help="Organization name")
    def create_user(
        email: str,
        password: str,
        role: str,
        organization_name: str,
    ) -> None:
        normalized_email = email.strip().lower()
        normalized_org_name = organization_name.strip()
        normalized_role = role.strip().lower()

        if not normalized_org_name:
            raise click.ClickException("Organization name is required.")

        existing_user = User.query.filter_by(email=normalized_email).first()
        if existing_user:
            raise click.ClickException(f"User with email '{normalized_email}' already exists.")

        organization = Organization.query.filter_by(name=normalized_org_name).first()
        if organization is None:
            organization = Organization(name=normalized_org_name)
            db.session.add(organization)
            db.session.flush()

        user = User(
            email=normalized_email,
            organization_id=organization.id,
            role=normalized_role,
            password_hash=generate_password_hash(password),
            is_active=True,
        )

        db.session.add(user)
        db.session.commit()

        click.echo(
            f"Created user '{user.email}' with role '{user.role}' in organization '{organization.name}'."
        )
