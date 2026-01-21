"""
Тесты для AmoCRM клиента
Тестируем новые методы: create_contact, update_contact
"""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta

from src.amocrm_client import AmoCRMClient
from src.config import Settings


class TestAmoCRMClient(unittest.IsolatedAsyncioTestCase):
    """Тесты для AmoCRMClient"""

    def setUp(self):
        """Подготовка перед каждым тестом"""
        # Mock settings
        self.mock_settings = MagicMock(spec=Settings)
        self.mock_settings.AMOCRM_DOMAIN = "test.amocrm.ru"
        self.mock_settings.AMOCRM_CLIENT_ID = "test_client_id"
        self.mock_settings.AMOCRM_CLIENT_SECRET = "test_client_secret"
        self.mock_settings.AMOCRM_REDIRECT_URI = "https://test.com/callback"
        self.mock_settings.AMOCRM_ACCESS_TOKEN = "test_access_token"
        self.mock_settings.AMOCRM_REFRESH_TOKEN = "test_refresh_token"
        self.mock_settings.AMOCRM_TOKEN_EXPIRES_AT = None
        self.mock_settings.AMOCRM_FIELD_TELEGRAM_USERNAME = 123456
        self.mock_settings.AMOCRM_FIELD_TELEGRAM_CHAT_ID = 123457
        self.mock_settings.AMOCRM_FIELD_TELEGRAM_CONSENT = 123458

        # Patch settings в модуле
        self.settings_patcher = patch('src.amocrm_client.settings', self.mock_settings)
        self.settings_patcher.start()

    def tearDown(self):
        """Очистка после теста"""
        self.settings_patcher.stop()

    async def test_create_contact_full_data(self):
        """
        Test #AmoCRM-1: create_contact() создает контакт со всеми полями
        """
        client = AmoCRMClient()

        # Mock ensure_token_valid
        client.ensure_token_valid = AsyncMock(return_value=True)

        # Mock успешный ответ от AmoCRM API
        mock_response_data = {
            '_embedded': {
                'contacts': [
                    {
                        'id': 12345,
                        'name': 'Иван Иванов'
                    }
                ]
            }
        }

        # Mock _make_request
        client._make_request = AsyncMock(return_value=(200, mock_response_data))

        # Вызываем метод
        contact_id = await client.create_contact(
            first_name='Иван',
            last_name='Иванов',
            phone='+79991234567',
            telegram_username='@ivanov',
            telegram_chat_id=123456789
        )

        # Проверяем результат
        self.assertEqual(contact_id, 12345)

        # Проверяем что _make_request был вызван с правильными данными
        client._make_request.assert_called_once()
        call_args = client._make_request.call_args

        # Проверяем метод и URL
        self.assertEqual(call_args[0][1], 'POST')  # method
        self.assertIn('/contacts', call_args[0][2])  # url

        # Проверяем тело запроса
        request_json = call_args[1]['json']
        self.assertIsInstance(request_json, list)
        self.assertEqual(len(request_json), 1)

        contact_data = request_json[0]
        self.assertEqual(contact_data['name'], 'Иван Иванов')
        self.assertEqual(contact_data['first_name'], 'Иван')
        self.assertEqual(contact_data['last_name'], 'Иванов')

        # Проверяем custom поля
        custom_fields = contact_data['custom_fields_values']
        self.assertGreaterEqual(len(custom_fields), 3)  # phone, username, chat_id

        # Проверяем телефон
        phone_field = next((f for f in custom_fields if f.get('field_code') == 'PHONE'), None)
        self.assertIsNotNone(phone_field)
        self.assertEqual(phone_field['values'][0]['value'], '+79991234567')

    async def test_create_contact_minimal_data(self):
        """
        Test #AmoCRM-2: create_contact() работает с минимальными данными
        """
        client = AmoCRMClient()
        client.ensure_token_valid = AsyncMock(return_value=True)

        mock_response_data = {
            '_embedded': {
                'contacts': [{'id': 99999}]
            }
        }
        client._make_request = AsyncMock(return_value=(200, mock_response_data))

        # Создаем контакт только с именем
        contact_id = await client.create_contact(first_name='Петр')

        self.assertEqual(contact_id, 99999)

        # Проверяем что запрос содержит только имя
        call_args = client._make_request.call_args
        contact_data = call_args[1]['json'][0]
        self.assertEqual(contact_data['name'], 'Петр')
        self.assertEqual(contact_data['first_name'], 'Петр')
        self.assertNotIn('last_name', contact_data)

    async def test_create_contact_no_token(self):
        """
        Test #AmoCRM-3: create_contact() возвращает None если нет токена
        """
        client = AmoCRMClient()
        client.ensure_token_valid = AsyncMock(return_value=False)

        contact_id = await client.create_contact(first_name='Test')

        self.assertIsNone(contact_id)

    async def test_create_contact_api_error(self):
        """
        Test #AmoCRM-4: create_contact() обрабатывает ошибки API
        """
        import aiohttp

        client = AmoCRMClient()
        client.ensure_token_valid = AsyncMock(return_value=True)

        # Mock ошибку HTTP
        client._make_request = AsyncMock(
            side_effect=aiohttp.ClientResponseError(
                request_info=MagicMock(),
                history=(),
                status=400,
                message='Bad Request'
            )
        )

        contact_id = await client.create_contact(first_name='Test')

        self.assertIsNone(contact_id)

    async def test_update_contact_full_data(self):
        """
        Test #AmoCRM-5: update_contact() обновляет контакт со всеми полями
        """
        client = AmoCRMClient()
        client.ensure_token_valid = AsyncMock(return_value=True)

        # Mock find_contact_by_id для получения текущих данных
        client.find_contact_by_id = AsyncMock(return_value={
            'id': 12345,
            'first_name': 'Иван',
            'last_name': 'Иванов'
        })

        # Mock успешное обновление
        mock_response_data = {
            '_embedded': {
                'contacts': [{'id': 12345}]
            }
        }
        client._make_request = AsyncMock(return_value=(200, mock_response_data))

        # Обновляем контакт
        result = await client.update_contact(
            contact_id=12345,
            first_name='Петр',
            phone='+79997654321',
            telegram_chat_id=987654321
        )

        self.assertTrue(result)

        # Проверяем что запрос правильный
        call_args = client._make_request.call_args
        self.assertEqual(call_args[0][1], 'PATCH')
        self.assertIn('/contacts/12345', call_args[0][2])

        contact_data = call_args[1]['json']
        self.assertEqual(contact_data['first_name'], 'Петр')
        self.assertIn('name', contact_data)  # должно быть обновлено полное имя

    async def test_update_contact_partial_data(self):
        """
        Test #AmoCRM-6: update_contact() обновляет только указанные поля
        """
        client = AmoCRMClient()
        client.ensure_token_valid = AsyncMock(return_value=True)
        client.find_contact_by_id = AsyncMock(return_value={
            'id': 12345,
            'first_name': 'Иван',
            'last_name': 'Иванов'
        })
        client._make_request = AsyncMock(return_value=(200, {}))

        # Обновляем только телефон
        result = await client.update_contact(
            contact_id=12345,
            phone='+79991111111'
        )

        self.assertTrue(result)

        # Проверяем что не обновляем имя
        contact_data = client._make_request.call_args[1]['json']
        self.assertNotIn('first_name', contact_data)

        # Но телефон должен быть в custom_fields
        custom_fields = contact_data.get('custom_fields_values', [])
        phone_field = next((f for f in custom_fields if f.get('field_code') == 'PHONE'), None)
        self.assertIsNotNone(phone_field)

    async def test_update_contact_no_data(self):
        """
        Test #AmoCRM-7: update_contact() возвращает True если нечего обновлять
        """
        client = AmoCRMClient()
        client.ensure_token_valid = AsyncMock(return_value=True)

        # Вызываем без параметров
        result = await client.update_contact(contact_id=12345)

        self.assertTrue(result)  # должен вернуть True без запроса к API

    async def test_update_contact_no_token(self):
        """
        Test #AmoCRM-8: update_contact() возвращает False если нет токена
        """
        client = AmoCRMClient()
        client.ensure_token_valid = AsyncMock(return_value=False)

        result = await client.update_contact(
            contact_id=12345,
            first_name='Test'
        )

        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
