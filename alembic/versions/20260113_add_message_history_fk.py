"""Add FK from message_history to chat_mappings.

Revision ID: 20260113_add_message_history_fk
Revises: 
Create Date: 2026-01-13
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260113_add_message_history_fk"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_foreign_key(
        "fk_message_history_chat_mapping_id",
        "message_history",
        "chat_mappings",
        ["chat_mapping_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_message_history_chat_mapping_id",
        "message_history",
        type_="foreignkey",
    )
