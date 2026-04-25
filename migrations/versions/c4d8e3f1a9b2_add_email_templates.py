"""Add email_templates table and seed the six required templates.

Revision ID: c4d8e3f1a9b2
Revises: b5e1c9d27a84
Create Date: 2026-04-25
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c4d8e3f1a9b2"
down_revision = "b5e1c9d27a84"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False, unique=True),
        sa.Column("subject", sa.String(length=255), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column(
            "description",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "available_variables",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_by_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_email_templates_key",
        "email_templates",
        ["key"],
        unique=True,
    )

    # Seed the six required templates. Imported lazily so the migration file
    # can be loaded by Alembic even before the app package is on sys.path.
    from app.email.seed_data import SEED_TEMPLATES

    bind = op.get_bind()
    table = sa.table(
        "email_templates",
        sa.column("key", sa.String),
        sa.column("subject", sa.String),
        sa.column("body_text", sa.Text),
        sa.column("body_html", sa.Text),
        sa.column("description", sa.String),
        sa.column("available_variables", sa.JSON),
    )

    rows = [
        {
            "key": t["key"],
            "subject": t["subject"],
            "body_text": t["body_text"],
            "body_html": t["body_html"],
            "description": t["description"],
            "available_variables": t["available_variables"],
        }
        for t in SEED_TEMPLATES
    ]
    bind.execute(table.insert(), rows)


def downgrade() -> None:
    op.drop_index("ix_email_templates_key", table_name="email_templates")
    op.drop_table("email_templates")
