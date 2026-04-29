"""add email template text/html content columns

Revision ID: r1a2b3c4d5e6
Revises: 00f8cc745fd8
Create Date: 2026-04-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "r1a2b3c4d5e6"
down_revision = "00f8cc745fd8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("email_templates", sa.Column("text_content", sa.Text(), nullable=True))
    op.add_column("email_templates", sa.Column("html_content", sa.Text(), nullable=True))
    op.execute("UPDATE email_templates SET text_content = body_text WHERE text_content IS NULL")
    op.execute("UPDATE email_templates SET html_content = body_html WHERE html_content IS NULL")
    op.alter_column("email_templates", "text_content", nullable=False)


def downgrade() -> None:
    op.drop_column("email_templates", "html_content")
    op.drop_column("email_templates", "text_content")
