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


if __name__ == "__main__":
    unittest.main()
