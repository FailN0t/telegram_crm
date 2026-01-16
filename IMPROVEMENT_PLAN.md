# План улучшения Telegram CRM Console

**Дата создания:** 2026-01-16
**Версия:** 1.0
**Статус:** Draft (Черновик)

---

## Содержание

1. [Обзор](#обзор)
2. [Этапы выполнения](#этапы-выполнения)
3. [Высокий приоритет (Критические задачи)](#высокий-приоритет-критические-задачи)
4. [Средний приоритет](#средний-приоритет)
5. [Низкий приоритет](#низкий-приоритет)
6. [График выполнения](#график-выполнения)
7. [Риски и митигация](#риски-и-митигация)
8. [Критерии приемки](#критерии-приемки)

---

## Обзор

### Цель
Подготовить Telegram CRM Console к production развертыванию, устранив критические проблемы безопасности, производительности и надежности, а также улучшив архитектуру и UX.

### Подход
Работа разделена на 3 этапа по приоритетам:
- **Этап 1:** Критические проблемы (блокируют production)
- **Этап 2:** Производительность и архитектура
- **Этап 3:** Расширенная функциональность

### Принципы
- ✅ Каждая задача должна быть протестирована
- ✅ Изменения должны быть обратно совместимыми (или с миграцией)
- ✅ Документация обновляется вместе с кодом
- ✅ Критические изменения проходят code review

---

## Этапы выполнения

### Этап 1: Высокий приоритет (Критические задачи)
**Цель:** Устранить блокеры для production
**Срок:** 10-14 рабочих дней
**Статус:** Не начато

### Этап 2: Средний приоритет
**Цель:** Улучшить производительность и поддерживаемость
**Срок:** 15-20 рабочих дней
**Статус:** Не начато

### Этап 3: Низкий приоритет
**Цель:** Расширенная функциональность
**Срок:** 10-12 рабочих дней
**Статус:** Не начато

---

## Высокий приоритет (Критические задачи)

### 🔴 Задача 1.1: Добавить Foreign Key constraints в БД

**Приоритет:** Критический
**Сложность:** Средняя
**Оценка:** 2-3 дня
**Ответственные файлы:** `src/database.py`, `alembic/versions/*.py`

#### Описание проблемы
В текущей БД отсутствуют Foreign Key constraints между связанными таблицами:
- `message_outbox.chat_mapping_id` → `chat_mappings.id`
- `message_delivery_attempts.outbox_id` → `message_outbox.id`
- `ui_message_history.chat_id` → `ui_chats.id`
- И другие связи

Это приводит к:
- Orphan записям (удалили чат, но сообщения остались)
- Нарушению целостности данных
- Сложности отладки

#### Шаги реализации

**1. Анализ существующих связей (0.5 дня)**
- [ ] Просмотреть все модели в `src/database.py`
- [ ] Составить список всех FK, которые нужно добавить
- [ ] Проверить текущие данные на orphan записи

**2. Создать Alembic миграцию (1 день)**
- [ ] Создать миграцию: `alembic revision -m "add_foreign_key_constraints"`
- [ ] Добавить FK constraints с `ondelete="CASCADE"` или `ondelete="SET NULL"` в зависимости от логики
- [ ] Добавить индексы для FK полей (если отсутствуют)

**3. Обновить модели SQLAlchemy (0.5 дня)**
```python
# Пример:
class MessageOutbox(Base):
    chat_mapping_id = Column(Integer, ForeignKey('chat_mappings.id', ondelete='CASCADE'), nullable=False)
    chat_mapping = relationship('ChatMapping', back_populates='outbox_messages')
```

**4. Тестирование (1 день)**
- [ ] Запустить миграцию на тестовой БД
- [ ] Проверить cascade delete
- [ ] Убедиться, что приложение работает корректно
- [ ] Написать unit тесты для проверки FK constraints

#### Риски
- **Риск:** Существующие orphan записи сломают миграцию
  **Митигация:** Очистить orphan записи перед добавлением FK (в той же миграции)

- **Риск:** CASCADE удаление может удалить больше, чем нужно
  **Митигация:** Тщательно выбрать ondelete стратегию для каждого FK

#### Критерии приемки
- ✅ Все FK constraints добавлены в БД
- ✅ Миграция успешно проходит на пустой и заполненной БД
- ✅ Нет orphan записей после CASCADE удалений
- ✅ Unit тесты покрывают основные сценарии

---

### 🔴 Задача 1.2: Убрать in-memory переменные

**Приоритет:** Критический
**Сложность:** Высокая
**Оценка:** 3-4 дня
**Ответственные файлы:** `src/telegram_client.py`

#### Описание проблемы
В `telegram_client.py` используются in-memory структуры:
```python
_messages = deque(maxlen=200)  # История сообщений
_chats = {}                     # Информация о чатах
_auth_phone = None              # 2FA состояние
```

При рестарте приложения все данные теряются, что неприемлемо для production.

#### Шаги реализации

**1. Аудит использования in-memory переменных (0.5 дня)**
- [ ] Найти все места, где используются `_messages`, `_chats`, `_auth_phone`
- [ ] Понять, какие данные уже дублируются в БД (`ui_message_history`, `ui_chats`)
- [ ] Определить, что нужно мигрировать

**2. Миграция `_messages` → БД (1 день)**
- [ ] Убедиться, что все сообщения сохраняются в `ui_message_history`
- [ ] Заменить чтение из `_messages` на запросы к БД
- [ ] Удалить `_messages` deque

**3. Миграция `_chats` → БД (1 день)**
- [ ] Убедиться, что все чаты сохраняются в `ui_chats`
- [ ] Заменить чтение из `_chats` на запросы к БД
- [ ] Добавить кэширование на уровне Redis, если нужна производительность

**4. Миграция `_auth_phone` → Redis (0.5 дня)**
- [ ] Создать Redis ключ для 2FA состояния: `telegram:2fa:{session_id}`
- [ ] Сохранять `phone_code_hash` в Redis с TTL 5 минут
- [ ] Читать из Redis при submit_code

**5. Тестирование (1 день)**
- [ ] Тест: Рестарт приложения не теряет историю сообщений
- [ ] Тест: Рестарт между send_code и submit_code не ломает авторизацию
- [ ] Тест: Чаты остаются доступными после рестарта
- [ ] Нагрузочный тест: Производительность не упала

#### Риски
- **Риск:** Производительность ухудшится из-за запросов к БД
  **Митигация:** Добавить Redis кэш для горячих данных (последние 50 сообщений на чат)

- **Риск:** Race conditions при параллельных запросах
  **Митигация:** Использовать SELECT FOR UPDATE или оптимистичные блокировки

#### Критерии приемки
- ✅ Нет in-memory переменных в `telegram_client.py`
- ✅ Рестарт приложения не приводит к потере данных
- ✅ 2FA авторизация работает через рестарт
- ✅ Производительность не хуже текущей (±10%)

---

### 🔴 Задача 1.3: Исправить атомарность AntiSpam (Redis MULTI/EXEC)

**Приоритет:** Критический
**Сложность:** Средняя
**Оценка:** 2 дня
**Ответственные файлы:** `src/antispam.py`

#### Описание проблемы
Текущая реализация AntiSpam проверяет лимиты и инкрементит счетчики в два отдельных шага:
```python
# Проверка
count = await redis.get(key)
if count >= limit:
    raise Exception("Limit exceeded")

# Инкремент (НЕ АТОМАРНО!)
await redis.incr(key)
```

При параллельных запросах между проверкой и инкрементом может пройти другой запрос, что приведет к превышению лимита.

#### Шаги реализации

**1. Вариант 1: Redis Lua скрипт (Рекомендуется) (1 день)**
- [ ] Создать Lua скрипт для атомарной проверки+инкремента:
```lua
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])

local current = redis.call('GET', key)
if current and tonumber(current) >= limit then
    return {0, tonumber(current)}  -- Лимит превышен
end

local new_val = redis.call('INCR', key)
if new_val == 1 then
    redis.call('EXPIRE', key, ttl)
end
return {1, new_val}  -- Успех
```

- [ ] Обернуть в Python метод `_atomic_check_and_increment()`
- [ ] Заменить все вызовы проверки+инкремента

**2. Вариант 2: Redis WATCH/MULTI/EXEC (Альтернатива) (1 день)**
- [ ] Использовать оптимистичную блокировку:
```python
async with redis.pipeline() as pipe:
    while True:
        try:
            await pipe.watch(key)
            count = await pipe.get(key)
            if count and int(count) >= limit:
                raise LimitExceeded()

            pipe.multi()
            pipe.incr(key)
            await pipe.execute()
            break
        except WatchError:
            continue  # Retry
```

**3. Тестирование (1 день)**
- [ ] Unit тест: Проверка атомарности (мок Redis)
- [ ] Интеграционный тест: 100 параллельных запросов, лимит не превышен
- [ ] Нагрузочный тест: 1000 req/s, лимиты соблюдаются

#### Риски
- **Риск:** Lua скрипты могут быть сложны для отладки
  **Митигация:** Добавить подробное логирование результатов скрипта

- **Риск:** WATCH/MULTI может привести к большому количеству ретраев
  **Митигация:** Использовать Lua (атомарный, без ретраев)

#### Критерии приемки
- ✅ Проверка и инкремент лимитов атомарны
- ✅ 1000 параллельных запросов не превышают лимит
- ✅ Производительность не хуже текущей

---

### 🔴 Задача 1.4: Добавить idempotency проверку webhook

**Приоритет:** Критический
**Сложность:** Низкая
**Оценка:** 1-2 дня
**Ответственные файлы:** `src/api_server.py` (строки 1789-1832)

#### Описание проблемы
Webhook endpoint `/api/webhook/amocrm` не проверяет дубликаты. AmoCRM может отправить один и тот же webhook 3-5 раз (ретраи при таймауте), что приводит к дублированию сообщений клиентам.

Текущий код:
```python
@router.post("/webhook/amocrm")
async def amocrm_webhook(request: Request):
    payload = await request.json()
    # НЕТ ПРОВЕРКИ НА ДУБЛИКАТ!
    await process_webhook(payload)
    return {"status": "ok"}
```

#### Шаги реализации

**1. Использовать существующую таблицу `message_inbox` (1 день)**
- [ ] В начале обработки webhook вычислить `payload_hash`:
```python
import hashlib
import json

payload_str = json.dumps(payload, sort_keys=True)
payload_hash = hashlib.sha256(payload_str.encode()).hexdigest()
```

- [ ] Проверить, существует ли запись в `message_inbox` с таким `payload_hash`:
```python
async with db.begin():
    existing = await db.execute(
        select(MessageInbox).where(MessageInbox.payload_hash == payload_hash)
    )
    if existing.scalar_one_or_none():
        logger.info(f"Duplicate webhook ignored: {payload_hash}")
        return {"status": "ok", "duplicate": True}

    # Сохранить запись о webhook
    inbox_entry = MessageInbox(
        payload_hash=payload_hash,
        source="amocrm_webhook",
        received_at=datetime.utcnow()
    )
    db.add(inbox_entry)
```

- [ ] Продолжить обработку webhook

**2. Добавить TTL для записей в `message_inbox` (0.5 дня)**
- [ ] Создать миграцию: добавить поле `expires_at` в `message_inbox`
- [ ] Периодически очищать старые записи (cron job или TTL index в Postgres)

**3. Тестирование (0.5 дня)**
- [ ] Unit тест: Первый webhook обрабатывается
- [ ] Unit тест: Второй идентичный webhook игнорируется
- [ ] Интеграционный тест: 5 одинаковых webhook → только 1 сообщение отправлено

#### Риски
- **Риск:** `payload_hash` collision (очень маловероятно с SHA256)
  **Митигация:** Использовать SHA256 (collision probability ≈ 0)

- **Риск:** Рост таблицы `message_inbox`
  **Митигация:** TTL cleanup (удалять записи старше 7 дней)

#### Критерии приемки
- ✅ Дубликаты webhook игнорируются
- ✅ Запись о webhook сохраняется в `message_inbox`
- ✅ Старые записи очищаются автоматически
- ✅ Unit и интеграционные тесты проходят

---

### 🔴 Задача 1.5: Реализовать graceful shutdown

**Приоритет:** Критический
**Сложность:** Средняя
**Оценка:** 2-3 дня
**Ответственные файлы:** `src/main.py`, `src/outbox_worker.py`, `src/telegram_client.py`

#### Описание проблемы
При получении SIGTERM (Docker stop, Kubernetes pod termination) приложение завершается немедленно, что приводит к:
- Потере текущих отправляемых сообщений (outbox worker)
- Разрыву соединения с Telegram без disconnect
- Незавершенным транзакциям в БД

#### Шаги реализации

**1. Graceful shutdown для FastAPI сервера (1 день)**
- [ ] Добавить signal handler в `main.py`:
```python
import signal
import asyncio

shutdown_event = asyncio.Event()

def signal_handler(sig, frame):
    logger.info(f"Received signal {sig}, initiating graceful shutdown...")
    shutdown_event.set()

signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)
```

- [ ] В `main()`:
```python
async def main():
    # Запуск сервера
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)

    # Запуск в отдельной задаче
    server_task = asyncio.create_task(server.serve())

    # Ждем сигнала
    await shutdown_event.wait()

    # Graceful shutdown
    logger.info("Stopping server...")
    server.should_exit = True
    await server_task

    # Закрыть Telegram клиент
    if telegram_client:
        await telegram_client.disconnect()

    logger.info("Shutdown complete")
```

**2. Graceful shutdown для Outbox Worker (1 день)**
- [ ] В `outbox_worker.py` добавить signal handler
- [ ] При получении SIGTERM:
  - Прекратить polling новых сообщений
  - Дождаться завершения текущих отправок (max 30 сек)
  - Вернуть незавершенные сообщения в статус `queued`
  - Закрыть соединение с БД и Telegram

```python
shutdown_requested = False

def signal_handler(sig, frame):
    global shutdown_requested
    logger.info("Shutdown requested, finishing current batch...")
    shutdown_requested = True

signal.signal(signal.SIGTERM, signal_handler)

async def run_worker():
    while not shutdown_requested:
        # Process batch
        await process_outbox_batch()
        await asyncio.sleep(1)

    logger.info("Graceful shutdown complete")
```

**3. Обновить Docker Compose (0.5 дня)**
- [ ] Добавить `stop_grace_period: 30s` для сервисов
- [ ] Добавить health checks

**4. Тестирование (0.5 дня)**
- [ ] Тест: SIGTERM во время отправки сообщения не теряет сообщение
- [ ] Тест: Telegram клиент корректно disconnect
- [ ] Тест: БД транзакции commit или rollback

#### Риски
- **Риск:** Outbox worker не успеет завершить все сообщения за 30 сек
  **Митигация:** Вернуть незавершенные в `queued` статус, они будут обработаны после рестарта

#### Критерии приемки
- ✅ SIGTERM корректно обрабатывается
- ✅ Текущие операции завершаются (или откатываются)
- ✅ Telegram disconnect вызывается
- ✅ Логи показывают "Graceful shutdown complete"

---

## Средний приоритет

### 🟡 Задача 2.1: Вынести UI в отдельные HTML/CSS/JS файлы

**Приоритет:** Средний
**Сложность:** Средняя
**Оценка:** 3-4 дня
**Ответственные файлы:** `src/api_server.py` (строки 1-1500), новые: `src/static/`, `src/templates/`

#### Описание проблемы
В `api_server.py` 1500+ строк HTML/CSS/JS встроены как строки Python. Это приводит к:
- Отсутствию syntax highlighting
- Сложности редактирования
- Невозможности минификации и кэширования
- Плохой производительности (HTML рендерится каждый раз)

#### Шаги реализации

**1. Создать структуру статических файлов (0.5 дня)**
```
src/
  static/
    css/
      main.css
      chat.css
    js/
      main.js
      chat.js
      sse.js
    img/
  templates/
    index.html
    chat.html
    login.html
```

**2. Извлечь HTML в Jinja2 шаблоны (1 день)**
- [ ] Установить Jinja2 (если не установлен)
- [ ] Создать base.html шаблон с layout
- [ ] Извлечь `/ui/chats` HTML → `templates/chat.html`
- [ ] Извлечь `/ui/auth` HTML → `templates/login.html`

**3. Извлечь CSS (0.5 дня)**
- [ ] Создать `static/css/main.css` с общими стилями
- [ ] Создать `static/css/chat.css` с стилями чата
- [ ] Подключить в шаблонах: `<link rel="stylesheet" href="/static/css/main.css">`

**4. Извлечь JavaScript (1 день)**
- [ ] Создать `static/js/sse.js` для Server-Sent Events логики
- [ ] Создать `static/js/chat.js` для UI логики чата
- [ ] Добавить обработку событий, AJAX запросы

**5. Настроить FastAPI StaticFiles (0.5 дня)**
```python
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app.mount("/static", StaticFiles(directory="src/static"), name="static")
templates = Jinja2Templates(directory="src/templates")

@app.get("/ui/chats")
async def ui_chats(request: Request):
    return templates.TemplateResponse("chat.html", {"request": request})
```

**6. Минификация и кэширование (0.5 дня)**
- [ ] Добавить Cache-Control headers для статики
- [ ] Опционально: минификация CSS/JS (webpack/vite)

**7. Тестирование (1 день)**
- [ ] UI работает идентично старой версии
- [ ] Статические файлы кэшируются
- [ ] SSE события приходят корректно

#### Риски
- **Риск:** Сломается существующая функциональность UI
  **Митигация:** Тестировать каждый шаг, сохранить старую версию для отката

#### Критерии приемки
- ✅ Весь HTML в `templates/`
- ✅ Весь CSS в `static/css/`
- ✅ Весь JS в `static/js/`
- ✅ UI работает идентично
- ✅ Статические файлы кэшируются браузером

---

### 🟡 Задача 2.2: Заменить polling на SSE

**Приоритет:** Средний
**Сложность:** Низкая
**Оценка:** 2 дня
**Ответственные файлы:** `src/static/js/chat.js` (после задачи 2.1)

#### Описание проблемы
UI делает 3 polling запроса каждые 3-6 секунд:
- `/api/ui/chats` — список чатов
- `/api/ui/messages/{chat_id}` — сообщения чата
- `/api/ui/events` — события

При 10 операторах это 30+ req/s, задержка до 4-6 секунд.

Однако уже реализован `/api/ui/stream` (SSE), но не используется полностью.

#### Шаги реализации

**1. Расширить SSE события (0.5 дня)**
- [ ] Добавить event type: `chat_list_update`
```python
async def send_chat_list_update():
    await sse_manager.send_event({
        "type": "chat_list_update",
        "data": {
            "chats": [...]
        }
    })
```

- [ ] Триггерить при:
  - Новом сообщении (любой чат)
  - Изменении статуса чата

**2. Обновить JS для SSE (1 день)**
- [ ] Подключиться к `/api/ui/stream` при загрузке страницы
- [ ] Обрабатывать события:
  - `ui_message` → обновить список сообщений
  - `chat_list_update` → обновить список чатов
  - `ui_event` → показать уведомление

```javascript
const eventSource = new EventSource('/api/ui/stream');

eventSource.addEventListener('ui_message', (e) => {
    const data = JSON.parse(e.data);
    appendMessage(data);
});

eventSource.addEventListener('chat_list_update', (e) => {
    const data = JSON.parse(e.data);
    updateChatList(data.chats);
});
```

**3. Удалить polling код (0.5 дня)**
- [ ] Убрать `setInterval()` для polling
- [ ] Оставить fallback: если SSE disconnect, показать ошибку

**4. Тестирование (1 день)**
- [ ] Новое сообщение появляется мгновенно (< 1 сек)
- [ ] Список чатов обновляется в real-time
- [ ] При disconnect SSE показывается warning

#### Риски
- **Риск:** SSE могут disconnect при reverse proxy таймаутах
  **Митигация:** Настроить Nginx: `proxy_read_timeout 3600s;`

#### Критерии приемки
- ✅ Нет polling запросов (проверить в DevTools)
- ✅ Новые сообщения появляются мгновенно
- ✅ При disconnect SSE пользователь видит warning

---

### 🟡 Задача 2.3: Рефакторинг дублирующегося кода

**Приоритет:** Средний
**Сложность:** Низкая
**Оценка:** 2-3 дня
**Ответственные файлы:** `src/api_server.py`, `src/bridge.py`

#### Описание проблемы
Повторяющиеся проверки и логика в коде:
- Проверка `if not bridge.amocrm` повторена 3 раза
- Проверка авторизации Telegram дублируется
- Обработка ошибок копипаста

#### Шаги реализации

**1. Создать helper функции (1 день)**
```python
# src/utils/helpers.py

async def require_amocrm_integration(bridge: Bridge):
    """Проверка наличия AmoCRM интеграции."""
    if not bridge.amocrm:
        raise HTTPException(
            status_code=503,
            detail="AmoCRM integration not configured"
        )

async def require_telegram_auth(telegram_client):
    """Проверка авторизации Telegram."""
    if not telegram_client or not await telegram_client.is_authorized():
        raise HTTPException(
            status_code=401,
            detail="Telegram not authorized"
        )
```

**2. Создать декораторы для endpoint'ов (1 день)**
```python
from functools import wraps

def requires_amocrm(func):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        bridge = kwargs.get('bridge')
        await require_amocrm_integration(bridge)
        return await func(*args, **kwargs)
    return wrapper

# Использование:
@router.post("/api/send-message")
@requires_amocrm
async def send_message(request: SendMessageRequest, bridge: Bridge = Depends(get_bridge)):
    # amocrm уже проверен
    ...
```

**3. Рефакторинг обработки ошибок (0.5 дня)**
- [ ] Создать базовый exception handler
- [ ] Стандартизировать формат ошибок API

**4. Code review и cleanup (0.5 дня)**
- [ ] Удалить мертвый код
- [ ] Упростить сложные условия
- [ ] Добавить docstrings

#### Критерии приемки
- ✅ Нет дублирующихся проверок
- ✅ Все helper функции покрыты тестами
- ✅ Code coverage не упал

---

### 🟡 Задача 2.4: Добавить поддержку мульти-аккаунтов

**Приоритет:** Средний
**Сложность:** Очень высокая
**Оценка:** 8-10 дней
**Ответственные файлы:** `src/telegram_client.py`, `src/database.py`, `src/api_server.py`

#### Описание проблемы
Текущая архитектура поддерживает только 1 Telegram аккаунт. Для масштабирования нужна возможность:
- Работать с несколькими аккаунтами одновременно
- Распределять нагрузку между аккаунтами
- Изолировать сессии и лимиты

#### Шаги реализации

**1. Проектирование архитектуры (1 день)**
- [ ] Спроектировать схему БД для мульти-аккаунтов:
```sql
CREATE TABLE telegram_accounts (
    id SERIAL PRIMARY KEY,
    phone_number VARCHAR(20) UNIQUE NOT NULL,
    session_string TEXT,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMP DEFAULT NOW()
);

ALTER TABLE chat_mappings ADD COLUMN account_id INTEGER REFERENCES telegram_accounts(id);
ALTER TABLE message_outbox ADD COLUMN account_id INTEGER REFERENCES telegram_accounts(id);
```

- [ ] Спроектировать `TelegramClientManager` для управления множеством клиентов

**2. Обновить модели БД (1 день)**
- [ ] Создать модель `TelegramAccount`
- [ ] Добавить `account_id` во все связанные таблицы
- [ ] Создать Alembic миграцию

**3. Рефакторинг `telegram_client.py` (3 дня)**
- [ ] Создать `TelegramClientManager`:
```python
class TelegramClientManager:
    def __init__(self):
        self.clients: Dict[int, TelegramClient] = {}

    async def get_client(self, account_id: int) -> TelegramClient:
        if account_id not in self.clients:
            account = await load_account(account_id)
            client = await self._create_client(account)
            self.clients[account_id] = client
        return self.clients[account_id]

    async def add_account(self, phone: str) -> int:
        # Создать новый аккаунт
        ...
```

- [ ] Обновить все методы для работы с `account_id`

**4. Обновить API endpoints (2 дня)**
- [ ] Добавить `account_id` в запросы `/api/send-message`
- [ ] UI: выбор аккаунта для отправки
- [ ] UI: список всех аккаунтов с их статусами

**5. Балансировка нагрузки (1 день)**
- [ ] Создать `AccountLoadBalancer`:
```python
async def select_account_for_send(chat_id: str) -> int:
    # Round-robin или least-loaded
    ...
```

**6. Тестирование (2 дня)**
- [ ] Тест: 2 аккаунта одновременно отправляют сообщения
- [ ] Тест: Лимиты изолированы между аккаунтами
- [ ] Тест: UI показывает все аккаунты

#### Риски
- **Риск:** Очень большой рефакторинг, может сломать существующую функциональность
  **Митигация:** Поэтапное внедрение, feature flag для мульти-аккаунтов

- **Риск:** Telethon может не поддерживать множественные клиенты в одном процессе
  **Митигация:** Тестировать на ранней стадии, возможно использовать отдельные процессы

#### Критерии приемки
- ✅ Можно добавить несколько Telegram аккаунтов
- ✅ Сообщения отправляются с разных аккаунтов
- ✅ Лимиты AntiSpam изолированы по аккаунтам
- ✅ UI показывает статус всех аккаунтов

---

## Низкий приоритет

### 🟢 Задача 3.1: Per-operator rate limiting

**Приоритет:** Низкий
**Сложность:** Средняя
**Оценка:** 2-3 дня
**Ответственные файлы:** `src/antispam.py`, `src/database.py`

#### Описание проблемы
Текущие лимиты AntiSpam глобальные (на весь аккаунт). Нужна возможность:
- Установить индивидуальные лимиты для оператора
- Отследить, кто отправляет больше всего сообщений
- Предотвратить злоупотребления одним оператором

#### Шаги реализации

**1. Добавить поле `operator_id` в outbox (1 день)**
- [ ] Создать таблицу `operators`:
```sql
CREATE TABLE operators (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(100) UNIQUE,
    hourly_limit INTEGER DEFAULT 50,
    daily_limit INTEGER DEFAULT 200,
    created_at TIMESTAMP DEFAULT NOW()
);
```

- [ ] Добавить `operator_id` в `message_outbox`
- [ ] API: передавать `operator_id` при отправке

**2. Расширить AntiSpam (1 день)**
- [ ] Добавить проверку per-operator лимитов:
```python
async def check_operator_limits(operator_id: int, account_id: int):
    # Redis key: antispam:operator:{operator_id}:hourly
    hourly_key = f"antispam:operator:{operator_id}:hourly"
    daily_key = f"antispam:operator:{operator_id}:daily"

    # Проверить лимиты
    ...
```

**3. UI для операторов (1 день)**
- [ ] Страница `/ui/operators` со списком операторов
- [ ] Статистика отправок по операторам
- [ ] Возможность изменить лимиты

#### Критерии приемки
- ✅ Каждый оператор имеет свои лимиты
- ✅ Превышение лимита блокирует только конкретного оператора
- ✅ UI показывает статистику по операторам

---

### 🟢 Задача 3.2: Admin UI для конфигурации

**Приоритет:** Низкий
**Сложность:** Средняя
**Оценка:** 4-5 дней
**Ответственные файлы:** Новые: `src/admin/`, `src/templates/admin/`

#### Описание проблемы
Все настройки сейчас в `.env` файле. Для удобства нужен Admin UI:
- Управление AmoCRM интеграцией (OAuth)
- Настройка лимитов AntiSpam
- Управление аккаунтами Telegram
- Просмотр логов и метрик

#### Шаги реализации

**1. Создать базовый Admin UI (2 дня)**
- [ ] Использовать FastAPI + Jinja2
- [ ] Страницы:
  - `/admin/` — дашборд
  - `/admin/accounts` — Telegram аккаунты
  - `/admin/settings` — настройки
  - `/admin/logs` — логи

**2. Управление настройками (1 день)**
- [ ] Создать таблицу `system_settings`:
```sql
CREATE TABLE system_settings (
    key VARCHAR(100) PRIMARY KEY,
    value TEXT,
    description TEXT,
    updated_at TIMESTAMP DEFAULT NOW()
);
```

- [ ] API для чтения/записи настроек

**3. Аутентификация Admin UI (1 день)**
- [ ] Добавить базовую аутентификацию (логин/пароль)
- [ ] Или использовать JWT токены

**4. Интеграция с AmoCRM OAuth (1 день)**
- [ ] UI для OAuth авторизации AmoCRM
- [ ] Кнопка "Connect AmoCRM"

#### Критерии приемки
- ✅ Admin UI доступен на `/admin/`
- ✅ Можно изменять настройки через UI
- ✅ Защищено аутентификацией

---

### 🟢 Задача 3.3: Нагрузочные тесты

**Приоритет:** Низкий
**Сложность:** Средняя
**Оценка:** 3-4 дня
**Ответственные файлы:** Новые: `tests/load/`

#### Описание проблемы
Нет понимания, какую нагрузку выдерживает система. Нужны нагрузочные тесты для:
- Определения максимальной пропускной способности
- Выявления узких мест
- Проверки поведения под нагрузкой

#### Шаги реализации

**1. Выбрать инструмент нагрузочного тестирования (0.5 дня)**
- [ ] Locust (рекомендуется, Python-based)
- [ ] k6 (альтернатива, JS-based)

**2. Написать сценарии (2 дня)**
```python
# tests/load/locustfile.py
from locust import HttpUser, task, between

class TelegramCRMUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def send_message(self):
        self.client.post("/api/send-message", json={
            "contact_id": 12345,
            "message": "Test message",
            "account_id": 1
        }, headers={"X-API-Key": "..."})

    @task(1)
    def list_chats(self):
        self.client.get("/api/ui/chats")
```

**3. Запустить тесты (1 день)**
- [ ] Тест 1: 100 req/s в течение 5 минут
- [ ] Тест 2: 500 req/s в течение 1 минуты
- [ ] Тест 3: Постепенное увеличение нагрузки (ramp-up)

**4. Анализ результатов (0.5 дня)**
- [ ] Записать метрики: latency, throughput, error rate
- [ ] Выявить узкие места (CPU, DB, Redis)
- [ ] Рекомендации по оптимизации

#### Критерии приемки
- ✅ Нагрузочные тесты написаны
- ✅ Результаты задокументированы
- ✅ Система выдерживает 100 req/s без ошибок

---

## График выполнения

### Фаза 1: Критические задачи (10-14 дней)

| Неделя | Задачи | Статус |
|--------|--------|--------|
| **Неделя 1** | 1.1 FK constraints (3 дн)<br>1.2 In-memory → БД (4 дн) | ⏳ Pending |
| **Неделя 2** | 1.3 AntiSpam атомарность (2 дн)<br>1.4 Webhook idempotency (2 дн)<br>1.5 Graceful shutdown (3 дн) | ⏳ Pending |

### Фаза 2: Производительность (15-20 дней)

| Неделя | Задачи | Статус |
|--------|--------|--------|
| **Неделя 3** | 2.1 UI в отдельные файлы (4 дн)<br>2.2 Polling → SSE (2 дн) | ⏳ Pending |
| **Неделя 4** | 2.3 Рефакторинг кода (3 дн)<br>2.4 Мульти-аккаунты (начало) | ⏳ Pending |
| **Неделя 5** | 2.4 Мульти-аккаунты (продолжение, 10 дн) | ⏳ Pending |

### Фаза 3: Расширенная функциональность (10-12 дней)

| Неделя | Задачи | Статус |
|--------|--------|--------|
| **Неделя 6** | 3.1 Per-operator limiting (3 дн)<br>3.2 Admin UI (начало) | ⏳ Pending |
| **Неделя 7** | 3.2 Admin UI (5 дн)<br>3.3 Нагрузочные тесты (4 дн) | ⏳ Pending |

**Общий срок:** 7-8 недель (35-42 рабочих дня)

---

## Риски и митигация

### Технические риски

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Миграции БД сломают production данные | Средняя | Критическое | Тестировать на копии production БД, иметь rollback план |
| Производительность упадет после перехода на БД | Средняя | Высокое | Добавить Redis кэш, мониторить метрики |
| Telethon не поддержит мульти-клиенты | Низкая | Высокое | Тестировать рано, fallback: отдельные процессы |
| Graceful shutdown не завершит все задачи за 30 сек | Средняя | Среднее | Откатить в queued статус незавершенные |
| SSE disconnect при reverse proxy | Средняя | Низкое | Настроить Nginx timeouts |

### Организационные риски

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| Недостаточно времени для всех задач | Высокая | Среднее | Приоритезировать, начать с критических |
| Отсутствие code review | Средняя | Высокое | Обязательный review для критических изменений |
| Недостаточное тестирование | Средняя | Высокое | Минимум 80% coverage для новых изменений |

---

## Критерии приемки

### Фаза 1: Критические задачи

- [ ] Все FK constraints добавлены в БД
- [ ] Нет in-memory переменных, все в БД/Redis
- [ ] AntiSpam лимиты атомарны, проходят нагрузочные тесты
- [ ] Webhook дубликаты игнорируются
- [ ] Graceful shutdown работает (проверено вручную)
- [ ] **Критерий готовности к production:** Все задачи выполнены, unit тесты проходят

### Фаза 2: Производительность

- [ ] UI в отдельных файлах, кэшируется
- [ ] Нет polling, только SSE
- [ ] Code coverage > 80%
- [ ] Мульти-аккаунты работают (минимум 2 аккаунта одновременно)

### Фаза 3: Расширенная функциональность

- [ ] Per-operator лимиты настраиваются
- [ ] Admin UI доступен и защищен
- [ ] Нагрузочные тесты показывают > 100 req/s

---

## Приложения

### A. Контрольный список перед запуском production

- [ ] Все критические задачи (1.1-1.5) выполнены
- [ ] Unit тесты покрывают > 80% кода
- [ ] Интеграционные тесты проходят
- [ ] Миграции БД протестированы на копии production
- [ ] Rollback план подготовлен
- [ ] Мониторинг настроен (Prometheus + Grafana)
- [ ] Alerting настроен (критические ошибки → Slack/email)
- [ ] Backup БД настроен (ежедневный)
- [ ] Документация обновлена (README, DEPLOYMENT)
- [ ] Runbook обновлен с новыми процедурами

### B. Полезные команды

```bash
# Запуск unit тестов
pytest tests/ -v

# Запуск нагрузочных тестов
locust -f tests/load/locustfile.py --host=http://localhost:8000

# Создать Alembic миграцию
alembic revision --autogenerate -m "description"

# Применить миграции
alembic upgrade head

# Rollback миграции
alembic downgrade -1

# Проверка покрытия тестами
pytest --cov=src --cov-report=html
```

---

---

## ⚠️ КРИТИЧЕСКИЙ АНАЛИЗ ПЛАНА

### Что УПУЩЕНО в плане (критические проблемы)

#### 🔴 Упущение #1: Синхронные SQL в async контексте

**Проблема:** В исходном анализе была выявлена проблема "Синхронные SQL в async" ([telegram_client.py:627-666]()), но в плане нет задачи по её исправлению.

**Текущий код:**
```python
# telegram_client.py - БЛОКИРУЕТ event loop!
db = next(get_db())
result = db.query(UiChat).filter(...).first()  # Синхронный query в async функции
```

**Последствия:**
- Блокировка event loop при каждом входящем сообщении
- Пропуск сообщений при высокой нагрузке
- Degraded performance для всех запросов

**Требуется добавить:** Задача 1.6 "Заменить синхронные SQL на async"
- Оценка: 2-3 дня
- Приоритет: Критический (блокирует production)

---

#### 🔴 Упущение #2: Telethon session storage для Kubernetes

**Проблема:** Текущая система хранит `.session` файлы локально, что несовместимо с Kubernetes multi-pod deployment.

**Последствия:**
- Невозможно масштабировать горизонтально (multiple pods)
- При рестарте pod'а теряется сессия
- Требуется re-authorization после каждого деплоя

**Требуется добавить:** Задача 1.7 "Мигрировать Telethon session в БД"
- StringSession → PostgreSQL
- Оценка: 1-2 дня
- Приоритет: Критический для Kubernetes deployment

---

#### 🟡 Упущение #3: CI/CD pipeline

**Проблема:** Нет автоматизации тестирования и деплоя.

**Требуется:**
- GitHub Actions / GitLab CI для автоматического запуска тестов
- Автоматический деплой в staging после merge в main
- Manual approval для production деплоя

**Оценка:** 2-3 дня
**Приоритет:** Высокий (предотвращает регрессии)

---

#### 🟡 Упущение #4: Zero-downtime deployment strategy

**Проблема:** План не описывает, как деплоить без остановки сервиса.

**Требуется:**
- Blue-green deployment или rolling updates
- Health checks для ready/live проверок
- Database migration strategy (forward-compatible migrations)

**Оценка:** 2 дня
**Приоритет:** Высокий

---

#### 🟡 Упущение #5: Performance baseline и monitoring

**Проблема:** Нет метрик "до" изменений, невозможно сравнить производительность "после".

**Требуется:**
- Замерить current metrics: latency p50/p95/p99, throughput, error rate
- Установить alert thresholds
- Dashboard для визуализации метрик

**Оценка:** 1-2 дня
**Приоритет:** Средний (но должно быть ДО начала изменений)

---

#### 🟢 Упущение #6: Security audit

**Проблема:** Admin UI (задача 3.2) не включает security review.

**Требуется:**
- OWASP Top 10 проверка
- SQL injection, XSS, CSRF protection
- Rate limiting для Admin endpoints
- Audit logging (кто что изменил)

**Оценка:** 1-2 дня
**Приоритет:** Средний (перед включением Admin UI в production)

---

#### 🟢 Упущение #7: Disaster Recovery Plan

**Проблема:** Что делать, если production полностью упадет?

**Требуется:**
- Backup/restore процедуры для БД
- Point-in-time recovery (PITR) для PostgreSQL
- Runbook для emergency scenarios
- Contact list (кто отвечает за что)

**Оценка:** 1 день (документация)
**Приоритет:** Средний

---

#### 🟢 Упущение #8: User training для операторов

**Проблема:** UI изменится (задача 2.1-2.2), операторов нужно обучить.

**Требуется:**
- Документация для операторов (screenshots, workflow)
- Training session перед rollout
- FAQ для частых вопросов

**Оценка:** 1-2 дня
**Приоритет:** Низкий (но обязательно перед production rollout)

---

### Критика оценок времени

| Задача | Оригинальная оценка | Реалистичная оценка | Комментарий |
|--------|---------------------|---------------------|-------------|
| 1.1 FK constraints | 2-3 дня | **3-5 дней** | Нужно больше времени на тестирование с production-подобными данными |
| 1.2 In-memory → БД | 3-4 дня | **5-7 дней** | Race conditions сложнее, чем кажется; нужно больше тестов |
| 2.4 Мульти-аккаунты | 8-10 дней | **12-15 дней** | Очень большой рефакторинг, высокий риск регрессий |
| 3.3 Нагрузочные тесты | 3-4 дня | **5-6 дней** | Анализ результатов занимает больше времени |

**Итого:** Вместо 35-42 дней → **45-55 дней (9-11 недель)**

---

### Критика зависимостей между задачами

**Проблема:** План не показывает, какие задачи можно делать параллельно, а какие зависят друг от друга.

**Зависимости:**
```
1.1 FK constraints  ─┐
                     ├─→ Можно делать параллельно
1.3 AntiSpam        ─┘

1.2 In-memory → БД  ──→  БЛОКИРУЕТ  ──→  1.5 Graceful shutdown
                                          (зависит от отсутствия in-memory)

2.1 UI в файлы      ──→  БЛОКИРУЕТ  ──→  2.2 Polling → SSE
                                          (SSE код в JS файлах)

1.* (все критические)  ──→  БЛОКИРУЮТ  ──→  Production deployment
```

**Рекомендация:** Начать с задач без зависимостей (1.1, 1.3, 1.4) параллельно.

---

### Критика рисков

#### Недооцененные риски:

1. **Риск: Production data corruption при миграциях**
   - Вероятность: **ВЫСОКАЯ** (не средняя)
   - Требуется: Mandatory backup перед КАЖДОЙ миграцией
   - Требуется: Dry-run на staging с production snapshot

2. **Риск: Telegram ban при нарушении rate limits**
   - Вероятность: Средняя
   - Влияние: **КАТАСТРОФИЧЕСКОЕ**
   - Митигация: Conservative limits в AntiSpam (меньше, чем Telegram допускает)

3. **Риск: Breaking changes для существующих API клиентов**
   - Вероятность: Высокая
   - Влияние: Высокое
   - Митигация: API versioning (/api/v1/, /api/v2/), deprecation notices

4. **Риск: Team velocity ниже ожидаемой**
   - Вероятность: **ОЧЕНЬ ВЫСОКАЯ**
   - Влияние: Срыв сроков
   - Митигация: Добавить 30% buffer к каждой оценке

---

### Что еще ЗАБЫЛИ

#### 1. Staging Environment
**Проблема:** Где тестировать изменения перед production?

**Требуется:**
- Staging environment с копией production БД (anonymized)
- Отдельный Telegram test аккаунт
- Отдельный AmoCRM sandbox аккаунт

**Оценка:** 1-2 дня setup
**Приоритет:** Критический (нужен ДО начала работ)

---

#### 2. Database Connection Pooling Review
**Проблема:** Async SQLAlchemy требует правильной настройки connection pool.

**Требуется:**
- Проверить pool_size, max_overflow настройки
- Мониторинг pool exhaustion
- Timeout настройки

**Оценка:** 0.5 дня
**Приоритет:** Средний

---

#### 3. Distributed Tracing
**Проблема:** При проблемах в production сложно найти bottleneck.

**Требуется:**
- OpenTelemetry или Jaeger
- Trace request через: API → Outbox → Telegram → AmoCRM
- Correlation ID для всех логов

**Оценка:** 2-3 дня
**Приоритет:** Низкий (но очень полезно для debugging)

---

#### 4. Rate Limiting для API endpoints
**Проблема:** Нет защиты от abuse внешних API клиентов.

**Требуется:**
- Rate limit middleware (например, slowapi)
- Per-API-key limits
- 429 Too Many Requests response

**Оценка:** 1 день
**Приоритет:** Средний

---

#### 5. Database Indexes Review
**Проблема:** После добавления FK нужно убедиться, что все индексы оптимальны.

**Требуется:**
- Проверить execution plans для частых запросов
- Добавить composite indexes где нужно
- Удалить неиспользуемые indexes

**Оценка:** 1-2 дня
**Приоритет:** Средний

---

#### 6. Secrets Management
**Проблема:** Как безопасно хранить API keys, passwords в production?

**Требуется:**
- Vault / AWS Secrets Manager / Azure Key Vault
- Rotation policy для secrets
- Audit log для access к secrets

**Оценка:** 1-2 дня
**Приоритет:** Высокий для production

---

#### 7. Compliance & GDPR
**Проблема:** Хранение персональных данных клиентов требует compliance.

**Требуется:**
- Data retention policy (сколько хранить историю сообщений?)
- Right to be forgotten (удаление данных по запросу)
- Data export (пользователь может запросить свои данные)
- Encryption at rest для sensitive data

**Оценка:** 2-3 дня
**Приоритет:** Высокий (юридические последствия)

---

#### 8. WebSocket alternative для SSE
**Проблема:** SSE односторонний (server → client), не поддерживает binary data.

**Рекомендация:** Рассмотреть WebSocket для bidirectional communication
- Позволит отправлять сообщения прямо из UI
- Лучше для real-time features

**Оценка:** 3-4 дня (альтернатива задаче 2.2)
**Приоритет:** Низкий (SSE достаточно для текущих требований)

---

## 📋 ОБНОВЛЕННЫЙ ПЛАН С ДОПОЛНЕНИЯМИ

### Фаза 0: Подготовка (ОБЯЗАТЕЛЬНО ДО НАЧАЛА) - 3-5 дней

| Задача | Оценка | Приоритет |
|--------|--------|-----------|
| 0.1 Настроить staging environment | 2 дня | Критический |
| 0.2 Замерить performance baseline | 1 день | Высокий |
| 0.3 Настроить CI/CD pipeline | 2 дня | Высокий |
| 0.4 Создать backup стратегию | 1 день | Высокий |

### Фаза 1: Критические задачи (ОБНОВЛЕНО) - 18-24 дня

| Задача | Оригинал | Обновлено | Изменение |
|--------|----------|-----------|-----------|
| 1.1 FK constraints | 2-3 дня | **3-5 дней** | +1-2 дня на тестирование |
| 1.2 In-memory → БД | 3-4 дня | **5-7 дней** | +2-3 дня на race conditions |
| 1.3 AntiSpam атомарность | 2 дня | 2 дня | без изменений |
| 1.4 Webhook idempotency | 1-2 дня | 1-2 дня | без изменений |
| 1.5 Graceful shutdown | 2-3 дня | 2-3 дня | без изменений |
| **1.6 Async SQL (НОВОЕ)** | - | **2-3 дня** | Упущено в оригинале |
| **1.7 Session в БД (НОВОЕ)** | - | **1-2 дня** | Для Kubernetes |
| 1.8 Zero-downtime deployment | - | **2 дня** | Упущено |

**Итого Фаза 1:** 18-24 дня (вместо 10-14)

---

### Дополнительные задачи (можно делать параллельно)

#### Security & Compliance (3-5 дней)
- [ ] Security audit (2 дня)
- [ ] GDPR compliance review (2-3 дня)
- [ ] Secrets management (1-2 дня)

#### Operational Excellence (4-6 дней)
- [ ] Disaster Recovery Plan (1 день - документация)
- [ ] Distributed tracing (2-3 дня)
- [ ] API rate limiting (1 день)
- [ ] DB indexes review (1-2 дня)

#### User Experience (2-3 дня)
- [ ] User training materials (1-2 дня)
- [ ] Operator documentation (1 день)

---

## 🎯 ОБНОВЛЕННЫЙ ГРАФИК

### Реалистичный timeline:

```
Фаза 0: Подготовка           ██████                      (3-5 дней)
Фаза 1: Критические          ████████████████████        (18-24 дня)
Фаза 2: Производительность   ████████████████████████    (18-25 дней)
Фаза 3: Расширенное          ████████████                (12-15 дней)
Security & Ops               ██████                      (5-8 дней)
                             ─────────────────────────────────────
Итого:                       56-77 дней (11-15 недель)
```

**С учетом buffer 30%:** **73-100 дней (15-20 недель)**

---

## ⚡ РЕКОМЕНДАЦИИ ПО ПРИОРИТИЗАЦИИ

### Минимально жизнеспособный production (MVP)

Если нужно запустить СРОЧНО, минимальный набор:

**Must-have (блокируют production):**
1. ✅ Задача 1.1: FK constraints
2. ✅ Задача 1.2: In-memory → БД
3. ✅ Задача 1.3: AntiSpam атомарность
4. ✅ Задача 1.4: Webhook idempotency
5. ✅ Задача 1.6: Async SQL (НОВОЕ)
6. ✅ Задача 0.1: Staging setup
7. ✅ Задача 0.4: Backup стратегия

**Оценка MVP:** 15-20 дней

**После MVP можно запустить в production с ограничениями:**
- Только 1 аккаунт
- UI как есть (встроенный HTML)
- Manual deployment
- Ограниченный мониторинг

---

## 🚨 КРИТИЧЕСКИЕ ВЫВОДЫ

### Главные проблемы оригинального плана:

1. **❌ Оптимистичные оценки** - реальность на 40-50% больше
2. **❌ Упущены критические задачи** - Async SQL, Session storage
3. **❌ Нет подготовительной фазы** - staging, baseline, CI/CD
4. **❌ Недооценены риски** - особенно data corruption
5. **❌ Нет минимального MVP** - все или ничего
6. **❌ Зависимости не визуализированы** - непонятно, что можно параллелить

### Что делать:

1. ✅ **Начать с Фазы 0** (staging, baseline, CI/CD)
2. ✅ **Выбрать стратегию:** MVP (15-20 дней) или Full (15-20 недель)
3. ✅ **Добавить 30% buffer** к каждой оценке
4. ✅ **Mandatory backup** перед каждой production миграцией
5. ✅ **Code review** для всех критических изменений
6. ✅ **Постепенный rollout:** staging → canary → production

---

## 📊 МАТРИЦА ЗАВИСИМОСТЕЙ (Визуализация)

```
Фаза 0 (Подготовка)
├─ 0.1 Staging          ──┐
├─ 0.2 Baseline         ──┼─→  Требуется ДО любых изменений
├─ 0.3 CI/CD            ──┤
└─ 0.4 Backup           ──┘

Фаза 1 (Критические)
├─ 1.1 FK constraints   ──→  Независимая, можно параллельно
├─ 1.3 AntiSpam         ──→  Независимая, можно параллельно
├─ 1.4 Webhook idemp.   ──→  Независимая, можно параллельно
├─ 1.6 Async SQL        ──→  Независимая, можно параллельно
│
├─ 1.2 In-memory → БД   ──→  БЛОКИРУЕТ  ──→  1.5 Graceful shutdown
│                                             1.7 Session → БД
└─ 1.8 Zero-downtime    ──→  Требует 1.1-1.7

Фаза 2 (Производительность)
├─ 2.1 UI в файлы       ──→  БЛОКИРУЕТ  ──→  2.2 SSE
├─ 2.3 Рефакторинг      ──→  Независимая
└─ 2.4 Мульти-аккаунты  ──→  Требует 1.2, 1.7 (session в БД)

Критический путь (longest path):
0.1→0.2→1.2→1.5→1.7→2.4 = 3+1+7+3+2+15 = 31 день минимум
```

---

**Конец документа (обновлено)**

*Версия: 2.0*
*Дата обновления: 2026-01-16*
*Статус: Draft с критическим анализом*

**Рекомендуется обсудить с командой:**
1. Выбор стратегии: MVP vs Full implementation
2. Доступные ресурсы и realistic timeline
3. Бюджет на infrastructure (staging, monitoring, etc.)
4. Risk appetite (насколько критично время запуска?)

---
---

# 🚀 РАДИКАЛЬНЫЙ ПЛАН: 12 ЧАСОВ С AI АГЕНТАМИ

## ⚡ КРИТИЧЕСКИЙ АНАЛИЗ: Можно ли за 12 часов?

### Реальность работы с AI агентами

**Преимущества AI:**
- ✅ Массовая параллелизация (10-20 агентов одновременно)
- ✅ Быстрое написание шаблонного кода
- ✅ Автоматизация тестов
- ✅ Рефакторинг и code cleanup
- ✅ Работа 24/7 без перерывов

**Ограничения AI:**
- ❌ Плохо принимает архитектурные решения
- ❌ Требует четких, детальных инструкций
- ❌ Не может тестировать интеграции с внешними API (Telegram, AmoCRM)
- ❌ Нужен человек-координатор для review
- ❌ Сложные race conditions и edge cases пропускает

**Формула эффективности:**
```
12 часов × 10 агентов параллельно = 120 человеко-часов
НО: реальная эффективность ≈ 40-50% из-за coordination overhead
Итого: ~50-60 эффективных человеко-часов
```

---

## 🎯 ЧТО РЕАЛЬНО МОЖНО СДЕЛАТЬ ЗА 12 ЧАСОВ

### Категоризация задач по сложности для AI

#### 🟢 ЛЕГКО для AI (30 мин - 2 часа):
- ✅ FK constraints в БД (1.5 часа)
- ✅ Webhook idempotency проверка (1 час)
- ✅ AntiSpam Lua скрипт (1.5 часа)
- ✅ Async SQL рефакторинг (2 часа при четких инструкциях)
- ✅ Рефакторинг дублирующегося кода (1 час)
- ✅ Rate limiting для API (1 час)

#### 🟡 СРЕДНЕ для AI (2-4 часа):
- ⚠️ In-memory → БД миграция (3-4 часа, высокий риск багов)
- ⚠️ Graceful shutdown (2-3 часа)
- ⚠️ Session в БД (2 часа)
- ⚠️ UI в отдельные файлы (3 часа, но низкий приоритет)

#### 🔴 СЛОЖНО/НЕВОЗМОЖНО для AI за 12 часов:
- ❌ Мульти-аккаунты (12-15 дней → СЛИШКОМ СЛОЖНО)
- ❌ Admin UI (4-5 дней → СЛИШКОМ ДОЛГО)
- ❌ Нагрузочные тесты (требует реальную инфраструктуру)
- ❌ Staging setup (требует инфраструктуру и credentials)
- ❌ CI/CD pipeline (требует GitHub/GitLab access)

---

## 🔥 ULTRA-MVP: МИНИМУМ ДЛЯ PRODUCTION ЗА 12 ЧАСОВ

### Стратегия: "Убрать только критические блокеры"

**Цель:** Исправить 5 критических проблем, которые ТОЧНО сломают production

### Приоритет #1: Целостность данных (4 часа)

| Задача | Агент | Время | Риск для AI |
|--------|-------|-------|-------------|
| **1.1 FK constraints** | Agent-DB | 1.5ч | Низкий ✅ |
| **1.4 Webhook idempotency** | Agent-API | 1ч | Низкий ✅ |
| **1.6 Async SQL** | Agent-Perf | 2ч | Средний ⚠️ |

**Критерий успеха:** Нет data corruption, нет race conditions

---

### Приоритет #2: Безопасность и лимиты (3 часа)

| Задача | Агент | Время | Риск для AI |
|--------|-------|-------|-------------|
| **1.3 AntiSpam атомарность** | Agent-Redis | 1.5ч | Низкий ✅ |
| **Rate limiting API** | Agent-Security | 1ч | Низкий ✅ |
| **API key validation** | Agent-Security | 0.5ч | Низкий ✅ |

**Критерий успеха:** Невозможно превысить Telegram limits, API защищен

---

### Приоритет #3: Стабильность (3 часа)

| Задача | Агент | Время | Риск для AI |
|--------|-------|-------|-------------|
| **1.5 Graceful shutdown** | Agent-Ops | 2ч | Средний ⚠️ |
| **1.7 Session в БД** | Agent-DB | 1ч | Низкий ✅ |

**Критерий успеха:** Рестарт не теряет данные

---

### Приоритет #4: Code quality (2 часа)

| Задача | Агент | Время | Риск для AI |
|--------|-------|-------|-------------|
| **2.3 Рефакторинг дублей** | Agent-Refactor | 1ч | Низкий ✅ |
| **Tests для критических изменений** | Agent-Test | 1ч | Средний ⚠️ |

**Критерий успеха:** Code coverage > 70%, нет дублей

---

## 📋 12-ЧАСОВОЙ EXECUTION PLAN

### Фаза 1: Подготовка (30 минут) - ЧЕЛОВЕК

**00:00 - 00:30** | Coordinator (человек)
- [ ] Создать feature branch: `feature/12h-production-fixes`
- [ ] Backup текущей БД (если есть staging)
- [ ] Подготовить инструкции для каждого агента
- [ ] Создать задачи в todo list для tracking
- [ ] Настроить мониторинг прогресса

---

### Фаза 2: Параллельный запуск (4 часа) - AI АГЕНТЫ

**00:30 - 04:30** | 6 агентов параллельно

#### 🤖 Agent-DB-1: FK Constraints
```
Задача: Добавить Foreign Key constraints
Файлы: src/database.py, alembic/versions/
Время: 1.5 часа
Инструкции:
1. Найти все таблицы без FK
2. Создать миграцию с FK + CASCADE
3. Добавить cleanup скрипт для orphan записей
4. Написать тесты для FK constraints
```

#### 🤖 Agent-API: Webhook Idempotency
```
Задача: Добавить дедупликацию webhook
Файлы: src/api_server.py (строки 1789-1832)
Время: 1 час
Инструкции:
1. Использовать message_inbox для проверки payload_hash
2. Вернуть 200 OK для дубликатов
3. Добавить TTL cleanup (7 дней)
4. Написать тесты: первый webhook OK, второй ignored
```

#### 🤖 Agent-Perf: Async SQL
```
Задача: Заменить sync SQL на async
Файлы: src/telegram_client.py (строки 627-666)
Время: 2 часа
Инструкции:
1. Заменить next(get_db()) на async session
2. Заменить db.query() на async select()
3. Добавить await для всех DB операций
4. Тестировать: нет blocking calls
```

#### 🤖 Agent-Redis: AntiSpam Atomicity
```
Задача: Lua скрипт для атомарной проверки лимитов
Файлы: src/antispam.py
Время: 1.5 часа
Инструкции:
1. Создать Lua скрипт check_and_increment
2. Обернуть в Python метод
3. Заменить все check+incr на atomic call
4. Тест: 100 параллельных запросов не превышают limit
```

#### 🤖 Agent-Security: Rate Limiting
```
Задача: Rate limiting для API endpoints
Файлы: src/api_server.py
Время: 1 час
Инструкции:
1. Установить slowapi library
2. Добавить @limiter.limit("100/hour") к send-message
3. Добавить per-API-key limits
4. Тест: 429 после превышения
```

#### 🤖 Agent-Ops: Graceful Shutdown
```
Задача: Обработка SIGTERM
Файлы: src/main.py, src/outbox_worker.py
Время: 2 часа
Инструкции:
1. Signal handler для SIGTERM
2. Завершить текущие операции (max 30 сек)
3. Disconnect Telegram client
4. Тест: docker stop не теряет сообщения
```

---

### Фаза 3: Review & Integration (2 часа) - ЧЕЛОВЕК + AI

**04:30 - 06:30** | Code Review

#### 🧑 Coordinator (человек):
- [ ] Review всех PR от агентов
- [ ] Проверить конфликты между изменениями
- [ ] Merge в feature branch
- [ ] Запустить интеграционные тесты

#### 🤖 Agent-Test:
```
Задача: Написать интеграционные тесты
Время: 1.5 часа
Инструкции:
1. End-to-end тест: отправка сообщения через API
2. Тест: рестарт приложения не теряет данные
3. Тест: webhook дубликаты игнорируются
4. Тест: AntiSpam лимиты работают
```

---

### Фаза 4: Дополнительные задачи (3 часа) - AI АГЕНТЫ

**06:30 - 09:30** | 4 агента параллельно (если фаза 2-3 прошла успешно)

#### 🤖 Agent-DB-2: Session в БД
```
Задача: StringSession → PostgreSQL
Файлы: src/telegram_client.py, src/database.py
Время: 1 час
```

#### 🤖 Agent-Refactor: Code Cleanup
```
Задача: Удалить дубликаты кода
Файлы: src/api_server.py, src/bridge.py
Время: 1 час
```

#### 🤖 Agent-Doc: Documentation Update
```
Задача: Обновить документацию
Файлы: README.md, DEPLOYMENT.md
Время: 1 час
```

#### 🤖 Agent-Config: Docker & Deployment
```
Задача: Обновить docker-compose
Файлы: docker-compose.production.yml
Время: 1 час
- Добавить stop_grace_period: 30s
- Добавить health checks
```

---

### Фаза 5: Testing & Deployment (2 часа) - ЧЕЛОВЕК

**09:30 - 11:30** | Финальное тестирование

#### Manual Testing Checklist:
- [ ] Запустить приложение локально
- [ ] Отправить тестовое сообщение → успех
- [ ] Отправить 100 сообщений → лимиты работают
- [ ] Отправить webhook 5 раз → только 1 обработан
- [ ] Рестарт приложения → данные не потеряны
- [ ] docker stop → graceful shutdown
- [ ] Проверить логи на ошибки

#### Deployment (если есть staging):
- [ ] Deploy на staging
- [ ] Smoke tests
- [ ] Rollback plan готов

---

### Фаза 6: Buffer & Firefighting (0.5 часа)

**11:30 - 12:00** | Исправление критических багов

Резерв времени на непредвиденные проблемы.

---

## ⚠️ ЧТО ТОЧНО НЕ УСПЕЕМ ЗА 12 ЧАСОВ

### Откладываем на потом:

#### ❌ Выкинуто полностью:
1. **Мульти-аккаунты** (задача 2.4) - слишком сложно, 12-15 дней работы
2. **Admin UI** (задача 3.2) - 4-5 дней, не критично
3. **Нагрузочные тесты** (задача 3.3) - требует инфраструктуру
4. **UI в файлы** (задача 2.1) - не критично, 3-4 дня
5. **Polling → SSE** (задача 2.2) - уже работает SSE частично

#### ⏸️ Отложено на следующий спринт:
1. **CI/CD pipeline** - требует GitHub access и время
2. **Staging setup** - требует инфраструктуру
3. **Performance baseline** - можно потом
4. **Security audit** - нужен человек-эксперт
5. **GDPR compliance** - юридический вопрос

#### ⚠️ In-memory → БД (задача 1.2):
**РЕШЕНИЕ: ЧАСТИЧНОЕ ИСПРАВЛЕНИЕ**
- Убрать только критичные in-memory переменные (_auth_phone для 2FA)
- Остальное оставить, но добавить warming при старте из БД
- Полная миграция - следующий спринт (5-7 дней)

---

## 🎯 КРИТЕРИИ УСПЕХА ДЛЯ 12-ЧАСОВОГО СПРИНТА

### Must-Have (без этого НЕ запускать production):
- ✅ FK constraints добавлены → нет orphan записей
- ✅ Webhook idempotency → нет дублей сообщений
- ✅ AntiSpam атомарность → нельзя превысить лимиты
- ✅ Async SQL → нет blocking event loop
- ✅ Graceful shutdown → рестарт безопасен

### Should-Have (желательно, но не критично):
- ✅ Rate limiting API → защита от abuse
- ✅ Session в БД → проще deployment
- ✅ Code refactoring → меньше технического долга
- ✅ Tests → уверенность в изменениях

### Nice-to-Have (бонус):
- ✅ Documentation обновлена
- ✅ Docker config улучшен

---

## 🚨 РИСКИ 12-ЧАСОВОГО СПРИНТА

### Высокие риски:

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| **AI агенты создают конфликты в коде** | Высокая | Четкое разделение файлов, частые merges |
| **Недостаточное тестирование** | Очень высокая | Mandatory manual testing в фазе 5 |
| **Сломается существующая функциональность** | Высокая | Feature flag для новых изменений |
| **Человек-координатор не успевает review** | Средняя | Автоматические pre-commit checks |
| **Отсутствие staging → тестируем на production** | Высокая | Mandatory backup, rollback plan |

### Критические допущения:

1. ✅ **Есть доступ к codebase** (git repo, write access)
2. ✅ **Можно запустить локально** (есть .env, зависимости)
3. ✅ **База данных доступна** (PostgreSQL, Redis)
4. ✅ **Человек-координатор доступен** все 12 часов
5. ⚠️ **Нет staging** - тестируем локально
6. ⚠️ **Нет production deployment** - только код готов

---

## 📊 РЕАЛИСТИЧНАЯ ОЦЕНКА: Что получим через 12 часов

### Оптимистичный сценарий (70% вероятность):
```
✅ 5 критических задач выполнены (FK, webhook, AntiSpam, async SQL, graceful)
✅ 2 дополнительные задачи (rate limiting, session в БД)
✅ Code coverage 70%+
✅ Документация обновлена
✅ Готово к deployment (но deployment не сделан)

Статус: ГОТОВО К PRODUCTION DEPLOYMENT
Риски: Средние (недостаточное тестирование)
```

### Реалистичный сценарий (50% вероятность):
```
✅ 4 критических задачи выполнены (FK, webhook, AntiSpam, async SQL)
⚠️ Graceful shutdown частично (basic implementation)
⚠️ 1 дополнительная задача (rate limiting ИЛИ session)
⚠️ Code coverage 50-60%
❌ Документация не обновлена

Статус: ПОЧТИ ГОТОВО К PRODUCTION
Риски: Высокие (нужно еще 2-4 часа доработки)
```

### Пессимистичный сценарий (20% вероятность):
```
✅ 3 задачи выполнены (FK, webhook, AntiSpam)
⚠️ Async SQL частично (много багов)
❌ Graceful shutdown не сделан
❌ Дополнительные задачи не начаты
⚠️ Code coverage 30-40%

Статус: НЕ ГОТОВО К PRODUCTION
Риски: Критические (нужна еще 1 неделя)
```

---

## 🛠️ ИНСТРУМЕНТЫ ДЛЯ КООРДИНАЦИИ

### Tracking прогресса:

```bash
# Real-time dashboard
watch -n 10 'git log --oneline --since="12 hours ago" | wc -l'

# Checklist в terminal
cat > /tmp/12h-sprint.txt << EOF
[ ] Agent-DB-1: FK constraints (1.5h)
[ ] Agent-API: Webhook idempotency (1h)
[ ] Agent-Perf: Async SQL (2h)
[ ] Agent-Redis: AntiSpam (1.5h)
[ ] Agent-Security: Rate limiting (1h)
[ ] Agent-Ops: Graceful shutdown (2h)
[ ] Code review (2h)
[ ] Testing (2h)
EOF

# Update:
vim /tmp/12h-sprint.txt
```

### Communication protocol для агентов:

```
AGENT ОБЯЗАН:
1. Создать feature branch: feature/agent-{name}-{task}
2. Коммитить каждые 30 минут
3. При проблеме - остановиться и спросить координатора
4. По завершении - создать PR с описанием изменений
5. Указать risk level: LOW / MEDIUM / HIGH
```

---

## 🎬 ФИНАЛЬНЫЕ РЕКОМЕНДАЦИИ

### Перед стартом (критически важно):

1. **✅ Backup БД** - mandatory, если есть production data
2. **✅ Git tag текущей версии** - для быстрого rollback
3. **✅ Проверить все зависимости** - pytest, alembic, etc установлены
4. **✅ Подготовить rollback plan** - если всё пойдет не так
5. **✅ Координатор готов 12 часов** - без перерывов на review

### Во время спринта:

- 🔄 **Review каждые 2 часа** - не ждать конца
- 🚨 **Stop-line на 10 часе** - если не успеваем, откатываем изменения
- 📝 **Документировать все решения** - для будущего
- 🧪 **Тестировать по ходу** - не откладывать на конец

### После спринта:

- 📊 **Post-mortem:** что получилось, что нет
- 📋 **Backlog:** что осталось на следующий раз
- 🚀 **Deployment plan:** когда и как запускать в production
- 🛡️ **Monitoring:** что отслеживать после deployment

---

## 💡 ГЛАВНЫЙ ВЫВОД

### 12 часов с AI агентами ≠ 12 часов человека

**Реально можно сделать:**
- 5-6 изолированных задач параллельно
- ~40-50 эффективных человеко-часов работы
- Много кода, но среднее качество

**НЕ ОЖИДАЙТЕ:**
- Идеальный production-ready код
- Полное тестирование
- Zero bugs
- Архитектурные улучшения

**ОЖИДАЙТЕ:**
- Критические блокеры устранены (70-80%)
- Код работает, но требует review
- Нужно еще 2-4 часа human review
- Deployment возможен, но рискованный

---

## ✅ ФИНАЛЬНЫЙ ЧЕКЛИСТ: ГОТОВЫ К 12-ЧАСОВОМУ СПРИНТУ?

### Подготовка:
- [ ] Git repo доступен, есть write access
- [ ] Локальное окружение работает (docker-compose up)
- [ ] Все зависимости установлены (requirements.txt)
- [ ] База данных пустая ИЛИ есть backup
- [ ] Координатор выделил 12 часов без перерывов
- [ ] План распределения агентов готов
- [ ] Rollback plan написан

### Во время:
- [ ] Каждые 2 часа - checkpoint и review
- [ ] Каждые 4 часа - merge и интеграция
- [ ] На 10 часе - stop/go decision
- [ ] Tracking прогресса в реальном времени

### После:
- [ ] Все изменения в feature branch
- [ ] Manual testing пройден
- [ ] Документация обновлена
- [ ] Deployment plan готов
- [ ] Post-mortem задокументирован

---

**ГОТОВЫ НАЧАТЬ? Let's ship it! 🚀**

*Следующий шаг: Выбрать, какие агенты запустить первыми и дать им детальные инструкции.*

---
---

## 🔬 МЕГА-КРИТИКА 12-ЧАСОВОГО ПЛАНА

### ЧТО МОЖЕТ ПОЙТИ НЕ ТАК (Реальные сценарии провала)

#### Сценарий провала #1: "Merge Hell"
**Проблема:** 6 агентов одновременно изменяют код → конфликты при merge

**Признаки:**
- Agent-DB изменил database.py
- Agent-Perf тоже изменил database.py (для async)
- Конфликты в 50+ строках
- Человек тратит 2 часа на разрешение конфликтов

**Вероятность:** 60-70%

**МИТИГАЦИЯ (добавить в план):**
```
ПРАВИЛО #1: Strict file ownership
- Agent-DB-1: ТОЛЬКО database.py + alembic/
- Agent-API: ТОЛЬКО api_server.py (строки 1789-1832)
- Agent-Perf: ТОЛЬКО telegram_client.py (строки 627-666)
- Agent-Redis: ТОЛЬКО antispam.py
- Agent-Ops: ТОЛЬКО main.py + outbox_worker.py

ПРАВИЛО #2: Lock files
- Агент берет файл → создает .lock файл
- Другие агенты ждут или спрашивают координатора

ПРАВИЛО #3: Merge каждые 90 минут (не в конце!)
- 02:00 - первый merge checkpoint
- 03:30 - второй merge checkpoint
- Конфликты решаются сразу, пока свежие
```

---

#### Сценарий провала #2: "Agent Hallucination"
**Проблема:** AI агент "придумывает" несуществующие функции или API

**Реальный пример:**
```python
# Agent написал:
await telegram_client.send_message_with_retry()  # Функции НЕ СУЩЕСТВУЕТ!

# Правильно:
await telegram_client.send_message()
```

**Вероятность:** 40-50%

**МИТИГАЦИЯ:**
```
ПРАВИЛО #4: Context verification
- Агент ОБЯЗАН сначала прочитать файл
- Агент ОБЯЗАН найти существующие функции
- Агент НЕ МОЖЕТ использовать функции, которых нет в коде

ПРАВИЛО #5: Lint & Type checks перед commit
- mypy --strict src/
- ruff check src/
- pytest tests/unit/ (быстрые тесты)
```

---

#### Сценарий провала #3: "Testing Theater"
**Проблема:** Агент пишет тесты, которые всегда проходят (fake tests)

**Реальный пример:**
```python
# Плохой тест (всегда зеленый):
def test_fk_constraints():
    assert True  # WTF?!

# Хороший тест:
def test_fk_constraints_cascade_delete():
    chat = create_chat()
    message = create_message(chat_id=chat.id)
    delete_chat(chat.id)
    assert get_message(message.id) is None  # Должно быть удалено
```

**Вероятность:** 80% (очень высокая!)

**МИТИГАЦИЯ:**
```
ПРАВИЛО #6: Test quality checklist
Coordinator проверяет каждый тест:
- [ ] Есть arrange/act/assert структура
- [ ] Тест проверяет РЕАЛЬНОЕ поведение (не assert True)
- [ ] Есть negative test (что произойдет при ошибке?)
- [ ] Можно запустить тест изолированно

ПРАВИЛО #7: Mutation testing
- Намеренно сломать код → тест должен упасть
- Если тест все еще зеленый → плохой тест
```

---

#### Сценарий провала #4: "Coordinator Burnout"
**Проблема:** Человек-координатор не успевает review 6 PR одновременно

**Признаки:**
- 04:30 - все агенты закончили
- 6 PR по 200-500 строк каждый
- Coordinator должен review 1500+ строк за 2 часа
- Пропускает критические баги

**Вероятность:** 70-80%

**МИТИГАЦИЯ:**
```
ПРАВИЛО #8: Incremental review
- Не ждать конца, review по ходу
- 01:30 - review первых коммитов (даже незаконченных)
- 03:00 - review почти готовых задач
- 04:30 - финальный review (минимальный)

ПРАВИЛО #9: Automated review first
- GitHub Actions / pre-commit hooks
- Ruff, mypy, pytest автоматически
- Coordinator смотрит только логику, не форматирование

ПРАВИЛО #10: Priority review
- Критические задачи (FK, webhook) - deep review
- Некритические (refactoring) - quick review
```

---

#### Сценарий провала #5: "Integration Surprise"
**Проблема:** Все задачи работают отдельно, но вместе ломаются

**Реальный пример:**
- Agent-DB добавил FK constraint на chat_id
- Agent-Perf изменил логику создания чатов (async)
- При интеграции: FK constraint violation (чат не успел создаться)

**Вероятность:** 60%

**МИТИГАЦИЯ:**
```
ПРАВИЛО #11: Integration tests ОБЯЗАТЕЛЬНЫ
После merge каждого агента:
- Запустить docker-compose up
- Прогнать smoke tests:
  1. Создать чат
  2. Отправить сообщение
  3. Получить webhook
  4. Перезапустить контейнер
  5. Проверить данные на месте

ПРАВИЛО #12: Feature flags
Каждое изменение за feature flag:
ENABLE_FK_CONSTRAINTS=true
ENABLE_ASYNC_SQL=true

Если integration ломается → отключить флаг
```

---

#### Сценарий провала #6: "11th Hour Bug"
**Проблема:** На 11 часе находим критический баг, 1 час до дедлайна

**Реальный пример:**
- 11:00 - финальное тестирование
- Обнаружен: Graceful shutdown ломает outbox worker
- Фикс займет 2-3 часа
- Дедлайн через 1 час

**Вероятность:** 50%

**МИТИГАЦИЯ:**
```
ПРАВИЛО #13: Stop line на 10 часе
10:00 - DECISION POINT:
- Если > 2 критических багов → ROLLBACK всё
- Если 1 критический баг → фикс ИЛИ отключить фичу
- Если 0 багов → продолжить

ПРАВИЛО #14: Rollback procedure готов с начала
00:30 - создать rollback.sh скрипт:
#!/bin/bash
git reset --hard HEAD@{12.hours.ago}
docker-compose down -v
docker-compose up -d
echo "Rollback complete"

ПРАВИЛО #15: Acceptable quality threshold
Лучше 4 качественные задачи, чем 6 кривых
Можно откатить graceful shutdown, если не успели
Must-have: FK + webhook + AntiSpam (всё остальное nice-to-have)
```

---

### КРИТИКА ОЦЕНОК ВРЕМЕНИ (детально)

#### Agent-DB-1: FK Constraints (оценка 1.5ч)

**Оптимистичный сценарий (30% вероятность):**
```
00:30-00:45 (15 мин) - Анализ существующих таблиц
00:45-01:15 (30 мин) - Создание миграции
01:15-01:45 (30 мин) - Тесты
01:45-02:00 (15 мин) - Cleanup orphan записей
ИТОГО: 1.5 часа
```

**Реалистичный сценарий (60% вероятность):**
```
00:30-01:00 (30 мин) - Анализ + чтение кода
01:00-01:45 (45 мин) - Создание миграции + первые баги
01:45-02:15 (30 мин) - Фикс багов в миграции
02:15-03:00 (45 мин) - Тесты + debugging
03:00-03:15 (15 мин) - Cleanup
ИТОГО: 2.75 часа (!!!)
```

**Пессимистичный сценарий (10% вероятность):**
```
Orphan записи ломают миграцию → 4 часа на cleanup → задача провалена
```

**ВЫВОД:** Реальная оценка = **2-3 часа**, не 1.5

---

#### Agent-Perf: Async SQL (оценка 2ч)

**Скрытые сложности:**
1. **Connection pooling** - нужно настроить правильно
2. **Transaction management** - async with db.begin() vs sync
3. **Existing queries** - может быть больше мест, чем строки 627-666
4. **Telethon integration** - async/await может конфликтовать

**Реалистичная оценка:**
```
00:30-01:00 (30 мин) - Аудит всех sync queries (не только 627-666!)
01:00-02:00 (60 мин) - Рефакторинг первой части
02:00-03:00 (60 мин) - Debugging "event loop already running"
03:00-03:30 (30 мин) - Тесты
ИТОГО: 3 часа (!!!)
```

**РИСК:** Может потребовать изменений в других модулях (bridge.py, outbox.py)

**ВЫВОД:** Реальная оценка = **2.5-4 часа**

---

#### Agent-Ops: Graceful Shutdown (оценка 2ч)

**Подводные камни:**
1. **SIGTERM vs SIGKILL** - нужно тестировать оба
2. **Outbox worker** - может обрабатывать сообщение в момент shutdown
3. **Telegram disconnect** - может занять 5-10 секунд
4. **Docker stop timeout** - по умолчанию 10 сек (мало!)

**Реалистичная оценка:**
```
00:30-01:00 (30 мин) - Чтение документации Uvicorn/asyncio signals
01:00-02:00 (60 мин) - Реализация для main.py
02:00-02:30 (30 мин) - Реализация для outbox_worker.py
02:30-03:30 (60 мин) - Тестирование (manual! docker stop в разные моменты)
03:30-04:00 (30 мин) - Фиксы багов
ИТОГО: 3.5 часа (!!!)
```

**ВЫВОД:** Реальная оценка = **3-4 часа**, один из самых сложных

---

### ПЕРЕОЦЕНКА ОБЩЕГО ПЛАНА

#### Исходный план (оптимистичный):
```
Фаза 2: Параллельный запуск    4 часа
Фаза 3: Review & Integration   2 часа
Фаза 4: Дополнительные         3 часа
Фаза 5: Testing                2 часа
Фаза 6: Buffer                 0.5 часа
ИТОГО:                         11.5 часов
```

#### Реалистичный план (с учетом критики):
```
Фаза 2: Параллельный запуск    5-6 часов (!!!)
  - FK constraints: 2.5ч
  - Webhook: 1.5ч
  - Async SQL: 3ч
  - AntiSpam: 2ч
  - Rate limiting: 1ч
  - Graceful: 3.5ч
  (Параллельно 6 агентов, самый долгий = 3.5ч, но с учетом координации = 5-6ч)

Фаза 3: Review & Integration   3-4 часа (!!!)
  - Review: 2ч
  - Merge conflicts: 1ч
  - Integration tests: 1ч

Фаза 4: СКОРЕЕ ВСЕГО НЕ БУДЕТ ВРЕМЕНИ
  - Session в БД: пропускаем
  - Refactoring: пропускаем
  - Documentation: minimal

Фаза 5: Testing                2-3 часа
  - Manual testing: 1.5ч
  - Bug fixes: 1.5ч

Фаза 6: Buffer                 НЕТ (уже потрачен)

ИТОГО:                         10-13 часов (!!!)
```

**ВЫВОД: 12 часов ВПРИТЫК!** Вероятность успеха 50-60%

---

## 🎯 ПЕРЕСМОТРЕННАЯ СТРАТЕГИЯ: REALISTIC 12-HOUR PLAN

### Вариант A: "Safe Bet" (вероятность успеха 80%)

**Делаем ТОЛЬКО must-have задачи:**
1. ✅ FK constraints (3ч)
2. ✅ Webhook idempotency (1.5ч)
3. ✅ AntiSpam atomicity (2ч)
4. ❌ Async SQL - ПРОПУСКАЕМ (слишком рискованно)
5. ❌ Graceful shutdown - ПРОПУСКАЕМ (слишком сложно)
6. ✅ Rate limiting (1ч)

**Timeline:**
```
00:00-00:30: Подготовка
00:30-04:00: 4 агента параллельно (FK, webhook, AntiSpam, rate limit)
04:00-06:00: Review + integration
06:00-08:00: Manual testing + fixes
08:00-10:00: Documentation + deployment prep
10:00-12:00: Buffer для непредвиденного

ИТОГО: 3 критические задачи гарантированно готовы
```

**Что получим:**
- ✅ Целостность данных (FK)
- ✅ Нет дублей (webhook)
- ✅ Нельзя спамить (AntiSpam)
- ✅ API защищен (rate limit)
- ❌ Async SQL остается проблемой (но не критичной)
- ❌ Graceful shutdown нет (но можно без него)

---

### Вариант B: "Ambitious" (вероятность успеха 50%)

**Пытаемся сделать всё из must-have:**
1. ✅ FK constraints (3ч)
2. ✅ Webhook idempotency (1.5ч)
3. ✅ AntiSpam atomicity (2ч)
4. ✅ Async SQL (3ч) - РИСКОВАННО
5. ✅ Graceful shutdown (3.5ч) - ОЧЕНЬ РИСКОВАННО
6. ✅ Rate limiting (1ч)

**Timeline:**
```
00:00-00:30: Подготовка
00:30-06:00: 6 агентов параллельно (5.5ч с координацией)
06:00-09:00: Review + integration + merge hell (3ч)
09:00-11:00: Manual testing + critical fixes (2ч)
11:00-12:00: Emergency fixes ИЛИ rollback

ИТОГО: 5-6 задач, но высокий риск багов
```

**Что может пойти не так:**
- Async SQL ломает Telethon integration
- Graceful shutdown недостаточно протестирован
- Merge conflicts занимают 2+ часа
- На 11 часе критический баг → rollback

---

### Вариант C: "Hybrid Adaptive" (РЕКОМЕНДУЕТСЯ)

**Стратегия:** Начинаем ambitious, но готовы откатить к safe

**00:00-00:30: Подготовка**
- Feature flags для каждой задачи
- Rollback plan готов
- Prioritized backlog

**00:30-05:00: Phase 1 - Core (4.5ч)**
Запускаем 4 агента (safe tasks):
- Agent-DB: FK constraints
- Agent-API: Webhook idempotency
- Agent-Redis: AntiSpam
- Agent-Security: Rate limiting

**05:00-05:30: CHECKPOINT #1 - GO/NO-GO DECISION**
```
IF все 4 задачи готовы И нет критических багов:
  → Запускаем Phase 2 (risky tasks)
ELSE:
  → Фокус на fixing Phase 1
```

**05:30-09:00: Phase 2 - Risky (3.5ч, conditional)**
Запускаем 2 агента (risky tasks):
- Agent-Perf: Async SQL
- Agent-Ops: Graceful shutdown

**09:00-09:30: CHECKPOINT #2 - INTEGRATION TEST**
```
Smoke test всех задач вместе:
IF > 1 критический баг:
  → Откат Phase 2 (отключить feature flags)
  → Deliver только Phase 1
ELSE:
  → Продолжаем
```

**09:30-11:00: Testing & Fixes**

**11:00-12:00: Final decision**
```
IF готовы 4+ задачи без критических багов:
  → SUCCESS
ELSE IF готовы 3 задачи (Phase 1):
  → PARTIAL SUCCESS (acceptable)
ELSE:
  → ROLLBACK всё
```

---

## 📐 МЕТРИКИ УСПЕХА (Измеримые)

### Количественные метрики:

**Must achieve (минимум):**
- ✅ 3+ задачи полностью завершены
- ✅ 0 критических багов (P0)
- ✅ Code coverage ≥ 60%
- ✅ All migrations успешно проходят (up/down)
- ✅ Docker-compose up работает

**Target (цель):**
- ✅ 5+ задач полностью завершены
- ✅ ≤ 2 некритических бага (P1-P2)
- ✅ Code coverage ≥ 70%
- ✅ Manual smoke tests проходят

**Stretch (идеально):**
- ✅ 6 задач + дополнительные (refactoring, docs)
- ✅ 0 багов
- ✅ Code coverage ≥ 80%
- ✅ Automated tests в CI

---

### Качественные метрики:

**Code quality checklist:**
```python
# Каждый PR должен пройти:
- [ ] Ruff linting (0 errors)
- [ ] Mypy type checking (0 errors in changed files)
- [ ] No hardcoded secrets
- [ ] No TODO/FIXME comments (ИЛИ создан ticket)
- [ ] Docstrings для новых функций
- [ ] Error handling есть (try/except где нужно)
```

**Test quality checklist:**
```python
# Для каждой задачи:
- [ ] Unit tests (≥ 1 per новая функция)
- [ ] Integration test (happy path)
- [ ] Negative test (error handling)
- [ ] Test можно запустить изолированно
- [ ] Test имеет assert (не просто assert True)
```

**Documentation checklist:**
```
- [ ] README обновлен (если API изменился)
- [ ] CHANGELOG запись добавлена
- [ ] Migration guide (если breaking changes)
- [ ] Inline comments для сложной логики
```

---

## 🚨 EMERGENCY PROCEDURES

### Emergency #1: "Agent Stuck" (Агент зависает)

**Признаки:**
- Агент не коммитит 60+ минут
- Нет ответа на вопросы
- Логи показывают бесконечный loop

**Процедура:**
```
1. STOP агента немедленно
2. Review код, который успел написать
3. DECISION:
   a) Код спасаем → человек дописывает (1-2ч)
   b) Код выбрасываем → перезапуск агента с новой инструкцией
   c) Задача слишком сложна → cancel, focus на других
```

---

### Emergency #2: "Critical Bug in Production Code"

**Признаки:**
- Агент изменил файл, который сломал запуск приложения
- docker-compose up падает с ошибкой
- Импорты сломаны

**Процедура:**
```
1. ROLLBACK конкретного файла:
   git checkout HEAD -- src/broken_file.py

2. Заблокировать агента от этого файла

3. Human fix ИЛИ restart агента с жестким constraint:
   "DO NOT MODIFY IMPORTS"
   "DO NOT RENAME FUNCTIONS"
```

---

### Emergency #3: "Merge Conflict Hell"

**Признаки:**
- 3+ агента изменили один файл
- Git показывает 100+ строк конфликтов
- Не понятно, какую версию оставить

**Процедура:**
```
1. STOP все агенты

2. Manual conflict resolution:
   - Человек читает оба варианта
   - Выбирает лучший ИЛИ комбинирует
   - 30-60 минут на файл

3. Если > 3 файлов с конфликтами:
   → ROLLBACK всех изменений в этом файле
   → Один агент переделывает с нуля
```

---

### Emergency #4: "Time Running Out"

**Признаки:**
- 10:00 на часах
- Осталось 2 часа
- Не все задачи готовы

**Процедура:**
```
TRIAGE:

P0 (must ship):
  - FK constraints
  - Webhook idempotency
  - AntiSpam atomicity

P1 (nice to have):
  - Rate limiting
  - Async SQL

P2 (can skip):
  - Graceful shutdown
  - Refactoring
  - Documentation

DECISION TREE:
IF все P0 готовы:
  → Ship P0, откатить P1/P2 если не готовы

IF хотя бы 1 P0 не готов:
  → ALL HANDS на этот P0
  → Откатить все остальное
```

---

## 🎓 LESSONS LEARNED (Прогнозируемые)

### Что мы узнаем через 12 часов:

**Технические уроки:**
1. AI агенты эффективны для **изолированных задач** (FK, webhook)
2. AI агенты плохи для **интеграционных задач** (async SQL с Telethon)
3. **Testing - слабое место AI** (нужен человек-review)
4. **Merge conflicts - biggest time sink** (нужна лучшая координация)

**Процессные уроки:**
1. **Checkpoints каждые 2 часа** - критически важны
2. **Feature flags** - спасают от rollback'а всего
3. **Rollback plan с начала** - обязателен
4. **Stop-line на 10 часе** - нужна дисциплина

**Человеческий фактор:**
1. **Coordinator burnout** - реальная проблема (нужны перерывы)
2. **Decision fatigue** - к 8 часу решения медленнее
3. **Optimism bias** - думаем успеем больше, чем реально

---

## 💰 COST-BENEFIT ANALYSIS

### Стоимость 12-часового спринта:

**Human time:**
- Coordinator: 12 часов × $50-100/час = **$600-1200**
- Post-sprint cleanup: 4 часа × $50-100/час = **$200-400**

**AI time:**
- 6 агентов × 4 часа активной работы × $0.10/1K tokens
- Оценка: ~500K tokens × $0.10 = **$50-100**

**Infrastructure:**
- Staging environment: $0 (локально)
- CI/CD: $0 (если есть GitHub Actions)

**TOTAL: $850-1700**

---

### ROI (Return on Investment):

**Без 12-часового спринта (альтернатива):**
- Human developer: 15-20 дней × 8 часов × $50-100/час = **$6,000-16,000**
- Timeline: 3-4 недели calendar time

**С 12-часовым спринтом:**
- Cost: $850-1700
- Timeline: 1 день (+ 1-2 дня cleanup)
- **Savings: $5,000-14,000**
- **Time savings: 2-3 недели**

**НО:**
- Quality risk: Средний (нужен human review)
- Technical debt: Вероятен (код не идеальный)
- Follow-up work: 1-2 дня cleanup

**VERDICT: Экономически выгодно, если:**
- ✅ Нужно быстро (time-to-market критичен)
- ✅ Есть human coordinator (senior dev)
- ✅ Acceptable 70-80% quality (не критичная система)
- ❌ НЕ выгодно для: medical, financial, safety-critical систем

---

## 🎬 ФИНАЛЬНЫЕ КОРРЕКТИРОВКИ ПЛАНА

### Что ДОБАВИТЬ в план:

#### 1. Pre-flight checklist (расширенный):
```bash
# 00:00 - Coordinator запускает:
./scripts/pre_flight_check.sh

Checklist:
- [ ] Git repo clean (no uncommitted changes)
- [ ] Docker-compose up работает
- [ ] Все тесты проходят (baseline)
- [ ] DB backup создан
- [ ] Rollback script протестирован (dry-run)
- [ ] Feature flags настроены
- [ ] Monitoring dashboard открыт
```

#### 2. Agent instruction template:
```markdown
# Agent: {NAME}
# Task: {DESCRIPTION}
# Time budget: {HOURS}
# Priority: P0/P1/P2

## FILES YOU CAN MODIFY:
- {list of files}

## FILES YOU CANNOT TOUCH:
- {list of files}

## SUCCESS CRITERIA:
- [ ] {criterion 1}
- [ ] {criterion 2}

## TESTS REQUIRED:
- [ ] Unit test: {description}
- [ ] Integration test: {description}

## COMMIT FREQUENCY:
Every 30 minutes OR when logical chunk is done

## WHEN TO ASK FOR HELP:
- Stuck > 20 minutes
- Need to modify locked file
- Breaking change required

## OUTPUT FORMAT:
1. Create branch: feature/agent-{name}-{task}
2. Commit with prefix: [AGENT-{NAME}] {message}
3. Final PR with:
   - Summary of changes
   - Risk level: LOW/MEDIUM/HIGH
   - Test results
   - Known issues (if any)
```

#### 3. Checkpoint protocol:
```
CHECKPOINT TIMES:
02:00, 04:00, 06:00, 08:00, 10:00

AT EACH CHECKPOINT:
1. All agents commit current state (even if unfinished)
2. Coordinator reviews:
   - Progress (on track / behind / ahead)
   - Blockers (any?)
   - Conflicts (any?)
3. DECISION:
   - Continue as planned
   - Adjust scope (drop tasks)
   - Reallocate agents

CHECKPOINT TEMPLATE:
Hour: {TIME}
Progress: {GREEN/YELLOW/RED}
Completed: {N} / {TOTAL} tasks
Blockers: {list}
Decision: {continue/adjust/abort}
```

---

## ✅ ОБНОВЛЕННЫЙ ФИНАЛЬНЫЙ ЧЕКЛИСТ

### Pre-Sprint (30 минут до старта):
- [ ] Human coordinator: кофе/еда на 12 часов готовы
- [ ] Телефон на беззвучном (никаких отвлечений)
- [ ] Slack/email закрыты (только emergency)
- [ ] Second monitor setup (код + dashboard)
- [ ] Git graph visualizer открыт (для отслеживания веток)
- [ ] Timer на каждые 2 часа (checkpoint reminder)

### Hour 0-2:
- [ ] 6 агентов запущены с четкими инструкциями
- [ ] Каждый агент сделал первый коммит (proof of life)
- [ ] Coordinator: track прогресса в spreadsheet
- [ ] No blockers на 01:00 mark

### Hour 2-4:
- [ ] Checkpoint #1 passed
- [ ] No merge conflicts (if any - resolved)
- [ ] At least 2 задачи на 80%+ completion
- [ ] Integration test setup готов

### Hour 4-6:
- [ ] Checkpoint #2 passed
- [ ] Core tasks (FK, webhook, AntiSpam) завершены
- [ ] First integration test прошел
- [ ] Code review начат

### Hour 6-8:
- [ ] Checkpoint #3 passed
- [ ] All agents finished OR stopped (no running tasks)
- [ ] Feature branch merged (all agents)
- [ ] Integration tests проходят

### Hour 8-10:
- [ ] Checkpoint #4 passed
- [ ] Manual testing начат
- [ ] Critical bugs (if any) в triage
- [ ] Documentation началась

### Hour 10-12:
- [ ] FINAL checkpoint
- [ ] GO/NO-GO decision made
- [ ] If GO: deployment prep done
- [ ] If NO-GO: rollback executed
- [ ] Post-mortem notes started

---

## 🏁 ИТОГОВЫЕ ВЫВОДЫ

### 12-часовой спринт ВОЗМОЖЕН, если:

**✅ ДА, делаем:**
1. Есть опытный human coordinator (senior+ level)
2. Цель: исправить 3-5 критических багов (не архитектурный рефакторинг)
3. Codebase знаком (не первый раз видим)
4. Задачи изолированы (минимум зависимостей)
5. Acceptable риск 20-30% (не production-critical система)

**❌ НЕТ, не делаем:**
1. Coordinator junior/middle level
2. Цель: большой рефакторинг или новая фича
3. Codebase незнаком
4. Задачи сильно связаны
5. Zero tolerance к багам (medical, financial)

---

### Realistic expectations:

**Что ТОЧНО получим:**
- ✅ 3-4 критические задачи решены
- ✅ Code работает (но не идеально)
- ✅ Tests есть (но coverage 60-70%, не 100%)
- ✅ Готово к staging deployment

**Что ВЕРОЯТНО получим:**
- ⚠️ 5-6 задач решены
- ⚠️ 1-2 некритичных бага
- ⚠️ Technical debt (надо будет почистить)

**Что НЕ ПОЛУЧИМ:**
- ❌ Production-ready без human review
- ❌ 100% test coverage
- ❌ Perfect code quality
- ❌ Full documentation

---

### The brutal truth:

```
12 часов с AI агентами =
  ~50-60 эффективных человеко-часов работы
  НО с coordination overhead 30-40%
  = ~30-40 полезных человеко-часов

Это примерно 1 неделя работы одного сеньора (40h)
Сжатая в 12 часов

Цена: stress, риски, технический долг
Выгода: скорость, cost savings

Worth it? DEPENDS ON YOUR CONTEXT
```

---

**ФИНАЛЬНЫЙ ВОПРОС:** Готовы ли вы рискнуть?

Если ДА → переходим к запуску агентов
Если НЕТ → планируем более консервативный подход (2-3 дня с меньшим риском)
