"""Add contact_add_log table for tracking contact additions.

This table is used by Contact Manager to:
1. Track all attempts to add Telegram users to contacts
2. Enforce rate limits (inbound: 50/hour, 150/day; outbound: 3/hour, 10/day)
3. Prevent Telegram account bans via Circuit Breaker pattern
4. Audit trail for compliance and debugging

Revision ID: 20260120_add_contact_add_log
Revises: 20260120_add_read_at
Create Date: 2026-01-20
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260120_add_contact_add_log"
down_revision = "20260120_add_read_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Create contact_add_log table with indexes for efficient rate limiting queries.

    Indexes strategy:
    - Single column indexes for basic queries
    - Composite indexes for rate limit queries (direction + timestamp)
    - Composite index for checking if user was already added
    """
    op.create_table(
        'contact_add_log',
        sa.Column('id', sa.Integer(), primary_key=True, nullable=False),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=False),
        sa.Column('direction', sa.String(10), nullable=False),
        sa.Column('source', sa.String(50), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
    )

    # Single column indexes
    op.create_index('idx_contact_add_log_user', 'contact_add_log', ['telegram_user_id'])
    op.create_index('idx_contact_add_log_direction', 'contact_add_log', ['direction'])
    op.create_index('idx_contact_add_log_success', 'contact_add_log', ['success'])
    op.create_index('idx_contact_add_log_created', 'contact_add_log', ['created_at'])

    # Composite indexes for efficient queries
    op.create_index(
        'idx_contact_add_log_direction_created',
        'contact_add_log',
        ['direction', 'created_at']
    )
    op.create_index(
        'idx_contact_add_log_user_success',
        'contact_add_log',
        ['telegram_user_id', 'success']
    )


def downgrade() -> None:
    """Remove contact_add_log table and all indexes."""
    # Drop indexes first
    op.drop_index('idx_contact_add_log_user_success', table_name='contact_add_log')
    op.drop_index('idx_contact_add_log_direction_created', table_name='contact_add_log')
    op.drop_index('idx_contact_add_log_created', table_name='contact_add_log')
    op.drop_index('idx_contact_add_log_success', table_name='contact_add_log')
    op.drop_index('idx_contact_add_log_direction', table_name='contact_add_log')
    op.drop_index('idx_contact_add_log_user', table_name='contact_add_log')

    # Drop table
    op.drop_table('contact_add_log')
