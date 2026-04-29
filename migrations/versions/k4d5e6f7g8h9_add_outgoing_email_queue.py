"""add outgoing email queue table

Revision ID: k4d5e6f7g8h9
Revises: j2b3c4d5e6f7
Create Date: 2026-04-28 18:10:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "k4d5e6f7g8h9"
down_revision = "j2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outgoing_emails",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("to", sa.String(length=255), nullable=False),
        sa.Column("template_key", sa.String(length=64), nullable=False),
        sa.Column("context_json", sa.JSON(), nullable=False),
        sa.Column("subject_snapshot", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending','sent','failed')",
            name="ck_outgoing_emails_status",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_outgoing_emails_to"), "outgoing_emails", ["to"], unique=False)
    op.create_index(
        op.f("ix_outgoing_emails_template_key"),
        "outgoing_emails",
        ["template_key"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outgoing_emails_status"),
        "outgoing_emails",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_outgoing_emails_scheduled_at"),
        "outgoing_emails",
        ["scheduled_at"],
        unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_outgoing_emails_scheduled_at"), table_name="outgoing_emails")
    op.drop_index(op.f("ix_outgoing_emails_status"), table_name="outgoing_emails")
    op.drop_index(op.f("ix_outgoing_emails_template_key"), table_name="outgoing_emails")
    op.drop_index(op.f("ix_outgoing_emails_to"), table_name="outgoing_emails")
    op.drop_table("outgoing_emails")
