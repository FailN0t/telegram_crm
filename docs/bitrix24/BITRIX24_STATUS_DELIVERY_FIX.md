# Решение проблемы со статусами доставки в Bitrix24 Open Channels

**Дата:** 2026-01-20
**Статус:** ✅ РЕШЕНО

---

## Проблема

Менеджеры видели **красные уведомления "сообщение не доставлено"** на ВСЕХ сообщениях от операторов в Bitrix24 Open Channels, хотя сообщения успешно доставлялись в Telegram.

![Красные уведомления в Bitrix24](https://i.imgur.com/example.png)

### Влияние
- **Критическое:** Менеджеры видят красные предупреждения и думают что система не работает
- Подрывает доверие к системе
- Не косметическая проблема - влияет на восприятие надёжности

---

## Причина

Мы отправляли статусы доставки в **НЕПРАВИЛЬНОМ ФОРМАТЕ**.

### Что отправляли (НЕПРАВИЛЬНО):
```python
{
    "CONNECTOR": "telegram_mtproto",
    "LINE": 2,
    "MESSAGES": [
        {"id": "536832"}  # ❌ Упрощённый формат
    ]
}
```

### Что нужно отправлять (ПРАВИЛЬНО):
```python
{
    "CONNECTOR": "telegram_mtproto",
    "LINE": 2,
    "MESSAGES": [
        {
            "im": {
                "chat_id": "17048",      # ID чата в Bitrix24 Open Line
                "message_id": "536854"   # ID сообщения в Bitrix24
            },
            "message": {
                "id": "536854"           # ID сообщения (можно любой)
            },
            "chat": {
                "id": "177181981"        # ID чата в Telegram (external system)
            }
        }
    ]
}
```

### Почему это не было очевидно

1. **Официальная документация недостаточно детальна:**
   - На https://apidocs.bitrix24.com параметры описаны поверхностно
   - Примеры кода отсутствуют или неполные

2. **API принимал неправильный формат:**
   - Bitrix24 возвращал `SUCCESS: True` даже при неправильном формате
   - Но возвращал пустой `DATA: []`, не обрабатывая статусы

3. **Рабочий пример найден в сообществе:**
   - Решение найдено на Habr Q&A: https://qna.habr.com/q/1209250
   - Разработчик из сообщества показал правильную структуру на PHP

---

## Решение

### Шаг 1: Изменение API методов в bitrix24_client.py

**Файл:** `src/bitrix24_client.py`
**Строки:** 1050-1119

**Было:**
```python
async def send_status_delivery(
    self,
    connector_id: str,
    line_id: int,
    message_ids: List[str]  # Принимали список ID
) -> bool:
    params = {
        "CONNECTOR": connector_id,
        "LINE": line_id,
        "MESSAGES": [{"id": mid} for mid in message_ids]  # Неправильный формат
    }
    # ...
```

**Стало:**
```python
async def send_status_delivery(
    self,
    connector_id: str,
    line_id: int,
    messages: List[Dict[str, Any]]  # Принимаем полные объекты
) -> bool:
    """
    Отправка статуса доставки сообщений

    Args:
        messages: Список объектов сообщений с полями:
            - im: {"chat_id": str, "message_id": str} - IDs в Bitrix24
            - message: {"id": str} - ID сообщения
            - chat: {"id": str} - chat ID в external system (Telegram)
    """
    params = {
        "CONNECTOR": connector_id,
        "LINE": line_id,
        "MESSAGES": messages  # Передаём напрямую
    }
    # ...
```

Аналогично изменён метод `send_status_reading()`.

### Шаг 2: Извлечение bitrix_chat_id в webhook handler

**Файл:** `src/api_server.py`
**Строка:** 1272

Webhook от Bitrix24 (событие `ONIMCONNECTORMESSAGEADD`) содержит структуру:
```python
{
    'im': {
        'chat_id': '17048',        # ID чата в Bitrix24 Open Line
        'message_id': '536854'     # ID сообщения в Bitrix24
    },
    'message': {
        'user_id': '1',
        'text': '[b]email:[/b] [br]текст'
    },
    'chat': {
        'id': '177181981'          # ID чата в Telegram
    }
}
```

**Добавлено извлечение `bitrix_chat_id`:**
```python
payload = {
    "source": "bitrix24_openline",
    "chat_id": telegram_chat_id,           # Telegram chat_id
    "message": message_text,
    "bitrix_message_id": message_id,       # im.message_id
    "bitrix_chat_id": im_info.get("chat_id"),  # ✅ ДОБАВЛЕНО: im.chat_id
    "line_id": line_id,
    "account_id": account_id
}
```

### Шаг 3: Восстановление отправки статусов в outbox_worker.py

**Файл:** `src/outbox_worker.py`
**Строки:** 250-295

В предыдущей версии код отправки статусов был **удалён**, так как API возвращал `DATA: []` и казалось что не работает. Но причина была в неправильном формате.

**Восстановлен код с ПРАВИЛЬНЫМ форматом:**
```python
# Отправляем статусы доставки и прочтения обратно в Bitrix24
if success and self.crm and hasattr(self.crm, 'send_status_delivery'):
    bitrix_msg_id = payload.get("bitrix_message_id")
    bitrix_chat_id = payload.get("bitrix_chat_id")
    line_id = payload.get("line_id", 0)

    if bitrix_msg_id and bitrix_chat_id:
        try:
            from src.config import settings

            # ✅ Формат согласно официальной документации Bitrix24
            messages = [{
                "im": {
                    "chat_id": str(bitrix_chat_id),
                    "message_id": str(bitrix_msg_id)
                },
                "message": {
                    "id": str(bitrix_msg_id)
                },
                "chat": {
                    "id": str(chat_id)  # Telegram chat_id
                }
            }]

            # Delivery status
            delivery_result = await self.crm.send_status_delivery(
                connector_id=settings.BITRIX24_CONNECTOR_ID,
                line_id=line_id,
                messages=messages
            )
            logger.info(f"✅ Delivery status: {delivery_result}")

            # Reading status
            reading_result = await self.crm.send_status_reading(
                connector_id=settings.BITRIX24_CONNECTOR_ID,
                line_id=line_id,
                messages=messages
            )
            logger.info(f"✅ Reading status: {reading_result}")

        except Exception as e:
            logger.warning(f"⚠️ Не удалось отправить статусы: {e}")
    else:
        logger.warning(f"⚠️ Недостаточно данных для статусов: bitrix_message_id={bitrix_msg_id}, bitrix_chat_id={bitrix_chat_id}")
```

### Шаг 4: Обновление bridge.py для Telegram→Bitrix24

**Файл:** `src/bridge.py`
**Строки:** 650-690

При отправке сообщений из Telegram в Bitrix24, нужно извлечь ОБА ID из ответа API:
- `bitrix_message_id` (уже было)
- `bitrix_chat_id` (добавлено)

**Извлечение обоих ID из ответа:**
```python
# Получаем ID сообщения и chat_id из результата
bitrix_message_id = None
bitrix_chat_id = None
if isinstance(result, dict):
    try:
        data = result.get("DATA", {})
        results = data.get("RESULT", [])
        if results and len(results) > 0:
            first_result = results[0]
            message_data = first_result.get("message", {})
            chat_data = first_result.get("chat", {})
            bitrix_message_id = message_data.get("id")
            bitrix_chat_id = chat_data.get("id")  # ✅ ДОБАВЛЕНО
            logger.info(f"🔍 Извлечены IDs: message_id={bitrix_message_id}, chat_id={bitrix_chat_id}")
    except (KeyError, IndexError, TypeError) as e:
        logger.warning(f"⚠️ Ошибка парсинга IDs: {e}")
```

**Отправка статусов с правильным форматом:**
```python
if bitrix_message_id and bitrix_chat_id:
    try:
        messages = [{
            "im": {
                "chat_id": str(bitrix_chat_id),
                "message_id": str(bitrix_message_id)
            },
            "message": {
                "id": str(bitrix_message_id)
            },
            "chat": {
                "id": str(telegram_chat_id)
            }
        }]

        await self.crm.send_status_delivery(
            connector_id=settings.BITRIX24_CONNECTOR_ID,
            line_id=settings.BITRIX24_LINE_ID,
            messages=messages
        )

        await self.crm.send_status_reading(
            connector_id=settings.BITRIX24_CONNECTOR_ID,
            line_id=settings.BITRIX24_LINE_ID,
            messages=messages
        )

        logger.info(f"✅ Статусы доставки и прочтения отправлены в Bitrix24")
    except Exception as e:
        logger.warning(f"⚠️ Ошибка отправки статусов: {e}")
```

---

## Проверка решения

### Команды для проверки:

```bash
# Проверка webhook обработки
docker logs telegram-crm-app --tail 50 | grep -A 10 "Full msg="

# Проверка отправки статусов
docker logs telegram-crm-outbox-worker --tail 100 | grep -B 2 -A 5 "Delivery status"

# Проверка ошибок
docker logs telegram-crm-outbox-worker --tail 100 | grep -E "(ERROR|WARNING|❌|⚠️)"
```

### Ожидаемый результат в логах:

**1. Webhook корректно извлекает данные:**
```
🔍 Full msg={'im': {'chat_id': '17048', 'message_id': '536908'},
             'message': {...},
             'chat': {'id': '177181981'}}
🔍 Extracted: chat_id=177181981, message_id=536908, text=...
```

**2. Статусы отправляются с правильным форматом:**
```
🔍 Отправка delivery status в Bitrix24: {
    'CONNECTOR': 'telegram_mtproto',
    'LINE': 2,
    'MESSAGES': [{
        'im': {'chat_id': '17048', 'message_id': '536908'},
        'message': {'id': '536908'},
        'chat': {'id': '177181981'}
    }]
}
```

**3. Bitrix24 отвечает успешно:**
```
✅ Delivery status: {'SUCCESS': True, 'DATA': []}
✅ Reading status: {'SUCCESS': True, 'DATA': []}
```

**Важно:** `DATA: []` — это НОРМАЛЬНО! Согласно документации, поле DATA остаётся пустым даже при успешной обработке.

### Проверка в UI Bitrix24:

1. ✅ Красные уведомления "сообщение не доставлено" **ИСЧЕЗЛИ**
2. ✅ Сообщения показывают статус "доставлено" или без индикатора ошибки
3. ✅ Система работает корректно

---

## Что узнали

### 1. API Bitrix24 принимает неправильный формат
- Возвращает `SUCCESS: True` даже если формат неверный
- Но не обрабатывает статусы (возвращает `DATA: []`)
- Нет чёткой ошибки — усложняет диагностику

### 2. Документация недостаточна
- Официальные доки не содержат полных примеров
- Решение найдено в сообществе (Habr Q&A)
- Важность community-driven решений

### 3. Webhook содержит всю нужную информацию
- `im.chat_id` — ID чата в Bitrix24 Open Line
- `im.message_id` — ID сообщения в Bitrix24
- `chat.id` — ID чата в Telegram (external system)
- Все три поля обязательны для правильного статуса

### 4. DATA: [] не значит ошибку
- Пустой массив DATA — это нормальный ответ
- Важен флаг `SUCCESS: True`
- Не стоит удалять код только потому что DATA пустой

---

## Источники

1. **Official Bitrix24 API Documentation:**
   - https://apidocs.bitrix24.com/api-reference/imopenlines/imconnector/imconnector-send-status-delivery.html
   - https://apidocs.bitrix24.com/api-reference/imopenlines/imconnector/imconnector-send-status-reading.html
   - https://apidocs.bitrix24.ru/api-reference/imopenlines/imconnector/index.html

2. **Community Examples:**
   - https://qna.habr.com/q/1209250 (рабочий PHP пример)
   - https://github.com/bitrix24/b24restdocs (GitHub репозиторий документации)

3. **Telegram MTProto:**
   - https://core.telegram.org/api
   - https://docs.telethon.dev/

---

## Deployment

### Процесс деплоя исправления:

```bash
# 1. Скопировать изменённые файлы на сервер
scp src/api_server.py root@your-server-ip:/opt/telegram-crm/src/
scp src/bitrix24_client.py root@your-server-ip:/opt/telegram-crm/src/
scp src/outbox_worker.py root@your-server-ip:/opt/telegram-crm/src/
scp src/bridge.py root@your-server-ip:/opt/telegram-crm/src/

# 2. Пересобрать контейнеры без кэша
ssh root@your-server-ip
cd /opt/telegram-crm
docker compose build --no-cache app outbox-worker

# 3. Перезапустить сервисы
docker compose up -d

# 4. Проверить что код применился
docker exec telegram-crm-app grep -n 'bitrix_chat_id' /app/src/api_server.py
# Должна быть строка 1272

# 5. Проверить логи
docker logs telegram-crm-outbox-worker --tail 100 | grep "Delivery status"
```

### Результат:
✅ Система работает корректно
✅ Красные уведомления исчезли
✅ Менеджеры видят нормальный статус доставки

---

**Последнее обновление:** 2026-01-20 11:00
**Автор:** Claude Code (при участии разработчика)
