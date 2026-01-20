"""Merge migration heads for magic link feature.

Revision ID: 20260121_merge_heads_for_magic_link
Revises: 20260120_add_check_constraint, 20260120_fix_composite_fk
Create Date: 2026-01-21
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260121_merge_heads_for_magic_link"
down_revision = ("20260120_add_check_constraint", "20260120_fix_composite_fk")
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Merge two migration branches - no schema changes needed."""
    pass


def downgrade() -> None:
    """Merge downgrade - no schema changes needed."""
    pass
