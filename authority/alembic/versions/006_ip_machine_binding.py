"""Add source_ip to heartbeat_log and registered_ip to installs

Revision ID: 006
Revises: 005
Create Date: 2026-06-23
"""
from alembic import op
import sqlalchemy as sa

revision = '006'
down_revision = '005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('installs', sa.Column('registered_ip', sa.String(), nullable=True))
    op.add_column('heartbeat_log', sa.Column('source_ip', sa.String(), nullable=True))
    op.create_index('idx_heartbeat_source_ip', 'heartbeat_log', ['source_ip'])


def downgrade() -> None:
    op.drop_index('idx_heartbeat_source_ip', table_name='heartbeat_log')
    op.drop_column('heartbeat_log', 'source_ip')
    op.drop_column('installs', 'registered_ip')
