"""Add media fields to ui_message_history.

Revision ID: 20260114_add_ui_message_media
Revises: 20260114_add_ui_event_log
Create Date: 2026-01-14
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260114_add_ui_message_media"
down_revision = "20260114_add_ui_event_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ui_message_history", sa.Column("media_url", sa.Text(), nullable=True))
    op.add_column("ui_message_history", sa.Column("media_name", sa.String(length=255), nullable=True))
    op.add_column("ui_message_history", sa.Column("media_mime", sa.String(length=255), nullable=True))
    op.add_column("ui_message_history", sa.Column("media_size", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("ui_message_history", "media_size")
    op.drop_column("ui_message_history", "media_mime")
    op.drop_column("ui_message_history", "media_name")
    op.drop_column("ui_message_history", "media_url")
