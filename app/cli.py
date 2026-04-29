import click
from flask import Flask

from app.api.models import ApiKey
from app.audit import record as audit_record
from app.audit.models import ActorType, AuditStatus
from app.audit.services import vacuum_audit_logs
from app.auth import services as auth_services
from app.backups.models import BackupTrigger
from app.backups.services import BackupError, create_backup, restore_backup
from app.billing import services as billing_service
from app.email.models import EmailTemplate, TemplateKey
from app.email.services import ensure_seed_templates, send_template_sync
from app.extensions import db
from app.integrations.ical.service import IcalService
from app.organizations.models import Organization
from app.owners.models import OwnerPayout, OwnerPayoutStatus, PropertyOwner
from app.owners.services import generate_monthly_payout, send_payout_email
from app.properties import services as property_service
from app.properties.models import Property, Unit
from app.reservations import services as reservation_service
from app.settings.services import ensure_seed_settings
from app.users import services as user_services
from app.users.models import User, UserRole


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

        try:
            user = user_services.create_user(
                email=email,
                password=password,
                role=UserRole.SUPERADMIN.value,
                organization_name=organization_name,
            )
        except user_services.UserServiceError as err:
            raise click.ClickException(str(err)) from err
        click.echo(f"Created superadmin '{user.email}' in organization '{user.organization.name}'.")
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

        try:
            user = user_services.create_user(
                email=email,
                password=password,
                role=role,
                organization_name=organization_name,
            )
        except user_services.UserServiceError as err:
            raise click.ClickException(str(err)) from err
        click.echo(
            f"Created user '{user.email}' with role '{user.role}' "
            f"in organization '{user.organization.name}'."
        )

    @app.cli.command("create-api-key")
    @click.option(
        "--name", prompt=True, help="Human-readable key name, e.g. 'Production integration'"
    )
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

        ok = send_template_sync(template, to=to, context=sample_context)
        if ok:
            click.echo(f"Sent template '{template}' to {to}.")
        else:
            raise click.ClickException(
                f"Failed to send template '{template}' — check the application log."
            )

    @app.cli.command("rotate-api-key")
    @click.option(
        "--prefix",
        prompt=True,
        help="Prefix of the API key to rotate (e.g. 'pms_abcd1234'). "
        "Visible in /admin or in 'flask shell' via ApiKey.query.",
    )
    def rotate_api_key(prefix: str) -> None:
        """Issue a fresh API key as a replacement for an existing one.

        Per project brief section 19: rotation must keep the *same logical
        identity* (organization, owning user, scopes, name) so consumers can
        switch from old to new without re-onboarding the integration. The
        old row stays in the database for forensics — it is just deactivated
        so further auth attempts fail.

        The plaintext value is printed once. It cannot be recovered.
        """

        normalized_prefix = prefix.strip()
        if not normalized_prefix:
            raise click.ClickException("Prefix is required.")

        # Find the active key matching the prefix. We refuse to rotate an
        # already-deactivated key — that is more likely a typo than the
        # operator's intent, and silently issuing a new key in that case
        # would obscure history.
        candidates = ApiKey.query.filter_by(key_prefix=normalized_prefix, is_active=True).all()
        if not candidates:
            raise click.ClickException(
                f"No active API key found with prefix {normalized_prefix!r}."
            )
        if len(candidates) > 1:
            ids = ", ".join(str(c.id) for c in candidates)
            raise click.ClickException(
                f"Prefix {normalized_prefix!r} matches multiple active keys "
                f"(ids: {ids}). Refusing to guess — deactivate one first."
            )

        old = candidates[0]

        new_api_key, raw_key = ApiKey.issue(
            name=old.name,
            organization_id=old.organization_id,
            user_id=old.user_id,
            scopes=old.scopes,
            expires_at=old.expires_at,
        )
        db.session.add(new_api_key)
        db.session.flush()  # Need ``new_api_key.id`` for the audit row.

        # Deactivate the old key only after the new row is persisted so a
        # crash in the middle does not leave the integration with no usable
        # key.
        old.is_active = False

        audit_record(
            "apikey.rotated",
            status=AuditStatus.SUCCESS,
            actor_type=ActorType.SYSTEM,
            organization_id=new_api_key.organization_id,
            target_type="api_key",
            target_id=new_api_key.id,
            context={
                "old_id": old.id,
                "old_prefix": old.key_prefix,
                "new_id": new_api_key.id,
                "new_prefix": new_api_key.key_prefix,
                "name": new_api_key.name,
                "scopes": new_api_key.scope_list,
            },
        )
        db.session.commit()

        click.echo("")
        click.echo(f"API key rotated for organization {new_api_key.organization.name!r}.")
        click.echo(f"  Old prefix: {old.key_prefix} (now inactive, kept for audit)")
        click.echo(f"  New name:   {new_api_key.name}")
        click.echo(f"  New prefix: {new_api_key.key_prefix}")
        click.echo(f"  New key:    {raw_key}")
        click.echo("")
        click.echo("Store the new key securely. It will NOT be shown again.")

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
            raise click.ClickException(f"Backup failed: {err}") from err

        click.echo("Backup complete:")
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
            safe_copy_filename, safe_copy_size = restore_backup(
                filename=filename, actor_user_id=None
            )
        except BackupError as err:
            raise click.ClickException(f"Restore failed: {err}") from err

        click.echo(
            f"Restore complete. Pre-restore safe-copy saved as {safe_copy_filename} "
            f"({safe_copy_size})."
        )

    @app.cli.command("invoices-mark-overdue")
    @click.option(
        "--organization-id",
        type=int,
        default=None,
        help="Limit to one organization id (default: all organizations).",
    )
    def invoices_mark_overdue(organization_id: int | None) -> None:
        """Mark open invoices overdue when due_date is before today (UTC date)."""

        n = billing_service.mark_overdue_invoices(organization_id=organization_id)
        click.echo(f"Marked {n} invoice(s) as overdue.")

    @app.cli.command("ical-sync")
    @click.option(
        "--organization-id",
        type=int,
        default=None,
        help="Limit import to one organization id (default: all organizations).",
    )
    def ical_sync(organization_id: int | None) -> None:
        """Poll configured iCal feeds and import availability blocks."""

        n = IcalService().sync_all_feeds(organization_id=organization_id)
        click.echo(f"Imported {n} iCal block(s).")

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

    @app.cli.command("seed-demo-data")
    def seed_demo_data() -> None:
        """Seed tenant-safe demo PMS data (idempotent)."""

        from datetime import date, timedelta

        created_counts = {
            "organizations": 0,
            "properties": 0,
            "units": 0,
            "reservations": 0,
        }

        organization = Organization.query.order_by(Organization.id.asc()).first()
        if organization is None:
            organization = Organization(name="Demo Organization")
            db.session.add(organization)
            db.session.commit()
            created_counts["organizations"] += 1

        guest = (
            User.query.filter_by(
                organization_id=organization.id,
                email=f"demo.guest+org{organization.id}@pindora.local",
            )
            .order_by(User.id.asc())
            .first()
        )
        if guest is None:
            guest = user_services.create_user(
                email=f"demo.guest+org{organization.id}@pindora.local",
                password="DemoPass123!",
                role=UserRole.USER.value,
                organization_name=organization.name,
            )

        property_name = "Demo Property"
        existing_property = Property.query.filter_by(
            organization_id=organization.id,
            name=property_name,
        ).first()
        if existing_property is None:
            property_row = property_service.create_property(
                organization_id=organization.id,
                name=property_name,
                address="Demo Street 1",
                actor_user_id=guest.id,
            )
            property_id = property_row["id"]
            created_counts["properties"] += 1
        else:
            property_id = existing_property.id

        unit_seeds = [
            ("Demo Unit 101", "single"),
            ("Demo Unit 102", "double"),
            ("Demo Unit 201", "suite"),
        ]
        unit_ids_by_name: dict[str, int] = {}
        for unit_name, unit_type in unit_seeds:
            existing_unit = Unit.query.filter_by(
                property_id=property_id,
                name=unit_name,
            ).first()
            if existing_unit is None:
                unit_row = property_service.create_unit(
                    organization_id=organization.id,
                    property_id=property_id,
                    name=unit_name,
                    unit_type=unit_type,
                    actor_user_id=guest.id,
                )
                unit_ids_by_name[unit_name] = unit_row["id"]
                created_counts["units"] += 1
            else:
                unit_ids_by_name[unit_name] = existing_unit.id

        today = date.today()
        reservation_seeds = [
            ("Demo Unit 101", 2, 5),
            ("Demo Unit 101", 7, 10),
            ("Demo Unit 102", 4, 8),
            ("Demo Unit 201", 12, 15),
        ]

        existing_rows = reservation_service.list_reservations(organization_id=organization.id)
        existing_keyset = {
            (
                row["unit_id"],
                row["guest_id"],
                row["start_date"],
                row["end_date"],
                row["status"],
            )
            for row in existing_rows
        }

        for unit_name, start_offset, end_offset in reservation_seeds:
            unit_id = unit_ids_by_name[unit_name]
            start_date = (today + timedelta(days=start_offset)).isoformat()
            end_date = (today + timedelta(days=end_offset)).isoformat()
            seed_key = (unit_id, guest.id, start_date, end_date, "confirmed")
            if seed_key in existing_keyset:
                continue
            _ = reservation_service.create_reservation(
                organization_id=organization.id,
                unit_id=unit_id,
                guest_id=guest.id,
                start_date_raw=start_date,
                end_date_raw=end_date,
                actor_user_id=guest.id,
            )
            created_counts["reservations"] += 1

        click.echo("Demo data seed complete.")
        click.echo(f"  Organization: {organization.name} (id={organization.id})")
        click.echo(f"  Property id:  {property_id}")
        click.echo(
            "  Created: "
            f"{created_counts['organizations']} org, "
            f"{created_counts['properties']} property, "
            f"{created_counts['units']} unit(s), "
            f"{created_counts['reservations']} reservation(s)"
        )

    @app.cli.command("cleanup-expired-tokens")
    def cleanup_expired_tokens() -> None:
        """Delete expired password-reset / email-2FA / portal magic-link tokens."""
        counts = auth_services.cleanup_expired_tokens()
        total = sum(counts.values())
        click.echo(f"Deleted {total} expired token row(s).")
        click.echo(f"  password_reset_tokens: {counts['password_reset_tokens']}")
        click.echo(f"  two_factor_email_codes: {counts['two_factor_email_codes']}")
        click.echo(f"  portal_magic_link_tokens: {counts['portal_magic_link_tokens']}")

    @app.cli.command("vacuum-audit-logs")
    @click.option(
        "--keep-days",
        type=int,
        required=True,
        help="Keep only audit rows newer than N days.",
    )
    def vacuum_audit_logs_command(keep_days: int) -> None:
        """Delete audit rows older than N days."""
        try:
            deleted = vacuum_audit_logs(keep_days=keep_days)
        except ValueError as err:
            raise click.ClickException(str(err)) from err
        click.echo(f"Deleted {deleted} audit row(s) older than {keep_days} day(s).")

    @app.cli.command("owners-generate-payouts")
    @click.option("--month", "period_month", required=True, help="Month in format YYYY-MM.")
    def owners_generate_payouts(period_month: str) -> None:
        owners = PropertyOwner.query.filter_by(is_active=True).all()
        generated = 0
        for owner in owners:
            generate_monthly_payout(owner_id=owner.id, period_month=period_month)
            generated += 1
        click.echo(f"Generated {generated} owner payout(s) for {period_month}.")

    @app.cli.command("owners-send-payout-emails")
    @click.option("--month", "period_month", required=True, help="Month in format YYYY-MM.")
    def owners_send_payout_emails(period_month: str) -> None:
        rows = (
            OwnerPayout.query.join(PropertyOwner, OwnerPayout.owner_id == PropertyOwner.id)
            .filter(
                OwnerPayout.period_month == period_month,
                OwnerPayout.status == OwnerPayoutStatus.DRAFT,
                PropertyOwner.is_active.is_(True),
            )
            .all()
        )
        sent = 0
        for row in rows:
            if send_payout_email(payout=row):
                sent += 1
        click.echo(f"Sent {sent} owner payout email(s) for {period_month}.")
