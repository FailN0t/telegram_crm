"""Add ui_auth_attempts table for magic link authentication.

Revision ID: 20260121_add_ui_auth_attempts_table
Revises: 20260121_merge_heads_for_magic_link
Create Date: 2026-01-21

Fix #169: Magic Link авторизация через Telegram
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260121_add_ui_auth_attempts_table"
down_revision = "20260121_merge_heads_for_magic_link"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create ui_auth_attempts table for audit trail of magic link auth attempts."""
    op.create_table(
        'ui_auth_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False, comment='Magic link UUID token'),
        sa.Column('telegram_user_id', sa.BigInteger(), nullable=True, comment='Telegram user ID if known'),
        sa.Column('ip_address', sa.String(length=45), nullable=True, comment='Client IP address'),
        sa.Column('user_agent', sa.Text(), nullable=True, comment='Client user agent'),
        sa.Column('success', sa.Boolean(), nullable=False, comment='Whether auth attempt was successful'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.text('NOW()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        comment='Audit trail for UI magic link authentication attempts'
    )

    # Create index on token for fast lookup
    op.create_index('ix_ui_auth_attempts_token', 'ui_auth_attempts', ['token'])

    # Create index on created_at for retention cleanup
    op.create_index('ix_ui_auth_attempts_created_at', 'ui_auth_attempts', ['created_at'])


def downgrade() -> None:
    """Drop ui_auth_attempts table."""
    op.drop_index('ix_ui_auth_attempts_created_at', table_name='ui_auth_attempts')
    op.drop_index('ix_ui_auth_attempts_token', table_name='ui_auth_attempts')
    op.drop_table('ui_auth_attempts')
