"""add audit log table

Revision ID: b5e1c9d27a84
Revises: a3f2d8b4e1c7
Create Date: 2026-04-24 19:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'b5e1c9d27a84'
down_revision = 'a3f2d8b4e1c7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('actor_type', sa.String(length=32), nullable=False),
        sa.Column('actor_id', sa.Integer(), nullable=True),
        sa.Column('actor_email', sa.String(length=255), nullable=True),
        sa.Column('organization_id', sa.Integer(), nullable=True),
        sa.Column('action', sa.String(length=128), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=True),
        sa.Column('target_type', sa.String(length=64), nullable=True),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('ip_address', sa.String(length=64), nullable=True),
        sa.Column('user_agent', sa.String(length=512), nullable=True),
        sa.Column('context', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(
            ['organization_id'], ['organizations.id'], ondelete='SET NULL'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_audit_logs_created_at'), ['created_at'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_audit_logs_actor_type'), ['actor_type'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_audit_logs_actor_id'), ['actor_id'], unique=False
        )
        batch_op.create_index(
            batch_op.f('ix_audit_logs_organization_id'),
            ['organization_id'],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f('ix_audit_logs_action'), ['action'], unique=False
        )


def downgrade():
    with op.batch_alter_table('audit_logs', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_audit_logs_action'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_organization_id'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_actor_id'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_actor_type'))
        batch_op.drop_index(batch_op.f('ix_audit_logs_created_at'))

    op.drop_table('audit_logs')
