"""Add guest CRM and reservation guest link

Revision ID: f1c2d3e4b5a6
Revises: a0b7abd18461
Create Date: 2026-04-26 21:45:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "f1c2d3e4b5a6"
down_revision = "a0b7abd18461"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "guests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=False),
        sa.Column("last_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("phone", sa.String(length=80), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("preferences", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("guests", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_guests_organization_id"), ["organization_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_guests_email"), ["email"], unique=False)

    # Backfill legacy reservation guests (previously users.id) so adding the
    # new reservations.guest_id -> guests.id FK succeeds on existing data.
    op.execute(
        sa.text(
            """
            INSERT INTO guests (id, organization_id, first_name, last_name, email, phone, notes, preferences)
            SELECT
                u.id,
                u.organization_id,
                split_part(u.email, '@', 1),
                '',
                u.email,
                NULL,
                NULL,
                NULL
            FROM users u
            WHERE NOT EXISTS (
                SELECT 1 FROM guests g WHERE g.id = u.id
            )
            """
        )
    )

    with op.batch_alter_table("reservations", schema=None) as batch_op:
        batch_op.add_column(sa.Column("guest_name", sa.String(length=255), nullable=False, server_default="Guest"))
        batch_op.drop_constraint("reservations_guest_id_fkey", type_="foreignkey")
        batch_op.create_foreign_key("reservations_guest_id_fkey", "guests", ["guest_id"], ["id"])
        batch_op.alter_column("guest_id", existing_type=sa.Integer(), nullable=True)


def downgrade():
    with op.batch_alter_table("reservations", schema=None) as batch_op:
        batch_op.alter_column("guest_id", existing_type=sa.Integer(), nullable=False)
        batch_op.drop_constraint("reservations_guest_id_fkey", type_="foreignkey")
        batch_op.create_foreign_key("reservations_guest_id_fkey", "users", ["guest_id"], ["id"])
        batch_op.drop_column("guest_name")

    with op.batch_alter_table("guests", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_guests_email"))
        batch_op.drop_index(batch_op.f("ix_guests_organization_id"))
    op.drop_table("guests")
