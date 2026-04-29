"""add iCal import tables

Revision ID: j2b3c4d5e6f7
Revises: h1a2b3c4d5e6
Create Date: 2026-04-28 17:25:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "j2b3c4d5e6f7"
down_revision = "h1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "imported_calendar_feeds",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_imported_calendar_feeds_organization_id"),
        "imported_calendar_feeds",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_imported_calendar_feeds_unit_id"),
        "imported_calendar_feeds",
        ["unit_id"],
        unique=False,
    )

    op.create_table(
        "imported_calendar_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("unit_id", sa.Integer(), nullable=False),
        sa.Column("feed_id", sa.Integer(), nullable=False),
        sa.Column("external_uid", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.String(length=512), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["feed_id"], ["imported_calendar_feeds.id"]),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.ForeignKeyConstraint(["unit_id"], ["units.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_imported_calendar_events_organization_id"),
        "imported_calendar_events",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_imported_calendar_events_unit_id"),
        "imported_calendar_events",
        ["unit_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_imported_calendar_events_feed_id"),
        "imported_calendar_events",
        ["feed_id"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_imported_calendar_events_feed_id"), table_name="imported_calendar_events")
    op.drop_index(op.f("ix_imported_calendar_events_unit_id"), table_name="imported_calendar_events")
    op.drop_index(op.f("ix_imported_calendar_events_organization_id"), table_name="imported_calendar_events")
    op.drop_table("imported_calendar_events")

    op.drop_index(op.f("ix_imported_calendar_feeds_unit_id"), table_name="imported_calendar_feeds")
    op.drop_index(op.f("ix_imported_calendar_feeds_organization_id"), table_name="imported_calendar_feeds")
    op.drop_table("imported_calendar_feeds")

