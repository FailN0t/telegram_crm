"""Add read_at field to message_outbox for tracking message read status.

Revision ID: 20260120_add_read_at
Revises: 20260118_remove_ui_chats_fk
Create Date: 2026-01-20
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260120_add_read_at"
down_revision = "20260118_remove_ui_chats_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add read_at timestamp field to message_outbox table.

    This field tracks when a message was read by the recipient in Telegram.
    - NULL means message not yet read
    - TIMESTAMP means message was read at this time

    This enables proper "reading status" updates to Bitrix24 based on
    actual Telegram MessageRead events instead of immediate status after send.
    """
    op.add_column(
        "message_outbox",
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Add index for efficient queries of unread messages
    op.create_index(
        "idx_message_outbox_unread",
        "message_outbox",
        ["chat_id", "status", "read_at"],
        postgresql_where=sa.text("status = 'sent' AND read_at IS NULL"),
    )


def downgrade() -> None:
    """Remove read_at field and index."""
    op.drop_index("idx_message_outbox_unread", table_name="message_outbox")
    op.drop_column("message_outbox", "read_at")
