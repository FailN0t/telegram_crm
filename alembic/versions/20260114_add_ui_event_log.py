"""Add ui_event_log table.

Revision ID: 20260114_add_ui_event_log
Revises: 20260113_add_message_history_fk
Create Date: 2026-01-14
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260114_add_ui_event_log"
down_revision = "20260113_add_message_history_fk"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ui_event_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("message", sa.String(length=255), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_ui_event_log_level", "ui_event_log", ["level"])
    op.create_index("idx_ui_event_log_message", "ui_event_log", ["message"])
    op.create_index("idx_ui_event_log_created_at", "ui_event_log", ["created_at"])


def downgrade() -> None:
    op.drop_index("idx_ui_event_log_created_at", table_name="ui_event_log")
    op.drop_index("idx_ui_event_log_message", table_name="ui_event_log")
    op.drop_index("idx_ui_event_log_level", table_name="ui_event_log")
    op.drop_table("ui_event_log")
