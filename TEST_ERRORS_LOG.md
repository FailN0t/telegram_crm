# Ошибки тестов и как исправлял

Ниже список ошибок, которые возникли при запуске тестов, и действия для исправления.

## 1) `python: command not found`
- Где: запуск `python -m unittest`
- Причина: в окружении доступен `python3`, но нет алиаса `python`
- Исправление: запускать `python3 -m unittest` или настроить алиас `python`

## 2) `AttributeError: 'AntiSpamManager' object has no attribute 'can_send_message'`
- Где: `test_demo.py`
- Причина: anti‑spam API изменён (объединена проверка и регистрация), старый метод удалён
- Исправление: обновил `test_demo.py` на `await antispam.try_register_send(...)`

## 3) `sqlite3.IntegrityError: UNIQUE constraint failed: message_outbox.idempotency_key`
- Где: `tests/test_outbox_models.py`
- Причина: в БД уже лежали записи из прошлых запусков тестов
- Исправление: в `setUpClass` очищаю таблицы `message_delivery_attempts` и `message_outbox`

## 4) `sqlite3.IntegrityError: UNIQUE constraint failed: telegram_sessions.phone`
- Где: `tests/test_telegram_session.py`
- Причина: повторные записи с тем же `phone` оставались в тестовой БД
- Исправление: в `setUpClass` очищаю таблицу `telegram_sessions`

## 5) `Redis недоступен: Authentication required` (предупреждение)
- Где: вывод `test_demo.py`
- Причина: Redis требует пароль, а в `.env`/тестовом окружении пароль не указан
- Исправление: это не ошибка тестов, а предупреждение. Можно:
  - указать `REDIS_URL` с паролем, или
  - игнорировать, если Redis для демо не нужен
