"""Add updated_at to ui_message_history.

Revision ID: 20260114_add_ui_message_updated_at
Revises: 20260114_add_chat_profile_compliance
Create Date: 2026-01-14
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260114_add_ui_message_updated_at"
down_revision = "20260114_add_chat_profile_compliance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ui_message_history", sa.Column("updated_at", sa.DateTime(), nullable=True))
    op.create_index("idx_ui_message_history_updated_at", "ui_message_history", ["updated_at"])


def downgrade() -> None:
    op.drop_index("idx_ui_message_history_updated_at", table_name="ui_message_history")
    op.drop_column("ui_message_history", "updated_at")
