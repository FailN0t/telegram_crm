"""Fix composite FK constraints for multi-account support

Revision ID: 20260120_fix_composite_fk
Revises: 20260120_fix_chat_mapping
Create Date: 2026-01-20

Fixes: #102, #103, #119 (FK constraints on non-primary keys)

BREAKING CHANGE: This migration replaces simple FK constraints on telegram_chat_id
with composite FK constraints on (account_id, telegram_chat_id). This is required
for multi-account support where telegram_chat_id is not globally unique.

Tables affected:
- chat_profiles
- message_outbox
- ui_message_history
- ui_chats
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260120_fix_composite_fk"
down_revision = "20260120_fix_chat_mapping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Replace simple FK constraints with composite FK constraints"""

    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        # =========================================================================
        # chat_profiles table
        # =========================================================================

        # Drop old FK constraint on telegram_chat_id
        op.drop_constraint(
            'chat_profiles_telegram_chat_id_fkey',
            'chat_profiles',
            type_='foreignkey'
        )

        # Drop old unique constraint on telegram_chat_id
        op.execute("ALTER TABLE chat_profiles DROP CONSTRAINT IF EXISTS chat_profiles_telegram_chat_id_key")

        # Add composite FK constraint
        op.create_foreign_key(
            'fk_chat_profiles_account_chat',
            'chat_profiles',
            'chat_mappings',
            ['account_id', 'telegram_chat_id'],
            ['account_id', 'telegram_chat_id'],
            ondelete='CASCADE'
        )

        # Add composite unique index
        op.create_index(
            'idx_chat_profiles_account_chat',
            'chat_profiles',
            ['account_id', 'telegram_chat_id'],
            unique=True
        )

        # =========================================================================
        # message_outbox table
        # =========================================================================

        # Drop old FK constraint on chat_id -> telegram_chat_id
        op.drop_constraint(
            'message_outbox_chat_id_fkey',
            'message_outbox',
            type_='foreignkey'
        )

        # Add composite FK constraint
        op.create_foreign_key(
            'fk_message_outbox_account_chat',
            'message_outbox',
            'chat_mappings',
            ['account_id', 'chat_id'],
            ['account_id', 'telegram_chat_id'],
            ondelete='CASCADE'
        )

        # Add composite index for performance
        op.create_index(
            'idx_message_outbox_account_chat',
            'message_outbox',
            ['account_id', 'chat_id']
        )

        # =========================================================================
        # ui_message_history table
        # =========================================================================

        # Drop old FK constraint on chat_id -> telegram_chat_id
        op.drop_constraint(
            'ui_message_history_chat_id_fkey',
            'ui_message_history',
            type_='foreignkey'
        )

        # Add composite FK constraint
        op.create_foreign_key(
            'fk_ui_message_history_account_chat',
            'ui_message_history',
            'chat_mappings',
            ['account_id', 'chat_id'],
            ['account_id', 'telegram_chat_id'],
            ondelete='CASCADE'
        )

        # Add composite index for performance
        op.create_index(
            'idx_ui_message_history_account_chat',
            'ui_message_history',
            ['account_id', 'chat_id']
        )

        # =========================================================================
        # ui_chats table
        # =========================================================================

        # Drop old FK constraint on chat_id -> telegram_chat_id
        op.drop_constraint(
            'ui_chats_chat_id_fkey',
            'ui_chats',
            type_='foreignkey'
        )

        # Drop old unique constraint on chat_id
        op.execute("ALTER TABLE ui_chats DROP CONSTRAINT IF EXISTS ui_chats_chat_id_key")

        # Add composite FK constraint
        op.create_foreign_key(
            'fk_ui_chats_account_chat',
            'ui_chats',
            'chat_mappings',
            ['account_id', 'chat_id'],
            ['account_id', 'telegram_chat_id'],
            ondelete='CASCADE'
        )

        # Add composite unique index
        op.create_index(
            'idx_ui_chats_account_chat',
            'ui_chats',
            ['account_id', 'chat_id'],
            unique=True
        )

    elif dialect_name == 'sqlite':
        # SQLite doesn't support dropping constraints easily
        # Composite FK will be created when table is created with new schema
        # For existing SQLite databases, this is non-critical (testing only)
        pass


def downgrade() -> None:
    """Restore simple FK constraints (may fail if data has multi-account setup)"""

    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        # WARNING: This downgrade will fail if:
        # 1. Multiple accounts have same telegram_chat_id
        # 2. chat_profiles or ui_chats have duplicate chat_ids across accounts

        # chat_profiles
        op.drop_constraint('fk_chat_profiles_account_chat', 'chat_profiles', type_='foreignkey')
        op.drop_index('idx_chat_profiles_account_chat', table_name='chat_profiles')
        op.create_foreign_key(
            'chat_profiles_telegram_chat_id_fkey',
            'chat_profiles',
            'chat_mappings',
            ['telegram_chat_id'],
            ['telegram_chat_id'],
            ondelete='CASCADE'
        )
        op.execute("ALTER TABLE chat_profiles ADD CONSTRAINT chat_profiles_telegram_chat_id_key UNIQUE (telegram_chat_id)")

        # message_outbox
        op.drop_constraint('fk_message_outbox_account_chat', 'message_outbox', type_='foreignkey')
        op.drop_index('idx_message_outbox_account_chat', table_name='message_outbox')
        op.create_foreign_key(
            'message_outbox_chat_id_fkey',
            'message_outbox',
            'chat_mappings',
            ['chat_id'],
            ['telegram_chat_id'],
            ondelete='CASCADE'
        )

        # ui_message_history
        op.drop_constraint('fk_ui_message_history_account_chat', 'ui_message_history', type_='foreignkey')
        op.drop_index('idx_ui_message_history_account_chat', table_name='ui_message_history')
        op.create_foreign_key(
            'ui_message_history_chat_id_fkey',
            'ui_message_history',
            'chat_mappings',
            ['chat_id'],
            ['telegram_chat_id'],
            ondelete='CASCADE'
        )

        # ui_chats
        op.drop_constraint('fk_ui_chats_account_chat', 'ui_chats', type_='foreignkey')
        op.drop_index('idx_ui_chats_account_chat', table_name='ui_chats')
        op.create_foreign_key(
            'ui_chats_chat_id_fkey',
            'ui_chats',
            'chat_mappings',
            ['chat_id'],
            ['telegram_chat_id'],
            ondelete='CASCADE'
        )
        op.execute("ALTER TABLE ui_chats ADD CONSTRAINT ui_chats_chat_id_key UNIQUE (chat_id)")
