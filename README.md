# Telegram CRM Console (MTProto)

Проект для сценария, когда **нужно писать клиентам первыми** в Telegram. Работает через MTProto (личный аккаунт, не бот) и включает локальную UI‑консоль, API, очереди, антиспам, хранение истории и интеграцию с AmoCRM (опционально).

## Что умеет
- Писать первым через MTProto (личный аккаунт Telegram).
- Мульти-аккаунты MTProto (переключение аккаунта в UI).
- Локальная UI‑консоль: авторизация, список чатов, история, шаблоны, карточка контакта.
- Лимиты per‑operator и страница `/ui/operators` для настройки.
- Admin UI: `/admin` (аккаунты, лимиты, настройки).
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

## 📚 Документация

### Начало работы
- [START_HERE.md](START_HERE.md) — **начните отсюда!**
- [QUICKSTART.md](QUICKSTART.md) — полный пошаговый запуск локально
- [CONFIGURATION.md](CONFIGURATION.md) — полный справочник по `.env`
- [UI_GUIDE.md](UI_GUIDE.md) — как работать в UI

### Архитектура и API
- [ARCHITECTURE.md](ARCHITECTURE.md) — компоненты, потоки данных, таблицы
- [API.md](API.md) — все API endpoints и примеры запросов
- [TECHNICAL.md](TECHNICAL.md) — env vars таблица, диагностика

### Операции и Production
- [DEPLOYMENT.md](DEPLOYMENT.md) — прод‑развертывание (Docker + Nginx)
- [OBSERVABILITY.md](OBSERVABILITY.md) — метрики, логи, error tracking
- [RUNBOOK.md](RUNBOOK.md) — аварии, бэкапы, восстановление
- [TESTING.md](TESTING.md) — тесты и частые ошибки

### Релизы и изменения
- [CHANGELOG.md](CHANGELOG.md) — история изменений
- [RELEASE_NOTES.md](RELEASE_NOTES.md) — релизные заметки
- [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) — чек‑лист релиза

### Специальные темы
- [MTPROTO_GUIDE.md](MTPROTO_GUIDE.md) — риски MTProto, лимиты, комплаенс
- [NEED_TO_FIX.md](NEED_TO_FIX.md) — известные проблемы и roadmap
- [EXECUTIVE_SUMMARY.md](EXECUTIVE_SUMMARY.md) — обзор для менеджмента

### Дополнительно
- [docs/bitrix24/](docs/bitrix24/) — интеграция с Bitrix24
- [docs/agent/](docs/agent/) — AI Agent документация
- [docs/methodology/](docs/methodology/) — методология разработки
- [docs/operations/](docs/operations/) — операционные процедуры
- [CLAUDE.md](CLAUDE.md) — инструкции для Claude Code AI

## Важно
- MTProto = личный аккаунт Telegram. Используйте **отдельный номер**.
- Всегда работайте только с **согласиями клиентов**.
- Сессия Telethon (`.session`) — это полный доступ к аккаунту. Храните как секрет.
