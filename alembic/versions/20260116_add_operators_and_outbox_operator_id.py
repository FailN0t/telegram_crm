"""Add operators table and operator_id to outbox.

Revision ID: 20260116_add_operators
Revises: 20260116_add_telegram_accounts
Create Date: 2026-01-16
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260116_add_operators"
down_revision = "20260116_add_telegram_accounts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add operators table and operator_id column."""

    op.create_table(
        "operators",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("username", sa.String(length=100), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=True),
        sa.Column("email", sa.String(length=100), nullable=True),
        sa.Column("hourly_limit", sa.Integer(), nullable=False, server_default=sa.text("50")),
        sa.Column("daily_limit", sa.Integer(), nullable=False, server_default=sa.text("200")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_operators_username", "operators", ["username"], unique=True)
    op.create_index("idx_operators_email", "operators", ["email"], unique=True)

    with op.batch_alter_table("message_outbox") as batch:
        batch.add_column(sa.Column("operator_id", sa.Integer(), nullable=True))
        batch.create_index("idx_message_outbox_operator_id", ["operator_id"])
        batch.create_foreign_key(
            "fk_message_outbox_operator_id",
            "operators",
            ["operator_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    """Remove operators table and operator_id column."""

    with op.batch_alter_table("message_outbox") as batch:
        batch.drop_constraint("fk_message_outbox_operator_id", type_="foreignkey")
        batch.drop_index("idx_message_outbox_operator_id")
        batch.drop_column("operator_id")

    op.drop_index("idx_operators_email", table_name="operators")
    op.drop_index("idx_operators_username", table_name="operators")
    op.drop_table("operators")
