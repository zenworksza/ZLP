"""Phase 2 fixes: Add encrypted secret storage and replay prevention

Revision ID: 002
Revises: 001
Create Date: 2026-06-11

"""
from alembic import op
import sqlalchemy as sa

revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add encrypted secret columns to installs table
    op.add_column(
        'installs',
        sa.Column('shared_secret_encrypted', sa.String(), nullable=False, server_default=''),
    )
    op.add_column(
        'installs',
        sa.Column('shared_secret_nonce', sa.String(), nullable=False, server_default=''),
    )

    # Remove server defaults now that columns are populated
    # (In production, you'd migrate existing data first)
    op.alter_column('installs', 'shared_secret_encrypted', server_default=None)
    op.alter_column('installs', 'shared_secret_nonce', server_default=None)


def downgrade() -> None:
    op.drop_column('installs', 'shared_secret_nonce')
    op.drop_column('installs', 'shared_secret_encrypted')
