"""Initial ZLP schema

Revision ID: 001
Revises:
Create Date: 2026-06-05

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Products table
    op.create_table(
        'products',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False, primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('slug', sa.Text(), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()'))
    )

    # License keys table
    op.create_table(
        'license_keys',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False, primary_key=True),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('key', sa.Text(), nullable=False, unique=True),
        sa.Column('plan', sa.Text(), nullable=False),  # starter | professional | enterprise
        sa.Column('seats', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default='active'),  # active | suspended | revoked
        sa.Column('customer_ref', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    )

    # Installs table
    op.create_table(
        'installs',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False, primary_key=True),
        sa.Column('key_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('install_id', sa.Text(), nullable=False, unique=True),
        sa.Column('domain', sa.Text(), nullable=False),
        sa.Column('fingerprint', sa.Text(), nullable=False),
        sa.Column('machine_id', sa.Text(), nullable=False),
        sa.Column('first_seen', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_heartbeat', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.Text(), nullable=False, server_default='active'),  # active | blocked | anomalous
        sa.ForeignKeyConstraint(['key_id'], ['license_keys.id'], ondelete='CASCADE'),
    )

    # Heartbeat log table (append-only)
    op.create_table(
        'heartbeat_log',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False, primary_key=True),
        sa.Column('install_id', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('payload_hash', sa.Text(), nullable=True),
        sa.Column('response_status', sa.Text(), nullable=True),  # valid | revoked | fingerprint_mismatch | error
    )

    # Anomaly events table
    op.create_table(
        'anomaly_events',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False, primary_key=True),
        sa.Column('install_id', sa.Text(), nullable=False),
        sa.Column('score', sa.Float(), nullable=False),
        sa.Column('reason', sa.Text(), nullable=False),
        sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('resolved_at', sa.DateTime(timezone=True), nullable=True),
    )

    # Audit trail table
    op.create_table(
        'audit_trail',
        sa.Column('id', postgresql.UUID(as_uuid=True), server_default=sa.text('gen_random_uuid()'), nullable=False, primary_key=True),
        sa.Column('actor', sa.Text(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('target_type', sa.Text(), nullable=True),
        sa.Column('target_id', sa.Text(), nullable=True),
        sa.Column('timestamp', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('now()')),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    # Indexes
    op.create_index('idx_installs_key_id', 'installs', ['key_id'])
    op.create_index('idx_installs_install_id', 'installs', ['install_id'])
    op.create_index('idx_heartbeat_install_id', 'heartbeat_log', ['install_id'])
    op.create_index('idx_heartbeat_timestamp', 'heartbeat_log', ['timestamp'], postgresql_using='btree')
    op.create_index('idx_license_keys_key', 'license_keys', ['key'])
    op.create_index('idx_license_keys_product', 'license_keys', ['product_id'])


def downgrade() -> None:
    op.drop_index('idx_license_keys_product')
    op.drop_index('idx_license_keys_key')
    op.drop_index('idx_heartbeat_timestamp')
    op.drop_index('idx_heartbeat_install_id')
    op.drop_index('idx_installs_install_id')
    op.drop_index('idx_installs_key_id')
    op.drop_table('audit_trail')
    op.drop_table('anomaly_events')
    op.drop_table('heartbeat_log')
    op.drop_table('installs')
    op.drop_table('license_keys')
    op.drop_table('products')
