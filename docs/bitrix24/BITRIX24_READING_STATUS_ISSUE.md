# Проблема: Галочка "просмотрено" появляется сразу

**Дата:** 2026-01-20
**Обновлено:** 2026-01-20 15:35
**Статус:** 📋 ОТЛОЖЕНО В БЕКЛОГ (отключена отправка reading status до выяснения причины)

---

## Проблема

После отправки сообщения в Telegram сразу появляется галочка **"Сообщение просмотрено"**, хотя пользователь ещё не прочитал сообщение.

![Галочка "просмотрено" сразу после отправки](screenshot.png)

---

## Причина

**Это проблема на НАШЕЙ стороне.**

В коде `src/outbox_worker.py` (строки 282-288) мы отправляем **оба статуса одновременно**:

```python
# Delivery status (✅ ПРАВИЛЬНО - отправляем сразу после доставки)
delivery_result = await self.crm.send_status_delivery(
    connector_id=settings.BITRIX24_CONNECTOR_ID,
    line_id=line_id,
    messages=messages
)
logger.info(f"✅ Delivery status: {delivery_result}")

# Reading status (❌ НЕПРАВИЛЬНО - отправляем сразу, не дожидаясь прочтения)
reading_result = await self.crm.send_status_reading(
    connector_id=settings.BITRIX24_CONNECTOR_ID,
    line_id=line_id,
    messages=messages
)
logger.info(f"✅ Reading status: {reading_result}")
```

### Что происходит сейчас:

1. Сообщение отправляется в Telegram ✅
2. Мы отправляем в Bitrix24: **"доставлено"** ✅
3. Мы **СРАЗУ** отправляем в Bitrix24: **"прочитано"** ❌ (хотя пользователь ещё не прочитал!)
4. Bitrix24 показывает галочку "просмотрено" ❌

---

## Правильное поведение

### Delivery Status (доставлено):
- Отправлять **СРАЗУ** после успешной доставки в Telegram
- Это правильно — сообщение действительно доставлено

### Reading Status (прочитано):
- Отправлять **ТОЛЬКО** когда пользователь реально прочитал
- Нужно дождаться события от Telegram MTProto
- Telegram сообщает о прочтении через специальные события

---

## Решение

### Вариант 1: Убрать отправку reading status (простой)

**Преимущества:**
- Быстрое решение (удалить 6 строк кода)
- Bitrix24 не будет показывать неправильную галочку

**Недостатки:**
- Теряем информацию о прочтении
- Bitrix24 не узнает когда пользователь действительно прочитал

**Код:**
```python
# Delivery status
delivery_result = await self.crm.send_status_delivery(
    connector_id=settings.BITRIX24_CONNECTOR_ID,
    line_id=line_id,
    messages=messages
)
logger.info(f"✅ Delivery status: {delivery_result}")

# ❌ УБРАТЬ: Reading status не отправляем
# reading_result = await self.crm.send_status_reading(...)
```

### Вариант 2: Отправлять reading status по реальному событию (правильный)

**Преимущества:**
- Правильное поведение
- Bitrix24 показывает точную информацию
- Соответствует стандартам мессенджеров

**Недостатки:**
- Требует дополнительной разработки
- Нужно обрабатывать события Telegram MTProto

**Что нужно сделать:**

1. **Добавить обработчик событий прочтения в `src/telegram_client.py`:**

Telegram MTProto отправляет события:
- `UpdateReadHistoryInbox` — входящие сообщения прочитаны
- `UpdateReadHistoryOutbox` — исходящие сообщения прочитаны

```python
from telethon import events

@client.on(events.MessageRead)
async def handle_message_read(event):
    """Обработка события прочтения сообщения"""
    chat_id = event.chat_id
    max_id = event.max_id  # ID последнего прочитанного сообщения

    logger.info(f"📖 Сообщения прочитаны в чате {chat_id} до ID {max_id}")

    # Найти связь с Bitrix24
    mapping = await get_chat_mapping(chat_id)
    if not mapping or not mapping.crm_contact_id:
        return

    # Найти сообщения из message_outbox для этого чата
    # которые были отправлены и ещё не отмечены как прочитанные
    unread_messages = await get_unread_outbox_messages(chat_id, max_id)

    # Отправить reading status для каждого сообщения
    for msg in unread_messages:
        bitrix_msg_id = msg.payload.get("bitrix_message_id")
        bitrix_chat_id = msg.payload.get("bitrix_chat_id")

        if bitrix_msg_id and bitrix_chat_id:
            await crm_client.send_status_reading(
                connector_id=settings.BITRIX24_CONNECTOR_ID,
                line_id=msg.payload.get("line_id", 0),
                messages=[{
                    "im": {"chat_id": str(bitrix_chat_id), "message_id": str(bitrix_msg_id)},
                    "message": {"id": str(bitrix_msg_id)},
                    "chat": {"id": str(chat_id)}
                }]
            )

            # Отметить сообщение как прочитанное в БД
            await mark_message_as_read(msg.id)
```

2. **Добавить поле `read_at` в таблицу `message_outbox`:**

```sql
ALTER TABLE message_outbox ADD COLUMN read_at TIMESTAMP NULL;
```

3. **Убрать немедленную отправку reading status из `outbox_worker.py`:**

Удалить строки 282-288.

---

## Рекомендация

**Краткосрочно (сейчас):**
- Используйте **Вариант 1** — уберите отправку reading status
- Это исправит проблему с неправильной галочкой
- Bitrix24 будет показывать только статус "доставлено"

**Долгосрочно (в будущем):**
- Реализуйте **Вариант 2** — обработку реальных событий прочтения
- Это даст точную информацию о прочтении
- Соответствует поведению других мессенджеров

---

## Код для немедленного исправления

### Файл: `src/outbox_worker.py`

**Строки 282-288 — УДАЛИТЬ:**
```python
# Reading status
reading_result = await self.crm.send_status_reading(
    connector_id=settings.BITRIX24_CONNECTOR_ID,
    line_id=line_id,
    messages=messages  # Тот же формат
)
logger.info(f"✅ Reading status: {reading_result}")
```

### Файл: `src/bridge.py`

**Строки ~680-690 — УДАЛИТЬ второй вызов:**
```python
# ❌ УБРАТЬ: Reading status
# await self.crm.send_status_reading(
#     connector_id=settings.BITRIX24_CONNECTOR_ID,
#     line_id=settings.BITRIX24_LINE_ID,
#     messages=messages
# )
```

**Оставить только:**
```python
# ✅ ОСТАВИТЬ: Delivery status
await self.crm.send_status_delivery(
    connector_id=settings.BITRIX24_CONNECTOR_ID,
    line_id=settings.BITRIX24_LINE_ID,
    messages=messages
)
logger.info(f"✅ Статус доставки отправлен в Bitrix24")
```

---

## Проверка после исправления

### Ожидаемое поведение:
1. ✅ Сообщение отправляется в Telegram
2. ✅ В Bitrix24 появляется статус "доставлено" (одна галочка или без галочки)
3. ❌ Статус "прочитано" НЕ появляется сразу (правильно!)
4. ✅ В будущем: статус "прочитано" появится только после реального прочтения

### Команды для проверки:
```bash
# Проверить что reading status больше не отправляется
docker logs telegram-crm-outbox-worker --tail 100 | grep "Reading status"
# Должно быть пусто

# Проверить что delivery status отправляется
docker logs telegram-crm-outbox-worker --tail 100 | grep "Delivery status"
# Должны быть записи
```

---

## 📋 Текущее решение (ВРЕМЕННОЕ - Отключена отправка reading status)

**Дата реализации:** 2026-01-20
**Статус:** Отложено в беклог до выяснения причины

### Что было сделано:

#### Попытка 1: Реализация Вариант 2 (обработка MessageRead events)

1. **Миграция БД** (`alembic/versions/20260120_add_read_at_to_message_outbox.py`):
   - Добавлено поле `read_at TIMESTAMP` в таблицу `message_outbox`
   - Создан индекс для быстрого поиска непрочитанных сообщений
   - Миграция успешно применена на production

2. **Убрана немедленная отправка reading_status**:
   - `src/outbox_worker.py:282-288` - удалён код немедленной отправки
   - `src/bridge.py:694-700` - удалён код немедленной отправки
   - Заменено на комментарии с объяснением

3. **Добавлен обработчик событий MessageRead**:
   - `src/telegram_client.py:253-259` - зарегистрирован обработчик Telethon events.MessageRead
   - `src/telegram_client.py:1252-1359` - реализован метод `_handle_message_read()`

**Результат:** ❌ Не сработало - галочка "просмотрено" все равно появлялась сразу после отправки

#### Попытка 2: Полное отключение reading status (ТЕКУЩЕЕ РЕШЕНИЕ)

**Дата:** 2026-01-20 15:35

**Изменения:**
- `src/telegram_client.py:256-259` - закомментирован обработчик MessageRead
- Контейнер `outbox-worker` пересобран с `--no-cache` и перезапущен
- Проверено что код обновился в контейнере

**Код:**
```python
# MessageRead обработчик отключен - reading status не отправляется
# В Bitrix24 будет показываться только "доставлено", без "просмотрено"
# self.client.add_event_handler(
#     self._handle_message_read,
#     events.MessageRead()
# )
```

### Текущий результат:

- ✅ Статус доставки (delivery) отправляется корректно
- ✅ Статус прочтения (reading) **НЕ отправляется вообще**
- ⚠️ В Bitrix24 показывается только "доставлено", без галочки "просмотрено"
- 📋 **Проблема отложена в беклог** - требуется дополнительное исследование почему MessageRead events не работают корректно

### Что осталось в коде для будущей отладки:

1. **Миграция БД с полем `read_at`** - осталась, не мешает
2. **Метод `_handle_message_read()`** - реализован, но не вызывается
3. **Инфраструктура для отслеживания прочтения** - готова к использованию

### Для продолжения работы в будущем:

1. Исследовать почему Telegram MessageRead events срабатывают некорректно
2. Возможно проблема в:
   - Особенностях работы MTProto API
   - Различиях между личными чатами и группами
   - Задержках в получении событий от Telegram
   - Различиях между входящими/исходящими событиями (`event.inbox` vs `event.outbox`)
3. Рассмотреть альтернативные подходы:
   - Polling статуса прочтения через `get_messages()` с проверкой флагов
   - Использование UpdateReadHistoryOutbox вместо MessageRead
   - Комбинированный подход с задержкой и проверкой

---

## Связанные документы
- [BITRIX24_STATUS_DELIVERY_FIX.md](BITRIX24_STATUS_DELIVERY_FIX.md) — исправление формата статусов
- [BITRIX24_OPENLINES_TROUBLESHOOTING.md](BITRIX24_OPENLINES_TROUBLESHOOTING.md) — полная история исправлений

---

**Последнее обновление:** 2026-01-20 15:35
**Статус:** 📋 ОТЛОЖЕНО В БЕКЛОГ

**Текущее состояние на production:**
- ✅ Delivery status работает корректно
- ❌ Reading status отключен (не отправляется)
- 🔧 Требуется дополнительное исследование для корректной работы MessageRead events
