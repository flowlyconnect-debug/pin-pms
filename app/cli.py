import click
from flask import Flask
from werkzeug.security import generate_password_hash

from app.api.models import ApiKey
from app.extensions import db
from app.organizations.models import Organization
from app.users.models import User, UserRole


def _create_user(
    email: str,
    password: str,
    role: str,
    organization_name: str,
) -> User:
    """Shared helper for all CLI commands that provision a user.

    Normalizes inputs, ensures the target organization exists, refuses to
    overwrite an existing account, and returns the persisted ``User``.
    """

    normalized_email = email.strip().lower()
    normalized_org_name = organization_name.strip()
    normalized_role = role.strip().lower()

    if not normalized_email:
        raise click.ClickException("Email is required.")
    if not password:
        raise click.ClickException("Password is required.")
    if not normalized_org_name:
        raise click.ClickException("Organization name is required.")

    valid_roles = {r.value for r in UserRole}
    if normalized_role not in valid_roles:
        raise click.ClickException(
            f"Invalid role '{normalized_role}'. Must be one of: {', '.join(sorted(valid_roles))}."
        )

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
    return user


def register_cli_commands(app: Flask) -> None:
    @app.cli.command("create-superadmin")
    @click.option("--email", prompt=True, help="Superadmin email address")
    @click.option(
        "--password",
        prompt=True,
        hide_input=True,
        confirmation_prompt=True,
        help="Superadmin password",
    )
    @click.option("--organization-name", prompt=True, help="Organization name")
    def create_superadmin(
        email: str,
        password: str,
        organization_name: str,
    ) -> None:
        """Create a superadmin user. 2FA is enforced on first login."""

        user = _create_user(
            email=email,
            password=password,
            role=UserRole.SUPERADMIN.value,
            organization_name=organization_name,
        )
        click.echo(
            f"Created superadmin '{user.email}' in organization '{user.organization.name}'."
        )
        click.echo(
            "On first login the user will be required to set up TOTP 2FA before "
            "any superadmin action is permitted."
        )

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
        """Create a user with an arbitrary role. Use ``create-superadmin`` for superadmins."""

        user = _create_user(
            email=email,
            password=password,
            role=role,
            organization_name=organization_name,
        )
        click.echo(
            f"Created user '{user.email}' with role '{user.role}' "
            f"in organization '{user.organization.name}'."
        )

    @app.cli.command("create-api-key")
    @click.option("--name", prompt=True, help="Human-readable key name, e.g. 'Production integration'")
    @click.option("--user-email", prompt=True, help="Email of the user that owns the key")
    @click.option(
        "--scopes",
        default="",
        show_default=True,
        help="Comma-separated list of scope identifiers (optional)",
    )
    def create_api_key(name: str, user_email: str, scopes: str) -> None:
        """Issue a new API key scoped to a user's organization.

        The plaintext key is printed once. It cannot be recovered afterwards —
        store it in a secret manager immediately.
        """

        normalized_email = user_email.strip().lower()
        user = User.query.filter_by(email=normalized_email).first()
        if user is None:
            raise click.ClickException(f"User '{normalized_email}' not found.")
        if not user.is_active:
            raise click.ClickException(
                f"User '{normalized_email}' is not active. Reactivate before issuing keys."
            )

        api_key, raw_key = ApiKey.issue(
            name=name,
            organization_id=user.organization_id,
            user_id=user.id,
            scopes=scopes,
        )
        db.session.add(api_key)
        db.session.commit()

        click.echo("")
        click.echo(f"API key issued for {user.email} (organization: {user.organization.name}).")
        click.echo(f"  Name:   {api_key.name}")
        click.echo(f"  Prefix: {api_key.key_prefix}")
        click.echo(f"  Key:    {raw_key}")
        click.echo("")
        click.echo("Store this key securely. It will NOT be shown again.")
