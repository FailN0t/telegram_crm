# AmoCRM Widget Setup Guide

## Обзор

AmoCRM Widget интеграция позволяет менеджерам общаться с клиентами в Telegram прямо из карточки контакта в AmoCRM. Аналог Radist, i2crm, Wazzup.

**Функционал:**
- ✅ Отдельная вкладка "Telegram" в карточке контакта
- ✅ Отправка сообщений из AmoCRM → Telegram
- ✅ История переписки в карточке
- ✅ Входящие сообщения из Telegram → AmoCRM в реальном времени
- ✅ Статусы доставки (queued/sent/delivered/read/failed)

## Архитектура

```
AmoCRM Contact Card
    └── Telegram Tab (iframe)
        ├── GET /api/amocrm/widget/chat?contact_id=123
        ├── POST /api/amocrm/widget/send
        └── GET /api/amocrm/widget/history

AmoCRM Webhook
    └── POST /api/webhook/amocrm
        ├── tasks.add (existing)
        └── notes.add (new) - примечания с тегом #telegram

Telegram → AmoCRM
    └── Incoming message
        ├── Saved to UiMessageHistory
        ├── Note created in AmoCRM contact
        └── Widget polls and shows in real-time
```

## Установка

### 1. Откройте страницу установки

```
https://your-domain.com/api/amocrm/widget/install
```

Эта страница содержит пошаговые инструкции и автоматически подставляет URL вашего сервера.

### 2. Создайте интеграцию в AmoCRM

1. Перейдите в **Настройки → Интеграции → Создать интеграцию**
2. Выберите тип: **Widget (виджет)**
3. Заполните:
   - Название: `Telegram CRM`
   - Redirect URI: `https://your-domain.com/api/amocrm/callback`

4. Скопируйте `Client ID` и `Client Secret`

### 3. Настройте переменные окружения

Добавьте в `.env`:

```bash
# AmoCRM OAuth
AMOCRM_CLIENT_ID=your_client_id_here
AMOCRM_CLIENT_SECRET=your_client_secret_here
AMOCRM_SUBDOMAIN=your_subdomain  # например: yourdomain

# AmoCRM Webhook (опционально для безопасности)
AMOCRM_WEBHOOK_SECRET=random_secret_string
```

### 4. Настройте Widget в AmoCRM

В разделе виджета добавьте:

**URL iframe:**
```
https://your-domain.com/api/amocrm/widget/chat?contact_id={{contact.id}}
```

**Параметры:**
- Размещение: Карточка контакта (отдельная вкладка)
- Название вкладки: `Telegram`
- Доступ: Все пользователи

### 5. Настройте Webhook

В AmoCRM добавьте webhook:

**URL:**
```
https://your-domain.com/api/webhook/amocrm
```

**Secret (если используется):** значение из `AMOCRM_WEBHOOK_SECRET`

**События:**
- `notes.add` - для отправки сообщений через примечания с тегом #telegram
- `contacts.update` - для синхронизации изменений (опционально)

### 6. Создайте пользовательские поля

В AmoCRM создайте следующие поля для контактов:

| Название | Тип | API Name | Описание |
|----------|-----|----------|----------|
| Telegram Username | Текст | `telegram_username` | @username клиента |
| Telegram Chat ID | Число | `telegram_chat_id` | ID чата Telegram |
| Telegram согласие | Переключатель | `telegram_consent` | Согласие на рассылку |

**После создания полей:**
1. Перейдите в **Настройки → API**
2. Найдите ID созданных полей
3. Обновите в коде `src/amocrm_client.py` константы:
   ```python
   TELEGRAM_USERNAME_FIELD_ID = 000001  # замените на ваш ID
   TELEGRAM_CHAT_ID_FIELD_ID = 000002   # замените на ваш ID
   TELEGRAM_CONSENT_FIELD_ID = 000003   # замените на ваш ID
   ```

### 7. Авторизуйтесь в AmoCRM

1. Перейдите в админ-панель: `https://your-domain.com/admin/settings`
2. В разделе "AmoCRM Settings" нажмите кнопку авторизации
3. Разрешите доступ в AmoCRM
4. Проверьте что токены сохранились

### 8. Примените миграцию БД

```bash
python3 -m alembic upgrade head
```

Это добавит поле `delivery_status` в таблицу `ui_message_history`.

## Использование

### Отправка сообщений из AmoCRM (3 способа)

#### Способ 1: Через Widget (рекомендуется)

1. Откройте карточку контакта в AmoCRM
2. Перейдите на вкладку "Telegram"
3. Напишите сообщение и нажмите "Отправить"
4. Сообщение появится в истории со статусом

#### Способ 2: Через примечания с тегом #telegram

1. Откройте карточку контакта
2. Добавьте примечание с текстом:
   ```
   Привет! Ваш заказ готов #telegram
   ```
3. Webhook обработает примечание и отправит сообщение
4. Тег `#telegram` будет удалён из текста

#### Способ 3: Через API endpoint (для интеграций)

```bash
curl -X POST https://your-domain.com/api/send-message \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_secret_key" \
  -d '{
    "contact_id": 12345,
    "message": "Тестовое сообщение"
  }'
```

### Получение входящих сообщений

Входящие сообщения из Telegram автоматически:
1. Сохраняются в `ui_message_history` с `direction="inbound"`
2. Создают примечание в карточке контакта AmoCRM (формат: "📥 Входящее от Имя: текст")
3. Отображаются в widget при следующем обновлении (polling каждые 5 секунд)

## Endpoints

### GET /api/amocrm/widget/install

Страница с инструкциями по установке.

### GET /api/amocrm/widget/chat

Возвращает HTML widget с интерфейсом чата.

**Параметры:**
- `contact_id` (required) - ID контакта в AmoCRM
- `account_id` (optional) - ID Telegram аккаунта

**Пример:**
```
/api/amocrm/widget/chat?contact_id=12345
```

### POST /api/amocrm/widget/send

Отправляет сообщение из widget.

**Body:**
```json
{
  "contact_id": 12345,
  "message": "Текст сообщения",
  "phone": "+79991234567",  // optional
  "username": "username"     // optional
}
```

**Response:**
```json
{
  "success": true,
  "message": "Message queued for delivery"
}
```

### GET /api/amocrm/widget/history

Возвращает историю сообщений для контакта.

**Параметры:**
- `contact_id` (required) - ID контакта
- `limit` (optional, default=50) - количество сообщений
- `offset` (optional, default=0) - смещение для пагинации

**Response:**
```json
{
  "messages": [
    {
      "id": 1,
      "direction": "inbound",
      "message_text": "Привет!",
      "status": "received",
      "created_at": "2026-01-22T10:00:00"
    },
    {
      "id": 2,
      "direction": "outbound",
      "message_text": "Здравствуйте!",
      "status": "sent",
      "delivery_status": "delivered",
      "created_at": "2026-01-22T10:01:00"
    }
  ]
}
```

### POST /api/webhook/amocrm

Webhook endpoint для приёма событий от AmoCRM.

**Headers:**
- `X-Webhook-Secret` - секрет для валидации (если настроен)

**Поддерживаемые события:**
- `tasks.add` - новые задачи (существующая функциональность)
- `notes.add` - новые примечания (проверяет тег #telegram)

## Database Schema

### UiMessageHistory

```sql
CREATE TABLE ui_message_history (
    id SERIAL PRIMARY KEY,
    account_id INTEGER REFERENCES telegram_accounts(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    direction VARCHAR(10) NOT NULL,  -- 'inbound' | 'outbound'
    message_text TEXT,
    message_type VARCHAR(50),
    username VARCHAR(255),
    display_name VARCHAR(255),
    status VARCHAR(20) DEFAULT 'sent',
    delivery_status VARCHAR(20) DEFAULT 'queued',  -- NEW FIELD
    error_message TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
```

**delivery_status значения:**
- `queued` - в очереди на отправку
- `sent` - отправлено через MTProto
- `delivered` - доставлено (Telegram подтвердил)
- `read` - прочитано клиентом
- `failed` - ошибка отправки

## Troubleshooting

### Widget не отображается в карточке

1. Проверьте что widget активирован в настройках интеграции AmoCRM
2. Проверьте URL iframe - должен содержать правильный домен
3. Проверьте что OAuth токены валидны (`/admin/settings`)

### Сообщения не отправляются

1. Проверьте логи: `docker-compose logs -f api_server`
2. Проверьте `message_outbox` таблицу на застрявшие сообщения
3. Проверьте что контакт имеет заполненное поле `telegram_username` или `telegram_chat_id`
4. Проверьте что есть `ChatMapping` между контактом и чатом Telegram

### Входящие не отображаются

1. Проверьте что примечания создаются в AmoCRM (раздел контакта)
2. Проверьте таблицу `ui_message_history` - сохраняются ли сообщения
3. Проверьте консоль браузера - работает ли polling
4. Убедитесь что миграция с `delivery_status` применена

### Webhook не срабатывает

1. Проверьте настройки webhook в AmoCRM (правильный URL, активен)
2. Проверьте `X-Webhook-Secret` header совпадает с `.env`
3. Проверьте логи на ошибки обработки webhook
4. Проверьте таблицу `message_inbox` на дубликаты (idempotency)

## Development

### Локальное тестирование widget

```bash
# Запустить сервер
python3 -m src.main

# Открыть widget напрямую
http://localhost:8000/api/amocrm/widget/chat?contact_id=12345
```

### Тестирование webhook локально

Используйте ngrok для туннеля:

```bash
ngrok http 8000
```

Затем в AmoCRM укажите webhook URL:
```
https://abc123.ngrok.io/api/webhook/amocrm
```

## Roadmap

Планируемые улучшения:

- [ ] WebSocket вместо polling для real-time updates
- [ ] Поддержка вложений (фото, файлы)
- [ ] Read receipts tracking (обработка MTProto событий)
- [ ] Templates (шаблоны сообщений)
- [ ] Автоответы
- [ ] Analytics (метрики по переписке)
- [ ] Multi-agent support

## Support

Для вопросов и поддержки:
- GitHub Issues: [создать issue](https://github.com/your-repo/issues)
- Документация: `/docs` директория

---

**Версия:** 1.0
**Дата:** 2026-01-22
**Автор:** Telegram CRM Team
