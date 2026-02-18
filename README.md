# Telegram CRM Console (MTProto)

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-336791.svg)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED.svg)](https://docker.com)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**A self-hosted Telegram CRM system that enables first-contact outreach via MTProto (personal accounts, not bots).** Includes a web-based operator console, REST API, message queuing, anti-spam controls, and optional AmoCRM/Bitrix24 integration.

> Built as a self-hosted alternative to Radist.online, Wazzup24, and i2crm — with full control over your data and infrastructure.

---

## Key Features

- **MTProto Messaging** — Send first messages via personal Telegram accounts (not Bot API)
- **Multi-Account Support** — Manage multiple Telegram accounts with round-robin selection
- **Operator Console** — Real-time web UI with chat list, message history, templates, and SSE updates
- **Message Queue** — Database-backed outbox with retry logic and exponential backoff
- **Anti-Spam Engine** — Global + per-operator rate limits, consent checks, quiet hours, opt-out
- **Contact Protection** — Circuit Breaker pattern, burst detection, direction-aware limits to prevent account bans
- **CRM Integration** — Optional bridge to AmoCRM or Bitrix24 (contact sync, notes, webhooks)
- **Admin Panel** — Account management, operator limits, system settings, audit logs
- **Observability** — Prometheus metrics, structured logging, Sentry-compatible error tracking
- **Production-Ready** — Docker Compose, Nginx, PostgreSQL, Redis, Alembic migrations

## Architecture

```
                        +-----------------------+
                        |    Operator Console   |
                        |   (HTML/JS + SSE)     |
                        +----------+------------+
                                   |
                        +----------v------------+
                        |   FastAPI Server       |
                        |   /api/* + /api/ui/*   |
                        +--+--------+--------+--+
                           |        |        |
              +------------+   +----+----+   +------------+
              |                |         |                 |
    +---------v------+  +-----v---+  +--v---------+  +---v---------+
    | MTProto Client |  | Outbox  |  | Anti-Spam  |  | CRM Bridge  |
    |  (Telethon)    |  | Worker  |  | Manager    |  | AmoCRM /    |
    |  Multi-account |  | Retry   |  | Rate Limit |  | Bitrix24    |
    +--------+-------+  +----+----+  +------------+  +-------------+
             |               |
    +--------v---------------v--------+
    |         PostgreSQL + Redis       |
    |  Messages, Queue, Sessions, etc  |
    +----------------------------------+
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.11+, FastAPI, Telethon (MTProto) |
| Database | PostgreSQL 15, SQLAlchemy (async), Alembic |
| Cache / Rate Limiting | Redis 7 |
| Frontend | Vanilla HTML/JS, SSE (Server-Sent Events) |
| Media Storage | MinIO / S3-compatible (optional) |
| Deployment | Docker Compose, Nginx, systemd |
| Monitoring | Prometheus, Loki, Sentry-compatible DSN |
| CRM | AmoCRM (OAuth), Bitrix24 (OAuth + Open Channels) |

## Quick Start

```bash
cp env.template .env
# Fill in: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, API_SECRET_KEY, DATABASE_URL

pip3 install -r requirements-production.txt
python3 -m alembic upgrade head
python3 -m src.main
```

Open `http://localhost:8000/ui` for the operator console.

## API Example

```bash
curl -X POST http://localhost:8000/api/send-message \
  -H "X-Api-Secret: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"phone": "+79991234567", "message": "Hello!"}'
```

## Documentation

| Document | Description |
|----------|-------------|
| [QUICKSTART.md](QUICKSTART.md) | Step-by-step local setup guide |
| [ARCHITECTURE.md](ARCHITECTURE.md) | System components and data flows |
| [API.md](API.md) | REST API reference with examples |
| [CONFIGURATION.md](CONFIGURATION.md) | Full `.env` variable reference |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Production deployment (Docker + Nginx) |
| [TESTING.md](TESTING.md) | Running tests (unit, integration, load) |
| [OBSERVABILITY.md](OBSERVABILITY.md) | Metrics, logs, error tracking |
| [RUNBOOK.md](RUNBOOK.md) | Incident response and recovery |
| [MTPROTO_GUIDE.md](MTPROTO_GUIDE.md) | MTProto safety, limits, compliance |
| [UI_GUIDE.md](UI_GUIDE.md) | Operator console user guide |
| [CHANGELOG.md](CHANGELOG.md) | Version history |

### CRM Integration
| Document | Description |
|----------|-------------|
| [docs/AMOCRM_SETUP_QUICK.md](docs/AMOCRM_SETUP_QUICK.md) | AmoCRM quick setup |
| [docs/AMOCRM_WIDGET_SETUP.md](docs/AMOCRM_WIDGET_SETUP.md) | AmoCRM widget integration |
| [docs/bitrix24/](docs/bitrix24/) | Bitrix24 integration guides |

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

## Important

- MTProto uses **personal Telegram accounts** (not Bot API). Use a **dedicated phone number**.
- Always obtain **user consent** before messaging.
- Telethon session files (`.session`) grant full account access — treat as secrets.

---

# Telegram CRM Console (MTProto) — Русская версия

**Самостоятельно размещаемая CRM-система для Telegram, позволяющая писать клиентам первыми через MTProto (личные аккаунты, не боты).** Включает веб-консоль оператора, REST API, очередь сообщений, антиспам и опциональную интеграцию с AmoCRM/Bitrix24.

> Самостоятельная альтернатива Radist.online, Wazzup24 и i2crm — с полным контролем над данными и инфраструктурой.

---

## Возможности

- **MTProto-отправка** — Первые сообщения через личные аккаунты Telegram
- **Мульти-аккаунт** — Управление несколькими аккаунтами с round-robin выбором
- **Консоль оператора** — Веб-UI с чатами, историей, шаблонами и SSE-обновлениями
- **Очередь сообщений** — Outbox в БД с ретраями и exponential backoff
- **Антиспам** — Глобальные + per-operator лимиты, consent, quiet hours, opt-out
- **Защита аккаунта** — Circuit Breaker, burst detection, direction-aware лимиты
- **CRM-интеграция** — Мост к AmoCRM или Bitrix24 (контакты, примечания, вебхуки)
- **Админ-панель** — Управление аккаунтами, лимитами, настройками, аудит
- **Наблюдаемость** — Prometheus метрики, структурные логи, Sentry-совместимый tracking
- **Production-ready** — Docker Compose, Nginx, PostgreSQL, Redis, Alembic

## Быстрый старт

```bash
cp env.template .env
# Заполните: TELEGRAM_API_ID, TELEGRAM_API_HASH, TELEGRAM_PHONE, API_SECRET_KEY, DATABASE_URL

pip3 install -r requirements-production.txt
python3 -m alembic upgrade head
python3 -m src.main
```

Откройте `http://localhost:8000/ui` — консоль оператора.

## Пример API-запроса

```bash
curl -X POST http://localhost:8000/api/send-message \
  -H "X-Api-Secret: YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"phone": "+79991234567", "message": "Привет!"}'
```

## Документация

| Документ | Описание |
|----------|----------|
| [QUICKSTART.md](QUICKSTART.md) | Пошаговый запуск локально |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Компоненты и потоки данных |
| [API.md](API.md) | Справочник REST API с примерами |
| [CONFIGURATION.md](CONFIGURATION.md) | Полный справочник переменных `.env` |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Production-развёртывание (Docker + Nginx) |
| [TESTING.md](TESTING.md) | Запуск тестов (unit, integration, load) |
| [OBSERVABILITY.md](OBSERVABILITY.md) | Метрики, логи, error tracking |
| [RUNBOOK.md](RUNBOOK.md) | Реагирование на инциденты |
| [MTPROTO_GUIDE.md](MTPROTO_GUIDE.md) | Безопасность MTProto, лимиты, комплаенс |
| [UI_GUIDE.md](UI_GUIDE.md) | Руководство по консоли оператора |
| [CHANGELOG.md](CHANGELOG.md) | История изменений |

### CRM-интеграция
| Документ | Описание |
|----------|----------|
| [docs/AMOCRM_SETUP_QUICK.md](docs/AMOCRM_SETUP_QUICK.md) | Быстрая настройка AmoCRM |
| [docs/AMOCRM_WIDGET_SETUP.md](docs/AMOCRM_WIDGET_SETUP.md) | Виджет AmoCRM |
| [docs/bitrix24/](docs/bitrix24/) | Руководства по Bitrix24 |

## Лицензия

Проект лицензирован под MIT License — см. [LICENSE](LICENSE).

## Важно

- MTProto использует **личные аккаунты** Telegram. Используйте **отдельный номер**.
- Всегда получайте **согласие клиента** перед отправкой.
- Сессии Telethon (`.session`) дают полный доступ к аккаунту — храните как секреты.
