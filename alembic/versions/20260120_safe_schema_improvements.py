"""Safe schema improvements: indexes, check constraints

Revision ID: 20260120_safe_schema
Revises: 20260120_merge_heads
Create Date: 2026-01-20

Fixes: #32, #33, #34, #35, #104, #106, #107, #108, #109
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260120_safe_schema"
down_revision = "20260120_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add safe schema improvements"""

    # #32, #107: CHECK constraints for message statuses
    op.create_check_constraint(
        "ck_message_outbox_status",
        "message_outbox",
        "status IN ('queued', 'processing', 'sent', 'failed', 'dead')"
    )

    op.create_check_constraint(
        "ck_ui_message_history_status",
        "ui_message_history",
        "status IN ('queued', 'processing', 'sent', 'failed', 'dead', 'received')"
    )

    op.create_check_constraint(
        "ck_ui_message_history_direction",
        "ui_message_history",
        "direction IN ('inbound', 'outbound')"
    )

    # #34: Index (account_id, created_at) for MessageHistory
    op.create_index(
        "idx_message_history_account_created",
        "message_history",
        ["account_id", "created_at"],
        unique=False
    )

    # #35, #108: Composite index (status, next_attempt_at, chat_id) for MessageOutbox
    # This replaces the simpler (status, next_attempt_at) index if it exists
    # Note: idx_message_outbox_status_next_attempt already exists from 20260116_add_index_tuning
    # Adding chat_id to it for better performance
    op.create_index(
        "idx_message_outbox_status_next_chat",
        "message_outbox",
        ["status", "next_attempt_at", "chat_id"],
        unique=False
    )

    # #109: Index (direction, created_at) for MessageHistory
    op.create_index(
        "idx_message_history_direction_created",
        "message_history",
        ["direction", "created_at"],
        unique=False
    )

    op.create_index(
        "idx_ui_message_history_direction_created",
        "ui_message_history",
        ["direction", "created_at"],
        unique=False
    )


def downgrade() -> None:
    """Remove safe schema improvements"""

    # Drop indexes
    op.drop_index("idx_ui_message_history_direction_created", table_name="ui_message_history")
    op.drop_index("idx_message_history_direction_created", table_name="message_history")
    op.drop_index("idx_message_outbox_status_next_chat", table_name="message_outbox")
    op.drop_index("idx_message_history_account_created", table_name="message_history")

    # Drop check constraints
    op.drop_constraint("ck_ui_message_history_direction", "ui_message_history")
    op.drop_constraint("ck_ui_message_history_status", "ui_message_history")
    op.drop_constraint("ck_message_outbox_status", "message_outbox")
