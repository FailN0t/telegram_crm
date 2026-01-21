"""Add CHECK constraint for chat_mapping_id > 0

Revision ID: 20260120_add_check_constraint
Revises: 20260120_add_contact_add_log
Create Date: 2026-01-20

Fixes: #117 (chat_mapping_id=0 при mapping=None - invalid FK!)

This migration adds a CHECK constraint to ensure chat_mapping_id > 0 in message_history table.
This prevents invalid FK values like 0 or negative numbers.
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260120_add_check_constraint"
down_revision = "20260120_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add CHECK constraint to prevent chat_mapping_id <= 0"""

    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        # PostgreSQL: Add CHECK constraint
        op.create_check_constraint(
            'check_message_history_valid_mapping_id',
            'message_history',
            'chat_mapping_id > 0'
        )

    elif dialect_name == 'sqlite':
        # SQLite: CHECK constraints must be added during table creation
        # For existing SQLite databases, this is a no-op
        # New tables will get the constraint from the model definition
        pass


def downgrade() -> None:
    """Remove CHECK constraint"""

    bind = op.get_bind()
    dialect_name = bind.dialect.name

    if dialect_name == 'postgresql':
        # PostgreSQL: Drop CHECK constraint
        op.drop_constraint(
            'check_message_history_valid_mapping_id',
            'message_history',
            type_='check'
        )

    elif dialect_name == 'sqlite':
        # SQLite: No downgrade needed (constraint was not added)
        pass
