import os
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlparse

import click
from flask import Flask

from app.api.models import ApiKey
from app.api.services import ApiKeyRotateError
from app.api.services import rotate_api_key as rotate_api_key_service
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
from app.gdpr.services import (
    anonymize_user_data,
    delete_user_data,
    export_json_safe,
    export_user_data,
)
from app.integrations.ical.service import IcalService
from app.organizations.models import Organization
from app.owners.models import OwnerPayout, OwnerPayoutStatus, PropertyOwner
from app.owners.services import generate_monthly_payout, send_payout_email
from app.payments import services as payments_service
from app.payments.models import Payment
from app.properties import services as property_service
from app.properties.models import Property, Unit
from app.reservations import services as reservation_service
from app.reservations.models import Reservation
from app.settings.services import ensure_seed_settings
from app.users import services as user_services
from app.users.models import User, UserRole


def register_cli_commands(app: Flask) -> None:
    @app.cli.command("sentry-test")
    def sentry_test() -> None:
        """Send a test message to Sentry without exposing DSN secrets."""

        dsn = (app.config.get("SENTRY_DSN") or "").strip()
        if not dsn:
            click.echo("SENTRY_DSN is not configured. Set it and retry.", err=True)
            raise SystemExit(1)
        try:
            import sentry_sdk
        except Exception as err:
            raise click.ClickException(f"Sentry SDK is not available: {err}") from err
        sentry_sdk.capture_message("Sentry test from Pin PMS CLI")
        click.echo(
            f"Sent test event to Sentry. Check your project at {_safe_sentry_project_url(dsn)}."
        )

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
    @click.option("--key-id", type=int, required=True, help="Database id of the API key to rotate.")
    @click.option("--reason", default=None, help="Optional note recorded in the audit log.")
    def rotate_api_key(key_id: int, reason: str | None) -> None:
        """Issue a fresh API key as a replacement for an existing one (init template §19).

        Keeps the same logical identity (organization, owning user, scopes, name,
        expiry). The old row remains for forensics with ``is_active`` cleared and
        ``rotated_at`` set. The plaintext value is printed once and is not stored.
        """

        try:
            _old, _new_api_key, raw_key = rotate_api_key_service(key_id, reason=reason)
        except ApiKeyRotateError as err:
            raise click.ClickException(str(err)) from err

        db.session.commit()

        click.echo(raw_key)

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

        backup_dir = Path(app.config.get("BACKUP_DIR", "/var/backups/pindora"))
        click.echo("Backup created:")
        click.echo(f"  SQL dump:            {backup.location}")
        if backup.email_templates_filename:
            click.echo(f"  Email templates JSON: {backup_dir / backup.email_templates_filename}")
        if backup.settings_filename:
            click.echo(f"  Settings JSON:        {backup_dir / backup.settings_filename}")
        click.echo(f"  Size:                {backup.size_human}")

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
    @click.option(
        "--restore-json-exports",
        is_flag=True,
        default=False,
        help=(
            "Also upsert email templates and settings from the JSON exports "
            "paired with this backup. Redacted secret values are preserved as-is "
            "in the database."
        ),
    )
    def backup_restore(filename: str, no_confirm: bool, restore_json_exports: bool) -> None:
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
        if restore_json_exports:
            click.echo(
                click.style(
                    "JSON exports (email templates + settings) will also be "
                    "upserted; redacted secret values stay as-is in the database.",
                    fg="yellow",
                )
            )
        if not no_confirm:
            click.confirm("Proceed with restore?", abort=True)

        click.echo("Restoring…")
        try:
            safe_copy_filename, safe_copy_size = restore_backup(
                filename=filename,
                actor_user_id=None,
                restore_json_exports=restore_json_exports,
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

    @app.cli.command("leases-generate-cycle-invoices")
    def leases_generate_cycle_invoices() -> None:
        """Generate due lease-cycle invoices (all organizations)."""

        summary = billing_service.generate_due_lease_invoices(run_date=None)
        click.echo(
            f"Lease cycle invoices created={summary['created']} skipped={summary['skipped']} errors={len(summary['errors'])}"
        )

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

    @app.cli.command("payments-test-stripe")
    @click.option("--invoice-id", type=int, required=True)
    def payments_test_stripe(invoice_id: int) -> None:
        out = payments_service.create_checkout(
            invoice_id=invoice_id,
            provider_name="stripe",
            return_url=app.config.get("PAYMENT_RETURN_URL")
            or "http://127.0.0.1:5000/portal/payments/return",
            cancel_url="http://127.0.0.1:5000/portal/invoices",
            actor_user_id=None,
            idempotency_key=None,
        )
        click.echo(out["redirect_url"])

    @app.cli.command("payments-test-paytrail")
    @click.option("--invoice-id", type=int, required=True)
    def payments_test_paytrail(invoice_id: int) -> None:
        out = payments_service.create_checkout(
            invoice_id=invoice_id,
            provider_name="paytrail",
            return_url=app.config.get("PAYMENT_RETURN_URL")
            or "http://127.0.0.1:5000/portal/payments/return",
            cancel_url="http://127.0.0.1:5000/portal/invoices",
            actor_user_id=None,
            idempotency_key=None,
        )
        click.echo(out["redirect_url"])

    @app.cli.command("payments-list")
    @click.option("--status", default=None)
    def payments_list(status: str | None) -> None:
        q = Payment.query
        if status:
            q = q.filter(Payment.status == status)
        for row in q.order_by(Payment.id.desc()).limit(200).all():
            click.echo(
                f"#{row.id} org={row.organization_id} provider={row.provider} status={row.status} amount={row.amount} {row.currency}"
            )

    @app.cli.command("payments-prune-expired")
    @click.option("--days", default=30, type=int)
    def payments_prune_expired(days: int) -> None:
        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        rows = Payment.query.filter(
            Payment.status.in_(["pending", "expired"]),
            Payment.created_at < cutoff,
        ).all()
        for row in rows:
            row.status = "expired"
            audit_record(
                "payment.expired",
                status=AuditStatus.SUCCESS,
                actor_type=ActorType.SYSTEM,
                organization_id=row.organization_id,
                target_type="payment",
                target_id=row.id,
                commit=False,
            )
        db.session.commit()
        click.echo(f"Expired {len(rows)} payment(s).")

    @app.cli.command("debug-availability-range")
    @click.option("--organization-id", type=int, required=True)
    @click.option("--start", "start_raw", required=True, help="Range start date YYYY-MM-DD.")
    @click.option("--days", type=int, default=14, show_default=True)
    @click.option("--property-id", type=int, default=None)
    @click.option("--unit-id", type=int, default=None)
    @click.option("--include-cancelled", is_flag=True, default=False)
    def debug_availability_range(
        organization_id: int,
        start_raw: str,
        days: int,
        property_id: int | None,
        unit_id: int | None,
        include_cancelled: bool,
    ) -> None:
        """Debug availability overlap resolution without persistent prints."""

        start_date = reservation_service.parse_calendar_iso_bound(start_raw)
        if start_date is None:
            raise click.ClickException("Invalid --start date.")
        safe_days = max(1, min(days, 31))
        end_date = start_date + timedelta(days=safe_days - 1)
        overlap_end_exclusive = end_date + timedelta(days=1)

        query = (
            Reservation.query.join(Unit, Reservation.unit_id == Unit.id)
            .join(Property, Unit.property_id == Property.id)
            .filter(
                Property.organization_id == organization_id,
                Reservation.start_date < overlap_end_exclusive,
                Reservation.end_date > start_date,
            )
            .order_by(Reservation.start_date.asc(), Reservation.id.asc())
        )
        if property_id is not None:
            query = query.filter(Property.id == property_id)
        if unit_id is not None:
            query = query.filter(Reservation.unit_id == unit_id)
        if not include_cancelled:
            query = query.filter(Reservation.status.in_(("confirmed", "active")))
        rows = query.all()

        matrix = reservation_service.compute_availability_matrix(
            organization_id=organization_id,
            start_date=start_date,
            end_date=end_date,
            property_id=property_id,
            include_cancelled=include_cancelled,
        )

        status_counts: dict[str, int] = {}
        for prop in matrix.get("properties", []):
            for unit in prop.get("units", []):
                if unit_id is not None and unit.get("id") != unit_id:
                    continue
                for day in unit.get("days", []):
                    status = str(day.get("status") or "unknown")
                    status_counts[status] = status_counts.get(status, 0) + 1

        click.echo(
            "Visible range: "
            f"{start_date.isoformat()} .. {end_date.isoformat()} "
            f"(overlap end exclusive {overlap_end_exclusive.isoformat()})"
        )
        click.echo(
            "Filters: "
            f"organization_id={organization_id} "
            f"property_id={property_id if property_id is not None else '-'} "
            f"unit_id={unit_id if unit_id is not None else '-'} "
            f"include_cancelled={include_cancelled}"
        )
        click.echo(f"Matching reservations: {len(rows)}")
        for row in rows:
            click.echo(
                f"- id={row.id} unit_id={row.unit_id} status={row.status} "
                f"{row.start_date.isoformat()}..{row.end_date.isoformat()} "
                f"guest={row.guest_name}"
            )
        click.echo(f"Matrix status counts: {status_counts}")

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
            demo_guest_password = os.getenv(
                "DEMO_GUEST_PASSWORD",
                "dev-only-insecure-demo-guest-password",
            )
            guest = user_services.create_user(
                email=f"demo.guest+org{organization.id}@pindora.local",
                password=demo_guest_password,
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
        showcase_seed = ("Demo Unit 201", 2, 5, "Ville Testaaja")

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

        showcase_unit_name, showcase_start_offset, showcase_end_offset, showcase_guest_name = (
            showcase_seed
        )
        showcase_unit_id = unit_ids_by_name[showcase_unit_name]
        showcase_start_date = (today + timedelta(days=showcase_start_offset)).isoformat()
        showcase_end_date = (today + timedelta(days=showcase_end_offset)).isoformat()
        showcase_key = (
            showcase_unit_id,
            None,
            showcase_start_date,
            showcase_end_date,
            "confirmed",
        )
        if showcase_key not in existing_keyset:
            _ = reservation_service.create_reservation(
                organization_id=organization.id,
                unit_id=showcase_unit_id,
                guest_id=None,
                guest_name=showcase_guest_name,
                start_date_raw=showcase_start_date,
                end_date_raw=showcase_end_date,
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

    @app.cli.command("gdpr-export-user")
    @click.option("--email", required=True, help="User email address.")
    @click.option(
        "--output",
        default=None,
        help="Optional file path to write JSON (otherwise printed to stdout).",
    )
    def gdpr_export_user(email: str, output: str | None) -> None:
        """Export a portable JSON bundle for the given user (no secrets)."""

        normalized_email = email.strip().lower()
        user = User.query.filter_by(email=normalized_email).first()
        if user is None:
            click.echo(f"User '{normalized_email}' not found.", err=True)
            raise click.Abort()
        try:
            data = export_user_data(user.id)
        except Exception as err:  # noqa: BLE001
            raise click.ClickException(str(err)) from err
        text = export_json_safe(data)
        if output:
            path = Path(output).expanduser()
            path.write_text(text, encoding="utf-8")
            click.echo(f"Wrote GDPR export to {path}.")
        else:
            click.echo(text)

    @app.cli.command("gdpr-anonymize-user")
    @click.option("--email", required=True, help="User email address.")
    @click.confirmation_option(prompt="Haluatko varmasti anonymisoida käyttäjän?")
    def gdpr_anonymize_user(email: str) -> None:
        """Replace PII with placeholders and deactivate the account."""

        normalized_email = email.strip().lower()
        user = User.query.filter_by(email=normalized_email).first()
        if user is None:
            click.echo(f"User '{normalized_email}' not found.", err=True)
            raise click.Abort()
        try:
            anonymize_user_data(user.id)
        except Exception as err:  # noqa: BLE001
            raise click.ClickException(str(err)) from err
        click.echo(f"User {user.id} anonymized.")

    @app.cli.command("gdpr-delete-user")
    @click.option("--email", required=True, help="User email address.")
    @click.confirmation_option(prompt="POISTO ON LOPULLINEN. Haluatko varmasti?")
    def gdpr_delete_user(email: str) -> None:
        """Permanently remove the user row after anonymization (superadmin shell tool)."""

        normalized_email = email.strip().lower()
        user = User.query.filter_by(email=normalized_email).first()
        if user is None:
            click.echo(f"User '{normalized_email}' not found.", err=True)
            raise click.Abort()
        uid = user.id
        try:
            delete_user_data(uid, from_cli=True)
        except Exception as err:  # noqa: BLE001
            raise click.ClickException(str(err)) from err
        click.echo(f"User id {uid} permanently deleted (GDPR).")


def _safe_sentry_project_url(dsn: str) -> str:
    try:
        parsed = urlparse(dsn)
        host = parsed.hostname or "sentry.io"
        path_parts = [part for part in parsed.path.split("/") if part]
        project_id = path_parts[-1] if path_parts else "project"
        return f"https://{host}/organizations/<org>/projects/<project>/?project={project_id}"
    except Exception:
        return "https://sentry.io/"
