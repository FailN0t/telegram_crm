# Contact Manager - Новые проблемы после исправлений

**Дата:** 2026-01-20
**Статус:** 🔴 КРИТИЧЕСКАЯ ПРОБЛЕМА НАЙДЕНА

---

## 🚨 КРИТИЧЕСКАЯ ПРОБЛЕМА #1: threading.Lock в async коде

### Обнаруженная проблема

**Файл:** [src/contact_manager.py](src/contact_manager.py:84)

```python
from threading import Lock  # ← СИНХРОННЫЙ lock

class ContactAddCircuitBreaker:
    def __init__(self):
        self._lock = Lock()  # ← threading.Lock (БЛОКИРУЕТ THREAD!)

    def is_open(self) -> bool:
        with self._lock:  # ← Блокирует весь event loop!
            ...
```

**НО:** Circuit Breaker вызывается из **async** контекста!

```python
class ContactManager:
    def __init__(self):
        self._lock = asyncio.Lock()  # ← ContactManager правильно использует asyncio.Lock

    async def can_add_contact(...):
        # Вызывает Circuit Breaker (threading.Lock) из async кода!
        if self.circuit_breaker.is_open():  # ← БЛОКИРУЕТ EVENT LOOP!
            ...
```

### Почему это критично?

1. **Event Loop Blocking:**
   - `threading.Lock` блокирует **thread**, а не только coroutine
   - В async/await коде это **замораживает весь event loop**
   - Все другие async операции ждут, пока lock не освободится

2. **Cascade Failure:**
   ```
   Request 1: Ждет threading.Lock → Event loop заблокирован
   Request 2: Не может начаться (event loop frozen)
   Request 3: Не может начаться (event loop frozen)
   ...
   Request 100: Все зависли
   ```

3. **Performance Degradation:**
   - При 10 concurrent requests → 10x медленнее
   - При 100 concurrent requests → полный deadlock

### Сценарий воспроизведения

```python
# Тест на блокировку event loop
import asyncio

async def test_concurrent_checks():
    tasks = []
    for i in range(100):
        task = contact_manager.add_to_contacts_with_protection(...)
        tasks.append(task)

    # BUG: threading.Lock блокирует event loop
    # Вместо parallel execution → sequential execution
    results = await asyncio.gather(*tasks)

# Ожидаемое время: ~10 секунд (parallel)
# Реальное время: ~1000 секунд (sequential из-за threading.Lock)
```

### Решение

**Заменить `threading.Lock` на `asyncio.Lock` и сделать методы async:**

```python
import asyncio  # Вместо from threading import Lock

class ContactAddCircuitBreaker:
    def __init__(self):
        self._lock = asyncio.Lock()  # ← Async lock

    async def is_open(self) -> bool:  # ← async method
        async with self._lock:
            ...

    async def check_burst_limit(self) -> Tuple[bool, str]:  # ← async
        async with self._lock:
            ...

    async def record_add_attempt(self):  # ← async
        async with self._lock:
            ...

    async def record_success(self):  # ← async
        async with self._lock:
            ...

    async def record_failure(self, reason: str):  # ← async
        async with self._lock:
            ...
```

**И обновить все вызовы на await:**

```python
class ContactManager:
    async def can_add_contact(...):
        # Было:
        if self.circuit_breaker.is_open():

        # Стало:
        if await self.circuit_breaker.is_open():
```

### Severity: 🔴 CRITICAL

- Блокирует event loop
- Деградация performance при concurrent requests
- Может вызвать deadlock

---

## ⚠️ ВЫСОКАЯ ПРОБЛЕМА #2: Повторные DB queries при double-checked locking

### Обнаруженная проблема

**Файл:** [src/contact_manager.py](src/contact_manager.py:360-397)

```python
async def add_to_contacts_with_protection(...):
    # 1. Первый вызов (БЕЗ lock)
    can_add, reason = await self.can_add_contact(...)  # ← 3 DB queries

    # 2. Взятие lock
    async with self._lock:
        # 3. Повторный вызов (С lock) - double-checked locking
        can_add_recheck, _ = await self.can_add_contact(...)  # ← ЕЩЕ 3 DB queries
```

**Итого:** 6 DB queries вместо 3

### Почему это проблема?

1. **При 100 concurrent requests:**
   - Без double-checked: 300 queries
   - С double-checked: **600 queries** (2x нагрузка!)

2. **Connection Pool Exhaustion (опять!):**
   - Каждый request делает 2x queries
   - Pool может исчерпаться даже с нашими исправлениями

3. **Latency:**
   - Дополнительные 50-100ms на повторные queries

### Решение

**Вариант 1:** Использовать cached результат

```python
async def add_to_contacts_with_protection(...):
    # 1. Первая проверка
    can_add, reason = await self.can_add_contact(...)

    if not can_add:
        return False, None

    # 2. В lock - проверяем только изменившиеся условия
    async with self._lock:
        # Проверяем только burst limit (быстро, без DB)
        can_burst, burst_reason = await self.circuit_breaker.check_burst_limit()
        if not can_burst:
            return False, None

        # Circuit breaker state (быстро, без DB)
        if await self.circuit_breaker.is_open():
            return False, "circuit_breaker_open"

        # Продолжаем с добавлением...
```

**Вариант 2:** Оптимистичная блокировка (рекомендуется)

```python
# Убрать double-checked locking вообще
# Риск race condition минимален т.к. limits достаточно большие
```

### Severity: ⚠️ HIGH

- 2x DB queries
- Connection pool exhaustion risk
- Performance degradation

---

## ⚠️ СРЕДНЯЯ ПРОБЛЕМА #3: Privacy errors не логируются

### Обнаруженная проблема

**Файл:** [src/contact_manager.py](src/contact_manager.py:477-482)

```python
elif "user_privacy" in error_str or "privacy" in error_str:
    # Not an error - just privacy settings
    logger.info(f"ℹ️ User denied contact addition")
    # DON'T count this as failure for circuit breaker

# Log failure to database
try:
    async with SessionLocal() as db:
        ...  # ← НО для privacy errors тоже нужен лог!
```

**Проблема:** Privacy errors НЕ логируются в `contact_add_log`

### Почему это проблема?

1. **Неполная статистика:**
   - Сколько users скрыли phone? → Неизвестно
   - Success rate неточный

2. **Дублирующиеся попытки:**
   - can_add_contact() не знает что user уже был rejected
   - Будет пытаться добавить снова и снова

### Решение

```python
elif "user_privacy" in error_str or "privacy" in error_str:
    logger.info(f"ℹ️ User denied contact addition")
    # DON'T count as failure for circuit breaker

    # BUT log to DB for statistics
    try:
        async with SessionLocal() as db:
            log_entry = ContactAddLog(
                telegram_user_id=telegram_user_id,
                direction=direction,
                source=source,
                success=False  # или можно добавить отдельное поле privacy_denied
            )
            db.add(log_entry)
            await db.commit()
    except Exception as db_error:
        logger.error(f"❌ Failed to log privacy denial: {db_error}")

    return False, None
```

### Severity: 🟡 MEDIUM

---

## ⚠️ СРЕДНЯЯ ПРОБЛЕМА #4: client.is_connected() TOCTOU race

### Обнаруженная проблема

**Файл:** [src/contact_manager.py](src/contact_manager.py:354-357)

```python
# 1. Check client is connected
if not client.is_connected():
    logger.error("❌ Telegram client not connected")
    return False, None

# ... много кода ...

# 2. Вызов API (client может уже disconnected!)
result = await client(functions.contacts.AddContactRequest(...))
```

**TOCTOU (Time-of-check to time-of-use) race condition:**
- Проверяем в строке 355
- Используем в строке 447 (спустя много операций)
- Между ними client может disconnect

### Почему это проблема?

1. **False sense of security:**
   - Проверка дает false positive
   - API call может упасть с ConnectionError

2. **Unhandled exception (частично):**
   - Есть общий `except Exception`, но не специфичный для disconnect

### Решение

**Вариант 1:** Проверка прямо перед API вызовом

```python
async with self._lock:
    # ... другие проверки ...

    # Проверка непосредственно перед вызовом
    if not client.is_connected():
        logger.error("❌ Client disconnected before API call")
        return False, None

    result = await asyncio.wait_for(
        client(functions.contacts.AddContactRequest(...)),
        timeout=10.0
    )
```

**Вариант 2:** Специфичный exception handling

```python
except (ConnectionError, OSError) as e:
    logger.error(f"❌ Client disconnected during API call: {e}")
    self.circuit_breaker.record_failure("client_disconnected")
    # ... log to DB ...
    return False, None
```

### Severity: 🟡 MEDIUM

---

## 📊 ИТОГОВАЯ ОЦЕНКА ПОСЛЕ ОБНАРУЖЕНИЯ НОВЫХ ПРОБЛЕМ

### До новых проблем:
```
Contact Manager: 9.5/10 (production-ready)
```

### После обнаружения:
```
Contact Manager: 7/10 (staging-ready, НЕ production-ready)

БЛОКЕРЫ для production:
- #1: threading.Lock в async коде (CRITICAL)
```

---

## 🚀 ПЛАН ИСПРАВЛЕНИЯ

### Критично (немедленно):
1. ✅ Заменить `threading.Lock` на `asyncio.Lock` в Circuit Breaker
2. ✅ Сделать все методы Circuit Breaker async
3. ✅ Обновить все вызовы на await

### Важно (до production):
4. ⚠️ Оптимизировать double-checked locking (убрать повторные DB queries)
5. ⚠️ Логировать privacy errors в БД

### Желательно (можно отложить):
6. 🟡 Проверка client.is_connected() перед API вызовом
7. 🟡 Специфичный exception handling для disconnect

---

## 🧪 ТЕСТИРОВАНИЕ

### Тест #1: Event Loop Blocking

```python
import asyncio
import time

async def test_concurrent_circuit_breaker():
    start = time.time()

    # 100 concurrent checks
    tasks = [
        contact_manager.circuit_breaker.is_open()
        for _ in range(100)
    ]

    await asyncio.gather(*tasks)

    elapsed = time.time() - start

    # С threading.Lock: ~1 секунда (sequential)
    # С asyncio.Lock: ~0.01 секунды (parallel)
    assert elapsed < 0.1, f"Event loop blocking detected! {elapsed}s"
```

### Тест #2: Connection Pool

```python
async def test_connection_pool_exhaustion():
    # 50 concurrent requests с double-checked locking
    tasks = [
        contact_manager.add_to_contacts_with_protection(...)
        for _ in range(50)
    ]

    # Должно успешно выполниться без ошибок pool exhaustion
    results = await asyncio.gather(*tasks, return_exceptions=True)

    errors = [r for r in results if isinstance(r, Exception)]
    pool_errors = [e for e in errors if "QueuePool" in str(e)]

    assert len(pool_errors) == 0, f"Pool exhaustion: {pool_errors}"
```

---

*Обнаружено: 2026-01-20*
*Проблем: 4 (1 CRITICAL, 1 HIGH, 2 MEDIUM)*
*Статус: Требует исправления перед production*
