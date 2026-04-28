"""add lock devices access codes and checkin

Revision ID: j2b3c4d5e6f8
Revises: h1a2b3c4d5e6
Create Date: 2026-04-28 16:58:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "j2b3c4d5e6f8"
down_revision = "h1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lock_devices",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_device_id", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("battery_level", sa.Integer(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lock_devices_organization_id"), "lock_devices", ["organization_id"], unique=False)
    op.create_index(op.f("ix_lock_devices_unit_id"), "lock_devices", ["unit_id"], unique=False)
    op.create_index(op.f("ix_lock_devices_provider_device_id"), "lock_devices", ["provider_device_id"], unique=False)

    op.create_table(
        "access_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reservation_id", sa.Integer(), nullable=False),
        sa.Column("lock_device_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("provider_code_id", sa.String(length=128), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["lock_device_id"], ["lock_devices.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revoked_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(op.f("ix_access_codes_reservation_id"), "access_codes", ["reservation_id"], unique=False)
    op.create_index(op.f("ix_access_codes_lock_device_id"), "access_codes", ["lock_device_id"], unique=False)
    op.create_index(op.f("ix_access_codes_is_active"), "access_codes", ["is_active"], unique=False)
    op.create_index(op.f("ix_access_codes_idempotency_key"), "access_codes", ["idempotency_key"], unique=True)

    op.create_table(
        "portal_checkin_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reservation_id", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index(op.f("ix_portal_checkin_tokens_reservation_id"), "portal_checkin_tokens", ["reservation_id"], unique=False)
    op.create_index(op.f("ix_portal_checkin_tokens_token_hash"), "portal_checkin_tokens", ["token_hash"], unique=True)

    op.create_table(
        "guest_checkins",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reservation_id", sa.Integer(), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("date_of_birth", sa.Date(), nullable=False),
        sa.Column("id_document_path", sa.Text(), nullable=False),
        sa.Column("rules_accepted", sa.Boolean(), nullable=False),
        sa.Column("rules_signature", sa.String(length=255), nullable=False),
        sa.Column("checked_in_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("checked_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["reservation_id"], ["reservations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reservation_id"),
    )
    op.create_index(op.f("ix_guest_checkins_reservation_id"), "guest_checkins", ["reservation_id"], unique=True)


def downgrade():
    op.drop_index(op.f("ix_guest_checkins_reservation_id"), table_name="guest_checkins")
    op.drop_table("guest_checkins")
    op.drop_index(op.f("ix_portal_checkin_tokens_token_hash"), table_name="portal_checkin_tokens")
    op.drop_index(op.f("ix_portal_checkin_tokens_reservation_id"), table_name="portal_checkin_tokens")
    op.drop_table("portal_checkin_tokens")
    op.drop_index(op.f("ix_access_codes_idempotency_key"), table_name="access_codes")
    op.drop_index(op.f("ix_access_codes_is_active"), table_name="access_codes")
    op.drop_index(op.f("ix_access_codes_lock_device_id"), table_name="access_codes")
    op.drop_index(op.f("ix_access_codes_reservation_id"), table_name="access_codes")
    op.drop_table("access_codes")
    op.drop_index(op.f("ix_lock_devices_provider_device_id"), table_name="lock_devices")
    op.drop_index(op.f("ix_lock_devices_unit_id"), table_name="lock_devices")
    op.drop_index(op.f("ix_lock_devices_organization_id"), table_name="lock_devices")
    op.drop_table("lock_devices")
