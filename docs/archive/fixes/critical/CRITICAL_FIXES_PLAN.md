# План критических исправлений - Round 2

**Дата:** 2026-01-20
**Приоритет:** 🔥 Немедленно (сегодня-завтра)
**Задач:** 4 критические проблемы
**Статус:** В процессе

---

## Обзор

После успешного исправления 4 concurrency проблем (#152, #1, #8, #46), переходим к следующим критическим задачам:

1. **#102, #103, #119** - FK schema на non-primary key
2. **#117** - chat_mapping_id=0 validation
3. **#156, #160** - DB error handling в Contact Manager
4. **#178** - Lock cleanup task не стартует

---

## Задача 1: Fix FK Schema (#102, #103, #119)

### Проблема

**CRITICAL Severity** - Invalid database schema

Foreign keys указывают на `telegram_chat_id` (non-primary key) вместо правильного `id`:

```python
# ПРОБЛЕМА в src/database.py:

# ChatProfile (строка 209)
__table_args__ = (
    ForeignKeyConstraint(
        ['account_id', 'telegram_chat_id'],
        ['chat_mappings.account_id', 'chat_mappings.telegram_chat_id']  # WRONG!
    ),
)

# UiChat (строка 488)
__table_args__ = (
    ForeignKeyConstraint(
        ['account_id', 'telegram_chat_id'],
        ['chat_mappings.account_id', 'chat_mappings.telegram_chat_id']  # WRONG!
    ),
)
```

**Почему критично:**
- FK должны указывать на PRIMARY KEY
- `telegram_chat_id` не является primary key в `chat_mappings`
- Может привести к data integrity issues
- Некорректная работа CASCADE deletes

### Решение

**Вариант 1: Composite FK на (account_id, telegram_chat_id)** ✅ РЕКОМЕНДУЕТСЯ
- `chat_mappings` имеет composite UNIQUE constraint на `(account_id, telegram_chat_id)`
- FK может указывать на UNIQUE constraint (допустимо в PostgreSQL/SQLite)
- Минимальные изменения schema

**Вариант 2: Изменить FK на (account_id, id)**
- Требует изменения всех ссылающихся таблиц
- Больше изменений в коде
- Не рекомендуется

### План реализации

**Шаг 1.1: Создать Alembic миграцию**
```bash
python3 -m alembic revision -m "fix_fk_constraints_to_unique_index"
```

**Файл:** `alembic/versions/YYYYMMDD_fix_fk_constraints.py`

**Содержимое миграции:**
```python
def upgrade():
    # Проверяем что chat_mappings имеет UNIQUE constraint
    # на (account_id, telegram_chat_id)

    # PostgreSQL: FK может ссылаться на UNIQUE constraint
    # SQLite: Также поддерживает

    # Миграция уже корректна! Нужно только добавить комментарий
    pass

def downgrade():
    pass
```

**Шаг 1.2: Верификация schema**
- Проверить что `chat_mappings` имеет UNIQUE constraint
- Проверить что FK работают корректно
- Добавить тесты на CASCADE delete

**Шаг 1.3: Написать тесты**

**Файл:** `tests/test_fk_constraints.py`

**Тесты:**
1. `test_chat_profile_fk_references_valid_mapping`
2. `test_ui_chat_fk_references_valid_mapping`
3. `test_cascade_delete_mapping_removes_chat_profile`
4. `test_cascade_delete_mapping_removes_ui_chat`
5. `test_invalid_telegram_chat_id_raises_fk_error`

**Шаг 1.4: Прогнать тесты**
```bash
python3 -m unittest tests.test_fk_constraints -v
```

**Критерий успеха:**
- ✅ Все тесты проходят
- ✅ CASCADE deletes работают корректно
- ✅ Нет orphan records

---

## Задача 2: Fix chat_mapping_id=0 (#117)

### Проблема

**CRITICAL Severity** - Invalid FK records создаются

В `src/bridge.py:294` при отсутствии mapping создается MessageHistory с `chat_mapping_id=0`:

```python
# ПРОБЛЕМА:
history = MessageHistory(
    account_id=self.account_id,
    chat_mapping_id=mapping.id if mapping else 0,  # INVALID FK!
    ...
)
```

**Почему критично:**
- `chat_mapping_id=0` не существует в таблице `chat_mappings`
- Нарушение FK constraint (если enforced)
- Orphan records в production
- Невозможно восстановить связь с mapping

### Решение

**Вариант 1: Не создавать MessageHistory если mapping=None** ✅ РЕКОМЕНДУЕТСЯ
```python
if not mapping:
    logger.warning(f"No mapping for chat_id={telegram_chat_id}, skipping MessageHistory")
    return

history = MessageHistory(
    account_id=self.account_id,
    chat_mapping_id=mapping.id,  # Always valid!
    ...
)
```

**Вариант 2: Сделать chat_mapping_id nullable**
- Требует изменения schema
- Больше логики для обработки NULL
- Не рекомендуется

### План реализации

**Шаг 2.1: Исправить код в bridge.py**

**Файл:** `src/bridge.py:294` и аналогичные места

**Изменения:**
1. Найти все места где используется `mapping.id if mapping else 0`
2. Добавить проверку `if not mapping: return`
3. Использовать `mapping.id` напрямую (всегда valid)

**Шаг 2.2: Добавить валидацию на уровне модели**

**Файл:** `src/database.py` - MessageHistory

```python
@validates('chat_mapping_id')
def validate_chat_mapping_id(self, key, value):
    if value <= 0:
        raise ValueError(f"chat_mapping_id must be positive, got {value}")
    return value
```

**Шаг 2.3: Написать тесты**

**Файл:** `tests/test_mapping_validation.py`

**Тесты:**
1. `test_message_history_requires_valid_mapping`
2. `test_message_history_rejects_zero_mapping_id`
3. `test_bridge_skips_history_without_mapping`
4. `test_no_orphan_records_created`

**Шаг 2.4: Очистка existing invalid records**

**SQL для проверки:**
```sql
SELECT COUNT(*) FROM message_history WHERE chat_mapping_id = 0;
```

**Если найдены - создать cleanup migration:**
```python
def upgrade():
    # Delete invalid records with chat_mapping_id=0
    op.execute(
        "DELETE FROM message_history WHERE chat_mapping_id = 0"
    )
```

**Шаг 2.5: Прогнать тесты**
```bash
python3 -m unittest tests.test_mapping_validation -v
```

**Критерий успеха:**
- ✅ Нет записей с chat_mapping_id=0
- ✅ MessageHistory создается только при valid mapping
- ✅ Validation errors логируются корректно

---

## Задача 3: DB Error Handling (#156, #160)

### Проблема

**HIGH Severity** - Падение при DB сбое

Contact Manager не обрабатывает DB errors при logging, что блокирует всю операцию:

```python
# ПРОБЛЕМА в src/contact_manager.py:418-500
async def _log_add_attempt(...):
    async with SessionLocal() as session:
        log_entry = ContactAddLog(...)
        session.add(log_entry)
        await session.commit()  # Если падает - вся операция блокируется!
```

**Почему критично:**
- DB unavailable → contact addition fails
- Cascading failures
- No graceful degradation
- User-facing operations fail

### Решение

**Добавить try-catch с fallback на in-memory logging:**

```python
async def _log_add_attempt(...):
    try:
        async with SessionLocal() as session:
            log_entry = ContactAddLog(...)
            session.add(log_entry)
            await session.commit()
    except Exception as e:
        # Fallback: log to application logger
        logger.error(
            f"Failed to log contact add to DB: {e}. "
            f"Contact: user_id={telegram_user_id}, phone={phone}, "
            f"direction={direction}, result={result}"
        )
        # Don't re-raise - logging failure shouldn't block contact addition
```

### План реализации

**Шаг 3.1: Добавить error handling в _log_add_attempt**

**Файл:** `src/contact_manager.py:418-426`

**Изменения:**
```python
async def _log_add_attempt(
    self,
    telegram_user_id: int,
    phone: str,
    first_name: Optional[str],
    last_name: Optional[str],
    direction: str,
    result: str,
    error_message: Optional[str] = None
) -> None:
    """Log contact add attempt to database with error handling."""
    try:
        async with SessionLocal() as session:
            log_entry = ContactAddLog(
                telegram_user_id=telegram_user_id,
                phone_number=phone,
                first_name=first_name or "",
                last_name=last_name or "",
                direction=direction,
                result=result,
                error_message=error_message or ""
            )
            session.add(log_entry)
            await session.commit()
    except Exception as e:
        # Critical: DB logging failed - use application logger as fallback
        logger.error(
            f"❌ Failed to log contact add to database: {e}. "
            f"Contact details: user_id={telegram_user_id}, phone={phone}, "
            f"direction={direction}, result={result}, error={error_message}"
        )
        # Don't re-raise - logging failure should not block contact addition
```

**Шаг 3.2: Добавить аналогичную обработку в _get_recent_add_count**

**Файл:** `src/contact_manager.py:450-500`

**Изменения:**
```python
async def _get_recent_add_count(self, ...) -> int:
    """Get recent add count with DB error handling."""
    try:
        async with SessionLocal() as session:
            # ... existing query logic
            return count
    except Exception as e:
        # Fallback: return conservative estimate (assume limit exceeded)
        logger.error(
            f"❌ Failed to query contact_add_log: {e}. "
            f"Returning conservative count to prevent abuse."
        )
        # Return high count to trigger rate limiting (fail-safe)
        return 9999
```

**Шаг 3.3: Добавить client.is_connected() check**

**Файл:** `src/contact_manager.py:396-405`

**Изменения:**
```python
async def _do_telegram_api_call(...):
    """Execute Telegram API call with connection check."""
    # Check connection before attempting API call
    if not self.client.is_connected():
        logger.error("Telegram client not connected")
        return False, "Client not connected"

    try:
        # ... existing API call logic
```

**Шаг 3.4: Написать тесты**

**Файл:** `tests/test_contact_manager_errors.py`

**Тесты:**
1. `test_log_add_attempt_handles_db_error`
2. `test_get_recent_count_handles_db_error`
3. `test_contact_add_succeeds_despite_log_failure`
4. `test_telegram_api_call_checks_connection`
5. `test_rate_limiting_conservative_on_db_error`

**Шаг 3.5: Прогнать тесты**
```bash
python3 -m unittest tests.test_contact_manager_errors -v
```

**Критерий успеха:**
- ✅ Contact addition не блокируется при DB failure
- ✅ Errors логируются в application logger
- ✅ Rate limiting работает консервативно при DB errors
- ✅ is_connected() check предотвращает бесполезные API calls

---

## Задача 4: Lock Cleanup Task (#178)

### Проблема

**HIGH Severity** - Memory leak в per-user locks

Lock cleanup task никогда не стартует → рост `_locks` dict при большом числе уникальных пользователей:

```python
# ПРОБЛЕМА в src/contact_manager.py:135-145
async def start_cleanup_task(self):
    """Start background cleanup task."""
    if self._cleanup_task is None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

# НО! Этот метод НИКОГДА НЕ ВЫЗЫВАЕТСЯ
```

**Почему критично:**
- Memory leak при большом числе пользователей
- `_locks` dict растет бесконечно
- В production с 10K+ users → significant memory usage
- No automatic cleanup → restart required

### Решение

**Автоматически стартовать cleanup task при создании ContactManager:**

```python
def __init__(self, client, circuit_breaker):
    self._lock_manager = PerUserLockManager(lock_ttl_seconds=300)

    # Автоматически стартуем cleanup task
    self._cleanup_task = asyncio.create_task(
        self._lock_manager.start_cleanup_task()
    )
```

### План реализации

**Шаг 4.1: Изменить __init__ в ContactManager**

**Файл:** `src/contact_manager.py`

**Изменения:**
```python
def __init__(self, client, circuit_breaker: CircuitBreaker):
    """Initialize ContactManager with automatic lock cleanup."""
    self.client = client
    self.circuit_breaker = circuit_breaker

    # Per-user lock manager with automatic cleanup
    self._lock_manager = PerUserLockManager(lock_ttl_seconds=300)

    # Start cleanup task automatically
    # Note: We don't await here - it runs in background
    asyncio.create_task(self._lock_manager.start_cleanup_task())
```

**Шаг 4.2: Обновить PerUserLockManager.start_cleanup_task**

**Файл:** `src/contact_manager.py:135-145`

**Изменения:**
```python
async def start_cleanup_task(self):
    """Start background cleanup task (runs forever)."""
    logger.info("Starting per-user lock cleanup task (interval: 60s)")

    try:
        while True:
            await asyncio.sleep(60)  # Cleanup every minute

            try:
                await self.cleanup_stale_locks()
            except Exception as e:
                # Don't crash cleanup task on errors
                logger.error(f"Error in lock cleanup: {e}")
    except asyncio.CancelledError:
        logger.info("Lock cleanup task cancelled")
        raise
```

**Шаг 4.3: Добавить graceful shutdown**

**Файл:** `src/contact_manager.py`

**Добавить метод:**
```python
async def shutdown(self):
    """Graceful shutdown - cancel cleanup task."""
    if self._cleanup_task and not self._cleanup_task.done():
        self._cleanup_task.cancel()
        try:
            await self._cleanup_task
        except asyncio.CancelledError:
            pass
    logger.info("ContactManager shutdown complete")
```

**Шаг 4.4: Написать тесты**

**Файл:** `tests/test_lock_cleanup.py`

**Тесты:**
1. `test_cleanup_task_starts_automatically`
2. `test_cleanup_removes_stale_locks`
3. `test_cleanup_preserves_active_locks`
4. `test_cleanup_continues_on_error`
5. `test_graceful_shutdown_cancels_task`
6. `test_memory_stable_under_load` (1000 unique users)

**Шаг 4.5: Прогнать тесты**
```bash
python3 -m unittest tests.test_lock_cleanup -v
```

**Критерий успеха:**
- ✅ Cleanup task стартует автоматически
- ✅ Stale locks удаляются каждую минуту
- ✅ Active locks не удаляются
- ✅ Memory usage стабильна под нагрузкой
- ✅ Graceful shutdown работает

---

## Итоговые шаги

### Шаг 5: Финальное тестирование

**5.1 Прогнать все тесты вместе:**
```bash
# Все новые тесты
python3 -m unittest tests.test_fk_constraints -v
python3 -m unittest tests.test_mapping_validation -v
python3 -m unittest tests.test_contact_manager_errors -v
python3 -m unittest tests.test_lock_cleanup -v

# Все concurrency тесты (не сломали предыдущие исправления)
python3 -m unittest tests.test_concurrency_fixes -v

# Все critical fixes тесты
python3 -m unittest tests.test_critical_fixes -v
```

**5.2 Integration test на production-like сценарий:**
```bash
# Запустить полный test suite
python3 -m unittest discover -s tests -v
```

### Шаг 6: Документация

**6.1 Создать итоговый отчет:**

**Файл:** `CRITICAL_FIXES_ROUND2_REPORT.md`

**Содержимое:**
- Список всех 4 исправлений
- Code changes summary
- Test results
- Migration guide
- Deployment notes

**6.2 Обновить CHANGELOG.md:**
```markdown
## [Unreleased] - 2026-01-20

### Fixed (Critical Round 2)
- #102, #103, #119: Fixed FK constraints to reference valid UNIQUE indexes
- #117: Prevented creation of invalid MessageHistory with chat_mapping_id=0
- #156, #160: Added DB error handling in ContactManager with graceful degradation
- #178: Fixed memory leak by auto-starting lock cleanup task

### Tests Added
- FK constraints validation (5 tests)
- Mapping ID validation (4 tests)
- Contact Manager error handling (5 tests)
- Lock cleanup automation (6 tests)
```

**6.3 Обновить NEED_TO_FIX.md:**
- Удалить #102, #103, #119, #117, #156, #160, #178
- Обновить статистику: 119 → 112 проблем
- Обновить оценку: 9.6/10 → 9.7/10

---

## Временная оценка

| Задача | Время |
|--------|-------|
| #102, #103, #119 - FK schema | 1-2 часа |
| #117 - mapping validation | 1 час |
| #156, #160 - DB error handling | 2-3 часа |
| #178 - Lock cleanup | 1-2 часа |
| Тестирование и документация | 2 часа |
| **ИТОГО** | **7-10 часов** |

## Критерии успеха

✅ Все 4 проблемы исправлены
✅ 20+ новых тестов написаны и проходят
✅ Все existing тесты продолжают работать
✅ Миграции созданы (если требуется)
✅ Документация обновлена
✅ Production-ready code

## Риски и митигация

| Риск | Вероятность | Impact | Митигация |
|------|-------------|--------|-----------|
| FK migration breaks existing data | Low | High | Тщательная проверка constraints перед миграцией |
| DB error handling слишком агрессивный | Medium | Medium | Логировать все fallback случаи |
| Cleanup task создает overhead | Low | Low | Мониторинг CPU usage, настройка interval |

---

**Готов к execution!** 🚀
