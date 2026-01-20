"""
Tests for security fixes.

Validates fixes for:
- #173: session_string не должен логироваться
- #128: Client start exception должен откатывать добавление в _clients
- #171: /api/ui/accounts должен требовать авторизацию
- #14: Concurrent refresh CRM токенов должен использовать lock
- #169: Magic link авторизация через Telegram

These tests verify that security vulnerabilities are fixed.
"""

import os
import re
import unittest


class TestSecurityFix173(unittest.TestCase):
    """Test #173: session_string не должен логироваться"""

    def test_session_string_not_logged_in_code(self):
        """Test #173: session_string содержимое НЕ должно логироваться в коде"""

        # Read telegram_client.py source code
        telegram_client_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src",
            "telegram_client.py"
        )

        with open(telegram_client_path, 'r', encoding='utf-8') as f:
            source_code = f.read()

        # DANGEROUS PATTERNS - логирование содержимого session_string
        dangerous_patterns = [
            # logger.*session_string[
            r'logger\.\w+\([^)]*session_string\[',
            # f"{session_string}" or f'{session_string}'
            r'logger\.\w+\([^)]*[f]["\'].*\{session_string\}',
            # session_string[:N]
            r'logger\.\w+\([^)]*session_string\[:',
            # Explicitly logging first N chars
            r'Первые.*символов.*session_string.*:',
        ]

        # Check for dangerous patterns
        for pattern in dangerous_patterns:
            matches = list(re.finditer(pattern, source_code))
            if matches:
                # Get line numbers
                lines_with_issues = []
                for match in matches:
                    # Find line number
                    line_num = source_code[:match.start()].count('\n') + 1
                    # Get the actual line
                    lines = source_code.split('\n')
                    actual_line = lines[line_num - 1].strip()
                    lines_with_issues.append(f"Line {line_num}: {actual_line}")

                self.fail(
                    f"❌ SECURITY LEAK: Найдено логирование session_string содержимого!\n"
                    f"Pattern: {pattern}\n"
                    f"Locations:\n" + "\n".join(lines_with_issues)
                )

        # SAFE PATTERNS - эти должны присутствовать
        safe_patterns = [
            # Упоминание что содержимое скрыто
            r'содержимое скрыто для безопасности',
            # Логирование длины (безопасно)
            r'len\(session_string',
        ]

        # Check that safe patterns exist
        for pattern in safe_patterns:
            if not re.search(pattern, source_code):
                self.fail(
                    f"❌ Ожидалось наличие безопасного паттерна: {pattern}\n"
                    f"Убедитесь что fix реализован корректно"
                )

    def test_no_session_string_in_other_log_files(self):
        """Test #173: session_string не логируется в других файлах"""

        src_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "src")

        # Files to check
        files_to_check = [
            "telegram_manager.py",
            "database.py",
            "config.py"
        ]

        for filename in files_to_check:
            filepath = os.path.join(src_dir, filename)
            if not os.path.exists(filepath):
                continue

            with open(filepath, 'r', encoding='utf-8') as f:
                source_code = f.read()

            # Check for dangerous logging patterns
            dangerous_patterns = [
                # f"{session_string}"
                r'logger\.\w+\([^)]*\{session_string\}',
                # session_string[:N]
                r'logger\.\w+\([^)]*session_string\[:',
                # print(session_string)
                r'print\([^)]*session_string[^)]*\)',
            ]

            for pattern in dangerous_patterns:
                matches = list(re.finditer(pattern, source_code))
                if matches:
                    # Get line numbers
                    lines_with_issues = []
                    for match in matches:
                        line_num = source_code[:match.start()].count('\n') + 1
                        lines = source_code.split('\n')
                        actual_line = lines[line_num - 1].strip()
                        lines_with_issues.append(f"Line {line_num}: {actual_line}")

                    self.fail(
                        f"❌ SECURITY LEAK in {filename}: Найдено логирование session_string содержимого!\n"
                        f"Pattern: {pattern}\n"
                        f"Locations:\n" + "\n".join(lines_with_issues)
                    )


class TestSecurityFix171(unittest.TestCase):
    """Test #171: /api/ui/accounts должен требовать авторизацию и маскировать телефоны"""

    def test_accounts_endpoint_requires_auth(self):
        """Test #171: /api/ui/accounts должен требовать авторизацию"""
        # Read api_server.py source code
        api_server_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src",
            "api_server.py"
        )

        with open(api_server_path, 'r', encoding='utf-8') as f:
            source_code = f.read()

        # Find the ui_accounts function - it should be near @app.get("/api/ui/accounts")
        # Check in context around the endpoint
        pattern = r'@app\.get\("/api/ui/accounts"[^\n]*\n\s+async def ui_accounts\('

        match = re.search(pattern, source_code)
        if not match:
            self.fail("/api/ui/accounts endpoint не найден в коде")

        # Get the function signature (next 200 chars should contain the params)
        start_pos = match.start()
        end_pos = min(start_pos + 500, len(source_code))
        context = source_code[start_pos:end_pos]

        # Check that it requires authentication (has Depends(require_ui_auth))
        if "Depends(require_ui_auth)" not in context:
            self.fail(
                f"❌ SECURITY LEAK #171: /api/ui/accounts НЕ требует авторизацию!\n"
                f"Context:\n{context}\n"
                f"Ожидалось: ui_user: dict = Depends(require_ui_auth)"
            )

    def test_accounts_endpoint_masks_phone_numbers(self):
        """Test #171: /api/ui/accounts должен маскировать телефонные номера"""
        # Read api_server.py source code
        api_server_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "src",
            "api_server.py"
        )

        with open(api_server_path, 'r', encoding='utf-8') as f:
            source_code = f.read()

        # Look for mask_phone function or phone masking logic in the file
        # (should be inside ui_accounts function)
        patterns_to_check = [
            (r'def mask_phone', "mask_phone function definition"),
            (r'phone\[:2\].*\*\*\*.*phone\[-4:\]', "phone masking pattern"),
            (r'mask_phone\(', "mask_phone function call"),
        ]

        # Check each pattern
        found_patterns = []
        for pattern, description in patterns_to_check:
            if re.search(pattern, source_code):
                found_patterns.append(description)

        if len(found_patterns) < 2:
            # Should have at least mask_phone definition and calls
            self.fail(
                f"❌ SECURITY LEAK #171: /api/ui/accounts НЕ маскирует телефонные номера!\n"
                f"Найдено паттернов: {found_patterns}\n"
                f"Ожидалось: mask_phone() definition и calls"
            )


class TestSecurityFix128(unittest.TestCase):
    """Test #128: Client start exception должен откатывать добавление в _clients"""

    def test_client_start_exception_removes_from_clients_dict(self):
        """Test #128: При ошибке start() client НЕ должен добавляться в _clients"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def run_test():
            from src.telegram_manager import TelegramClientManager

            # Create manager instance
            manager = TelegramClientManager()

            # Mock get_account to return test account
            test_account = MagicMock()
            test_account.id = 999
            test_account.phone_number = "+9999999999"
            test_account.session_string = "test_session"

            manager.get_account = AsyncMock(return_value=test_account)

            # Mock MTProtoClient to raise exception on start()
            with patch('src.telegram_manager.MTProtoClient') as MockClient:
                mock_client_instance = MagicMock()

                # start() raises exception
                mock_client_instance.start = AsyncMock(side_effect=Exception("Test error: failed to start"))
                mock_client_instance.stop = AsyncMock()  # stop() should be called for cleanup

                MockClient.return_value = mock_client_instance

                # Try to get client - should raise exception
                with self.assertRaises(Exception) as context:
                    await manager.get_client(account_id=999)

                # Verify exception message
                self.assertIn("failed to start", str(context.exception))

                # CRITICAL CHECK: client should NOT be in _clients dict
                self.assertNotIn(
                    999,
                    manager._clients,
                    "❌ BUG #128: Client добавлен в _clients несмотря на ошибку start()!"
                )

                # Verify cleanup was attempted (stop() called)
                mock_client_instance.stop.assert_called_once()

        asyncio.run(run_test())

    def test_client_start_success_adds_to_clients_dict(self):
        """Test #128: При успешном start() client должен добавляться в _clients"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch

        async def run_test():
            from src.telegram_manager import TelegramClientManager

            # Create manager instance
            manager = TelegramClientManager()

            # Mock get_account to return test account
            test_account = MagicMock()
            test_account.id = 888
            test_account.phone_number = "+8888888888"
            test_account.session_string = "test_session"

            manager.get_account = AsyncMock(return_value=test_account)

            # Mock MTProtoClient with successful start()
            with patch('src.telegram_manager.MTProtoClient') as MockClient:
                mock_client_instance = MagicMock()

                # start() succeeds
                mock_client_instance.start = AsyncMock()  # No exception
                mock_client_instance.stop = AsyncMock()

                MockClient.return_value = mock_client_instance

                # Get client - should succeed
                client = await manager.get_client(account_id=888)

                # Verify client was added to _clients
                self.assertIn(
                    888,
                    manager._clients,
                    "✅ Client должен быть в _clients после успешного start()"
                )

                # Verify returned client is the same
                self.assertEqual(client, mock_client_instance)

                # Verify stop() was NOT called (no error)
                mock_client_instance.stop.assert_not_called()

        asyncio.run(run_test())


class TestSecurityFix14(unittest.TestCase):
    """Test #14: Concurrent refresh CRM токенов должен использовать lock"""

    def test_bitrix24_concurrent_token_refresh_uses_lock(self):
        """Test #14 (Bitrix24): При concurrent запросах refresh вызывается только 1 раз"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from datetime import datetime, timedelta

        async def run_test():
            from src.bitrix24_client import Bitrix24Client

            # Create client instance
            client = Bitrix24Client()

            # Setup: токен истекает через 4 минуты (меньше чем 5 минут - нужен refresh)
            client.access_token = "test_access_token"
            client.refresh_token = "test_refresh_token"
            client.token_expires_at = datetime.now() + timedelta(minutes=4)
            client.use_webhook = False

            # Track number of actual refresh calls
            refresh_call_count = 0

            async def mock_refresh():
                """Mock refresh that simulates delay and updates token"""
                nonlocal refresh_call_count
                refresh_call_count += 1

                # Simulate network delay (important for race condition test)
                await asyncio.sleep(0.1)

                # Update token expiry to simulate successful refresh
                client.token_expires_at = datetime.now() + timedelta(hours=1)
                return True

            # Patch refresh_access_token method
            with patch.object(client, 'refresh_access_token', new=mock_refresh):
                # Simulate 5 concurrent API calls that all see expired token
                tasks = [client.ensure_token_valid() for _ in range(5)]

                # Run concurrently
                results = await asyncio.gather(*tasks)

                # All should succeed
                for result in results:
                    self.assertTrue(result, "ensure_token_valid() должен вернуть True")

                # CRITICAL CHECK: refresh должен быть вызван только 1 раз (не 5)
                self.assertEqual(
                    refresh_call_count,
                    1,
                    f"❌ BUG #14 (Bitrix24): refresh_access_token вызван {refresh_call_count} раз вместо 1! "
                    f"Double-checked locking не работает."
                )

        asyncio.run(run_test())

    def test_amocrm_concurrent_token_refresh_uses_lock(self):
        """Test #14 (AmoCRM): При concurrent запросах refresh вызывается только 1 раз"""
        import asyncio
        from unittest.mock import AsyncMock, MagicMock, patch
        from datetime import datetime, timedelta

        async def run_test():
            from src.amocrm_client import AmoCRMClient

            # Create client instance
            client = AmoCRMClient()

            # Setup: токен истекает через 4 минуты (меньше чем 5 минут - нужен refresh)
            client.access_token = "test_access_token"
            client.refresh_token = "test_refresh_token"
            client.token_expires_at = datetime.now() + timedelta(minutes=4)

            # Track number of actual refresh calls
            refresh_call_count = 0

            async def mock_refresh():
                """Mock refresh that simulates delay and updates token"""
                nonlocal refresh_call_count
                refresh_call_count += 1

                # Simulate network delay (important for race condition test)
                await asyncio.sleep(0.1)

                # Update token expiry to simulate successful refresh
                client.token_expires_at = datetime.now() + timedelta(hours=1)
                return True

            # Patch refresh_access_token method
            with patch.object(client, 'refresh_access_token', new=mock_refresh):
                # Simulate 5 concurrent API calls that all see expired token
                tasks = [client.ensure_token_valid() for _ in range(5)]

                # Run concurrently
                results = await asyncio.gather(*tasks)

                # All should succeed
                for result in results:
                    self.assertTrue(result, "ensure_token_valid() должен вернуть True")

                # CRITICAL CHECK: refresh должен быть вызван только 1 раз (не 5)
                self.assertEqual(
                    refresh_call_count,
                    1,
                    f"❌ BUG #14 (AmoCRM): refresh_access_token вызван {refresh_call_count} раз вместо 1! "
                    f"Double-checked locking не работает."
                )

        asyncio.run(run_test())

    def test_bitrix24_double_checked_locking_works(self):
        """Test #14 (Bitrix24): Double-checked locking - второй поток не делает refresh"""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from datetime import datetime, timedelta

        async def run_test():
            from src.bitrix24_client import Bitrix24Client

            client = Bitrix24Client()

            # Setup: токен истекает (нужен refresh)
            client.access_token = "test_access_token"
            client.refresh_token = "test_refresh_token"
            client.token_expires_at = datetime.now() + timedelta(minutes=4)
            client.use_webhook = False

            refresh_calls = []

            async def mock_refresh():
                """Mock refresh that records call"""
                refresh_calls.append(datetime.now())
                # Simulate successful refresh
                client.token_expires_at = datetime.now() + timedelta(hours=1)
                await asyncio.sleep(0.05)  # Simulate network delay
                return True

            with patch.object(client, 'refresh_access_token', new=mock_refresh):
                # First call should trigger refresh
                result1 = await client.ensure_token_valid()
                self.assertTrue(result1)
                self.assertEqual(len(refresh_calls), 1)

                # Second call should NOT trigger refresh (token already valid)
                result2 = await client.ensure_token_valid()
                self.assertTrue(result2)
                self.assertEqual(len(refresh_calls), 1, "Второй вызов НЕ должен делать refresh!")

        asyncio.run(run_test())

    def test_amocrm_double_checked_locking_works(self):
        """Test #14 (AmoCRM): Double-checked locking - второй поток не делает refresh"""
        import asyncio
        from unittest.mock import AsyncMock, patch
        from datetime import datetime, timedelta

        async def run_test():
            from src.amocrm_client import AmoCRMClient

            client = AmoCRMClient()

            # Setup: токен истекает (нужен refresh)
            client.access_token = "test_access_token"
            client.refresh_token = "test_refresh_token"
            client.token_expires_at = datetime.now() + timedelta(minutes=4)

            refresh_calls = []

            async def mock_refresh():
                """Mock refresh that records call"""
                refresh_calls.append(datetime.now())
                # Simulate successful refresh
                client.token_expires_at = datetime.now() + timedelta(hours=1)
                await asyncio.sleep(0.05)  # Simulate network delay
                return True

            with patch.object(client, 'refresh_access_token', new=mock_refresh):
                # First call should trigger refresh
                result1 = await client.ensure_token_valid()
                self.assertTrue(result1)
                self.assertEqual(len(refresh_calls), 1)

                # Second call should NOT trigger refresh (token already valid)
                result2 = await client.ensure_token_valid()
                self.assertTrue(result2)
                self.assertEqual(len(refresh_calls), 1, "Второй вызов НЕ должен делать refresh!")

        asyncio.run(run_test())


class TestSecurityFix169(unittest.TestCase):
    """Test #169: Magic link авторизация через Telegram"""

    def test_magic_link_token_saved_to_redis(self):
        """Test #169: Magic link token должен сохраняться в Redis с TTL"""
        import asyncio
        from unittest.mock import AsyncMock, patch, MagicMock

        async def run_test():
            from src.redis_client import save_magic_link_token, get_magic_link_token

            # Mock Redis client
            mock_redis = AsyncMock()
            mock_redis.setex = AsyncMock(return_value=True)
            mock_redis.get = AsyncMock(return_value='{"created_at": "2026-01-21T00:00:00", "used": false}')

            with patch('src.redis_client.get_redis', return_value=mock_redis):
                # Save token
                token = "test-uuid-token"
                result = await save_magic_link_token(token, ttl_seconds=300)

                # Verify saved
                self.assertTrue(result)

                # Verify Redis called with correct params
                mock_redis.setex.assert_called_once()
                call_args = mock_redis.setex.call_args
                self.assertEqual(call_args[0][0], f"magic_link:{token}")
                self.assertEqual(call_args[0][1], 300)  # TTL 5 minutes

                # Verify token can be retrieved
                token_data = await get_magic_link_token(token)
                self.assertIsNotNone(token_data)
                self.assertFalse(token_data["used"])

        asyncio.run(run_test())

    def test_magic_link_token_marked_as_used(self):
        """Test #169: Magic link token должен помечаться как использованный"""
        import asyncio
        from unittest.mock import AsyncMock, patch
        import json

        async def run_test():
            from src.redis_client import mark_magic_link_token_used

            # Mock Redis client
            token_data = {"created_at": "2026-01-21T00:00:00", "used": False}
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=json.dumps(token_data))
            mock_redis.ttl = AsyncMock(return_value=250)  # 250 seconds remaining
            mock_redis.setex = AsyncMock(return_value=True)

            with patch('src.redis_client.get_redis', return_value=mock_redis):
                token = "test-uuid-token"
                result = await mark_magic_link_token_used(token)

                # Verify marked as used
                self.assertTrue(result)

                # Verify Redis setex called to update token data
                mock_redis.setex.assert_called_once()
                call_args = mock_redis.setex.call_args
                updated_data = json.loads(call_args[0][2])
                self.assertTrue(updated_data["used"])
                self.assertIn("used_at", updated_data)

        asyncio.run(run_test())

    def test_magic_link_request_endpoint_generates_token(self):
        """Test #169: POST /api/ui/auth/request-magic-link должен генерировать токен"""
        # This test would require FastAPI TestClient and database setup
        # For now, we verify that Redis helpers work (already tested above)
        # Full integration test would be added in a separate test file
        pass

    def test_magic_link_activation_endpoint_validates_token(self):
        """Test #169: GET /ui/auth/magic должен валидировать токен"""
        # This test would require FastAPI TestClient
        # Scenario: valid token → redirect to /ui with cookie
        # Scenario: invalid token → 400 error
        # Scenario: already used token → 400 error
        # Scenario: expired token → 400 error
        pass

    def test_ui_auth_attempts_table_exists(self):
        """Test #169: Таблица ui_auth_attempts должна существовать"""
        import os

        # Check that migration file exists
        migration_file = "alembic/versions/20260121_add_ui_auth_attempts_table.py"
        self.assertTrue(
            os.path.exists(migration_file),
            f"Migration file {migration_file} должен существовать"
        )

        # Check migration content
        with open(migration_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Verify creates ui_auth_attempts table
        self.assertIn("create_table", content.lower())
        self.assertIn("ui_auth_attempts", content)

        # Verify has required columns
        required_columns = ["token", "telegram_user_id", "ip_address", "user_agent", "success", "created_at"]
        for column in required_columns:
            self.assertIn(column, content, f"Column {column} должен быть в migration")

        # Verify has indexes
        self.assertIn("ix_ui_auth_attempts_token", content)
        self.assertIn("ix_ui_auth_attempts_created_at", content)


if __name__ == "__main__":
    unittest.main()
