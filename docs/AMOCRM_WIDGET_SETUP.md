# AmoCRM Integration Setup Guide

## Обзор

Интеграция Telegram CRM с AmoCRM позволяет менеджерам общаться с клиентами через Telegram. Аналог Radist, i2crm, Wazzup.

**Реализованный функционал:**
- ✅ OAuth интеграция с AmoCRM (API доступ)
- ✅ Отправка сообщений из AmoCRM → Telegram через API
- ✅ Webhook для приёма событий от AmoCRM
- ✅ Отправка сообщений через примечания с тегом #telegram
- ✅ Входящие сообщения из Telegram → создают примечания в AmoCRM
- ✅ HTML widget с чатом (iframe)
- ✅ История переписки с real-time обновлениями
- ✅ Статусы доставки (queued/sent/delivered/read/failed)

**Ограничения текущей реализации:**
- ⚠️ Виджет не встраивается автоматически в карточку контакта (требуется публикация в маркетплейс AmoCRM или установка через раздел API → Виджеты)
- ✅ Можно использовать прямой URL виджета в браузере
- ✅ Можно отправлять сообщения через примечания с #telegram (работает уже)

## Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                      AmoCRM Integration                      │
└─────────────────────────────────────────────────────────────┘

OAuth Integration (Приватная интеграция)
    ├── Client ID + Client Secret
    ├── Access Token (до 2031 года)
    ├── Custom Fields: telegram_username, telegram_chat_id, telegram_consent
    └── Webhooks: notes.add, contacts.update

API Endpoints
    ├── POST /api/send-message - отправка через API
    ├── POST /api/webhook/amocrm - приём событий
    ├── GET /api/amocrm/widget/chat?contact_id=123 - HTML виджет
    ├── POST /api/amocrm/widget/send - отправка из виджета
    ├── GET /api/amocrm/widget/history - история сообщений
    └── GET /api/amocrm/widget/download - скачать виджет

Message Flow
    AmoCRM (примечание #telegram) → Webhook → Bridge → Telegram
    Telegram → Bridge → UiMessageHistory → AmoCRM (примечание)
```

## Текущий статус

### ✅ Что работает СЕЙЧАС

**1. Отправка через примечания (готово к использованию):**
```
1. Откройте карточку контакта в AmoCRM
2. Добавьте примечание: "Привет! Как дела? #telegram"
3. Сообщение автоматически отправится клиенту в Telegram
```

**2. Входящие сообщения:**
```
1. Клиент пишет в Telegram
2. В AmoCRM автоматически создаётся примечание:
   "📥 Входящее от Имя Клиента: текст сообщения"
```

**3. API отправка:**
```bash
curl -X POST https://your-server.example.com/api/send-message \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_secret_key" \
  -d '{
    "contact_id": 12345,
    "message": "Тестовое сообщение"
  }'
```

**4. Прямой доступ к виджету:**
```
https://your-server.example.com/api/amocrm/widget/chat?contact_id=CONTACT_ID
```
Откройте в браузере, заменив CONTACT_ID на ID контакта из AmoCRM.

### ⚠️ Что требует дополнительной настройки

**Встраивание виджета В карточку контакта (как у Radist/Wazzup):**

Для этого нужен один из вариантов:

#### Вариант 1: Установка через раздел API → Виджеты

1. Откройте AmoCRM → **Настройки** (значок шестерёнки)
2. В левом меню найдите **"API"** (не "Интеграции"!)
3. Перейдите на вкладку **"Виджеты"**
4. Нажмите **"Добавить виджет"** (внизу страницы)
5. Скачайте виджет: https://your-server.example.com/api/amocrm/widget/download
6. Загрузите скачанный `telegram_crm_widget.zip`
7. Нажмите **"Установить"**

**Если раздела "API → Виджеты" нет** → переходите к Варианту 2.

#### Вариант 2: Публикация в маркетплейс AmoCRM

Для встраивания виджета как у Radist/Wazzup нужно подать интеграцию на публикацию:

1. **Документация:** https://www.amocrm.ru/developers/content/integrations/marketplace
2. **Процесс:**
   - Подать заявку через партнёрский портал AmoCRM
   - Модерация кода и функционала (2-4 недели)
   - После одобрения → виджет в маркетплейсе
3. **Требования:**
   - Проверка безопасности JavaScript кода
   - Описание, иконки, скриншоты
   - Условия использования

**После публикации:**
- ✅ Виджет встраивается в карточки автоматически
- ✅ Доступен для установки всем пользователям AmoCRM
- ✅ Работает точно как Radist/Wazzup

#### Вариант 3: Browser Extension (временное решение)

Установить расширение браузера (Tampermonkey/Greasemonkey), которое автоматически встроит iframe с виджетом в карточки контактов AmoCRM.

## Установка (пошаговая)

### Шаг 1: Настройка OAuth интеграции (✅ УЖЕ ВЫПОЛНЕНО)

Если вы следовали предыдущим инструкциям, у вас уже настроено:
- ✅ OAuth интеграция "Telegram CRM" в AmoCRM
- ✅ Client ID и Secret в `.env`
- ✅ Access Token получен и сохранён
- ✅ Custom поля созданы (telegram_username, telegram_chat_id, telegram_consent)

Проверить можно в `.env`:
```bash
AMOCRM_DOMAIN=yourdomain.amocrm.ru
AMOCRM_CLIENT_ID=...
AMOCRM_CLIENT_SECRET=...
AMOCRM_ACCESS_TOKEN=...
AMOCRM_FIELD_TELEGRAM_USERNAME=<field_id>
AMOCRM_FIELD_TELEGRAM_CHAT_ID=<field_id>
AMOCRM_FIELD_TELEGRAM_CONSENT=<field_id>
```

### Шаг 2: Настройка Webhook в AmoCRM

1. Откройте вашу интеграцию в AmoCRM
2. Перейдите на вкладку **"Ключи и доступы"**
3. Найдите раздел **"Webhooks"**
4. Добавьте webhook:
   - **URL:** `https://your-server.example.com/api/webhook/amocrm`
   - **События:**
     - ✅ `notes.add` - для отправки через примечания с #telegram
     - ✅ `contacts.update` - для синхронизации изменений (опционально)

5. Сохраните секрет webhook в `.env` (если используется):
   ```bash
   AMOCRM_WEBHOOK_SECRET=your_webhook_secret
   ```

### Шаг 3: Применение миграции БД

```bash
# На production сервере
ssh user@your-server.example.com
cd /opt/telegram-crm
docker exec amocrm-telegram-app python3 -m alembic upgrade heads
```

Это добавит поле `delivery_status` в таблицу `ui_message_history`.

### Шаг 4: Тестирование

#### Тест 1: Отправка через примечание
```
1. Откройте любую карточку контакта в AmoCRM
2. Убедитесь что у контакта заполнено поле telegram_username или telegram_chat_id
3. Добавьте примечание: "Тест отправки #telegram"
4. Проверьте что сообщение пришло клиенту в Telegram
5. В логах сервера должно быть: "📝 Отправка сообщения из примечания AmoCRM"
```

#### Тест 2: Входящее сообщение
```
1. Попросите клиента написать сообщение в Telegram
2. В AmoCRM откройте карточку контакта
3. Проверьте что появилось примечание: "📥 Входящее от Имя: текст"
```

#### Тест 3: Прямой виджет
```
1. Откройте: https://your-server.example.com/api/amocrm/widget/chat?contact_id=12345
   (замените 12345 на реальный ID контакта)
2. Должен открыться чат с историей сообщений
3. Попробуйте отправить сообщение через форму
4. Проверьте что оно дошло до клиента
```

## Использование

### Способ 1: Через примечания (рекомендуется СЕЙЧАС)

**Отправка сообщения:**
1. Откройте карточку контакта
2. Добавьте примечание с текстом и тегом `#telegram`
3. Сообщение автоматически отправится

**Преимущества:**
- ✅ Работает сразу, без установки виджета
- ✅ Удобно для быстрых сообщений
- ✅ История сохраняется в примечаниях

**Недостатки:**
- ⚠️ Нет real-time отображения входящих
- ⚠️ Нет статусов доставки в интерфейсе

### Способ 2: Через API endpoint

```bash
curl -X POST https://your-server.example.com/api/send-message \
  -H "Content-Type: application/json" \
  -H "X-API-Key: your_api_secret_key" \
  -d '{
    "contact_id": 12345,
    "message": "Привет! Как дела?",
    "phone": "+79991234567"
  }'
```

**Преимущества:**
- ✅ Программная отправка
- ✅ Интеграция с другими системами
- ✅ Идемпотентность (Idempotency-Key)

### Способ 3: Через виджет (после установки)

**После установки виджета через API → Виджеты или маркетплейс:**
1. Откройте карточку контакта в AmoCRM
2. Справа появится блок "💬 Telegram"
3. Введите сообщение и отправьте
4. Входящие появятся автоматически (polling 5 сек)

**Преимущества:**
- ✅ Real-time история переписки
- ✅ Статусы доставки
- ✅ Удобный интерфейс чата
- ✅ Полная интеграция в AmoCRM

## API Reference

### POST /api/send-message

Отправка сообщения через API.

**Headers:**
```
Content-Type: application/json
X-API-Key: your_api_secret_key
Idempotency-Key: unique_request_id (optional)
```

**Body:**
```json
{
  "contact_id": 12345,
  "message": "Текст сообщения",
  "phone": "+79991234567",
  "username": "telegram_username"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Message queued for delivery",
  "outbox_id": 123
}
```

### POST /api/webhook/amocrm

Webhook для приёма событий от AmoCRM.

**Headers:**
```
X-Webhook-Secret: webhook_secret (if configured)
```

**Обрабатываемые события:**
- `tasks.add` - новые задачи
- `notes.add` - новые примечания (проверяет тег #telegram)
- `contacts.update` - обновления контактов

**Примечание с #telegram:**
```json
{
  "notes": {
    "add": [{
      "id": 123,
      "entity_id": 12345,
      "note": {
        "text": "Привет! #telegram",
        "note_type": "common"
      }
    }]
  }
}
```

### GET /api/amocrm/widget/chat

HTML виджет с чатом для встраивания в AmoCRM.

**Parameters:**
- `contact_id` (required) - ID контакта в AmoCRM
- `account_id` (optional) - ID Telegram аккаунта

**Response:** HTML страница с iframe чатом

### POST /api/amocrm/widget/send

Отправка сообщения из виджета.

**Body:**
```json
{
  "contact_id": 12345,
  "message": "Текст сообщения",
  "phone": "+79991234567",
  "username": "telegram_username"
}
```

### GET /api/amocrm/widget/history

История сообщений для виджета.

**Parameters:**
- `contact_id` (required) - ID контакта
- `limit` (optional, default=50) - количество сообщений
- `offset` (optional, default=0) - смещение

**Response:**
```json
{
  "messages": [
    {
      "id": 1,
      "direction": "inbound",
      "message_text": "Привет!",
      "status": "received",
      "delivery_status": "delivered",
      "created_at": "2026-01-22T10:00:00"
    }
  ]
}
```

### GET /api/amocrm/widget/download

Скачать архив виджета для установки в AmoCRM.

**Response:** `telegram_crm_widget.zip` (содержит manifest.json и script.js)

### GET /api/amocrm/widget/install

Страница с инструкциями по установке виджета.

## Database Schema

### UiMessageHistory (обновлено)

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
    delivery_status VARCHAR(20) DEFAULT 'queued',  -- NEW: queued/sent/delivered/read/failed
    error_message TEXT,
    media_url TEXT,
    media_name VARCHAR(255),
    media_mime VARCHAR(255),
    media_size INTEGER,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_ui_message_history_delivery_status ON ui_message_history (delivery_status);
```

## Troubleshooting

### Примечание с #telegram не отправляется

**Проверьте:**
1. Webhook настроен в AmoCRM и событие `notes.add` включено
2. В логах сервера появляется: `"📝 Отправка сообщения из примечания AmoCRM"`
3. У контакта заполнено поле `telegram_username` или `telegram_chat_id`
4. Есть `ChatMapping` между контактом и Telegram чатом

**Команды для проверки:**
```bash
# Проверить логи webhook
docker logs amocrm-telegram-app --tail 100 | grep "webhook"

# Проверить ChatMapping для контакта
docker exec amocrm-telegram-postgres psql -U postgres -d telegram_crm \
  -c "SELECT * FROM chat_mappings WHERE amocrm_contact_id = 12345;"
```

### Входящие сообщения не создают примечания

**Проверьте:**
1. В логах есть: `"📥 Входящее от..."`
2. Проверьте таблицу `ui_message_history`:
```bash
docker exec amocrm-telegram-postgres psql -U postgres -d telegram_crm \
  -c "SELECT * FROM ui_message_history WHERE direction='inbound' ORDER BY created_at DESC LIMIT 10;"
```

### Виджет не загружается

**Если открываете прямой URL виджета:**
1. Проверьте что контакт существует в AmoCRM
2. Проверьте логи: `docker logs amocrm-telegram-app --tail 50`
3. Убедитесь что AmoCRM OAuth токен валиден

**Если виджет не появляется в карточке:**
- Виджет требует установки через "API → Виджеты" или публикации в маркетплейс
- Используйте Способ 1 (примечания) пока виджет не установлен

### Ошибка "Contact not found"

Убедитесь что:
1. ID контакта правильный
2. У вас есть доступ к этому контакту в AmoCRM
3. OAuth токен актуален

## Roadmap

### Ближайшие улучшения

- [ ] Публикация в маркетплейс AmoCRM
- [ ] WebSocket вместо polling для real-time обновлений
- [ ] Read receipts (отслеживание прочтения)
- [ ] Поддержка вложений (фото, файлы)

### Долгосрочные планы

- [ ] Групповые чаты
- [ ] Templates (шаблоны сообщений)
- [ ] Автоответы
- [ ] Analytics (метрики по переписке)
- [ ] Multi-agent support

## Support

**Документация:**
- Эта страница: `docs/AMOCRM_WIDGET_SETUP.md`
- Основная документация: `docs/` директория
- Страница установки: https://your-server.example.com/api/amocrm/widget/install

**Техническая поддержка:**
- GitHub Issues: создайте issue в репозитории
- Email: support@example.com

---

**Версия:** 1.0
**Дата:** 2026-01-22
**Статус:** Production Ready (примечания + API), Widget в разработке (требует публикации)
