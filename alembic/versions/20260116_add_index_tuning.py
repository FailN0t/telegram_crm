"""Add composite indexes for hot queries.

Revision ID: 20260116_add_index_tuning
Revises: 20260116_add_templates_and_tags
Create Date: 2026-01-16
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260116_add_index_tuning"
down_revision = "20260116_add_templates_and_tags"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add indexes for outbox/UI queries."""
    op.create_index(
        "idx_message_outbox_next_attempt_at",
        "message_outbox",
        ["next_attempt_at"],
        unique=False
    )
    op.create_index(
        "idx_message_outbox_status_next_attempt",
        "message_outbox",
        ["status", "next_attempt_at"],
        unique=False
    )
    op.create_index(
        "idx_message_inbox_created_at",
        "message_inbox",
        ["created_at"],
        unique=False
    )
    op.create_index(
        "idx_ui_message_history_account_chat_created",
        "ui_message_history",
        ["account_id", "chat_id", "created_at"],
        unique=False
    )
    op.create_index(
        "idx_ui_chats_account_last_timestamp",
        "ui_chats",
        ["account_id", "last_timestamp"],
        unique=False
    )


def downgrade() -> None:
    """Drop indexes added in upgrade."""
    op.drop_index("idx_ui_chats_account_last_timestamp", table_name="ui_chats")
    op.drop_index("idx_ui_message_history_account_chat_created", table_name="ui_message_history")
    op.drop_index("idx_message_inbox_created_at", table_name="message_inbox")
    op.drop_index("idx_message_outbox_status_next_attempt", table_name="message_outbox")
    op.drop_index("idx_message_outbox_next_attempt_at", table_name="message_outbox")
