# Contact Manager - Потенциальные проблемы и рекомендации

## ⚠️ КРИТИЧЕСКИЕ ПРОБЛЕМЫ

### 1. Race Condition в Circuit Breaker (ВЫСОКИЙ ПРИОРИТЕТ)

**Проблема:** Методы Circuit Breaker НЕ защищены блокировкой, только `add_to_contacts_with_protection` использует lock.

**Файл:** `src/contact_manager.py:78-93`

```python
def is_open(self) -> bool:
    if self._state == "OPEN":
        if self._cooldown_until and datetime.utcnow() >= self._cooldown_until:
            self._state = "HALF_OPEN"  # ⚠️ ЗАПИСЬ БЕЗ БЛОКИРОВКИ
            self._failure_count = 0
            return False
        return True
    return False
```

**Сценарий проблемы:**
- Корутина A вызывает `is_open()`, читает `_state = "OPEN"`
- Корутина B одновременно вызывает `is_open()`, читает `_state = "OPEN"`
- Обе пытаются изменить `_state` на "HALF_OPEN" одновременно

**Последствия:**
- Неконсистентное состояние Circuit Breaker
- Возможность пропустить операции когда circuit должен быть открыт
- Некорректный подсчет в `_recent_adds`

**Решение:**
```python
# Вариант 1: Защитить все методы блокировкой (медленнее)
async def is_open(self) -> bool:
    async with self._lock:
        if self._state == "OPEN":
            ...

# Вариант 2: Использовать threading.Lock для sync методов (быстрее)
from threading import Lock

class ContactAddCircuitBreaker:
    def __init__(self):
        self._lock = Lock()
        ...

    def is_open(self) -> bool:
        with self._lock:
            if self._state == "OPEN":
                ...
```

**Рекомендация:** Использовать `threading.Lock` т.к. методы синхронные.

---

### 2. Database Connection Pool Exhaustion (ВЫСОКИЙ ПРИОРИТЕТ)

**Проблема:** Множественные DB сессии открываются последовательно в одном методе.

**Файл:** `src/contact_manager.py:226-320`

```python
async def can_add_contact(self, direction: str, telegram_user_id: int):
    # Сессия 1
    async with SessionLocal() as db:
        existing = await db.execute(...)  # Query 1
        if existing.scalars().first():
            return True, "already_in_contacts"

        # Query 2
        hour_result = await db.execute(...)

        # Query 3
        day_result = await db.execute(...)
```

**Проблема:** При 100 одновременных входящих сообщениях = 100 DB сессий открыты одновременно.

**Последствия:**
- Исчерпание connection pool (по умолчанию ~20 connections)
- `sqlalchemy.exc.TimeoutError: QueuePool limit exceeded`
- Зависание всех операций

**Решение:**
```python
async def can_add_contact(self, direction: str, telegram_user_id: int):
    # Использовать ОДНУ сессию для всех queries
    async with SessionLocal() as db:
        # Query 1
        existing = await db.execute(...)
        if existing.scalars().first():
            return True, "already_in_contacts"

        # Query 2 (в той же сессии)
        hour_result = await db.execute(...)

        # Query 3 (в той же сессии)
        day_result = await db.execute(...)

        return True, "ok"
```

**Рекомендация:** Одна сессия на метод, все queries внутри одного контекста.

---

### 3. Блокировка на 5+ секунд (ВЫСОКИЙ ПРИОРИТЕТ)

**Проблема:** Lock удерживается во время долгих операций.

**Файл:** `src/contact_manager.py:364-381`

```python
async with self._lock:  # ⚠️ БЛОКИРОВКА НА 5+ СЕКУНД!
    can_add, reason = await self.can_add_contact(...)  # DB queries

    if reason == "already_in_contacts":
        sender = await asyncio.wait_for(
            client.get_entity(telegram_user_id),
            timeout=5.0  # ⚠️ ДО 5 СЕКУНД С БЛОКИРОВКОЙ!
        )
```

**Последствия:**
- Все другие вызовы `add_to_contacts_with_protection` ждут 5+ секунд
- При 10 одновременных входящих сообщениях = 50+ секунд ожидания
- Пользователи не получат ответ вовремя

**Решение:**
```python
# Проверки БЕЗ блокировки
can_add, reason = await self.can_add_contact(...)

if not can_add:
    return False, None

if reason == "already_in_contacts":
    # БЕЗ блокировки - это read-only операция
    sender = await asyncio.wait_for(
        client.get_entity(telegram_user_id),
        timeout=5.0
    )
    return True, phone_number

# Блокировка ТОЛЬКО для критической секции (добавление контакта)
async with self._lock:
    # Повторная проверка (double-checked locking)
    can_add, reason = await self.can_add_contact(...)
    if not can_add:
        return False, None

    self.circuit_breaker.record_add_attempt()

    # Добавление с timeout
    result = await asyncio.wait_for(...)
```

**Рекомендация:** Минимизировать время удержания блокировки.

---

### 4. Отсутствие обработки DB errors (СРЕДНИЙ ПРИОРИТЕТ)

**Проблема:** Нет try/except для DB операций.

**Файл:** `src/contact_manager.py:418-426, 450-458, 491-500`

```python
# SUCCESS - log to database
async with SessionLocal() as db:
    log_entry = ContactAddLog(...)  # ⚠️ Что если DB недоступна?
    db.add(log_entry)
    await db.commit()  # ⚠️ Может упасть с OperationalError
```

**Последствия:**
- Если PostgreSQL недоступен, exception прервет обработку сообщения
- Пользователь не получит ответ
- Circuit Breaker не обновится

**Решение:**
```python
try:
    async with SessionLocal() as db:
        log_entry = ContactAddLog(...)
        db.add(log_entry)
        await db.commit()
except Exception as e:
    logger.error(f"❌ Failed to log to database: {e}")
    # Продолжаем работу даже если лог не записался
```

**Рекомендация:** Обернуть все DB операции в try/except.

---

### 5. Необработанный exception в telegram_client.py (ВЫСОКИЙ ПРИОРИТЕТ)

**Проблема:** Если `contact_manager.add_to_contacts_with_protection()` упадет, вся обработка входящего сообщения остановится.

**Файл:** `src/telegram_client.py:1177-1193`

```python
if not phone_number and sender.username:
    from src.contact_manager import contact_manager

    success, phone_number = await contact_manager.add_to_contacts_with_protection(...)
    # ⚠️ Если exception - сообщение не обработается!
```

**Последствия:**
- Пользователь отправил сообщение, но система его не обработала
- CRM не получил уведомление
- Плохой UX

**Решение:**
```python
if not phone_number and sender.username:
    try:
        from src.contact_manager import contact_manager

        success, phone_number = await contact_manager.add_to_contacts_with_protection(...)

        if success and phone_number:
            logger.info(f"✅ Телефон получен: {phone_number}")
        elif success:
            logger.info("ℹ️ Контакт добавлен, но телефон скрыт")
        else:
            logger.warning("⚠️ Не удалось добавить контакт")

    except Exception as e:
        logger.error(f"❌ Ошибка Contact Manager: {e}", exc_info=True)
        # Продолжаем обработку сообщения БЕЗ телефона
        phone_number = None
```

**Рекомендация:** Добавить try/except и продолжить обработку без phone.

---

## ⚠️ ПРОБЛЕМЫ СРЕДНЕЙ ВАЖНОСТИ

### 6. Утечка памяти в _recent_adds

**Проблема:** Список `_recent_adds` очищается только при вызове `check_burst_limit()`.

**Файл:** `src/contact_manager.py:108-109`

```python
self._recent_adds = [ts for ts in self._recent_adds if ts > minute_ago]
```

**Сценарий:**
- Circuit Breaker открывается
- `check_burst_limit()` не вызывается 1 час
- `_recent_adds` содержит старые записи (memory leak)

**Решение:**
```python
def record_add_attempt(self):
    """Record an addition attempt (for burst detection)."""
    now = datetime.utcnow()

    # Cleanup old entries (> 60 seconds)
    minute_ago = now - timedelta(seconds=60)
    self._recent_adds = [ts for ts in self._recent_adds if ts > minute_ago]

    # Add new entry
    self._recent_adds.append(now)
```

**Рекомендация:** Очищать при каждом `record_add_attempt()`.

---

### 7. Отсутствие retention policy для contact_add_log

**Проблема:** Таблица `contact_add_log` растет бесконечно.

**Последствия:**
- Медленные queries через год работы
- Большой размер БД

**Решение:**
Добавить в `src/retention.py`:
```python
async def cleanup_contact_add_log(db: AsyncSession, days: int):
    """Delete contact addition logs older than N days."""
    if days <= 0:
        return 0

    cutoff = datetime.utcnow() - timedelta(days=days)
    result = await db.execute(
        delete(ContactAddLog).where(ContactAddLog.created_at < cutoff)
    )
    await db.commit()
    return result.rowcount
```

В `.env`:
```bash
CONTACT_ADD_LOG_RETENTION_DAYS=90  # 3 месяца
```

**Рекомендация:** Retention 90 дней.

---

### 8. Отсутствие проверки client.connected

**Проблема:** Telegram client может быть disconnected.

**Файл:** `src/contact_manager.py:396-405`

```python
result = await asyncio.wait_for(
    client(functions.contacts.AddContactRequest(...)),  # ⚠️ client может быть disconnected
    timeout=10.0
)
```

**Решение:**
```python
# Проверка перед вызовом
if not client.is_connected():
    logger.error("❌ Telegram client not connected")
    return False, None

result = await asyncio.wait_for(
    client(functions.contacts.AddContactRequest(...)),
    timeout=10.0
)
```

**Рекомендация:** Проверять `client.is_connected()` перед операциями.

---

### 9. Неэффективный query для "already_in_contacts"

**Проблема:** Загружает ВСЕ записи для user_id.

**Файл:** `src/contact_manager.py:261-270`

```python
existing = await db.execute(
    select(ContactAddLog).where(...)  # ⚠️ Может вернуть тысячи записей
)
if existing.scalars().first():
    return True, "already_in_contacts"
```

**Решение:**
```python
existing = await db.execute(
    select(ContactAddLog)
    .where(
        and_(
            ContactAddLog.telegram_user_id == telegram_user_id,
            ContactAddLog.success == True
        )
    )
    .limit(1)  # ✅ ТОЛЬКО ОДНА ЗАПИСЬ
)
if existing.scalars().first():
    return True, "already_in_contacts"
```

**Рекомендация:** Добавить `.limit(1)` для всех проверок существования.

---

### 10. Timezone-naive datetime

**Проблема:** `datetime.utcnow()` без timezone info.

**Файл:** Везде где используется `datetime.utcnow()`

**Последствия:**
- PostgreSQL хранит timestamp WITH timezone
- Сравнения могут быть неточными

**Решение:**
```python
from datetime import datetime, timezone

# Вместо:
now = datetime.utcnow()

# Использовать:
now = datetime.now(timezone.utc)
```

**Рекомендация:** Использовать timezone-aware datetime.

---

### 11. Нет rate limiting на /api/admin/contact-health

**Проблема:** Endpoint может быть использован для DoS.

**Файл:** `src/api_server.py`

**Решение:**
```python
from fastapi import Depends
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.get("/api/admin/contact-health")
@limiter.limit("10/minute")  # ✅ Макс 10 запросов в минуту
async def admin_contact_health(
    request: Request,
    ui_user: dict = Depends(require_admin)
):
    ...
```

**Рекомендация:** Добавить rate limiting.

---

## 📊 РЕКОМЕНДАЦИИ ПО ПРИОРИТЕТАМ

### Срочно (исправить до production):
1. ✅ **#5 - Exception handling в telegram_client.py** (15 минут)
2. ✅ **#4 - DB error handling** (30 минут)
3. ✅ **#1 - Race condition в Circuit Breaker** (1 час)

### Важно (исправить в течение недели):
4. ✅ **#3 - Блокировка на 5+ секунд** (1 час)
5. ✅ **#2 - Connection pool exhaustion** (30 минут)
6. ✅ **#9 - Неэффективные queries** (15 минут)

### Желательно (можно отложить):
7. ⏳ **#7 - Retention policy** (1 час)
8. ⏳ **#6 - Утечка памяти** (15 минут)
9. ⏳ **#8 - Проверка client.connected** (15 минут)
10. ⏳ **#10 - Timezone-aware datetime** (30 минут)
11. ⏳ **#11 - Rate limiting на endpoint** (30 минут)

---

## 🧪 Тестирование

### Нагрузочное тестирование:
```python
# Симуляция 100 одновременных входящих сообщений
async def test_concurrent_messages():
    tasks = []
    for i in range(100):
        task = contact_manager.add_to_contacts_with_protection(
            client=client,
            telegram_user_id=10000 + i,
            first_name=f"User{i}",
            last_name=None,
            username=f"user{i}",
            direction='inbound',
            source='test'
        )
        tasks.append(task)

    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Проверить на exceptions
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            print(f"Task {i} failed: {result}")
```

### Тест DB недоступности:
```python
# Остановить PostgreSQL и проверить что система продолжает работать
async def test_db_unavailable():
    # Stop PostgreSQL
    # os.system("docker stop postgres")

    success, phone = await contact_manager.add_to_contacts_with_protection(...)

    # Должно вернуть False, но НЕ упасть
    assert success == False or success == True  # Любой результат OK
```

---

## 📝 Итоговая оценка

**Общая оценка:** 7/10

**Сильные стороны:**
- ✅ Хорошая архитектура (Circuit Breaker + Rate Limiting)
- ✅ Comprehensive logging
- ✅ Audit trail в БД
- ✅ Отличное покрытие тестами (16/16)

**Слабые стороны:**
- ⚠️ Race conditions в concurrent environment
- ⚠️ Недостаточная обработка DB errors
- ⚠️ Блокировки на долгих операциях

**Готовность к production:**
- **Development:** ✅ Готово
- **Staging:** ⚠️ После исправления #1-#6
- **Production:** ❌ Требует исправления критических проблем

**ETA для production-ready:** 4-6 часов работы
