"""add api key model

Revision ID: a3f2d8b4e1c7
Revises: 08ce29e80519
Create Date: 2026-04-24 18:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = 'a3f2d8b4e1c7'
down_revision = '08ce29e80519'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('organization_id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('key_prefix', sa.String(length=32), nullable=False),
        sa.Column('key_hash', sa.String(length=128), nullable=False),
        sa.Column('scopes', sa.String(length=512), nullable=False, server_default=''),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id']),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f('ix_api_keys_organization_id'), ['organization_id'], unique=False
        )
        batch_op.create_index(batch_op.f('ix_api_keys_user_id'), ['user_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_api_keys_key_prefix'), ['key_prefix'], unique=False)
        batch_op.create_index(batch_op.f('ix_api_keys_key_hash'), ['key_hash'], unique=True)


def downgrade():
    with op.batch_alter_table('api_keys', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_api_keys_key_hash'))
        batch_op.drop_index(batch_op.f('ix_api_keys_key_prefix'))
        batch_op.drop_index(batch_op.f('ix_api_keys_user_id'))
        batch_op.drop_index(batch_op.f('ix_api_keys_organization_id'))

    op.drop_table('api_keys')
