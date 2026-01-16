# API Reference

## Авторизация
### Внешние API (`/api/*`)
- Требуется заголовок `X-API-Key: <API_SECRET_KEY>`.
- Idempotency: заголовок `Idempotency-Key` (опционально).
- Ограничение частоты запросов: `API_RATE_LIMIT_PER_MINUTE` (ответ `429 rate_limit_exceeded`).

### UI API (`/api/ui/*`)
- Если `UI_BASIC_AUTH_ENABLED=true`, используется Basic Auth.
- Иначе доступны без авторизации.

## Health и диагностика
- `GET /health` — общий статус (Telegram + DB).
- `GET /ready` — readiness probe.
- `GET /live` — liveness probe.
- `GET /startup` — startup probe (ожидание авторизации MTProto).
- `GET /metrics` — Prometheus метрики (при `ENABLE_METRICS=true`).

## Публичные endpoints

### `POST /api/send-message`
Отправка сообщения клиенту из внешней системы.

**Headers**
- `X-API-Key: <API_SECRET_KEY>`
- `Idempotency-Key: <optional>`

**Body**
```json
{
  "contact_id": 123456,
  "phone": "+79990000000",
  "username": "telegram_username",
  "account_id": 1,
  "message": "Привет!"
}
```
`account_id` опционален — если не задан, используется маппинг контакта или round‑robin среди активных аккаунтов.

**Ответ (успех)**
```json
{
  "success": true,
  "message": "Queued",
  "contact_id": 123456,
  "status": "queued",
  "outbox_id": 42,
  "idempotency_key": "..."
}
```

**Ошибки**
- `400` — не указан `phone` или `username`.
- `403` — неверный API ключ.
- `503` — AmoCRM не настроен/bridge не готов.
- `500` — ошибка отправки.

### `POST /api/webhook/amocrm`
Webhook от AmoCRM (создание задач).

**Headers**
- `X-Webhook-Secret: <secret>` если задан `AMOCRM_WEBHOOK_SECRET`.

**Ответ**
```json
{ "success": true, "message": "Queued" }
```

### `GET /api/stats`
Статистика (Telegram, маппинги, история).

**Headers**
- `X-API-Key: <API_SECRET_KEY>`

### `GET /api/contact/{contact_id}/status`
Проверка статуса контакта.

**Headers**
- `X-API-Key: <API_SECRET_KEY>`

## UI API

### `GET /api/ui/status`
Возвращает:
- `connected`, `authorized`, `user`
- `session` (файл или StringSession)
- `anti_spam` (текущие лимиты)
- `accounts` (статусы всех аккаунтов)
- `default_account_id`

### `GET /api/ui/accounts`
Список Telegram аккаунтов и их статусы.

### `GET /api/ui/events`
Список последних событий UI.

### `GET /api/ui/operators`
Список операторов и их лимитов.

**Ответ**
```json
{
  "operators": [
    {
      "id": 1,
      "username": "operator",
      "display_name": "Operator",
      "email": "operator@example.com",
      "hourly_limit": 50,
      "daily_limit": 200,
      "sent_last_hour": 12,
      "sent_last_day": 120,
      "created_at": "2026-01-16T10:00:00Z"
    }
  ]
}
```

### `PATCH /api/ui/operators/{operator_id}`
Обновление лимитов оператора. Требуется роль `admin`.

**Body**
```json
{
  "display_name": "Operator",
  "email": "operator@example.com",
  "hourly_limit": 60,
  "daily_limit": 240
}
```

**Ответ**
```json
{
  "success": true,
  "operator": {
    "id": 1,
    "username": "operator",
    "display_name": "Operator",
    "email": "operator@example.com",
    "hourly_limit": 60,
    "daily_limit": 240
  }
}
```

### `GET /api/ui/stream`
SSE‑поток событий.

**Query**
- `last_message_id`, `last_event_id` — для восстановления.
- `account_id` — фильтр по аккаунту.

**События**
- `event: ui_message`
- `event: ui_event`

## Admin API

> Требуется Basic Auth с ролью `admin`.

### `GET /api/admin/summary`
Сводка по системе (аккаунты, операторы, outbox, последнее событие).

### `GET /api/admin/accounts`
Список Telegram аккаунтов (label, active, статус).

### `PATCH /api/admin/accounts/{account_id}`
Обновление `label` и `is_active` аккаунта.

**Body**
```json
{
  "label": "Team A",
  "is_active": true
}
```

### `GET /api/admin/settings`
Список admin‑настроек и их текущие значения.

### `PATCH /api/admin/settings`
Обновление admin‑настроек.

**Body**
```json
{
  "values": {
    "MAX_MESSAGES_PER_HOUR": 60,
    "OUTBOX_POLL_INTERVAL": 3
  }
}
```

### `GET /api/admin/amocrm/status`
Статус AmoCRM OAuth (конфигурация + наличие токенов).

### `GET /api/admin/amocrm/oauth/url`
Вернёт URL для запуска OAuth (перенаправление в AmoCRM).

### `GET /api/admin/amocrm/oauth/callback`
OAuth callback, обменивает `code` на токены и перенаправляет обратно в `/admin/settings`.

### `GET /api/admin/templates`
Список шаблонов быстрых ответов (admin).

### `POST /api/admin/templates`
Создание шаблона.

**Body**
```json
{
  "label": "Приветствие",
  "body": "Привет! Спасибо за сообщение. Чем помочь?",
  "is_active": true
}
```

### `PATCH /api/admin/templates/{template_id}`
Обновление шаблона (label/body/is_active).

### `DELETE /api/admin/templates/{template_id}`
Удаление шаблона.

### `GET /api/admin/tags`
Список тегов (admin).

### `POST /api/admin/tags`
Создание тега.

**Body**
```json
{
  "name": "vip",
  "description": "Ключевой клиент",
  "color": "#229ED9",
  "is_active": true
}
```

### `PATCH /api/admin/tags/{tag_id}`
Обновление тега (name/description/color/is_active).

### `DELETE /api/admin/tags/{tag_id}`
Удаление тега.

### `POST /api/admin/retention/run`
Запуск очистки по retention-политике (удаление старых записей).

### `GET /api/admin/logs`
Tail логов приложения.

**Query**
- `limit` — максимум строк (1–1000)
- `level` — фильтр по уровню (INFO/WARNING/ERROR)
- `search` — подстрока

### `GET /api/admin/audit`
Audit log admin‑действий.

**Query**
- `limit` — максимум записей (1–200)
- `actor` — фильтр по пользователю
- `action` — фильтр по действию

### `GET /api/ui/templates`
Список активных шаблонов для UI.

### `GET /api/ui/tags`
Список активных тегов для UI.

### `GET /api/ui/chats`
Список чатов (для UI).

**Query**
- `account_id` — аккаунт, для которого вернуть список.

### `POST /api/ui/chats/{chat_id}/read`
Сброс счётчика непрочитанных.

**Query**
- `account_id`

### `GET /api/ui/chat/{chat_id}`
Детали чата: профиль + статистика.

**Query**
- `account_id`

### `POST /api/ui/chat/{chat_id}/profile`
Обновление профиля (tags/notes/consent/quiet hours).

**Query**
- `account_id`

**Body**
```json
{
  "tags": "lead, vip",
  "notes": "Клиент попросил перезвонить",
  "has_consent": true,
  "opted_out": false,
  "quiet_hours_start": "21:00",
  "quiet_hours_end": "09:00",
  "timezone": "Europe/Moscow"
}
```

### `POST /api/ui/auth/request-code`
Запрос кода авторизации.

**Body**
```json
{ "phone": "+79990000000", "account_id": 1 }
```

### `POST /api/ui/auth/submit-code`
Отправка кода авторизации.

**Body**
```json
{ "phone": "+79990000000", "code": "12345", "account_id": 1 }
```

### `POST /api/ui/auth/submit-password`
Отправка 2FA‑пароля.

**Body**
```json
{ "password": "your-2fa", "account_id": 1 }
```

### `POST /api/ui/auth/logout`
Выход и удаление локальной сессии.

**Query**
- `account_id`

### `POST /api/ui/send`
Отправка сообщения из UI.

**Body**
```json
{
  "chat_id": 123456,
  "username": "telegram_username",
  "phone": "+79990000000",
  "account_id": 1,
  "message": "Привет!",
  "idempotency_key": "optional"
}
```

### `GET /api/ui/messages`
История сообщений (последние N).

**Query**
- `limit` (по умолчанию 50)
- `chat_id` (опционально)
- `account_id`

## UI страницы
- `/ui/auth` — авторизация MTProto.
- `/ui` — консоль чатов.
