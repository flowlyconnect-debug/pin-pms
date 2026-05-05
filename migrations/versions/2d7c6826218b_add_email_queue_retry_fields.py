"""add_email_queue_retry_fields

Revision ID: 2d7c6826218b
Revises: a7b8c9d0e1f2
Create Date: 2026-05-05 11:39:16.296275

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '2d7c6826218b'
down_revision = 'a7b8c9d0e1f2'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('outgoing_emails', schema=None) as batch_op:
        batch_op.add_column(sa.Column('organization_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('recipient_email', sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column('attempt_count', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.create_index(batch_op.f('ix_outgoing_emails_next_attempt_at'), ['next_attempt_at'], unique=False)
        batch_op.create_index(batch_op.f('ix_outgoing_emails_organization_id'), ['organization_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_outgoing_emails_recipient_email'), ['recipient_email'], unique=False)
        batch_op.create_foreign_key(None, 'organizations', ['organization_id'], ['id'])


def downgrade():
    with op.batch_alter_table('outgoing_emails', schema=None) as batch_op:
        batch_op.drop_constraint('outgoing_emails_organization_id_fkey', type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_outgoing_emails_recipient_email'))
        batch_op.drop_index(batch_op.f('ix_outgoing_emails_organization_id'))
        batch_op.drop_index(batch_op.f('ix_outgoing_emails_next_attempt_at'))
        batch_op.drop_column('next_attempt_at')
        batch_op.drop_column('attempt_count')
        batch_op.drop_column('recipient_email')
        batch_op.drop_column('organization_id')
