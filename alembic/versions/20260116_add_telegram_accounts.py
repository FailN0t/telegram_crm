"""Add telegram_accounts and account_id columns.

Revision ID: 20260116_add_telegram_accounts
Revises: 20260116_add_foreign_key_constraints
Create Date: 2026-01-16
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision = "20260116_add_telegram_accounts"
down_revision = "20260116_add_foreign_key_constraints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add telegram_accounts table and bind existing data to default account."""

    op.create_table(
        "telegram_accounts",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("phone_number", sa.String(length=32), nullable=False),
        sa.Column("session_string", sa.Text(), nullable=True),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_telegram_accounts_phone", "telegram_accounts", ["phone_number"], unique=True)
    op.create_index("idx_telegram_accounts_active", "telegram_accounts", ["is_active"])

    conn = op.get_bind()
    phone = None
    session_string = None
    try:
        result = conn.execute(text("SELECT phone, session_string FROM telegram_sessions ORDER BY id LIMIT 1"))
        row = result.first()
        if row:
            phone = row[0]
            session_string = row[1]
    except Exception:
        phone = None

    if not phone:
        phone = "default"

    conn.execute(
        text(
            "INSERT INTO telegram_accounts (phone_number, session_string, label, is_active) "
            "VALUES (:phone, :session_string, :label, :is_active)"
        ),
        {
            "phone": phone,
            "session_string": session_string,
            "label": phone,
            "is_active": True,
        },
    )

    default_account_id = conn.execute(
        text("SELECT id FROM telegram_accounts ORDER BY id LIMIT 1")
    ).scalar()

    if default_account_id is None:
        raise RuntimeError("Failed to create default telegram account")

    account_default = sa.text(str(default_account_id))

    with op.batch_alter_table("chat_mappings") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=False, server_default=account_default))
        batch.create_index("idx_chat_mappings_account_id", ["account_id"])
        batch.create_foreign_key(
            "fk_chat_mappings_account_id",
            "telegram_accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("chat_profiles") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=False, server_default=account_default))
        batch.create_index("idx_chat_profiles_account_id", ["account_id"])
        batch.create_foreign_key(
            "fk_chat_profiles_account_id",
            "telegram_accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("message_outbox") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=False, server_default=account_default))
        batch.create_index("idx_message_outbox_account_id", ["account_id"])
        batch.create_foreign_key(
            "fk_message_outbox_account_id",
            "telegram_accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("message_history") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=False, server_default=account_default))
        batch.create_index("idx_message_history_account_id", ["account_id"])
        batch.create_foreign_key(
            "fk_message_history_account_id",
            "telegram_accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("ui_message_history") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=False, server_default=account_default))
        batch.create_index("idx_ui_message_history_account_id", ["account_id"])
        batch.create_foreign_key(
            "fk_ui_message_history_account_id",
            "telegram_accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("ui_chats") as batch:
        batch.add_column(sa.Column("account_id", sa.Integer(), nullable=False, server_default=account_default))
        batch.create_index("idx_ui_chats_account_id", ["account_id"])
        batch.create_foreign_key(
            "fk_ui_chats_account_id",
            "telegram_accounts",
            ["account_id"],
            ["id"],
            ondelete="CASCADE",
        )

    conn.execute(text("UPDATE chat_mappings SET account_id = :account_id"), {"account_id": default_account_id})
    conn.execute(text("UPDATE chat_profiles SET account_id = :account_id"), {"account_id": default_account_id})
    conn.execute(text("UPDATE message_outbox SET account_id = :account_id"), {"account_id": default_account_id})
    conn.execute(text("UPDATE message_history SET account_id = :account_id"), {"account_id": default_account_id})
    conn.execute(text("UPDATE ui_message_history SET account_id = :account_id"), {"account_id": default_account_id})
    conn.execute(text("UPDATE ui_chats SET account_id = :account_id"), {"account_id": default_account_id})


def downgrade() -> None:
    """Remove multi-account support columns and table."""

    with op.batch_alter_table("ui_chats") as batch:
        batch.drop_constraint("fk_ui_chats_account_id", type_="foreignkey")
        batch.drop_index("idx_ui_chats_account_id")
        batch.drop_column("account_id")

    with op.batch_alter_table("ui_message_history") as batch:
        batch.drop_constraint("fk_ui_message_history_account_id", type_="foreignkey")
        batch.drop_index("idx_ui_message_history_account_id")
        batch.drop_column("account_id")

    with op.batch_alter_table("message_history") as batch:
        batch.drop_constraint("fk_message_history_account_id", type_="foreignkey")
        batch.drop_index("idx_message_history_account_id")
        batch.drop_column("account_id")

    with op.batch_alter_table("message_outbox") as batch:
        batch.drop_constraint("fk_message_outbox_account_id", type_="foreignkey")
        batch.drop_index("idx_message_outbox_account_id")
        batch.drop_column("account_id")

    with op.batch_alter_table("chat_profiles") as batch:
        batch.drop_constraint("fk_chat_profiles_account_id", type_="foreignkey")
        batch.drop_index("idx_chat_profiles_account_id")
        batch.drop_column("account_id")

    with op.batch_alter_table("chat_mappings") as batch:
        batch.drop_constraint("fk_chat_mappings_account_id", type_="foreignkey")
        batch.drop_index("idx_chat_mappings_account_id")
        batch.drop_column("account_id")

    op.drop_index("idx_telegram_accounts_active", table_name="telegram_accounts")
    op.drop_index("idx_telegram_accounts_phone", table_name="telegram_accounts")
    op.drop_table("telegram_accounts")
