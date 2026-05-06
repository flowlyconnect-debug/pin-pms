"""add property_images table

Revision ID: b8c9d0e1f2a3
Revises: x7y8z9a0b1c2
Create Date: 2026-05-06 17:20:00
"""

from alembic import op
import sqlalchemy as sa


revision = "b8c9d0e1f2a3"
down_revision = "x7y8z9a0b1c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=1024), nullable=False),
        sa.Column("thumbnail_url", sa.String(length=1024), nullable=False),
        sa.Column("storage_key", sa.String(length=1024), nullable=False),
        sa.Column("thumbnail_storage_key", sa.String(length=1024), nullable=False),
        sa.Column("alt_text", sa.String(length=255), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["property_id"], ["properties.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("property_images", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_property_images_organization_id"), ["organization_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_property_images_property_id"), ["property_id"], unique=False)
    op.alter_column("property_images", "sort_order", server_default=None)


def downgrade() -> None:
    with op.batch_alter_table("property_images", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_property_images_property_id"))
        batch_op.drop_index(batch_op.f("ix_property_images_organization_id"))
    op.drop_table("property_images")
