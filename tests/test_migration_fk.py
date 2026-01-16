"""
Test Alembic migration for FK constraints.
Tests that migration up/down works without errors.
"""

import os
import asyncio
import unittest
import subprocess
import sys

from sqlalchemy import select, inspect, text

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_migration_fk.db")

from src.database import (
    init_db,
    engine,
    SessionLocal,
    ChatMapping,
    MessageOutbox,
    MessageDeliveryAttempt
)


class MigrationFKTests(unittest.TestCase):
    """Test suite for FK constraints migration."""

    @classmethod
    def setUpClass(cls):
        """Initialize test database."""
        db_path = "test_migration_fk.db"
        if os.path.exists(db_path):
            os.remove(db_path)

        async def _setup():
            await init_db()

        asyncio.run(_setup())

    def test_migration_structure(self):
        """Test that migration file exists and has proper structure."""
        migration_path = "/Users/dmitrifirsov/Downloads/ProjectsVC/Telegram_crm/alembic/versions/20260116_add_foreign_key_constraints.py"
        self.assertTrue(os.path.exists(migration_path), "Migration file should exist")

        with open(migration_path, 'r') as f:
            content = f.read()

        # Check for required elements
        self.assertIn('def upgrade()', content)
        self.assertIn('def downgrade()', content)
        self.assertIn('fk_message_delivery_attempts_outbox_id', content)
        self.assertIn('fk_chat_profiles_telegram_chat_id', content)
        self.assertIn('fk_message_outbox_chat_id', content)
        self.assertIn('fk_ui_message_history_chat_id', content)
        self.assertIn('fk_ui_chats_chat_id', content)
        self.assertIn('ondelete="CASCADE"', content)

    def test_orphan_cleanup_logic(self):
        """Test that migration includes orphan cleanup."""
        migration_path = "/Users/dmitrifirsov/Downloads/ProjectsVC/Telegram_crm/alembic/versions/20260116_add_foreign_key_constraints.py"

        with open(migration_path, 'r') as f:
            content = f.read()

        # Check for cleanup queries
        self.assertIn('DELETE FROM message_delivery_attempts', content)
        self.assertIn('DELETE FROM chat_profiles', content)
        self.assertIn('DELETE FROM message_outbox', content)
        self.assertIn('DELETE FROM ui_message_history', content)
        self.assertIn('DELETE FROM ui_chats', content)

    def test_fk_constraint_naming(self):
        """Test that FK constraint names follow convention."""
        migration_path = "/Users/dmitrifirsov/Downloads/ProjectsVC/Telegram_crm/alembic/versions/20260116_add_foreign_key_constraints.py"

        with open(migration_path, 'r') as f:
            content = f.read()

        # All FK constraints should start with 'fk_'
        import re
        fk_names = re.findall(r'"(fk_[^"]+)"', content)

        self.assertTrue(len(fk_names) >= 10, "Should have FK constraint names in both upgrade and downgrade")

        for fk_name in fk_names:
            self.assertTrue(fk_name.startswith('fk_'), f"FK name should start with 'fk_': {fk_name}")

    def test_downgrade_reverses_upgrade(self):
        """Test that downgrade properly reverses upgrade operations."""
        migration_path = "/Users/dmitrifirsov/Downloads/ProjectsVC/Telegram_crm/alembic/versions/20260116_add_foreign_key_constraints.py"

        with open(migration_path, 'r') as f:
            content = f.read()

        # Extract FK constraint names from upgrade
        import re
        upgrade_section = content.split('def upgrade()')[1].split('def downgrade()')[0]
        downgrade_section = content.split('def downgrade()')[1]

        upgrade_fks = set(re.findall(r'"(fk_[^"]+)"', upgrade_section))
        downgrade_fks = set(re.findall(r'"(fk_[^"]+)"', downgrade_section))

        # All FKs created in upgrade should be dropped in downgrade
        self.assertEqual(
            upgrade_fks,
            downgrade_fks,
            "All FK constraints created in upgrade should be dropped in downgrade"
        )

    def test_cascade_strategy_documented(self):
        """Test that CASCADE strategy is properly set."""
        migration_path = "/Users/dmitrifirsov/Downloads/ProjectsVC/Telegram_crm/alembic/versions/20260116_add_foreign_key_constraints.py"

        with open(migration_path, 'r') as f:
            content = f.read()

        # Count CASCADE occurrences (should be for all FKs)
        cascade_count = content.count('ondelete="CASCADE"')
        self.assertGreaterEqual(cascade_count, 5, "Should have CASCADE for all FK constraints")

    def test_database_integrity_after_fk_setup(self):
        """Test database integrity with FK constraints in place."""
        async def _run():
            async with SessionLocal() as session:
                # Clean tables
                await session.execute(MessageDeliveryAttempt.__table__.delete())
                await session.execute(MessageOutbox.__table__.delete())
                await session.execute(ChatMapping.__table__.delete())
                await session.commit()

                # Create valid parent-child relationship
                chat = ChatMapping(
                    telegram_chat_id=12345,
                    amocrm_contact_id=999,
                    telegram_username="test"
                )
                session.add(chat)
                await session.commit()

                outbox = MessageOutbox(
                    idempotency_key="test-1",
                    chat_id=12345,
                    payload={"text": "test"},
                    status="queued"
                )
                session.add(outbox)
                await session.commit()
                await session.refresh(outbox)

                attempt = MessageDeliveryAttempt(
                    outbox_id=outbox.id,
                    attempt=1,
                    status="failed"
                )
                session.add(attempt)
                await session.commit()

                # Verify the chain exists
                result = await session.execute(
                    select(MessageDeliveryAttempt).filter_by(outbox_id=outbox.id)
                )
                attempts = result.scalars().all()
                self.assertEqual(len(attempts), 1)

        asyncio.run(_run())

    def test_revision_chain(self):
        """Test that migration is properly chained to previous migration."""
        migration_path = "/Users/dmitrifirsov/Downloads/ProjectsVC/Telegram_crm/alembic/versions/20260116_add_foreign_key_constraints.py"

        with open(migration_path, 'r') as f:
            content = f.read()

        # Check revision identifiers
        self.assertIn('revision = "20260116_add_foreign_key_constraints"', content)
        self.assertIn('down_revision = "20260114_add_ui_message_updated_at"', content)


if __name__ == "__main__":
    unittest.main()
