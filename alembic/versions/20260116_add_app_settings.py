"""Add app_settings table for admin overrides.

Revision ID: 20260116_add_app_settings
Revises: 20260116_add_operators
Create Date: 2026-01-16
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260116_add_app_settings"
down_revision = "20260116_add_operators"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add app_settings table."""

    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), primary_key=True, nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_app_settings_key", "app_settings", ["key"], unique=False)
    op.create_index("idx_app_settings_updated_at", "app_settings", ["updated_at"], unique=False)


def downgrade() -> None:
    """Drop app_settings table."""

    op.drop_index("idx_app_settings_updated_at", table_name="app_settings")
    op.drop_index("idx_app_settings_key", table_name="app_settings")
    op.drop_table("app_settings")
