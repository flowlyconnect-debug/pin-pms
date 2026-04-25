import click
from flask import Flask
from werkzeug.security import generate_password_hash

from app.api.models import ApiKey
from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.backups.models import BackupTrigger
from app.backups.services import BackupError, create_backup, restore_backup
from app.email.models import EmailTemplate, TemplateKey
from app.email.services import ensure_seed_templates, send_template
from app.extensions import db
from app.organizations.models import Organization
from app.settings.services import ensure_seed_settings
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
    db.session.flush()  # Needs ``user.id`` for the audit row.

    is_superadmin = normalized_role == UserRole.SUPERADMIN.value
    audit_record(
        "superadmin.created" if is_superadmin else "user.created",
        status=AuditStatus.SUCCESS,
        actor_type=ActorType.SYSTEM,
        organization_id=organization.id,
        target_type="user",
        target_id=user.id,
        context={
            "email": user.email,
            "role": user.role,
            "organization": organization.name,
        },
    )
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
        db.session.flush()  # Needs ``api_key.id`` for the audit row.

        audit_record(
            "apikey.created",
            status=AuditStatus.SUCCESS,
            actor_type=ActorType.SYSTEM,
            organization_id=api_key.organization_id,
            target_type="api_key",
            target_id=api_key.id,
            context={
                "name": api_key.name,
                "prefix": api_key.key_prefix,
                "user_email": user.email,
                "scopes": api_key.scope_list,
            },
        )
        db.session.commit()

        click.echo("")
        click.echo(f"API key issued for {user.email} (organization: {user.organization.name}).")
        click.echo(f"  Name:   {api_key.name}")
        click.echo(f"  Prefix: {api_key.key_prefix}")
        click.echo(f"  Key:    {raw_key}")
        click.echo("")
        click.echo("Store this key securely. It will NOT be shown again.")

    @app.cli.command("send-test-email")
    @click.option("--to", prompt=True, help="Recipient email address")
    @click.option(
        "--template",
        default=TemplateKey.ADMIN_NOTIFICATION,
        show_default=True,
        type=click.Choice(list(TemplateKey.ALL), case_sensitive=False),
        help="Template key to render",
    )
    def send_test_email(to: str, template: str) -> None:
        """Render and send a template to verify Mailgun configuration.

        Honors ``MAIL_DEV_LOG_ONLY``: if set, the email is logged instead of
        sent and the command still reports success.
        """

        # Provide harmless placeholder values for every variable the seed
        # templates reference so the render does not blow up on missing keys.
        sample_context = {
            "user_email": to,
            "organization_name": "Test Organization",
            "login_url": "https://example.com/login",
            "reset_url": "https://example.com/reset/abc123",
            "expires_minutes": 30,
            "code": "123 456",
            "backup_name": "test-backup-2026-04-25",
            "completed_at": "2026-04-25 10:00:00 UTC",
            "size_human": "12.3 MB",
            "location": "/var/backups/pindora/test-backup.sql.gz",
            "failed_at": "2026-04-25 10:00:00 UTC",
            "error_message": "pg_dump: connection refused (test message)",
            "subject_line": "Test admin notification",
            "message": "This is a test message sent via 'flask send-test-email'.",
        }

        ok = send_template(template, to=to, context=sample_context)
        if ok:
            click.echo(f"Sent template '{template}' to {to}.")
        else:
            raise click.ClickException(
                f"Failed to send template '{template}' — check the application log."
            )

    @app.cli.command("backup-create")
    def backup_create() -> None:
        """Run pg_dump now and write a gzipped backup to BACKUP_DIR.

        Equivalent to clicking "Create backup now" in /admin/backups, but
        usable from a host cron / one-off Docker exec when the web UI is not
        accessible. The result is recorded in the ``backups`` table and the
        audit log just like a scheduled run.
        """

        click.echo("Running pg_dump…")
        try:
            backup = create_backup(trigger=BackupTrigger.MANUAL)
        except BackupError as err:
            raise click.ClickException(f"Backup failed: {err}")

        click.echo(f"Backup complete:")
        click.echo(f"  Filename: {backup.filename}")
        click.echo(f"  Location: {backup.location}")
        click.echo(f"  Size:     {backup.size_human}")

    @app.cli.command("backup-restore")
    @click.option(
        "--filename",
        prompt=True,
        help="Backup filename inside BACKUP_DIR, e.g. pindora-20260425T030000Z.sql.gz",
    )
    @click.option(
        "--no-confirm",
        is_flag=True,
        default=False,
        help="Skip the interactive confirmation prompt (use with care).",
    )
    def backup_restore(filename: str, no_confirm: bool) -> None:
        """Load a backup file over the current database.

        The web UI gates this behind a password + 2FA challenge; the CLI
        assumes the operator already has shell access to the host (which is
        equivalent in trust) and only requires an interactive confirmation
        unless ``--no-confirm`` is passed (e.g. for automated drills).
        """

        click.echo(
            click.style(
                "WARNING: this will overwrite the current database with the contents "
                f"of {filename!r}. A safe-copy of the current state is taken first.",
                fg="red",
                bold=True,
            )
        )
        if not no_confirm:
            click.confirm("Proceed with restore?", abort=True)

        click.echo("Restoring…")
        try:
            safe_copy = restore_backup(filename=filename, actor_user_id=None)
        except BackupError as err:
            raise click.ClickException(f"Restore failed: {err}")

        click.echo(
            f"Restore complete. Pre-restore safe-copy saved as {safe_copy.filename} "
            f"({safe_copy.size_human})."
        )

    @app.cli.command("seed-email-templates")
    def seed_email_templates() -> None:
        """Insert any default email templates that are not yet in the database.

        Idempotent — existing rows are not touched, so admin edits survive a
        re-run. Useful after adding a new template key in code.
        """

        before = {row.key for row in EmailTemplate.query.all()}
        ensure_seed_templates()
        after = {row.key for row in EmailTemplate.query.all()}
        added = sorted(after - before)
        if added:
            click.echo(f"Inserted missing templates: {', '.join(added)}")
        else:
            click.echo("All seed templates are already present.")

    @app.cli.command("seed-settings")
    def seed_settings() -> None:
        """Insert any default settings that are not yet in the database.

        Idempotent — existing rows are not touched, so admin edits survive a
        re-run. Useful after adding a new setting key in seed_data.
        """

        added = ensure_seed_settings()
        if added:
            click.echo(f"Inserted missing settings: {', '.join(added)}")
        else:
            click.echo("All seed settings are already present.")
