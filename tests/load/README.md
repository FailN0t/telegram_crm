# Load tests (Locust)

## Требования
- Python 3.10+
- `pip install -r requirements-dev.txt`

## Быстрый старт (UI сценарий)
```bash
locust -f tests/load/locustfile.py --host http://localhost:8000
```

Откройте http://localhost:8089 и запустите тест.

## Headless запуск
```bash
UI_LOAD_USER=admin UI_LOAD_PASS=pass UI_LOAD_CHAT_ID=42 \
locust -f tests/load/locustfile.py --host http://localhost:8000 \
  --headless -u 50 -r 5 -t 2m --csv perf_results/ui
```

## Переменные окружения
- `UI_LOAD_USER` — логин Basic Auth (по умолчанию `admin`)
- `UI_LOAD_PASS` — пароль Basic Auth (по умолчанию `pass`)
- `UI_LOAD_CHAT_ID` — chat_id для /api/ui/messages и /api/ui/send (по умолчанию `42`)
- `UI_LOAD_ACCOUNT_ID` — account_id, если нужно тестировать конкретный аккаунт

## Рекомендации
- Запускать на staging/тестовой БД, чтобы не засорять production.
- Для UI отправок рекомендуется `OUTBOX_PROCESS_INLINE=false`, чтобы не слать сообщения в Telegram.
