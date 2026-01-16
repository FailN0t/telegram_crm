"""Add message templates and tag catalog tables.

Revision ID: 20260116_add_templates_and_tags
Revises: 20260116_add_audit_log
Create Date: 2026-01-16
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260116_add_templates_and_tags"
down_revision = "20260116_add_audit_log"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add message_templates and tag_catalog tables."""

    op.create_table(
        "message_templates",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_message_templates_label", "message_templates", ["label"], unique=False)
    op.create_index("idx_message_templates_active", "message_templates", ["is_active"], unique=False)

    template_table = sa.table(
        "message_templates",
        sa.column("label", sa.String),
        sa.column("body", sa.Text),
        sa.column("is_active", sa.Boolean),
    )
    op.bulk_insert(
        template_table,
        [
            {
                "label": "Приветствие",
                "body": "Привет! Спасибо за сообщение. Чем помочь?",
                "is_active": True,
            },
            {
                "label": "Уточнение",
                "body": "Подскажите, пожалуйста, детали: ...",
                "is_active": True,
            },
            {
                "label": "В работе",
                "body": "Принял в работу. Вернусь с ответом в ближайшее время.",
                "is_active": True,
            },
            {
                "label": "Завершение",
                "body": "Спасибо! Если появятся вопросы — пишите.",
                "is_active": True,
            },
        ],
    )

    op.create_table(
        "tag_catalog",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False, unique=True),
        sa.Column("description", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("color", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("idx_tag_catalog_name", "tag_catalog", ["name"], unique=False)
    op.create_index("idx_tag_catalog_active", "tag_catalog", ["is_active"], unique=False)


def downgrade() -> None:
    """Drop message_templates and tag_catalog tables."""

    op.drop_index("idx_tag_catalog_active", table_name="tag_catalog")
    op.drop_index("idx_tag_catalog_name", table_name="tag_catalog")
    op.drop_table("tag_catalog")

    op.drop_index("idx_message_templates_active", table_name="message_templates")
    op.drop_index("idx_message_templates_label", table_name="message_templates")
    op.drop_table("message_templates")
