"""add lease templates and signing workflow

Revision ID: 51aed2f30e48
Revises: e1f2a3b4c5d6
Create Date: 2026-05-08 10:01:17.910878

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '51aed2f30e48'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('lease_templates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('organization_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=True),
    sa.Column('body_markdown', sa.Text(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('lease_templates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_lease_templates_organization_id'), ['organization_id'], unique=False)
    op.create_index(
        "uq_lease_templates_default_per_org",
        "lease_templates",
        ["organization_id"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )

    with op.batch_alter_table('leases', schema=None) as batch_op:
        batch_op.add_column(sa.Column('template_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('signed_token_hash', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('signing_sent_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('signed_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('signed_ip', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('signed_user_agent', sa.String(length=512), nullable=True))
        batch_op.add_column(sa.Column('signed_pdf_filename', sa.String(length=512), nullable=True))
        batch_op.create_index(batch_op.f('ix_leases_signed_token_hash'), ['signed_token_hash'], unique=False)
        batch_op.create_index(batch_op.f('ix_leases_template_id'), ['template_id'], unique=False)
        batch_op.create_foreign_key(None, 'lease_templates', ['template_id'], ['id'], ondelete='SET NULL')


def downgrade():
    with op.batch_alter_table('leases', schema=None) as batch_op:
        batch_op.drop_constraint(None, type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_leases_template_id'))
        batch_op.drop_index(batch_op.f('ix_leases_signed_token_hash'))
        batch_op.drop_column('signed_pdf_filename')
        batch_op.drop_column('signed_user_agent')
        batch_op.drop_column('signed_ip')
        batch_op.drop_column('signed_at')
        batch_op.drop_column('signing_sent_at')
        batch_op.drop_column('signed_token_hash')
        batch_op.drop_column('template_id')

    op.drop_index("uq_lease_templates_default_per_org", table_name="lease_templates")

    with op.batch_alter_table('lease_templates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_lease_templates_organization_id'))

    op.drop_table('lease_templates')
