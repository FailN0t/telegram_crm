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
https://ВАШ-ДОМЕН.bitrix24.ru/devops/section/standard/
```

Или через меню: **Приложения** → **Разработчикам** → **Другое** → **Локальное приложение**

### 1.2 Заполнение формы приложения

#### Основные настройки

| Поле | Значение |
|------|----------|
| **Название** | Telegram CRM |
| **Тип приложения** | **Серверное** (обязательно!) |

#### URL-адреса

> **КРИТИЧЕСКИ ВАЖНО:** Оба URL должны быть одинаковыми!

| Поле | Значение |
|------|----------|
| **Путь вашего обработчика** | `https://ваш-сервер.com/api/bitrix24/install` |
| **Путь для первоначальной установки** | `https://ваш-сервер.com/api/bitrix24/install` |

**Примеры:**
- `https://tg.example.com/api/bitrix24/install`
- `https://crm.mycompany.ru/api/bitrix24/install`

#### Код приложения (Client ID & Secret)

После создания приложения вы получите:
- **Код приложения (client_id)**: `local.XXXXXXXX.YYYYYYYY`
- **Ключ приложения (client_secret)**: длинная строка символов

**Скопируйте и сохраните эти данные!**

### 1.3 Права доступа (Scopes)

Отметьте следующие права:

- ✅ **imconnector** - Открытые линии (коннекторы) - **ОБЯЗАТЕЛЬНО**
- ✅ **crm** - CRM (для работы с контактами)
- ✅ **user** - Пользователи (для получения информации о пользователях)

> Права `imopenlines`, `im`, `placement` опциональны, но рекомендуются для расширенной функциональности.

---

## Шаг 2: Настройка переменных окружения

Добавьте в файл `.env`:

```bash
# ============================================
# Bitrix24 Configuration
# ============================================

# CRM провайдер
CRM_PROVIDER=bitrix24

# Bitrix24 OAuth (данные локального приложения)
BITRIX24_DOMAIN=ваш-домен.bitrix24.ru
BITRIX24_CLIENT_ID=local.XXXXXXXX.YYYYYYYY
BITRIX24_CLIENT_SECRET=ваш_секретный_ключ
BITRIX24_REDIRECT_URI=https://ваш-сервер.com/api/bitrix24/install

# Open Channels
BITRIX24_OPEN_CHANNELS_ENABLED=true
BITRIX24_CONNECTOR_ID=telegram_mtproto
BITRIX24_CONNECTOR_NAME=Telegram CRM
BITRIX24_LINE_ID=0
```

### Описание переменных

| Переменная | Описание | Пример |
|------------|----------|--------|
| `BITRIX24_DOMAIN` | Домен вашего портала Bitrix24 (без `https://`) | `mycompany.bitrix24.ru` |
| `BITRIX24_CLIENT_ID` | Код приложения из Шага 1 | `local.696d4abc.67109030` |
| `BITRIX24_CLIENT_SECRET` | Ключ приложения из Шага 1 | `puozvbq230p32qNaN7MP...` |
| `BITRIX24_REDIRECT_URI` | URL для OAuth callback (тот же что в настройках приложения) | `https://tg.example.com/api/bitrix24/install` |
| `BITRIX24_OPEN_CHANNELS_ENABLED` | Включить Open Channels | `true` или `false` |
| `BITRIX24_CONNECTOR_ID` | ID коннектора (уникальный идентификатор) | `telegram_mtproto` |
| `BITRIX24_CONNECTOR_NAME` | Название канала в Bitrix24 | `Telegram CRM` |
| `BITRIX24_LINE_ID` | ID открытой линии (0 = основная линия) | `0` |

> **Примечание:** `BITRIX24_LINE_ID=0` означает основную (дефолтную) линию Bitrix24. Если у вас несколько линий, укажите конкретный ID.

---

## Шаг 3: Установка приложения в Bitrix24

### 3.1 Запуск сервера

```bash
# Запуск в разработке
python3 -m src.main

# Или через Docker
docker-compose up -d
```

### 3.2 Установка приложения

> **ВАЖНО:** После запуска сервера установка происходит автоматически!

1. **Зайдите в ваше приложение в Bitrix24:**
   ```
   https://ваш-домен.bitrix24.ru/devops/section/standard/
   ```

2. **Нажмите "Установить"** на вашем приложении

3. **Bitrix24 автоматически:**
   - Отправит токены авторизации на ваш сервер
   - Зарегистрирует Open Channels коннектор
   - Активирует коннектор на линии
   - Зарегистрирует webhook события

4. **Вы увидите страницу подтверждения:**
   ```
   ✓ Приложение успешно установлено!
   Telegram CRM готов к работе.
   ```

### 3.3 Проверка в логах сервера

В логах должны появиться записи:

```
✅ Bitrix24 приложение установлено для ваш-домен.bitrix24.ru
✅ Коннектор telegram_mtproto зарегистрирован
✅ Коннектор активирован на линии 0
✅ События зарегистрированы
✅ Open Channels интеграция настроена
```

---

## Шаг 4: Как это работает

### 4.1 Схема интеграции

```
┌─────────────────┐                    ┌──────────────────┐                    ┌─────────────────┐
│                 │    MTProto         │                  │    REST API        │                 │
│    Telegram     │ ◄──────────────►   │   Ваш сервер     │ ◄──────────────►   │    Bitrix24     │
│    Клиент       │                    │  (telegram-crm)  │                    │   Open Lines    │
│                 │                    │                  │                    │                 │
└─────────────────┘                    └──────────────────┘                    └─────────────────┘
        │                                      │                                       │
        │                                      │                                       │
        ▼                                      ▼                                       ▼
   1. Клиент пишет              2. Система отправляет                3. Оператор видит
   сообщение в Telegram         через API в Bitrix24                 чат в карточке
                                                                      контакта
        │                                      │                                       │
        │                                      │                                       │
        ▼                                      ▼                                       ▼
   5. Получает ответ            4. Получает webhook                  Оператор отвечает
   в Telegram                   и отправляет через MTProto            клиенту
```

### 4.2 Где видны сообщения из Telegram

#### В карточках контактов:

1. Откройте **CRM** → **Контакты**
2. Выберите контакт
3. В карточке контакта найдите раздел **"Открытые линии"** или **"Чаты"**
4. Там будет виден коннектор **"Telegram CRM"** с синей иконкой
5. Все сообщения из Telegram отображаются в этом разделе

#### В общем списке чатов:

1. Откройте **CRM** → **Открытые линии**
2. Все активные чаты из Telegram будут отображаться в списке
3. Можно отвечать прямо из этого интерфейса

### 4.3 Связывание Telegram чата с контактом

Чтобы сообщения появились в карточке контакта, нужно связать Telegram чат с контактом в CRM.

**Способ 1: При отправке сообщения через API**

```bash
POST /api/send-message
{
  "phone": "+79991234567",
  "message": "Привет!",
  "crm_contact_id": "12345"  # ID контакта в Bitrix24
}
```

**Способ 2: Автоматически**

При первом сообщении система создаст связь между Telegram chat_id и контактом.

**Способ 3: Вручную через БД**

```sql
INSERT INTO chat_mappings (chat_id, crm_contact_id, account_id)
VALUES (123456789, '12345', 1);
```

---

## Шаг 5: Проверка статуса интеграции

### 5.1 Через API

```bash
curl "https://ваш-сервер.com/api/bitrix24/openlines/status" \
  -H "X-API-Key: ваш_api_secret_key"
```

**Ожидаемый ответ:**

```json
{
  "enabled": true,
  "connector_id": "telegram_mtproto",
  "line_id": 0,
  "connector_status": {
    "LINE": 0,
    "CONNECTOR": "telegram_mtproto",
    "ERROR": false,
    "CONFIGURED": true,
    "STATUS": true
  }
}
```

### 5.2 Через логи

```bash
# Docker
docker logs telegram-crm-app | grep "Open Channels"

# Локальный запуск
tail -f logs/app.log | grep "Open Channels"
```

Должны быть записи:
```
✅ Open Channels интеграция настроена
connector_registered: True
connector_activated: True
```

---

## Устранение неполадок

> Подробное руководство по troubleshooting см. в [BITRIX24_TROUBLESHOOTING.md](BITRIX24_TROUBLESHOOTING.md)

### Проблема: Белый экран при установке приложения

**Причина:** Возвращается редирект вместо HTML страницы.

**Решение:** Обновите код до последней версии - теперь возвращается HTML страница с подтверждением.

### Проблема: "Ошибка: отсутствуют данные авторизации"

**Причина:** Bitrix24 не передал токены авторизации.

**Решение:**
1. Проверьте что оба URL в настройках приложения одинаковые
2. Убедитесь что тип приложения = "Серверное"
3. Проверьте логи сервера на предмет ошибок

### Проблема: "ICON_REQUIRED" или "NO_PLACEMENT_HANDLER"

**Причина:** Старая версия кода без иконки или placement handler.

**Решение:** Обновите код до последней версии:
```bash
git pull origin feature/agent-db-fk-constraints
docker-compose build app
docker-compose up -d
```

### Проблема: Сообщения не появляются в Bitrix24

**Решение:**
1. Проверьте `BITRIX24_OPEN_CHANNELS_ENABLED=true` в `.env`
2. Проверьте что контакт связан с Telegram чатом (таблица `chat_mappings`)
3. Проверьте логи на ошибки Bitrix24 API

---

## API Endpoints

| Метод | Endpoint | Описание |
|-------|----------|----------|
| POST/GET | `/api/bitrix24/install` | Установка приложения (автоматическая OAuth) |
| GET | `/api/bitrix24/openlines/placement` | UI страница настроек коннектора |
| GET | `/api/bitrix24/openlines/status` | Статус интеграции |
| POST | `/api/webhook/bitrix24/openlines` | Webhook от Bitrix24 |

---

## Безопасность

1. **HTTPS обязателен** - Bitrix24 не отправляет webhook на HTTP
2. **Токены хранятся в БД** - Автоматически обновляются при истечении
3. **Права приложения** - Только необходимые scopes
4. **Webhook secret** - Опционально можно добавить `BITRIX24_WEBHOOK_SECRET` для проверки подлинности

---

## Поддержка

При возникновении проблем:

1. **Проверьте логи сервера:**
   ```bash
   docker logs -f telegram-crm-app
   ```

2. **Проверьте статус:**
   ```bash
   curl https://ваш-сервер.com/api/bitrix24/openlines/status
   ```

3. **Изучите troubleshooting:**
   - [BITRIX24_TROUBLESHOOTING.md](BITRIX24_TROUBLESHOOTING.md)

4. **Документация Bitrix24:**
   - https://dev.1c-bitrix.ru/rest_help/
   - https://dev.1c-bitrix.ru/rest_help/scope_im/imconnector/

---

## Changelog

### 2026-01-18
- ✅ Автоматическая установка при установке приложения в Bitrix24
- ✅ Поддержка AUTH_ID/REFRESH_ID формата токенов
- ✅ HTML страница подтверждения вместо редиректа
- ✅ Иконка Telegram для коннектора
- ✅ PLACEMENT_HANDLER для настроек коннектора
- ✅ Автоматическая регистрация и активация коннектора
