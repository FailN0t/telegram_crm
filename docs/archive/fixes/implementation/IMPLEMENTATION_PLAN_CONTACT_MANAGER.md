# План реализации Contact Manager

**Дата:** 2026-01-20
**Статус:** 📋 В процессе
**Цель:** Безопасное извлечение телефонов из Telegram с защитой от бана

---

## Этапы реализации

### ✅ Этап 0: Подготовка
- [x] Создать design document (TELEGRAM_CONTACT_MANAGEMENT_DESIGN.md)
- [x] Создать план реализации (этот файл)
- [ ] Создать ветку в git: `feature/contact-manager`

### 📝 Этап 1: Создание базовых компонентов

#### 1.1. Database Model
**Файл:** `src/database.py`
**Задача:** Добавить модель `ContactAddLog`

**Чеклист:**
- [ ] Добавить импорт для Index
- [ ] Добавить класс ContactAddLog с полями:
  - `id` (Integer, PK)
  - `telegram_user_id` (BigInteger, indexed)
  - `direction` (String(10): 'inbound'/'outbound')
  - `source` (String(50))
  - `success` (Boolean)
  - `created_at` (DateTime, indexed)
- [ ] Добавить индексы для быстрого поиска
- [ ] Проверить что модель экспортируется в `__all__`

#### 1.2. Alembic Migration
**Файл:** `alembic/versions/YYYYMMDD_add_contact_add_log.py`
**Задача:** Создать миграцию для новой таблицы

**Команды:**
```bash
# Создать миграцию автоматически
python3 -m alembic revision --autogenerate -m "add_contact_add_log_table"

# Если автогенерация не сработает, создать вручную
python3 -m alembic revision -m "add_contact_add_log_table"
```

**Чеклист:**
- [ ] Создать миграцию
- [ ] Проверить что upgrade() создаёт таблицу и индексы
- [ ] Проверить что downgrade() удаляет всё корректно
- [ ] Протестировать миграцию локально
- [ ] Применить миграцию: `python3 -m alembic upgrade head`
- [ ] Проверить в БД: `\d contact_add_log` (PostgreSQL) или `.schema contact_add_log` (SQLite)

#### 1.3. Contact Manager - Circuit Breaker
**Файл:** `src/contact_manager.py` (новый)
**Задача:** Реализовать ContactAddCircuitBreaker класс

**Чеклист:**
- [ ] Создать файл `src/contact_manager.py`
- [ ] Добавить импорты (datetime, asyncio, typing, logger)
- [ ] Реализовать ContactAddCircuitBreaker:
  - [ ] `__init__()` - инициализация состояния
  - [ ] `is_open()` - проверка состояния
  - [ ] `check_burst_limit()` - проверка burst (5/60s)
  - [ ] `record_add_attempt()` - запись попытки
  - [ ] `record_success()` - запись успеха
  - [ ] `record_failure()` - запись ошибки
  - [ ] `_open_circuit()` - открытие circuit breaker
- [ ] Добавить константы (MAX_FAILURES=3, COOLDOWN_SECONDS=300, MAX_BURST=5)
- [ ] Добавить docstrings ко всем методам

#### 1.4. Contact Manager - Main Class
**Файл:** `src/contact_manager.py` (продолжение)
**Задача:** Реализовать ContactManager класс

**Чеклист:**
- [ ] Реализовать ContactManager:
  - [ ] `__init__()` - создать circuit_breaker и lock
  - [ ] `can_add_contact()` - проверка всех лимитов
  - [ ] `add_to_contacts_with_protection()` - основной метод
- [ ] Добавить константы лимитов:
  - INBOUND_MAX_PER_HOUR = 50
  - INBOUND_MAX_PER_DAY = 150
  - OUTBOUND_MAX_PER_HOUR = 3
  - OUTBOUND_MAX_PER_DAY = 10
- [ ] Реализовать логику проверки:
  - Circuit breaker check
  - Burst limit check
  - Rate limit check (hourly/daily)
  - Already added check
- [ ] Реализовать добавление в контакты:
  - Telegram AddContactRequest с timeout
  - Обработка ошибок (flood, privacy, timeout)
  - Логирование в БД
  - Обновление circuit breaker
- [ ] Создать singleton: `contact_manager = ContactManager()`
- [ ] Добавить полные docstrings

#### 1.5. Monitoring Module
**Файл:** `src/monitoring.py` (новый)
**Задача:** Реализовать ContactAddMonitor класс

**Чеклист:**
- [ ] Создать файл `src/monitoring.py`
- [ ] Добавить импорты
- [ ] Реализовать ContactAddMonitor:
  - [ ] `check_health()` static method
  - [ ] Статистика за час (total, success, failures, failure_rate)
  - [ ] Статистика за день (total, success, failures, failure_rate)
  - [ ] Определение статуса (ok/warning/critical)
  - [ ] Логирование алертов при высоком failure_rate
- [ ] Добавить docstrings

---

### 📝 Этап 2: Интеграция в существующий код

#### 2.1. Модификация telegram_client.py
**Файл:** `src/telegram_client.py`
**Метод:** `_handle_incoming_message` (~строка 1167)

**Чеклист:**
- [ ] Найти метод `_handle_incoming_message`
- [ ] Найти строку `phone_number = getattr(sender, 'phone', None)`
- [ ] Добавить после неё блок:
  ```python
  if not phone_number and sender.username:
      from src.contact_manager import contact_manager
      logger.info(...)
      success, phone_number = await contact_manager.add_to_contacts_with_protection(...)
  ```
- [ ] Убедиться что phone_number передаётся в bridge.handle_incoming_message()
- [ ] Проверить что все параметры корректны

#### 2.2. Модификация bridge.py - handle_incoming_message
**Файл:** `src/bridge.py`
**Метод:** `handle_incoming_message` (~строка 727)

**Чеклист:**
- [ ] Найти метод `handle_incoming_message`
- [ ] Добавить параметр `phone: Optional[str]` в сигнатуру
- [ ] Найти вызов `self.crm.create_contact()`
- [ ] Добавить параметр `phone=phone` в вызов
- [ ] Проверить что phone передаётся дальше в CRM

#### 2.3. Модификация bridge.py - send_message_from_crm
**Файл:** `src/bridge.py`
**Метод:** `send_message_from_crm` (для outbound сценария)

**Чеклист:**
- [ ] Найти метод `send_message_from_crm`
- [ ] Найти блок создания нового контакта (`if not mapping`)
- [ ] Добавить проверку outbound лимитов:
  ```python
  from src.contact_manager import contact_manager
  can_add, reason = await contact_manager.can_add_contact(
      direction='outbound',
      telegram_user_id=0
  )
  if not can_add:
      return False, f"Rate limit: {reason}"
  ```
- [ ] Добавить TODO комментарий для полной реализации outbound

#### 2.4. Добавление Admin Endpoint
**Файл:** `src/api_server.py`

**Чеклист:**
- [ ] Найти раздел с admin endpoints (например, после `/admin/operators`)
- [ ] Добавить endpoint `/admin/contact-health`:
  ```python
  @app.get("/admin/contact-health")
  async def get_contact_health(
      current_user: dict = Depends(admin_required)
  ):
      from src.monitoring import ContactAddMonitor
      from src.contact_manager import contact_manager
      ...
  ```
- [ ] Вернуть JSON с circuit_breaker состоянием и health stats
- [ ] Добавить docstring с описанием endpoint

---

### 📝 Этап 3: Тестирование

#### 3.1. Unit тесты для ContactAddCircuitBreaker
**Файл:** `tests/test_contact_manager.py` (новый)

**Чеклист:**
- [ ] Создать файл `tests/test_contact_manager.py`
- [ ] Написать тесты для CircuitBreaker:
  - [ ] `test_circuit_breaker_initial_state()` - начальное состояние CLOSED
  - [ ] `test_circuit_breaker_opens_after_failures()` - открывается после 3 ошибок
  - [ ] `test_circuit_breaker_burst_limit()` - burst limit срабатывает
  - [ ] `test_circuit_breaker_cooldown()` - cooldown работает
  - [ ] `test_circuit_breaker_half_open_recovery()` - HALF_OPEN -> CLOSED
  - [ ] `test_circuit_breaker_record_success_resets()` - успех сбрасывает счётчик

#### 3.2. Unit тесты для ContactManager
**Файл:** `tests/test_contact_manager.py` (продолжение)

**Чеклист:**
- [ ] Написать тесты для ContactManager:
  - [ ] `test_rate_limit_inbound_hourly()` - hourly лимит для inbound
  - [ ] `test_rate_limit_inbound_daily()` - daily лимит для inbound
  - [ ] `test_rate_limit_outbound_hourly()` - hourly лимит для outbound
  - [ ] `test_rate_limit_outbound_daily()` - daily лимит для outbound
  - [ ] `test_already_added_returns_phone()` - повторное добавление
  - [ ] `test_circuit_breaker_blocks_when_open()` - circuit breaker блокирует
  - [ ] `test_burst_limit_blocks()` - burst limit блокирует

#### 3.3. Integration тесты
**Файл:** `tests/test_contact_manager_integration.py` (новый)

**Чеклист:**
- [ ] Создать файл для integration тестов
- [ ] Mock Telegram client
- [ ] Написать тесты:
  - [ ] `test_add_contact_success()` - успешное добавление
  - [ ] `test_add_contact_privacy_error()` - privacy error обрабатывается
  - [ ] `test_add_contact_timeout()` - timeout обрабатывается
  - [ ] `test_add_contact_flood_opens_circuit()` - flood открывает circuit
  - [ ] `test_database_logging()` - запись в БД работает

#### 3.4. Integration тест с telegram_client
**Файл:** `tests/test_telegram_client_contact_integration.py` (новый)

**Чеклист:**
- [ ] Создать файл для теста полного flow
- [ ] Mock TelegramClient и Bitrix24Client
- [ ] Написать тест:
  - [ ] `test_incoming_message_extracts_phone()` - полный flow от события до Bitrix24
  - [ ] Проверить что phone передаётся в bridge
  - [ ] Проверить что phone попадает в create_contact()

#### 3.5. Тесты для Monitoring
**Файл:** `tests/test_monitoring.py` (новый)

**Чеклист:**
- [ ] Создать файл
- [ ] Написать тесты:
  - [ ] `test_health_check_returns_stats()` - возвращает статистику
  - [ ] `test_health_status_ok()` - статус OK при low failure rate
  - [ ] `test_health_status_warning()` - статус WARNING при >30% failures
  - [ ] `test_health_status_critical()` - статус CRITICAL при >50% failures

#### 3.6. Запуск всех тестов
**Команды:**
```bash
# Запустить только новые тесты
python3 -m unittest tests.test_contact_manager
python3 -m unittest tests.test_monitoring

# Запустить все тесты
python3 -m unittest discover -s tests

# С coverage (если установлен)
coverage run -m unittest discover -s tests
coverage report
coverage html
```

**Чеклист:**
- [ ] Все тесты проходят локально на SQLite
- [ ] Все тесты проходят на PostgreSQL (если доступен)
- [ ] Coverage > 80% для новых файлов
- [ ] Нет warnings или deprecation notices

---

### 📝 Этап 4: Документация

#### 4.1. Обновление CLAUDE.md
**Файл:** `CLAUDE.md`

**Чеклист:**
- [ ] Добавить раздел "Contact Management" в Architecture Overview
- [ ] Описать ContactManager и его назначение
- [ ] Добавить в Critical Development Notes:
  - Всегда использовать ContactManager для добавления контактов
  - Никогда не вызывать AddContactRequest напрямую
  - Мониторить /admin/contact-health

#### 4.2. Создание руководства пользователя
**Файл:** `CONTACT_MANAGER_USAGE.md` (новый)

**Чеклист:**
- [ ] Создать файл с инструкциями для пользователей
- [ ] Включить разделы:
  - Что такое Contact Manager
  - Зачем нужен
  - Как проверить статус (curl /admin/contact-health)
  - Что делать если circuit breaker открыт
  - FAQ

#### 4.3. API Documentation
**Файл:** `API.md`

**Чеклист:**
- [ ] Добавить документацию для `/admin/contact-health` endpoint
- [ ] Пример запроса и ответа
- [ ] Описание полей response

#### 4.4. Changelog
**Файл:** `CHANGELOG.md`

**Чеклист:**
- [ ] Добавить запись о новой функции:
  ```markdown
  ## [Unreleased]

  ### Added
  - Contact Manager для безопасного извлечения телефонов из Telegram
  - Circuit Breaker защита от бана Telegram аккаунта
  - Rate limiting для inbound (50/час, 150/день) и outbound (3/час, 10/день)
  - Новая таблица БД: contact_add_log для аудита
  - Endpoint /admin/contact-health для мониторинга
  - Автоматическое извлечение phone из Telegram контактов
  - Передача phone в Bitrix24 при создании контактов
  ```

#### 4.5. Обновление README
**Файл:** `README.md`

**Чеклист:**
- [ ] Добавить упоминание о Contact Manager в Features
- [ ] Добавить ссылку на TELEGRAM_CONTACT_MANAGEMENT_DESIGN.md

---

### 📝 Этап 5: Финальная проверка и деплой

#### 5.1. Код-ревью чеклист

**Чеклист:**
- [ ] Все файлы имеют корректные docstrings
- [ ] Нет закомментированного кода (кроме примеров в комментариях)
- [ ] Нет TODO без issue номера
- [ ] Logging уровни корректны (INFO для normal flow, WARNING для limits, ERROR для failures)
- [ ] Нет print() statements (только logger)
- [ ] Все исключения обрабатываются
- [ ] Нет hardcoded значений (используются константы/config)
- [ ] Type hints везде где возможно
- [ ] Asyncio используется корректно (await, asyncio.Lock)

#### 5.2. Локальное тестирование

**Чеклист:**
- [ ] Запустить сервер локально: `python3 -m src.main`
- [ ] Проверить что миграция применена
- [ ] Отправить тестовое сообщение в Telegram
- [ ] Проверить логи: добавление контакта работает
- [ ] Проверить БД: запись в contact_add_log есть
- [ ] Проверить endpoint: `curl http://localhost:8000/admin/contact-health` (с auth)
- [ ] Проверить circuit breaker: trigger burst limit вручную
- [ ] Проверить что circuit breaker восстанавливается после cooldown

#### 5.3. Подготовка к деплою

**Чеклист:**
- [ ] Создать backup БД перед миграцией
- [ ] Проверить что миграция безопасна (только добавление, без изменения существующих таблиц)
- [ ] Подготовить rollback plan
- [ ] Проверить что в production есть необходимые Python зависимости (telethon уже есть)
- [ ] Проверить что environment variables не требуют изменений

#### 5.4. Деплой на staging/production

**Команды:**
```bash
# 1. Git
git checkout -b feature/contact-manager
git add .
git commit -m "feat: add Contact Manager for safe phone extraction"
git push origin feature/contact-manager

# 2. На сервере: Backup
docker exec telegram-crm-postgres pg_dump -U postgres telegram_crm > backup_before_contact_manager.sql

# 3. На сервере: Deploy
docker-compose -f docker-compose.production.yml down
git pull origin feature/contact-manager
docker-compose -f docker-compose.production.yml build --no-cache
docker-compose -f docker-compose.production.yml up -d

# 4. На сервере: Миграция
docker exec telegram-crm-app python3 -m alembic upgrade head

# 5. Проверка
docker logs telegram-crm-app --tail 50
docker logs telegram-crm-outbox-worker --tail 50
```

**Чеклист:**
- [ ] Backup создан
- [ ] Код задеплоен
- [ ] Миграция применена успешно
- [ ] Сервисы запустились без ошибок
- [ ] Логи не показывают критичных ошибок
- [ ] Endpoint /admin/contact-health доступен
- [ ] Первое входящее сообщение обрабатывается корректно

#### 5.5. Мониторинг после деплоя

**Чеклист:**
- [ ] Мониторить логи первые 30 минут
- [ ] Проверять /admin/contact-health каждые 5 минут
- [ ] Проверить что phone извлекается для новых контактов
- [ ] Проверить что phone попадает в Bitrix24
- [ ] Проверить что circuit breaker не открывается
- [ ] Проверить что rate limits соблюдаются
- [ ] Нет ошибок от Telegram API (flood, etc)

---

## Метрики успеха

### Функциональные метрики
- ✅ Phone извлекается для >70% входящих сообщений (с учётом privacy settings)
- ✅ Phone передаётся в Bitrix24 и виден менеджерам
- ✅ Circuit breaker не открывается при нормальной нагрузке
- ✅ Нет Telegram flood errors в логах

### Технические метрики
- ✅ Все тесты проходят (100%)
- ✅ Code coverage > 80% для новых файлов
- ✅ Нет критичных warnings от linters
- ✅ Документация полная и актуальная

### Безопасность
- ✅ Аккаунт Telegram не забанен
- ✅ Circuit breaker корректно срабатывает при ошибках
- ✅ Rate limits не превышаются
- ✅ Все операции логируются

---

## Rollback Plan

Если что-то пошло не так:

### Быстрый rollback (без потери данных)

```bash
# 1. Откатить код
git checkout main
docker-compose -f docker-compose.production.yml build --no-cache
docker-compose -f docker-compose.production.yml up -d

# 2. Откатить миграцию (опционально)
docker exec telegram-crm-app python3 -m alembic downgrade -1
```

**Что НЕ теряется:**
- Все существующие данные
- Таблица contact_add_log остаётся (не мешает)
- Mapping и контакты сохраняются

**Что перестаёт работать:**
- Извлечение phone для новых контактов
- Endpoint /admin/contact-health

### Полный rollback (с удалением таблицы)

```bash
# Если нужно удалить contact_add_log полностью
docker exec telegram-crm-app python3 -m alembic downgrade -1
```

---

## Примечания и риски

### Потенциальные проблемы

1. **Telegram privacy settings**
   - Не все пользователи разрешают видеть phone
   - Ожидаемо: ~30-50% будут скрывать номер
   - Решение: Это нормально, не считается ошибкой

2. **Telegram rate limits**
   - Риск: Превышение лимитов при высокой нагрузке
   - Решение: Circuit breaker + консервативные лимиты

3. **Circuit breaker false positives**
   - Риск: Открывается при легитимной нагрузке
   - Решение: Мониторинг и настройка лимитов

4. **Database lock contention**
   - Риск: contact_add_log может стать bottleneck
   - Решение: Индексы + asyncio.Lock

### Зависимости

**Python packages (уже установлены):**
- telethon >= 1.35.0
- sqlalchemy >= 2.0
- asyncpg (PostgreSQL)
- aiosqlite (SQLite для тестов)

**Внешние сервисы:**
- Telegram MTProto API
- PostgreSQL database
- Bitrix24 API

---

**Создано:** 2026-01-20
**Обновлено:** 2026-01-20
**Статус:** 📋 Ready for implementation
**Приоритет:** 🔴 Высокий
