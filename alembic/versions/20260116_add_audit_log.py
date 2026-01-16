"""Add audit_log table.

Revision ID: 20260116_add_audit_log
Revises: 20260116_add_app_settings
Create Date: 2026-01-16
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260116_add_audit_log"
down_revision = "20260116_add_app_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add audit_log table."""

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=50), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("entity_type", sa.String(length=100), nullable=True),
        sa.Column("entity_id", sa.String(length=100), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_audit_log_actor", "audit_log", ["actor"])
    op.create_index("idx_audit_log_role", "audit_log", ["role"])
    op.create_index("idx_audit_log_action", "audit_log", ["action"])
    op.create_index("idx_audit_log_entity_type", "audit_log", ["entity_type"])
    op.create_index("idx_audit_log_entity_id", "audit_log", ["entity_id"])
    op.create_index("idx_audit_log_created_at", "audit_log", ["created_at"])


def downgrade() -> None:
    """Drop audit_log table."""

    op.drop_index("idx_audit_log_created_at", table_name="audit_log")
    op.drop_index("idx_audit_log_entity_id", table_name="audit_log")
    op.drop_index("idx_audit_log_entity_type", table_name="audit_log")
    op.drop_index("idx_audit_log_action", table_name="audit_log")
    op.drop_index("idx_audit_log_role", table_name="audit_log")
    op.drop_index("idx_audit_log_actor", table_name="audit_log")
    op.drop_table("audit_log")
