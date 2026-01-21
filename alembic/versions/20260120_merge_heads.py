"""Merge migration heads.

Revision ID: 20260120_merge_heads
Revises: 20260116_add_index_tuning, 20260120_add_contact_add_log
Create Date: 2026-01-20
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260120_merge_heads"
down_revision = ("20260116_add_index_tuning", "20260120_add_contact_add_log")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge two migration branches - no schema changes needed."""
    pass


def downgrade() -> None:
    """Merge downgrade - no schema changes needed."""
    pass
