"""Remove ui_chats chat_id FK constraint.

Revision ID: 20260118_remove_ui_chats_fk
Revises: 20260116_add_foreign_key_constraints
Create Date: 2026-01-18
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260118_remove_ui_chats_fk"
down_revision = "20260116_add_foreign_key_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Remove UI table FK constraints to chat_mappings.

    The FK constraints prevent creating UI entries for chats
    that are not yet mapped to CRM contacts. This is wrong because:
    - ui_chats and ui_message_history store ALL chats visible in UI
    - chat_mappings stores ONLY CRM-linked chats
    - Not all chats need to be linked to CRM
    """
    # Drop FK constraint ui_chats.chat_id -> chat_mappings.telegram_chat_id
    op.drop_constraint(
        "fk_ui_chats_chat_id",
        "ui_chats",
        type_="foreignkey",
    )

    # Drop FK constraint ui_message_history.chat_id -> chat_mappings.telegram_chat_id
    op.drop_constraint(
        "fk_ui_message_history_chat_id",
        "ui_message_history",
        type_="foreignkey",
    )


def downgrade() -> None:
    """Re-add the FK constraint (not recommended)."""
    # Note: This will fail if there are orphan ui_chats records
    op.create_foreign_key(
        "fk_ui_chats_chat_id",
        "ui_chats",
        "chat_mappings",
        ["chat_id"],
        ["telegram_chat_id"],
        ondelete="CASCADE",
    )
