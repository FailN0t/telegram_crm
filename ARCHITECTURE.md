# Архитектура и потоки данных

## Общее устройство
Проект состоит из следующих компонентов:

1. **API сервер (FastAPI)** — `src/api_server.py`
   - Публичные API (`/api/*`) и UI API (`/api/ui/*`).
   - Отдаёт UI (`/ui`, `/ui/auth`) и статику `/static/*`.
   - Health‑checks, метрики, SSE.

2. **MTProto клиент (Telethon)** — `src/telegram_client.py`
   - Авторизация аккаунта.
   - Отправка сообщений и обработка входящих.
   - Сохранение истории UI + медиа.

3. **Outbox / Worker** — `src/outbox.py`, `src/outbox_worker.py`
   - Очередь исходящих в БД.
   - Ретраи с backoff.
   - Гарантия порядка по чатам.

4. **Хранилища**
   - **PostgreSQL** — основная БД (история, очереди, профили).
   - **Redis** — anti‑spam + 2FA state (опционально, но рекомендуется).
   - **MinIO** — медиа‑вложения (опционально).

5. **UI** — `static/ui.html`, `static/auth.html`, `static/*.js/css`

## Режимы работы
### 1) Inline (по умолчанию)
`OUTBOX_PROCESS_INLINE=true`
- API сервер сам инициализирует MTProto клиент.
- Отправка из API/UI происходит сразу после постановки в outbox.

### 2) С отдельным worker
`OUTBOX_PROCESS_INLINE=false`
- API сервер **не** держит Telegram соединение.
- Отправку выполняет `outbox_worker`.

Рекомендуется для production (разделение API и доставщика).

## Потоки данных

### Исходящие сообщения (API)
```
POST /api/send-message
        │
        ▼
MessageOutbox (queued)
        │
        ▼
OutboxWorker -> MTProto -> Telegram
        │
        ▼
MessageDeliveryAttempt + UiMessageHistory
```

### Исходящие сообщения (UI)
```
POST /api/ui/send
        │
        ▼
MessageOutbox + UiMessageHistory(status=queued)
        │
        ▼
OutboxWorker -> MTProto -> Telegram
        │
        ▼
UiMessageHistory(status=sent/failed)
```

### Входящие сообщения
```
Telegram -> MTProto event
        │
        ▼
UiMessageHistory(status=received)
        │
        ├─(если есть mapping)→ MessageHistory (CRM‑история)
        ▼
UI получает событие через SSE /api/ui/stream
```

## Хранилище данных (основные таблицы)
- `telegram_accounts` — список MTProto аккаунтов (phone, session_string, статус).
- `chat_mappings` — связь Telegram chat_id ↔ AmoCRM contact_id.
- `chat_profiles` — теги/заметки/consent/quiet hours.
- `message_outbox` — очередь исходящих (idempotency).
- `message_delivery_attempts` — попытки доставки.
- `message_inbox` — дедупликация входящих webhook.
- `telegram_sessions` — StringSession (опционально).
- `message_history` — история для CRM.
- `ui_message_history` — история для UI (inbound/outbound + статусы).
- `ui_chats` — агрегированное состояние чатов (last_message, unread).
- `ui_event_log` — журнал событий UI.
- `operators` — лимиты и метаданные операторов (hourly/daily).
- `app_settings` — admin‑overrides настроек (anti‑spam/outbox).

Account binding:
- `account_id` добавлен в `chat_mappings`, `chat_profiles`, `message_outbox`, `message_history`, `ui_message_history`, `ui_chats`.

Operator binding:
- `operator_id` добавлен в `message_outbox` и передается из UI (Basic Auth username).
- AntiSpam применяет per-operator лимиты поверх глобальных.

## Idempotency
- Для `/api/send-message` используется заголовок `Idempotency-Key` (если нет — генерируется из payload).
- Для вебхуков создаётся `message_inbox` с `payload_hash`.
- Для UI‑отправки можно передать `idempotency_key`.

## Компоненты в коде
```
src/
  api_server.py        # API + UI endpoints
  telegram_client.py   # MTProto клиент
  outbox.py            # очередь, ретраи
  outbox_worker.py     # доставка
  bridge.py            # логика AmoCRM ↔ Telegram
  database.py          # модели БД
  antispam.py          # лимиты
  media_storage.py     # MinIO
```

## UI обновления (SSE)
`/api/ui/stream` публикует события:
- `ui_message` — новые сообщения и обновления статуса.
- `ui_event` — системные события (ошибки, auth, отправка).

UI подписывается и обновляет список чатов/историю без polling.
