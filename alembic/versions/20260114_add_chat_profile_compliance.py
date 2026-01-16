"""Add compliance fields to chat_profiles.

Revision ID: 20260114_add_chat_profile_compliance
Revises: 20260114_add_ui_message_media
Create Date: 2026-01-14
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260114_add_chat_profile_compliance"
down_revision = "20260114_add_ui_message_media"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("chat_profiles", sa.Column("has_consent", sa.Boolean(), nullable=True))
    op.add_column("chat_profiles", sa.Column("opted_out", sa.Boolean(), nullable=True))
    op.add_column("chat_profiles", sa.Column("quiet_hours_start", sa.String(length=8), nullable=True))
    op.add_column("chat_profiles", sa.Column("quiet_hours_end", sa.String(length=8), nullable=True))
    op.add_column("chat_profiles", sa.Column("timezone", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("chat_profiles", "timezone")
    op.drop_column("chat_profiles", "quiet_hours_end")
    op.drop_column("chat_profiles", "quiet_hours_start")
    op.drop_column("chat_profiles", "opted_out")
    op.drop_column("chat_profiles", "has_consent")
