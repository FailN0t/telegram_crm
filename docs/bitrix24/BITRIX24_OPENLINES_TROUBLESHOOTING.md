# Bitrix24 Open Channels: История исправлений и решений

**Дата:** 2026-01-20
**Статус:** Работает (отправка/получение), требуется доработка статусов доставки

---

## Проблемы и решения (хронологически)

### 1. Сообщения не доставлялись (outbox worker отсутствовал)

**Симптомы:**
- Сообщения попадали в очередь `message_outbox` со статусом `queued`
- Никогда не отправлялись в Telegram

**Причина:**
- В `docker-compose.yml` отсутствовал сервис `outbox-worker`
- API сервер только принимал webhooks, но не обрабатывал очередь

**Решение:**
Добавлен сервис в `docker-compose.yml`:
```yaml
outbox-worker:
  build:
    context: .
    dockerfile: Dockerfile.production
  container_name: telegram-crm-outbox-worker
  restart: unless-stopped
  command: python -m src.outbox_worker
```

**Файлы:** `docker-compose.yml`

---

### 2. Префикс email в сообщениях

**Симптомы:**
- Сообщения в Telegram содержали префикс: `"lenin5558dif@gmail.com: Привет"`
- Вместо чистого текста: `"Привет"`

**Причина:**
- Bitrix24 отправляет сообщения с BB-code форматированием
- Формат: `[b]email@domain.com:[/b] [br]текст сообщения`

**Решение:**
Добавлена очистка BB-code в `src/api_server.py` (webhook handler):
```python
import re
# Удаляем префикс вида "[b]email@domain.com:[/b] [br]"
message_text = re.sub(r'\[b\][^@]+@[^:]+:\[/b\]\s*\[br\]', '', message_text)
# Удаляем остальные BB-code теги
message_text = re.sub(r'\[/?b\]|\[/?i\]|\[/?u\]|\[br\]', '', message_text)
message_text = message_text.strip()
```

**Файлы:** `src/api_server.py` (строки ~1245-1249)

---

### 3. message_id не передавался в payload

**Симптомы:**
- В логах: `bitrix_message_id=None`
- Статусы доставки не отправлялись в Bitrix24

**Причина:**
- Неправильное извлечение `message_id` из структуры webhook
- Изначально искали в `message_info.get("id")`
- На самом деле находится в `im_info.get("message_id")`

**Решение:**
Улучшена логика извлечения в `src/api_server.py`:
```python
im_info = msg.get("im", {})
message_id = (
    message_info.get("id") or
    im_info.get("message_id") or
    im_info.get("id") or
    msg.get("id")
)
```

**Файлы:** `src/api_server.py` (строки ~1231-1236)

---

### 4. Quiet hours блокировали сообщения

**Симптомы:**
- Сообщения в ночное время (01:00, 06:57) не отправлялись
- Ошибка: `"⏰ Неподходящее время (6:00). Отправляйте с 9:00 до 21:00"`

**Причина:**
- Anti-spam проверка блокировала отправку вне часов 9:00-21:00
- Open Channels предполагают ответы оператора 24/7

**Решение:**
Добавлен параметр `skip_quiet_hours`:

1. В `src/antispam.py`:
```python
async def try_register_send(
    self,
    user_id: int,
    is_new_chat: bool = False,
    operator_id: Optional[int] = None,
    skip_quiet_hours: bool = False  # НОВЫЙ ПАРАМЕТР
) -> Tuple[bool, str]:
    # Проверка времени отправки (не ночью)
    # Для Open Channels пропускаем эту проверку
    if not skip_quiet_hours and (now.hour < 9 or now.hour > 21):
        return False, f"⏰ Неподходящее время ({now.hour}:00). Отправляйте с 9:00 до 21:00"
```

2. В `src/telegram_client.py`:
```python
async def send_message_to_user(
    self,
    user: User,
    message: str,
    is_new_chat: Optional[bool] = None,
    operator_id: Optional[int] = None,
    skip_quiet_hours: bool = False  # НОВЫЙ ПАРАМЕТР
) -> Tuple[bool, str]:
    can_send, reason = await self.anti_spam.try_register_send(
        user.id,
        is_new_chat,
        operator_id=operator_id,
        skip_quiet_hours=skip_quiet_hours
    )
```

3. В `src/outbox_worker.py`:
```python
# Open Channels: пропускаем quiet hours
success, result = await client.send_message_to_user(
    target_user,
    message,
    operator_id=payload.get("operator_id"),
    skip_quiet_hours=True  # ДЛЯ OPEN CHANNELS
)
```

**Файлы:** `src/antispam.py`, `src/telegram_client.py`, `src/outbox_worker.py`

---

### 5. LINE передавался как строка вместо int

**Симптомы:**
- Bitrix24 API получал `LINE: '2'` (string)
- Ожидался `LINE: 2` (integer)

**Причина:**
- Bitrix24 отправляет LINE как строку в webhook
- Не было приведения типа перед отправкой в API

**Решение:**
В `src/api_server.py`:
```python
line_id = int(data.get("LINE", 0)) if data.get("LINE") else 0
```

**Файлы:** `src/api_server.py` (строка ~1212)

---

### 6. Конкуренция MTProto клиентов

**Симптомы:**
- Сообщения от клиентов (Telegram→Bitrix24) перестали приходить в Bitrix24
- Работала только отправка Bitrix24→Telegram

**Причина:**
- И API сервер, и outbox worker запускали MTProto клиента
- Оба процесса конкурировали за входящие события Telegram
- События приходили то в один процесс, то в другой

**Решение:**
Разделение ответственности:
1. В `.env` добавлено: `OUTBOX_PROCESS_INLINE=false`
2. **API сервер:** только обработка webhooks, без MTProto клиента
3. **Outbox worker:** единственный процесс с MTProto клиентом

**Файлы:** `.env`, архитектурное решение

---

### 7. Bridge не инициализирован в API сервере

**Симптомы:**
- Ошибка: `'NoneType' object has no attribute 'telegram'`
- При обработке webhook в API сервере

**Причина:**
- Когда `OUTBOX_PROCESS_INLINE=false`, bridge не создается в API сервере
- Код пытался вызвать `bridge.telegram.get_default_account_id()`

**Решение:**
Проверка наличия bridge и fallback на прямой запрос к БД в `src/api_server.py`:
```python
if bridge and bridge.telegram:
    account_id = await bridge.telegram.get_default_account_id()
else:
    # Если bridge не инициализирован, берем первый аккаунт из БД
    from sqlalchemy import select
    from src.database import TelegramAccount
    result = await db.execute(select(TelegramAccount).order_by(TelegramAccount.id).limit(1))
    first_account = result.scalars().first()
    account_id = first_account.id if first_account else 1
```

**Файлы:** `src/api_server.py` (строки ~1254-1263)

---

### 8. Bridge не установлен перед запуском клиентов

**Симптомы:**
- Входящие сообщения от Telegram не пересылались в Bitrix24 Open Channels
- Отправка Bitrix24→Telegram работала

**Причина:**
- В `outbox_worker.py` bridge создавался ПОСЛЕ запуска Telegram клиентов
- Клиенты стартовали без ссылки на bridge
- Обработчики входящих сообщений не могли переслать их в CRM

**Решение:**
Изменен порядок инициализации в `src/outbox_worker.py`:
```python
# 1. Создаем telegram_manager
self.telegram_manager = TelegramClientManager()

# 2. Создаем bridge ДО запуска клиентов
self.bridge = CRMTelegramBridge(self.telegram_manager, self.crm)

# 3. Устанавливаем bridge в telegram_manager
self.telegram_manager.set_bridge(self.bridge)
logger.info("✅ Bridge установлен в telegram_manager")

# 4. Теперь запускаем клиенты с уже установленным bridge
await self.telegram_manager.start_all()
```

**Файлы:** `src/outbox_worker.py` (строки 135-145)

---

### 9. Bitrix24 события не зарегистрированы

**Симптомы:**
- После перезапуска сервисов webhooks от Bitrix24 не приходили
- Никаких запросов на `/api/webhook/bitrix24/openlines`

**Причина:**
- События Open Channels не были зарегистрированы в Bitrix24
- Или стали неактивны после изменений

**Решение:**
Создан скрипт `reregister_events_without_auth.py`:
1. Загружает настройки из БД (`refresh_settings_from_db()`)
2. Удаляет старые события
3. Регистрирует заново:
   - ONIMCONNECTORMESSAGEADD (новое сообщение)
   - ONIMCONNECTORLINEDELETE (линия удалена)
   - ONIMCONNECTORMESSAGEUPDATE (сообщение обновлено)
   - ONIMCONNECTORMESSAGEDELETE (сообщение удалено)

Запуск:
```bash
docker exec telegram-crm-app python3 /app/reregister_events_without_auth.py
```

**Файлы:** `reregister_events_without_auth.py`

---

## Текущая архитектура

### Разделение процессов

**API сервер (`telegram-crm-app`):**
- Принимает webhooks от Bitrix24 на `/api/webhook/bitrix24/openlines`
- Парсит данные, очищает BB-code
- Создает записи в `message_outbox`
- НЕ запускает MTProto клиента

**Outbox worker (`telegram-crm-outbox-worker`):**
- Единственный процесс с MTProto клиентом Telegram
- Обрабатывает очередь `message_outbox`
- Отправляет сообщения в Telegram
- Получает входящие сообщения от Telegram
- Пересылает их в Bitrix24 Open Channels через bridge

### Поток данных

**Bitrix24 → Telegram:**
```
Оператор отправляет → Bitrix24 webhook → API сервер
  → message_outbox (queued) → Outbox worker
  → MTProto send → Telegram пользователь
  → message_outbox (sent)
```

**Telegram → Bitrix24:**
```
Пользователь отправляет → MTProto event → Outbox worker
  → Bridge → Bitrix24Client.send_message()
  → imconnector.send.messages API → Open Channels в Bitrix24
```

---

## ✅ Исправленные проблемы

### 10. Статусы доставки для исходящих сообщений (Bitrix24→Telegram) — РЕШЕНО

**Дата решения:** 2026-01-20

**Симптомы (было):**
- В Bitrix24 красные уведомления "сообщение не доставлено" на ВСЕХ сообщениях оператора
- Хотя сообщения успешно доставлялись в Telegram
- Менеджеры видели ошибки и теряли доверие к системе

**Причина:**
- Отправляли статусы доставки в **НЕПРАВИЛЬНОМ ФОРМАТЕ**
- Использовали упрощённую структуру: `"MESSAGES": [{"id": "536832"}]`
- Bitrix24 API принимал запрос (`SUCCESS: True`), но не обрабатывал статусы (`DATA: []`)

**Решение:**
Исправлен формат параметров в 4 файлах:

1. **`src/bitrix24_client.py`** (строки 1050-1119):
   - Изменена сигнатура `send_status_delivery()` и `send_status_reading()`
   - Теперь принимают `messages: List[Dict[str, Any]]` вместо `message_ids: List[str]`

2. **`src/api_server.py`** (строка 1272):
   - Добавлено извлечение `bitrix_chat_id` из webhook: `im_info.get("chat_id")`

3. **`src/outbox_worker.py`** (строки 250-295):
   - Восстановлен код отправки статусов с ПРАВИЛЬНЫМ форматом
   - Используется полная структура с полями `im`, `message`, `chat`

4. **`src/bridge.py`** (строки 650-690):
   - Извлечение обоих IDs: `bitrix_message_id` и `bitrix_chat_id`
   - Отправка статусов с правильным форматом

**Правильный формат:**
```python
"MESSAGES": [{
    "im": {
        "chat_id": "17048",       # ID чата в Bitrix24 Open Line
        "message_id": "536908"    # ID сообщения в Bitrix24
    },
    "message": {
        "id": "536908"            # ID сообщения (можно любой)
    },
    "chat": {
        "id": "177181981"         # ID чата в Telegram (external system)
    }
}]
```

**Результат:**
- ✅ Красные уведомления исчезли
- ✅ Bitrix24 корректно отображает статус доставки
- ✅ Менеджеры видят нормальную работу системы

**Проверка в логах:**
```bash
# Проверить формат отправки статусов
docker logs telegram-crm-outbox-worker --tail 100 | grep -A 5 "Delivery status"

# Должны видеть правильный формат:
# {'MESSAGES': [{'im': {'chat_id': '17048', 'message_id': '536908'},
#                'message': {'id': '536908'},
#                'chat': {'id': '177181981'}}]}
```

**Источники:**
- [Official API](https://apidocs.bitrix24.com/api-reference/imopenlines/imconnector/imconnector-send-status-delivery.html)
- [Working example (Habr)](https://qna.habr.com/q/1209250)
- Подробности: [BITRIX24_STATUS_DELIVERY_FIX.md](BITRIX24_STATUS_DELIVERY_FIX.md)

---

## Известные ограничения

На данный момент критических ограничений нет. Все основные функции работают корректно

---

## Как не откатиться назад

### Checklist при изменениях:

1. **При рестарте сервисов:**
   - ✅ Проверить, что `outbox-worker` запущен
   - ✅ Проверить, что только один процесс имеет MTProto клиента
   - ✅ Проверить события Bitrix24: `docker exec telegram-crm-app python3 /app/reregister_events_without_auth.py`

2. **При изменении кода:**
   - ✅ `OUTBOX_PROCESS_INLINE=false` должно быть в `.env`
   - ✅ Bridge устанавливается ДО запуска клиентов
   - ✅ BB-code очистка присутствует в webhook handler
   - ✅ `skip_quiet_hours=True` для Open Channels
   - ✅ `bitrix_chat_id` извлекается из webhook в payload
   - ✅ Статусы отправляются с полной структурой (im, message, chat)

3. **При миграции БД:**
   - ✅ Проверить наличие токенов в `app_settings`
   - ✅ Проверить `chat_mappings` для связи Telegram ↔ Bitrix24

---

## Полезные команды для диагностики

```bash
# Логи API сервера
docker logs telegram-crm-app --tail 100

# Логи outbox worker
docker logs telegram-crm-outbox-worker --tail 100

# Проверка очереди
docker exec telegram-crm-postgres psql -U postgres -d telegram_crm -c "
  SELECT id, status, payload->>'source' as source, created_at, attempts
  FROM message_outbox
  ORDER BY created_at DESC
  LIMIT 10;
"

# Проверка истории сообщений UI
docker exec telegram-crm-postgres psql -U postgres -d telegram_crm -c "
  SELECT id, chat_id, message_text, status, created_at
  FROM ui_message_history
  ORDER BY created_at DESC
  LIMIT 10;
"

# Перерегистрация Bitrix24 событий
docker exec telegram-crm-app python3 /app/reregister_events_without_auth.py

# Проверка статусов доставки
docker logs telegram-crm-outbox-worker --tail 100 | grep -A 5 "Delivery status"

# Проверка извлечения bitrix_chat_id из webhook
docker logs telegram-crm-app --tail 50 | grep "bitrix_chat_id"
```

---

**Последнее обновление:** 2026-01-20 11:00
**Статус:** ✅ Полностью функционально (включая статусы доставки)
