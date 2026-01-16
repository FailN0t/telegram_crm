# Telegram CRM Console (MTProto)

Проект для сценария, когда **нужно писать клиентам первыми** в Telegram. Работает через MTProto (личный аккаунт, не бот) и включает локальную UI‑консоль, API, очереди, антиспам, хранение истории и интеграцию с AmoCRM (опционально).

## Что умеет
- Писать первым через MTProto (личный аккаунт Telegram).
- Локальная UI‑консоль: авторизация, список чатов, история, шаблоны, карточка контакта.
- Очередь исходящих сообщений с ретраями (outbox + worker).
- Антиспам‑лимиты и комплаенс (consent, quiet hours, opt‑out).
- Хранение истории в БД (UI + CRM‑история).
- Observability: метрики, логи, error tracking (self‑hosted).

## Быстрый старт (минимум)
```bash
cp env.template .env
# заполните TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, API_SECRET_KEY, DATABASE_URL
pip3 install -r requirements-production.txt
python3 -m alembic upgrade head
python3 -m src.main
```

UI:
- Авторизация: `http://localhost:8000/ui/auth` (порт меняется через `API_PORT`)
- Консоль: `http://localhost:8000/ui`

Если `OUTBOX_PROCESS_INLINE=false`, запустите worker отдельно:
```bash
python3 -m src.outbox_worker
```

## Документация (с чего начать)
- `QUICKSTART.md` — полный пошаговый запуск локально.
- `CONFIGURATION.md` — полный справочник по `.env`.
- `ARCHITECTURE.md` — компоненты, потоки данных, таблицы.
- `API.md` — все API endpoints и примеры запросов.
- `UI_GUIDE.md` — как работать в UI.
- `MTPROTO_GUIDE.md` — риски MTProto, лимиты, комплаенс.
- `DEPLOYMENT.md` — прод‑развертывание (Docker + Nginx).
- `OBSERVABILITY.md` — метрики, логи, error tracking.
- `RUNBOOK.md` — аварии, бэкапы, восстановление.
- `TESTING.md` — тесты и частые ошибки.
- `RELEASE_CHECKLIST.md` — чек‑лист релиза.
- `RELEASE_NOTES.md` — релизные заметки.
- `PROD_READY_BACKLOG.md` — статус и roadmap до продакшена.

## Важно
- MTProto = личный аккаунт Telegram. Используйте **отдельный номер**.
- Всегда работайте только с **согласиями клиентов**.
- Сессия Telethon (`.session`) — это полный доступ к аккаунту. Храните как секрет.
