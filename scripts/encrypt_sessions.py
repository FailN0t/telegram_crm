#!/usr/bin/env python3
"""
Script to encrypt existing session strings in the database.

This script should be run ONCE after deploying session encryption feature.
It will:
1. Read all existing session strings from database
2. Encrypt them using configured encryption key
3. Update database with encrypted values

Usage:
    python scripts/encrypt_sessions.py [--dry-run]

Options:
    --dry-run    Show what would be done without making changes

Prerequisites:
    - SESSION_ENCRYPTION_KEY must be configured in .env
    - Database must be accessible
    - Backup database before running!
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, update
from src.database import SessionLocal, TelegramAccount, TelegramSession, engine
from src.crypto import get_session_encryption
from src.logger import logger


async def encrypt_telegram_accounts(dry_run: bool = False) -> int:
    """
    Encrypt session strings in telegram_accounts table.

    Args:
        dry_run: If True, only show what would be done

    Returns:
        Number of records that would be/were updated
    """
    encryptor = get_session_encryption()

    if not encryptor.is_enabled:
        logger.error("❌ Session encryption is NOT enabled! Check SESSION_ENCRYPTION_KEY.")
        return 0

    updated = 0

    async with SessionLocal() as db:
        # Read all accounts
        result = await db.execute(select(TelegramAccount))
        accounts = result.scalars().all()

        logger.info(f"Found {len(accounts)} telegram accounts")

        for account in accounts:
            # Get current session string (will be decrypted if already encrypted)
            current_value = account._session_string_encrypted

            if not current_value:
                logger.info(f"  Account {account.id} ({account.phone_number}): SKIP (no session)")
                continue

            # Try to decrypt - if it fails, it's plain text
            try:
                decrypted = encryptor.decrypt(current_value)

                # If decrypt succeeded and value changed, it was already encrypted
                if decrypted != current_value:
                    logger.info(
                        f"  Account {account.id} ({account.phone_number}): "
                        f"SKIP (already encrypted)"
                    )
                    continue

                # Plain text - need to encrypt
                encrypted = encryptor.encrypt(current_value)

                if dry_run:
                    logger.info(
                        f"  Account {account.id} ({account.phone_number}): "
                        f"WOULD ENCRYPT (len={len(current_value)} -> {len(encrypted)})"
                    )
                else:
                    # Update directly in DB to bypass property setter
                    await db.execute(
                        update(TelegramAccount)
                        .where(TelegramAccount.id == account.id)
                        .values(_session_string_encrypted=encrypted)
                    )
                    logger.info(
                        f"  Account {account.id} ({account.phone_number}): "
                        f"✅ ENCRYPTED (len={len(current_value)} -> {len(encrypted)})"
                    )

                updated += 1

            except Exception as e:
                logger.error(
                    f"  Account {account.id} ({account.phone_number}): "
                    f"❌ ERROR: {e}"
                )

        if not dry_run and updated > 0:
            await db.commit()
            logger.info(f"✅ Committed {updated} updates to telegram_accounts")

    return updated


async def encrypt_telegram_sessions(dry_run: bool = False) -> int:
    """
    Encrypt session strings in telegram_sessions table.

    Args:
        dry_run: If True, only show what would be done

    Returns:
        Number of records that would be/were updated
    """
    encryptor = get_session_encryption()

    if not encryptor.is_enabled:
        logger.error("❌ Session encryption is NOT enabled! Check SESSION_ENCRYPTION_KEY.")
        return 0

    updated = 0

    async with SessionLocal() as db:
        # Read all sessions
        result = await db.execute(select(TelegramSession))
        sessions = result.scalars().all()

        logger.info(f"Found {len(sessions)} telegram sessions")

        for session in sessions:
            # Get current session string
            current_value = session._session_string_encrypted

            if not current_value:
                logger.info(f"  Session {session.id} ({session.phone}): SKIP (no session)")
                continue

            # Try to decrypt - if it fails, it's plain text
            try:
                decrypted = encryptor.decrypt(current_value)

                # If decrypt succeeded and value changed, it was already encrypted
                if decrypted != current_value:
                    logger.info(
                        f"  Session {session.id} ({session.phone}): "
                        f"SKIP (already encrypted)"
                    )
                    continue

                # Plain text - need to encrypt
                encrypted = encryptor.encrypt(current_value)

                if dry_run:
                    logger.info(
                        f"  Session {session.id} ({session.phone}): "
                        f"WOULD ENCRYPT (len={len(current_value)} -> {len(encrypted)})"
                    )
                else:
                    # Update directly in DB to bypass property setter
                    await db.execute(
                        update(TelegramSession)
                        .where(TelegramSession.id == session.id)
                        .values(_session_string_encrypted=encrypted)
                    )
                    logger.info(
                        f"  Session {session.id} ({session.phone}): "
                        f"✅ ENCRYPTED (len={len(current_value)} -> {len(encrypted)})"
                    )

                updated += 1

            except Exception as e:
                logger.error(
                    f"  Session {session.id} ({session.phone}): "
                    f"❌ ERROR: {e}"
                )

        if not dry_run and updated > 0:
            await db.commit()
            logger.info(f"✅ Committed {updated} updates to telegram_sessions")

    return updated


async def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Encrypt existing session strings in database"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes"
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.info("🔍 DRY RUN MODE - no changes will be made")
    else:
        logger.warning("⚠️  LIVE MODE - database will be updated!")
        logger.warning("⚠️  Make sure you have a backup before proceeding!")

        response = input("Continue? (yes/no): ")
        if response.lower() not in ('yes', 'y'):
            logger.info("Aborted by user")
            return

    logger.info("=" * 60)
    logger.info("Encrypting TelegramAccount session strings...")
    logger.info("=" * 60)

    accounts_updated = await encrypt_telegram_accounts(dry_run=args.dry_run)

    logger.info("")
    logger.info("=" * 60)
    logger.info("Encrypting TelegramSession session strings...")
    logger.info("=" * 60)

    sessions_updated = await encrypt_telegram_sessions(dry_run=args.dry_run)

    logger.info("")
    logger.info("=" * 60)
    logger.info("SUMMARY")
    logger.info("=" * 60)
    logger.info(f"TelegramAccount: {accounts_updated} records {'would be ' if args.dry_run else ''}updated")
    logger.info(f"TelegramSession: {sessions_updated} records {'would be ' if args.dry_run else ''}updated")
    logger.info(f"Total: {accounts_updated + sessions_updated} records")

    if args.dry_run:
        logger.info("")
        logger.info("✅ Dry run completed. Run without --dry-run to apply changes.")
    else:
        logger.info("")
        logger.info("✅ Encryption completed successfully!")

    # Close engine
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
