"""Add delivery_status field to ui_message_history for AmoCRM widget

Revision ID: 20260122_add_delivery_status_to_ui_message_history
Revises: 20260121_add_ui_auth_attempts_table
Create Date: 2026-01-22

AmoCRM Widget Integration: Track Telegram delivery statuses (queued/sent/delivered/read/failed)
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260122_add_delivery_status_to_ui_message_history"
down_revision = ("20260116_add_index_tuning", "20260120_add_read_at")  # Merge migration
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add delivery_status column to ui_message_history table."""
    op.add_column(
        'ui_message_history',
        sa.Column('delivery_status', sa.String(length=20), server_default='queued', nullable=True)
    )

    # Create index on delivery_status for filtering
    op.create_index('idx_ui_message_history_delivery_status', 'ui_message_history', ['delivery_status'])


def downgrade() -> None:
    """Remove delivery_status column from ui_message_history table."""
    op.drop_index('idx_ui_message_history_delivery_status', table_name='ui_message_history')
    op.drop_column('ui_message_history', 'delivery_status')
