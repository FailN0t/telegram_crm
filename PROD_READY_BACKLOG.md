# Prod-Ready Backlog

## Предпосылки оценки
- 1 разработчик, 6–7 ч/день.
- Оценка приблизительная, без параллельной команды.
- Используем только бесплатные/opensource сервисы (без платных SaaS).

## Бэклог (P0/P1)

| Приоритет | Задача | Результат (Definition of Done) | Оценка |
| --- | --- | --- | --- |
| P0 | Аутентификация UI + роли | `/ui` защищен, роли operator/admin, аудит входов, logout | 3–4 дн |
| P0 | Секреты и конфиг | секреты в secret store, DEBUG off, сессия Telethon хранится безопасно | 2–3 дн |
| P0 | Transactional outbox | outbox в БД, атомарность записи, idempotency key | 4–6 дн |
| P0 | Inbox/dedup webhooks | таблица inbox, защита от дублей | 2–3 дн |
| P0 | Очередь отправки | очередь задач на Postgres/Redis (opensource), гарантии повторов | 3–5 дн |
| P0 | Воркеры | отдельный worker, ретраи с backoff, дедупликация | 3–4 дн |
| P0 | Ordering per chat | сохранение порядка сообщений в диалоге | 2–3 дн |
| P0 | Персистентная история | все сообщения и статусы в БД, без потери при рестарте | 3–4 дн |
| P0 | Медиа/вложения | хранение файлов в MinIO, ссылки в БД | 3–5 дн |
| P0 | Реал-тайм UI | WebSocket/SSE для новых сообщений/статусов | 3–4 дн |
| P0 | Комплаенс/лимиты | согласия, quiet-hours, лимиты, opt-out | 2–3 дн |
| P0 | Надежные интеграции CRM | валидация webhook, очереди на Amo/Bitrix, ретраи | 3–5 дн |
| P0 | Миграции БД | Alembic миграции, контроль версий схемы | 1–2 дн |
| P0 | Наблюдаемость | Prometheus/Grafana, Loki/ELK, self-hosted error tracking | 3–4 дн |
| P0 | Data retention + audit log | политики хранения, аудит действий оператора | 2–3 дн |
| P0 | Runbook + бэкапы | регламент восстановления, RPO/RTO, backup-drill | 2–3 дн |
| **P0** | **Async SQLAlchemy** | замена синхронных SQL-запросов на async, event loop не блокируется | 2–3 дн |
| **P0** | **Атомарный AntiSpam** | проверка+регистрация в одной атомарной операции, без race condition | 1–2 дн |
| **P0** | **Персистентный AntiSpam** | счётчики лимитов в Redis/БД, не сбрасываются при рестарте | 1–2 дн |
| **P0** | **Foreign Keys в БД** | добавить FK между таблицами, ON DELETE CASCADE/SET NULL | 0.5–1 дн |
| **P0** | **Graceful shutdown** | корректное завершение отправок при SIGTERM, drain очереди | 1–2 дн |
| **P0** | **2FA flow persistence** | сохранение состояния авторизации (phone_code_hash) в Redis/БД | 1 дн |
| **P0** | **In-memory → БД** | перенос `_messages`, `_chats` из памяти в БД, UI работает после рестарта | 2–3 дн |
| P1 | Мульти-аккаунты | несколько MTProto аккаунтов, роутинг | 4–6 дн |
| P1 | Админ-настройки | UI-управление шаблонами/лимитами/тегами | 3–5 дн |
| P1 | Нагрузочные тесты | сценарии 1k/10k сообщений | 2–3 дн |
| **P1** | **Вынести UI из Python** | HTML/CSS/JS в отдельные файлы, статика через nginx, кэширование | 1–2 дн |
| **P1** | **Code cleanup** | удалить дубликаты кода (api_server.py:1743-1759), рефакторинг | 1 дн |
| **P1** | **Telethon session в volume** | persistent volume для .session файла в k8s/docker | 0.5 дн |
| **P2** | **Timezone support** | quiet-hours с учётом часового пояса клиента | 1 дн |
| **P2** | **Rate limit per operator** | лимиты на оператора, не только глобальные | 1–2 дн |

---

## Найденные проблемы в текущем коде

> Эти проблемы выявлены при code review и требуют исправления.

### Критические (блокируют production)

| Проблема | Файл:строка | Описание | Последствия |
|----------|-------------|----------|-------------|
| In-memory история | `telegram_client.py:44` | `_messages = deque(maxlen=200)` и `_chats = {}` хранятся в памяти | Потеря всех чатов и сообщений при рестарте |
| Синхронный SQL в async | `telegram_client.py:627-666` | `db = next(get_db())` и `db.query()` блокируют event loop | Лаги, пропуск сообщений при нагрузке |
| Race condition AntiSpam | `antispam.py:39-100` | `can_send_message()` и `register_sent_message()` не атомарны | Превышение лимитов при параллельных запросах |
| AntiSpam сбрасывается | `antispam.py:18-24` | Счётчики в памяти | Обход лимитов перезапуском приложения |
| Нет idempotency webhook | `api_server.py:1789-1832` | Нет проверки на дубликат webhook | Клиент получает 3-5 одинаковых сообщений |
| Дубликаты кода | `api_server.py:1743-1759` | Проверка `if not bridge.amocrm` повторена 3 раза | Copy-paste ошибка, мёртвый код |
| Нет FK в БД | `database.py:96-97` | `chat_mapping_id` без `ForeignKey` | Orphan записи, нарушение целостности |
| 2FA state lost | `telegram_client.py:188` | `_auth_phone` в памяти | Рестарт между send_code и submit_code ломает авторизацию |

### Производительность

| Проблема | Файл:строка | Описание | Последствия |
|----------|-------------|----------|-------------|
| Polling UI | `api_server.py:1518-1521` | 3 запроса каждые 3-6 сек на оператора | 30+ req/sec при 10 операторах, задержка до 4 сек |
| HTML в Python | `api_server.py:21-1525` | 1500+ строк HTML/CSS/JS inline | Нет кэширования, минификации, сложно редактировать |

---

## Разбивка на задачи (по шагам)

### Шаг 0. Критические исправления кода (NEW)

> Эти задачи нужно сделать ДО остальных, иначе система будет терять данные.

**0.1 Async SQLAlchemy (2–3 дн)**
- [x] Установить `sqlalchemy[asyncio]` и `asyncpg`
- [x] Заменить `SessionLocal` на `async_sessionmaker`
- [x] Переписать `get_db()` как async generator
- [x] Заменить все `db.query()` на `await db.execute(select(...))`
- [x] Особое внимание: `telegram_client.py:627-666` — входящие сообщения

**0.2 In-memory → БД (2–3 дн)**
- [x] Создать таблицу `ui_chats` для хранения состояния чатов
- [x] Создать таблицу `ui_messages` для UI-истории (или использовать `message_history`)
- [x] Заменить `self._messages = deque()` на запросы к БД
- [x] Заменить `self._chats = {}` на запросы к БД
- [x] При старте загружать последние N чатов из БД

**0.3 Атомарный AntiSpam (1–2 дн)**
- [x] Объединить `can_send_message()` + `register_sent_message()` в один метод
- [x] Использовать `asyncio.Lock` или Redis MULTI/EXEC
- [x] Либо: проверка и инкремент в одной SQL-транзакции

**0.4 Персистентный AntiSpam (1–2 дн)**
- [x] Хранить счётчики в Redis (INCR с TTL) или в таблице `anti_spam_counters`
- [x] Ключи: `antispam:hour:{hour}:count`, `antispam:day:{date}:new_chats`
- [x] При старте загружать текущие значения

**0.5 Foreign Keys (0.5–1 дн)**
- [x] Добавить `ForeignKey('chat_mappings.id')` в `MessageHistory.chat_mapping_id`
- [x] Добавить `ondelete='CASCADE'` или `'SET NULL'`
- [x] Создать Alembic миграцию

**0.6 2FA flow persistence (1 дн)**
- [x] Сохранять `phone_code_hash` в Redis с TTL 5 минут
- [x] При submit_code получать hash из Redis
- [x] Очищать после успешной авторизации

**0.7 Code cleanup (1 дн)**
- [x] Удалить дублирующиеся проверки в `api_server.py:1743-1759`
- [x] Убрать неиспользуемый код
- [x] Добавить линтер (ruff/flake8) в CI

**0.8 Audit fixes (NEW)**
- [x] Исправить `api_server.py` undefined variables при `OUTBOX_PROCESS_INLINE=False`
- [x] Исключить двойное MTProto соединение (main без Telegram при `OUTBOX_PROCESS_INLINE=False`)
- [x] Добавить SQLite‑лок для `acquire_next_outbox()` чтобы избежать гонок
- [x] Обновлять `UiMessageHistory.status` после отправки worker'ом
- [x] Проверить `UI_BASIC_AUTH_ENABLED` в `config.py` (есть)
- [x] Персистировать `ui_event_log` в БД

### Шаг 1. Безопасность и доступ
- [x] Ввести Basic Auth для `/ui`, `/ui/auth` и `/api/ui/*`.
- [x] Добавить роли `operator/admin` (через `UI_BASIC_AUTH_USERS`).
- [x] Записывать аудит входов и действий (журнал событий UI).

### Шаг 2. Хранение и очереди
- [x] Добавить таблицы `message_outbox`, `message_delivery_attempts`.
- [x] Реализовать transactional outbox + idempotency.
- [x] Добавить inbox/dedup для webhook.
- [x] Перенести отправку в очередь (Postgres/Redis opensource).

### Шаг 3. Worker и ретраи
- [x] Вынести Telethon в отдельный worker.
- [x] Настроить backoff и классификацию ошибок.
- [x] Дедупликация отправок.
- [x] Обеспечить порядок сообщений на уровне чата.
- [x] **Добавить graceful shutdown** — при SIGTERM дождаться завершения текущих отправок.

### Шаг 4. Персистентная история
- [x] Добавить таблицу `ui_message_history` и запись входящих/исходящих событий.
- [x] UI читает историю из `ui_message_history`.
- [x] Сохранять все входящие/исходящие в БД.
- [x] Статусы доставки (queued/sent/failed).

### Шаг 5. Медиа
- [x] Сохранение медиа в MinIO.
- [x] Привязка в БД + ссылки в UI.

### Шаг 6. Реал-тайм UI
- [x] WebSocket/SSE для новых сообщений и статусов.
- [x] Бейджи статусов доставки.

### Шаг 7. Комплаенс
- [x] Хранить согласия (consent).
- [x] Quiet-hours, opt-out.
- [x] Лимиты антиспама на уровне worker.

### Шаг 8. CRM интеграции
- [x] Валидация webhook.
- [x] Очереди на отправку.
- [x] Ретраи интеграций.

### Шаг 9. Миграции
- [x] Перевести схему на Alembic.
- [x] Контроль версий.

### Шаг 10. Observability
- [x] Метрики Prometheus + Grafana.
- [x] Логи Loki/ELK (opensource).
- [x] Error tracking self-hosted.
- [x] Алерты по здоровью и лимитам.

### Шаг 11. Runbook и бэкапы
- [x] Регламент восстановления.
- [x] Резервное копирование + проверка + backup-drill (RPO/RTO).

### Шаг 12. UI улучшения (NEW)

**12.1 Вынести HTML из Python (1–2 дн)**
- [x] Создать папку `static/` с файлами `ui.html`, `auth.html`, `styles.css`, `app.js`
- [x] Настроить FastAPI `StaticFiles` или отдавать через nginx
- [x] Добавить Cache-Control заголовки
- [x] Минифицировать CSS/JS для production

**12.2 SSE вместо polling (уже в Шаг 6)**
- [x] Убрать `setInterval()` для чатов/сообщений
- [x] Отправлять события через SSE при новом сообщении
- [x] Fallback на polling для старых браузеров

### Шаг 13. Инфраструктура контейнеров (NEW)

**13.1 Telethon session persistence (0.5 дн)**
- [x] Создать PersistentVolumeClaim для `/app/sessions/`
- [x] Или: хранить session в БД (Telethon поддерживает `StringSession`)
- [x] Документировать в README

**13.2 Health checks (0.5 дн)**
- [x] Liveness probe: `/health` возвращает 200
- [x] Readiness probe: проверка Telegram connected + DB connected
- [x] Startup probe: дать время на авторизацию Telethon

---

## Итоговая оценка

### Было (до code review)
| Категория | Задач | Дней |
|-----------|-------|------|
| P0 | 16 | 42–58 |
| P1 | 3 | 9–14 |
| **Итого** | **19** | **51–72** |

### Стало (после code review)
| Категория | Задач | Дней |
|-----------|-------|------|
| P0 (старые) | 16 | 42–58 |
| P0 (новые критические) | 7 | 9–14 |
| P1 (старые) | 3 | 9–14 |
| P1 (новые) | 3 | 2.5–3.5 |
| P2 (новые) | 2 | 2–3 |
| **Итого** | **31** | **64.5–92.5** |

### Рекомендуемый порядок выполнения

```
Фаза 1: Критические исправления (Шаг 0)     ~10 дней
   ↓
Фаза 2: Безопасность (Шаг 1)                ~4 дня
   ↓
Фаза 3: Очереди и Worker (Шаги 2-3)         ~12 дней
   ↓
Фаза 4: Персистентность (Шаги 4-5)          ~7 дней
   ↓
Фаза 5: Realtime UI (Шаг 6)                 ~4 дня
   ↓
Фаза 6: Compliance + CRM (Шаги 7-8)         ~8 дней
   ↓
Фаза 7: DevOps (Шаги 9-11, 13)              ~8 дней
   ↓
Фаза 8: P1/P2 улучшения                     ~12 дней
```

**Минимум для production (P0 only):** ~60 дней
**Полный backlog (P0+P1+P2):** ~80 дней

---

## Архитектура очередей и хранения (сводка)

```
UI (/ui) ─▶ API (FastAPI) ─▶ Outbox (Postgres) ─▶ Queue (Redis)
                      │                            │
                      │                            ▼
                      │                        Worker (Telethon)
                      │                            │
                      ▼                            ▼
              WebSocket/SSE ◀──────── Events ◀── Status/Delivery (Postgres)
```

Компоненты:
- API: FastAPI (UI + REST + webhooks).
- Queue: Postgres (SKIP LOCKED) или Redis Streams (opensource).
- Worker: отдельный сервис, владеет Telethon-сессией.
- DB: Postgres (чат-профили, сообщения, outbox, попытки доставки, согласия).
- Storage: MinIO для медиа.
- Observability: Prometheus/Grafana + Loki/ELK + self-hosted error tracking.

---

## Чек-лист перед production

### Критические (MUST HAVE)
- [x] Async SQLAlchemy — нет блокировок event loop
- [x] История в БД — данные не теряются при рестарте
- [x] Очередь отправки — сообщения не теряются при FloodWait
- [x] Idempotency webhooks — нет дубликатов сообщений
- [x] Атомарный AntiSpam — нет race condition
- [x] Auth для /ui — нет публичного доступа
- [x] Secrets через `*_FILE` — поддержка Docker/K8s secret files
- [x] Data retention — политика хранения + очистка audit log
- [x] Foreign Keys — целостность БД
- [x] Graceful shutdown — нет потерь при деплое
- [x] DR drill чек-лист — `DR_DRILL.md`

### Важные (SHOULD HAVE)
- [x] WebSocket/SSE — realtime UI без polling
- [x] Персистентный AntiSpam — лимиты не обходятся рестартом
- [x] Alembic миграции — контроль схемы БД
- [x] Мониторинг — знаем о проблемах до пользователей
- [x] Бэкапы — RPO/RTO заданы и проверяются
- [x] API rate limiting — защита /api/* по лимитам
- [x] DB indexes review — индексы для горячих запросов

### Улучшения (NICE TO HAVE)
- [x] HTML вынесен из Python
- [x] Мульти-аккаунты MTProto
- [x] Timezone в quiet-hours
- [x] Лимиты per operator
- [x] Admin UI (/admin, /admin/accounts, /admin/settings, templates/tags)
- [x] Нагрузочные тесты (Locust сценарий + PERF_REPORT.md)

---

## Ссылки на проблемные места в коде

Для быстрой навигации:

| Проблема | Путь |
|----------|------|
| In-memory история | `src/telegram_client.py:44` |
| Синхронный SQL | `src/telegram_client.py:627-666` |
| Race condition | `src/antispam.py:39-100` |
| Счётчики в памяти | `src/antispam.py:18-24` |
| Webhook без dedup | `src/api_server.py:1789-1832` |
| Дубликаты кода | `src/api_server.py:1743-1759` |
| Нет FK | `src/database.py:96-97` |
| 2FA state | `src/telegram_client.py:188` |
| Polling UI | `src/api_server.py:1518-1521` |
| HTML inline | `src/api_server.py:21-1525` |
