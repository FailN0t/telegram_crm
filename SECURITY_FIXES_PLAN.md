# Security Fixes Implementation Plan

**Дата:** 2026-01-20
**Цель:** Исправить 5 критичных security проблем перед использованием системы
**Время:** ~4.5 часа

---

## Задача #14 - Lock для refresh CRM токенов (2 часа)

### Проблема
Несинхронизированный refresh CRM токенов → race condition под нагрузкой → 401 ошибки/потеря токена.

**Файлы:**
- `src/amocrm_client.py:96-129`
- `src/bitrix24_client.py:120-165`

### Симптомы
- Concurrent запросы к CRM видят одновременно истекший токен
- Оба вызывают refresh_token() одновременно
- Первый refresh успешен, второй fail (старый refresh_token уже невалиден)
- Потеря токена → все запросы к CRM fail → остановка работы

### Решение
1. Добавить `asyncio.Lock` в оба CRM клиента
2. Обернуть refresh_token() в `async with self._token_refresh_lock`
3. Double-checked locking: проверить токен до и после получения lock
4. Если токен обновился пока ждали lock - не делать refresh

### Файлы для изменения
- `src/amocrm_client.py` - добавить `self._token_refresh_lock = asyncio.Lock()`
- `src/bitrix24_client.py` - добавить `self._token_refresh_lock = asyncio.Lock()`

### Тесты
- `tests/test_security_fixes.py::test_amocrm_concurrent_token_refresh`
- `tests/test_security_fixes.py::test_bitrix24_concurrent_token_refresh`

**Сценарий теста:**
1. Мокаем expired токен
2. Запускаем 5 concurrent запросов к CRM API
3. Проверяем что refresh_token() вызван ровно 1 раз (не 5)
4. Все запросы успешны

---

## Задача #128 - Rollback client при ошибке start() (30 мин)

### Проблема
Client start exception не откатывает добавление в `_clients` → orphan clients в manager.

**Файл:** `src/telegram_manager.py:87-88`

### Симптомы
- `add_client()` добавляет client в `self._clients` dict
- Вызывает `client.start()`
- Если `start()` fail → exception, но client остается в `_clients`
- При следующем вызове `get_client()` возвращается неактивный client
- Все операции с ним fail

### Решение
1. Обернуть `client.start()` в try-except
2. При exception удалить client из `self._clients`
3. Re-raise exception для информирования caller

### Код
```python
async def add_client(self, account: TelegramAccount) -> TelegramClient:
    client = TelegramClient(...)
    self._clients[account.id] = client

    try:
        await client.start()
    except Exception as e:
        # Rollback: remove orphan client
        self._clients.pop(account.id, None)
        logger.error(f"Failed to start client for account {account.id}: {e}")
        raise

    return client
```

### Файлы для изменения
- `src/telegram_manager.py:74-92`

### Тесты
- `tests/test_security_fixes.py::test_client_start_exception_rollback`

**Сценарий теста:**
1. Мокаем `client.start()` чтобы raise Exception
2. Вызываем `add_client()`
3. Проверяем что exception raised
4. Проверяем что client НЕ в `_clients` dict

---

## Задача #169 - Magic Link авторизация через Telegram (1 час)

### Проблема (текущий подход)
Публичные UI auth endpoints без авторизации:
- `/api/ui/auth/request-code` - любой может запросить код
- `/api/ui/auth/submit-code` - bruteforce возможен
- `/api/ui/auth/password` - нет rate limiting

### Новое решение - Magic Link через Telegram

#### Архитектура
1. Пользователь заходит на `/ui` (или `/ui/auth`)
2. UI показывает: "Нажмите кнопку для получения ссылки в Telegram"
3. Пользователь нажимает кнопку → POST `/api/ui/auth/request-magic-link`
4. Backend:
   - Генерирует UUID токен
   - Сохраняет в Redis: `magic_link:{token}` = {created_at, used: false}, TTL 5 минут
   - Отправляет сообщение администратору в Telegram с кнопкой "Войти в UI"
   - Кнопка ведет на: `https://your-domain.com/ui/auth/magic?token={UUID}`
5. Пользователь кликает в Telegram → браузер открывает `/ui/auth/magic?token={UUID}`
6. Backend:
   - Проверяет токен в Redis
   - Если валиден и не использован → создает сессию (set cookie)
   - Помечает токен как использованный
   - Redirect на `/ui`

#### Преимущества
- ✅ Нет публичных endpoints для bruteforce
- ✅ Токен одноразовый (нельзя переиспользовать)
- ✅ Короткий TTL (5 минут)
- ✅ Авторизация через контролируемый канал (Telegram)
- ✅ Можно логировать все попытки входа

#### Таблица БД для audit
```sql
CREATE TABLE ui_auth_attempts (
    id SERIAL PRIMARY KEY,
    token VARCHAR(64) NOT NULL,
    telegram_user_id BIGINT,
    ip_address VARCHAR(45),
    user_agent TEXT,
    success BOOLEAN,
    created_at TIMESTAMP DEFAULT NOW()
);
```

### Файлы для изменения
- `src/database.py` - добавить `UiAuthAttempt` model
- `src/api_server.py` - новые endpoints:
  - `POST /api/ui/auth/request-magic-link` - генерация токена и отправка в Telegram
  - `GET /ui/auth/magic` - активация токена и создание сессии
- `src/redis_client.py` - helper для magic link токенов
- `static/ui/auth.html` - UI для запроса magic link
- Удалить старые endpoints: `/api/ui/auth/request-code`, `/api/ui/auth/submit-code`

### Миграция
- `alembic/versions/20260120_add_ui_auth_attempts.py`

### Тесты
- `tests/test_security_fixes.py::test_magic_link_request`
- `tests/test_security_fixes.py::test_magic_link_activation`
- `tests/test_security_fixes.py::test_magic_link_expired`
- `tests/test_security_fixes.py::test_magic_link_already_used`
- `tests/test_security_fixes.py::test_magic_link_invalid_token`

---

## Задача #171 - Защитить /api/ui/accounts (30 мин)

### Проблема
Публичный `/api/ui/accounts` раскрывает номера телефонов и статус аккаунтов.

**Файл:** `src/api_server.py` (эндпоинт `/api/ui/accounts`)

### Решение
1. Добавить проверку авторизации (Basic Auth или session cookie)
2. Возвращать 401 Unauthorized если не авторизован
3. При авторизации - возвращать данные но **маскировать часть номера**

### Код
```python
@app.get("/api/ui/accounts")
async def ui_accounts(
    request: Request,
    current_user: str = Depends(get_current_user)  # Add auth dependency
):
    # Only show if authenticated
    accounts = await get_accounts()

    # Mask phone numbers: +7***1234 instead of +71234567890
    for account in accounts:
        account["phone_number"] = mask_phone(account["phone_number"])

    return accounts

def mask_phone(phone: str) -> str:
    """Mask middle digits: +7***1234"""
    if len(phone) < 8:
        return "***"
    return phone[:2] + "***" + phone[-4:]
```

### Файлы для изменения
- `src/api_server.py` - добавить auth dependency для `/api/ui/accounts`

### Тесты
- `tests/test_security_fixes.py::test_accounts_requires_auth`
- `tests/test_security_fixes.py::test_accounts_masks_phone_numbers`

---

## Задача #173 - Убрать session_string из логов (15 мин)

### Проблема
Логируется часть `session_string` → утечка секретов в логи.

**Файл:** `src/telegram_client.py`

### Поиск всех мест логирования
```bash
grep -n "session_string" src/telegram_client.py
grep -n "session" src/telegram_client.py | grep logger
```

### Решение
1. Найти все logger.* вызовы с session_string
2. Заменить на маскированную версию: `session_string[:8]...` → `***REDACTED***`
3. Либо вообще удалить session_string из логов

### Примеры замены
```python
# БЫЛО:
logger.info(f"Starting client with session: {session_string[:50]}")

# СТАЛО:
logger.info(f"Starting client (session redacted for security)")

# ИЛИ:
logger.info(f"Starting client with session: ***REDACTED***")
```

### Файлы для изменения
- `src/telegram_client.py` - все места где логируется session
- `src/telegram_manager.py` - если есть логирование session

### Тесты
- `tests/test_security_fixes.py::test_session_string_not_logged`

**Сценарий теста:**
1. Захватываем логи (mock logger)
2. Вызываем операции с client
3. Проверяем что в логах НЕТ session_string

---

## Итоговая документация

После реализации всех задач создать:

### SECURITY_FIXES_REPORT.md
- Executive summary
- Детали каждого fix
- Результаты тестов
- Инструкции по деплою
- Security best practices

### Обновить NEED_TO_FIX.md
- Удалить #14, #128, #169, #171, #173 из списка
- Обновить статистику: 113 → 108 проблем
- Обновить CRITICAL: 1 → 1 (все были HIGH)
- Обновить HIGH: 19 → 14
- Обновить оценку: 9.70/10 → 9.75/10

---

## Чеклист выполнения

### Порядок реализации

1. ✅ Создать план (этот файл)
2. ⏭️ #173 - Убрать session_string из логов (15 мин) - **НАЧАТЬ С ЭТОГО** (быстро, low-risk)
3. ⏭️ #128 - Rollback client при ошибке (30 мин) - **ВТОРОЕ** (изолированное, простое)
4. ⏭️ #171 - Защитить /api/ui/accounts (30 мин) - **ТРЕТЬЕ** (простая auth проверка)
5. ⏭️ #14 - Lock для refresh CRM токенов (2 часа) - **ЧЕТВЕРТОЕ** (более сложное)
6. ⏭️ #169 - Magic Link через Telegram (1 час) - **ПОСЛЕДНЕЕ** (самое сложное, новая фича)

### После каждой задачи
- ✅ Написать тесты
- ✅ Прогнать тесты (`python3 -m unittest tests.test_security_fixes`)
- ✅ Зафиксировать изменения (update todo list)
- ✅ Добавить в итоговый отчет

### Финализация
- ✅ Создать migration для UiAuthAttempt (если нужно)
- ✅ Прогнать все тесты проекта
- ✅ Создать SECURITY_FIXES_REPORT.md
- ✅ Обновить NEED_TO_FIX.md
- ✅ Commit changes

---

## Приоритет и время

| Задача | Приоритет | Время | Сложность |
|--------|-----------|-------|-----------|
| #173 - Session string в логах | 1 | 15 мин | LOW |
| #128 - Rollback client | 2 | 30 мин | LOW |
| #171 - Защитить /api/ui/accounts | 3 | 30 мин | LOW |
| #14 - Lock для CRM токенов | 4 | 2 часа | MEDIUM |
| #169 - Magic Link auth | 5 | 1 час | MEDIUM |

**Итого:** 4.5 часа

---

## Критерии успеха

✅ Все 5 задач реализованы и протестированы
✅ Все новые тесты проходят (минимум 10 тестов)
✅ Нет регрессий в существующих тестах
✅ Документация создана и обновлена
✅ Система готова к production использованию

---

*Создано: 2026-01-20 23:50*
*Исполнитель: Claude Code Agent*
