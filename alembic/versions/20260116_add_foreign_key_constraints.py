"""Add foreign key constraints for data integrity.

Revision ID: 20260116_add_foreign_key_constraints
Revises: 20260114_add_ui_message_updated_at
Create Date: 2026-01-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "20260116_add_foreign_key_constraints"
down_revision = "20260114_add_ui_message_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add foreign key constraints with orphan cleanup."""

    # Get connection to execute cleanup queries
    conn = op.get_bind()

    # ========================================================================
    # 1. MessageDeliveryAttempt.outbox_id -> MessageOutbox.id
    # ========================================================================
    # Cleanup orphan delivery attempts (where outbox_id doesn't exist in message_outbox)
    conn.execute(text("""
        DELETE FROM message_delivery_attempts
        WHERE outbox_id NOT IN (SELECT id FROM message_outbox)
    """))

    # Add FK constraint with CASCADE (if outbox deleted, delete attempts)
    op.create_foreign_key(
        "fk_message_delivery_attempts_outbox_id",
        "message_delivery_attempts",
        "message_outbox",
        ["outbox_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # ========================================================================
    # 2. ChatProfile.telegram_chat_id -> ChatMapping.telegram_chat_id
    # ========================================================================
    # Cleanup orphan chat profiles (where telegram_chat_id doesn't exist in chat_mappings)
    conn.execute(text("""
        DELETE FROM chat_profiles
        WHERE telegram_chat_id NOT IN (SELECT telegram_chat_id FROM chat_mappings)
    """))

    # Add FK constraint with CASCADE (if chat mapping deleted, delete profile)
    op.create_foreign_key(
        "fk_chat_profiles_telegram_chat_id",
        "chat_profiles",
        "chat_mappings",
        ["telegram_chat_id"],
        ["telegram_chat_id"],
        ondelete="CASCADE",
    )

    # ========================================================================
    # 3. MessageOutbox.chat_id -> ChatMapping.telegram_chat_id
    # ========================================================================
    # Cleanup orphan outbox messages (where chat_id doesn't exist in chat_mappings)
    # Using CASCADE: orphan outbox messages without chat context are not useful
    conn.execute(text("""
        DELETE FROM message_outbox
        WHERE chat_id NOT IN (SELECT telegram_chat_id FROM chat_mappings)
    """))

    op.create_foreign_key(
        "fk_message_outbox_chat_id",
        "message_outbox",
        "chat_mappings",
        ["chat_id"],
        ["telegram_chat_id"],
        ondelete="CASCADE",
    )

    # ========================================================================
    # 4. UiMessageHistory.chat_id -> ChatMapping.telegram_chat_id
    # ========================================================================
    # Cleanup orphan UI messages (where chat_id doesn't exist in chat_mappings)
    conn.execute(text("""
        DELETE FROM ui_message_history
        WHERE chat_id NOT IN (SELECT telegram_chat_id FROM chat_mappings)
    """))

    # Add FK constraint with CASCADE (if chat mapping deleted, delete UI messages)
    op.create_foreign_key(
        "fk_ui_message_history_chat_id",
        "ui_message_history",
        "chat_mappings",
        ["chat_id"],
        ["telegram_chat_id"],
        ondelete="CASCADE",
    )

    # ========================================================================
    # 5. UiChat.chat_id -> ChatMapping.telegram_chat_id
    # ========================================================================
    # Cleanup orphan UI chats (where chat_id doesn't exist in chat_mappings)
    conn.execute(text("""
        DELETE FROM ui_chats
        WHERE chat_id NOT IN (SELECT telegram_chat_id FROM chat_mappings)
    """))

    # Add FK constraint with CASCADE (if chat mapping deleted, delete UI chat)
    op.create_foreign_key(
        "fk_ui_chats_chat_id",
        "ui_chats",
        "chat_mappings",
        ["chat_id"],
        ["telegram_chat_id"],
        ondelete="CASCADE",
    )

    # ========================================================================
    # Add indexes for FK fields if they don't exist already
    # ========================================================================
    # Note: Most indexes already exist based on database.py analysis
    # The following are already indexed:
    # - message_delivery_attempts.outbox_id (idx_message_delivery_attempts_outbox_id)
    # - chat_profiles.telegram_chat_id (idx_chat_profiles_telegram_chat_id)
    # - message_outbox.chat_id (idx_message_outbox_chat_id)
    # - ui_message_history.chat_id (idx_ui_message_history_chat_id)
    # - ui_chats.chat_id (idx_ui_chats_chat_id)


def downgrade() -> None:
    """Remove foreign key constraints."""

    # Drop FK constraints in reverse order
    op.drop_constraint(
        "fk_ui_chats_chat_id",
        "ui_chats",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_ui_message_history_chat_id",
        "ui_message_history",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_message_outbox_chat_id",
        "message_outbox",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_chat_profiles_telegram_chat_id",
        "chat_profiles",
        type_="foreignkey",
    )

    op.drop_constraint(
        "fk_message_delivery_attempts_outbox_id",
        "message_delivery_attempts",
        type_="foreignkey",
    )
