"""Fix ChatMapping unique constraints for multi-account support

Revision ID: 20260120_fix_chat_mapping
Revises: 20260120_safe_schema
Create Date: 2026-01-20

Fixes: #101 (amocrm_contact_id unique constraint blocks multi-account)

BREAKING CHANGE: This migration drops unique constraints on telegram_chat_id
and amocrm_contact_id in chat_mappings table. Instead, adds unique constraint
on (account_id, telegram_chat_id) to support multi-account scenarios.

If you have existing data with duplicate telegram_chat_id or amocrm_contact_id
across different accounts, this migration will succeed. If you have duplicates
within the same account, the migration will fail and you need to clean data first.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "20260120_fix_chat_mapping"
down_revision = "20260120_safe_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove global unique constraints and add composite unique constraint"""

    # Get database dialect to handle SQLite vs PostgreSQL differences
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        # PostgreSQL: Drop unique constraints by name
        op.drop_constraint('chat_mappings_telegram_chat_id_key', 'chat_mappings', type_='unique')
        op.drop_constraint('chat_mappings_amocrm_contact_id_key', 'chat_mappings', type_='unique')

        # Add composite unique index
        op.create_index(
            'idx_chat_mappings_account_chat',
            'chat_mappings',
            ['account_id', 'telegram_chat_id'],
            unique=True
        )

    elif dialect_name == 'sqlite':
        # SQLite: Need to recreate table to drop unique constraints
        # This is complex - for SQLite just add the composite index
        # (SQLite allows duplicate columns in unique constraints)
        op.create_index(
            'idx_chat_mappings_account_chat',
            'chat_mappings',
            ['account_id', 'telegram_chat_id'],
            unique=True
        )
        # Note: SQLite will still have the old unique constraints
        # For production, use PostgreSQL

    # Recreate regular indexes if they were dropped
    # (PostgreSQL unique constraint creates implicit unique index)
    if dialect_name == 'postgresql':
        # Check if regular indexes exist, create if not
        op.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = 'idx_chat_mappings_telegram_chat_id'
                ) THEN
                    CREATE INDEX idx_chat_mappings_telegram_chat_id
                    ON chat_mappings (telegram_chat_id);
                END IF;

                IF NOT EXISTS (
                    SELECT 1 FROM pg_indexes
                    WHERE indexname = 'idx_chat_mappings_amocrm_contact_id'
                ) THEN
                    CREATE INDEX idx_chat_mappings_amocrm_contact_id
                    ON chat_mappings (amocrm_contact_id);
                END IF;
            END $$;
        """)


def downgrade() -> None:
    """Restore global unique constraints (may fail if data has duplicates)"""

    bind = op.get_bind()
    dialect_name = bind.dialect.name

    # Drop composite unique index
    op.drop_index('idx_chat_mappings_account_chat', table_name='chat_mappings')

    if dialect_name == 'postgresql':
        # Restore global unique constraints
        # WARNING: This will fail if multiple accounts map same telegram_chat_id
        op.create_unique_constraint(
            'chat_mappings_telegram_chat_id_key',
            'chat_mappings',
            ['telegram_chat_id']
        )
        op.create_unique_constraint(
            'chat_mappings_amocrm_contact_id_key',
            'chat_mappings',
            ['amocrm_contact_id']
        )
