# Настройка Bitrix24 Open Channels (Открытые линии)

Данное руководство описывает настройку двусторонней интеграции Telegram с Bitrix24 через Open Channels (Открытые линии). После настройки операторы смогут отвечать клиентам прямо из карточки контакта в Bitrix24.

## Предварительные требования

- Доступ администратора к порталу Bitrix24
- Сервер с публичным HTTPS URL (для webhook)
- Настроенная система Telegram CRM Console

---

## Шаг 1: Создание локального приложения в Bitrix24

> **ВАЖНО:** Обычный входящий webhook НЕ поддерживает Open Channels! Необходимо создать полноценное OAuth-приложение.

### 1.1 Переход к созданию приложения

Откройте в браузере:
```
https://ВАШ-ДОМЕН.bitrix24.ru/devops/edit/local/
```

Или через меню: **Приложения** → **Разработчикам** → **Другое** → **Локальное приложение**

### 1.2 Заполнение формы приложения

| Поле | Значение |
|------|----------|
| **Название** | Telegram MTProto Integration |
| **Тип** | Серверное приложение |

### 1.3 Права доступа (scope)

Отметьте следующие права:

- [x] `imconnector` - Открытые линии (коннекторы)
- [x] `imopenlines` - Открытые линии
- [x] `im` - Чат и уведомления
- [x] `crm` - CRM
- [x] `user` - Пользователи
- [x] `placement` - Встройка интерфейса (опционально)

### 1.4 URL-адреса

| Поле | Значение |
|------|----------|
| **URL вашего обработчика** | `https://ваш-сервер.com/api/webhook/bitrix24/openlines` |
| **Redirect URI** | `https://ваш-сервер.com/api/bitrix24/oauth/callback` |

### 1.5 Сохранение и получение ключей

После сохранения скопируйте:
- **Код приложения (client_id)**: `local.xxxxxxxx.yyyyyyyy`
- **Ключ приложения (client_secret)**: `zzzzzzzzzzzzzz`

---

## Шаг 2: Создание Открытой линии

### 2.1 Переход в Контакт-центр

Откройте в Bitrix24:
```
https://ВАШ-ДОМЕН.bitrix24.ru/contact_center/
```

Или через меню: **CRM** → **Клиенты** → **Контакт-центр**

Альтернативный путь: **CRM** → **Ещё** → **Интеграции** → **Контакт-центр**

### 2.2 Создание линии

1. Нажмите **"Создать открытую линию"**
2. Заполните настройки:

| Параметр | Рекомендация |
|----------|-------------|
| **Название** | Telegram |
| **Очередь операторов** | Добавьте сотрудников |
| **Рабочее время** | По желанию |
| **Автоматические ответы** | По желанию |

3. Нажмите **Сохранить**

### 2.3 Получение ID линии

После сохранения ID линии будет виден:
- В URL страницы настроек: `...line_id=1`
- Или через API `/api/bitrix24/openlines/status`

---

## Шаг 3: Настройка переменных окружения

Добавьте в файл `.env`:

```bash
# ============================================
# Bitrix24 Open Channels Configuration
# ============================================

# CRM провайдер
CRM_PROVIDER=bitrix24

# Bitrix24 OAuth (данные локального приложения)
BITRIX24_DOMAIN=ваш-домен.bitrix24.ru
BITRIX24_CLIENT_ID=local.xxxxxxxx.yyyyyyyy
BITRIX24_CLIENT_SECRET=ваш_секретный_ключ
BITRIX24_REDIRECT_URI=https://ваш-сервер.com/api/bitrix24/oauth/callback

# Open Channels
BITRIX24_OPEN_CHANNELS_ENABLED=true
BITRIX24_CONNECTOR_ID=telegram_mtproto
BITRIX24_CONNECTOR_NAME=Telegram MTProto
BITRIX24_LINE_ID=1
```

### Описание переменных

| Переменная | Описание |
|------------|----------|
| `BITRIX24_DOMAIN` | Домен вашего портала Bitrix24 (без https://) |
| `BITRIX24_CLIENT_ID` | Код приложения из Шага 1 |
| `BITRIX24_CLIENT_SECRET` | Ключ приложения из Шага 1 |
| `BITRIX24_REDIRECT_URI` | URL для OAuth callback |
| `BITRIX24_OPEN_CHANNELS_ENABLED` | Включить Open Channels (`true`/`false`) |
| `BITRIX24_CONNECTOR_ID` | ID коннектора (можно оставить по умолчанию) |
| `BITRIX24_CONNECTOR_NAME` | Название канала в Bitrix24 |
| `BITRIX24_LINE_ID` | ID открытой линии из Шага 2 |

---

## Шаг 4: Запуск и OAuth авторизация

### 4.1 Запуск сервера

```bash
python3 -m src.main
```

### 4.2 Прохождение OAuth авторизации

1. Откройте в браузере:
   ```
   https://ваш-сервер.com/api/bitrix24/oauth/start
   ```

2. Вы будете перенаправлены на страницу Bitrix24

3. Нажмите **"Разрешить"** для предоставления прав приложению

4. После успешной авторизации увидите:
   ```json
   {
     "success": true,
     "message": "Авторизация Bitrix24 успешна! Токены сохранены."
   }
   ```

---

## Шаг 5: Регистрация коннектора

### 5.1 Вызов setup endpoint

```bash
curl -X POST "https://ваш-сервер.com/api/bitrix24/openlines/setup?webhook_url=https://ваш-сервер.com/api/webhook/bitrix24/openlines" \
  -H "X-API-Key: ваш_api_secret_key"
```

### 5.2 Ожидаемый ответ

```json
{
  "connector_registered": true,
  "connector_activated": true,
  "events_registered": {
    "ONIMCONNECTORMESSAGEADD": true,
    "ONIMCONNECTORLINEJOIN": true
  }
}
```

---

## Шаг 6: Проверка статуса интеграции

### 6.1 Запрос статуса

```bash
curl "https://ваш-сервер.com/api/bitrix24/openlines/status" \
  -H "X-API-Key: ваш_api_secret_key"
```

### 6.2 Пример ответа

```json
{
  "enabled": true,
  "connector_id": "telegram_mtproto",
  "line_id": 1,
  "connector_status": {
    "active": true,
    "connection": true
  },
  "available_lines": [...],
  "registered_events": [...]
}
```

---

## Шаг 7: Тестирование

### 7.1 Входящее сообщение (Telegram → Bitrix24)

1. Отправьте сообщение в Telegram с телефона клиента
2. В Bitrix24 откройте: **CRM** → **Открытые линии**
3. Должен появиться новый чат с сообщением

### 7.2 Исходящее сообщение (Bitrix24 → Telegram)

1. Ответьте на сообщение в окне чата Bitrix24
2. Проверьте, что сообщение доставлено в Telegram

### 7.3 Проверка в карточке контакта

1. Откройте карточку контакта в CRM
2. На вкладке "Чаты" или "Открытые линии" должна быть история переписки

---

## Схема работы

```
┌─────────────────┐                    ┌──────────────────┐                    ┌─────────────────┐
│                 │    MTProto         │                  │    REST API        │                 │
│    Telegram     │ ◄──────────────►   │   Ваш сервер     │ ◄──────────────►   │    Bitrix24     │
│    Клиент       │                    │                  │                    │   Open Lines    │
│                 │                    │                  │                    │                 │
└─────────────────┘                    └──────────────────┘                    └─────────────────┘
        │                                      │                                       │
        │                                      │                                       │
        ▼                                      ▼                                       ▼
   Пишет сообщение              Пересылает в Bitrix24                      Оператор видит чат
                                через imconnector API                      в карточке клиента
        │                                      │                                       │
        │                                      │                                       │
        ▼                                      ▼                                       ▼
   Получает ответ               Получает webhook от                       Оператор отвечает
   в Telegram                   Bitrix24 и отправляет                     клиенту
                                через MTProto
```

---

## Устранение неполадок

### Проблема: "connector not registered"

**Решение:** Повторно вызовите `/api/bitrix24/openlines/setup`

### Проблема: "401 Unauthorized" при вызове API

**Решение:**
1. Проверьте, прошли ли OAuth авторизацию
2. Повторите авторизацию: `/api/bitrix24/oauth/start`

### Проблема: Сообщения не появляются в Bitrix24

**Решение:**
1. Проверьте `BITRIX24_OPEN_CHANNELS_ENABLED=true`
2. Проверьте `BITRIX24_LINE_ID` соответствует ID линии
3. Проверьте логи сервера на ошибки

### Проблема: Ответы из Bitrix24 не доходят в Telegram

**Решение:**
1. Проверьте webhook URL в настройках приложения
2. Убедитесь, что сервер доступен по HTTPS
3. Проверьте логи на входящие webhook события

---

## API Endpoints

| Метод | Endpoint | Описание |
|-------|----------|----------|
| GET | `/api/bitrix24/oauth/start` | Начало OAuth авторизации |
| GET | `/api/bitrix24/oauth/callback` | Callback для OAuth |
| POST | `/api/bitrix24/openlines/setup` | Настройка коннектора |
| GET | `/api/bitrix24/openlines/status` | Статус интеграции |
| POST | `/api/webhook/bitrix24/openlines` | Webhook от Bitrix24 |

---

## Безопасность

1. **HTTPS обязателен** - Bitrix24 не отправляет webhook на HTTP
2. **API ключ** - Используйте `X-API-Key` для защиты endpoints
3. **Токены** - Хранятся в базе данных, автоматически обновляются
4. **Права** - Приложение имеет только необходимые права

---

## Поддержка

При возникновении проблем:
1. Проверьте логи сервера: `docker logs telegram-crm`
2. Проверьте статус: `/api/bitrix24/openlines/status`
3. Проверьте документацию Bitrix24: https://dev.1c-bitrix.ru/rest_help/
