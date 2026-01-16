# API Reference

## Авторизация
### Внешние API (`/api/*`)
- Требуется заголовок `X-API-Key: <API_SECRET_KEY>`.
- Idempotency: заголовок `Idempotency-Key` (опционально).

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
  "message": "Привет!"
}
```

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

### `GET /api/ui/events`
Список последних событий UI.

### `GET /api/ui/stream`
SSE‑поток событий.

**Query**
- `last_message_id`, `last_event_id` — для восстановления.

**События**
- `event: ui_message`
- `event: ui_event`

### `GET /api/ui/chats`
Список чатов (для UI).

### `POST /api/ui/chats/{chat_id}/read`
Сброс счётчика непрочитанных.

### `GET /api/ui/chat/{chat_id}`
Детали чата: профиль + статистика.

### `POST /api/ui/chat/{chat_id}/profile`
Обновление профиля (tags/notes/consent/quiet hours).

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
{ "phone": "+79990000000" }
```

### `POST /api/ui/auth/submit-code`
Отправка кода авторизации.

**Body**
```json
{ "phone": "+79990000000", "code": "12345" }
```

### `POST /api/ui/auth/submit-password`
Отправка 2FA‑пароля.

**Body**
```json
{ "password": "your-2fa" }
```

### `POST /api/ui/auth/logout`
Выход и удаление локальной сессии.

### `POST /api/ui/send`
Отправка сообщения из UI.

**Body**
```json
{
  "chat_id": 123456,
  "username": "telegram_username",
  "phone": "+79990000000",
  "message": "Привет!",
  "idempotency_key": "optional"
}
```

### `GET /api/ui/messages`
История сообщений (последние N).

**Query**
- `limit` (по умолчанию 50)
- `chat_id` (опционально)

## UI страницы
- `/ui/auth` — авторизация MTProto.
- `/ui` — консоль чатов.
