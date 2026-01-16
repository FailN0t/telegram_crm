# Тестирование

## Запуск тестов
Все тесты — `unittest`. По умолчанию используют SQLite файлы в корне проекта.
При необходимости можно прогонять на PostgreSQL (см. ниже).

### Запуск всех тестов
```bash
python3 -m unittest
```

### Запуск тестов на PostgreSQL (опционально)
Используйте отдельную тестовую БД и включите `create_all`:
```bash
DATABASE_URL=postgresql://postgres:pass@localhost:5432/telegram_bot_test \
DB_ALLOW_CREATE_ALL=true \
DB_USE_NULL_POOL=true \
python3 -m unittest discover -s tests
```

### Запуск отдельных тестов
```bash
python3 -m unittest tests.test_ui_api
python3 -m unittest tests.test_outbox_models
python3 -m unittest tests.test_webhook_dedup
python3 -m unittest tests.test_telegram_session
python3 -m unittest tests.test_ui_message_history
```

### Демонстрационный сценарий
```bash
python3 test_demo.py
```

## Что создается тестами
- `test_ui.db`, `test_outbox.db`, `test_webhook.db`, `test_telegram_session.db`, `test_ui_history.db`.

Если возникают проблемы с уникальностью — удалите файл БД и повторите тест.

## Частые ошибки и решения
1) `python: command not found`
- Причина: в окружении доступен `python3`, но нет алиаса `python`.
- Решение: запускать `python3 -m unittest`.

2) `AttributeError: 'AntiSpamManager' object has no attribute 'can_send_message'`
- Причина: API anti‑spam изменился.
- Решение: тесты должны вызывать `try_register_send(...)`.

3) `UNIQUE constraint failed` в тестовой БД
- Причина: остаются записи от прошлых запусков.
- Решение: удалить тестовую SQLite БД перед запуском.

4) `Redis недоступен: Authentication required` (warning)
- Причина: Redis требует пароль, но он не указан в тестовом окружении.
- Решение: указать `REDIS_URL` с паролем или игнорировать предупреждение.

## Нагрузочное тестирование
Locust сценарии лежат в `tests/load/`.

### Быстрый запуск
```bash
locust -f tests/load/locustfile.py --host http://localhost:8000
```

### Headless пример
```bash
UI_LOAD_USER=admin UI_LOAD_PASS=pass UI_LOAD_CHAT_ID=42 \
locust -f tests/load/locustfile.py --host http://localhost:8000 \
  --headless -u 50 -r 5 -t 2m --csv perf_results/ui
```
