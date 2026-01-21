# IMPLEMENTATION PLAN - Зеленая зона (73 проблемы)

**Цель:** Исправить все 73 безопасные проблемы без риска для логики отправки сообщений

**Время:** 5-7 дней

**Статус:** 🚀 В процессе

---

## ФАЗА 1: CRITICAL SECURITY (2-3 часа)

### Блок 1.1: Exposed Ports & Redis Password (15 мин)

**Файлы:** `docker-compose.production.yml`

- [ ] #54, #130 - Убрать expose Redis port 6379
- [ ] #131 - Убрать expose Postgres port 5432
- [ ] #129 - Использовать REDIS_PASSWORD в REDIS_URL

**Тесты:** docker-compose config

---

### Блок 1.2: Worker Service (30 мин)

**Файлы:** `docker-compose.production.yml`, `Dockerfile.worker` (новый)

- [ ] #53, #134 - Добавить worker service в docker-compose

**Тесты:** docker-compose up, проверка логов worker

---

### Блок 1.3: Security Hardening (1 час)

**Файлы:** `src/api_server.py`

- [ ] #37 - Rate limiting на UI auth endpoints
- [ ] #132 - Rate limiting на /health
- [ ] #41 - CSRF protection middleware
- [ ] #42 - CORS configuration

**Тесты:** `python3 -m unittest tests.test_ui_api`

---

### Блок 1.4: Grafana & Backup (30 мин)

**Файлы:** `docker-compose.observability.yml`, `scripts/backup.sh`

- [ ] #79 - Сменить Grafana credentials
- [ ] #86 - Исключить .env из бэкапа

**Тесты:** ручная проверка

---

## ФАЗА 2: DOCKER & INFRASTRUCTURE (2-3 часа)

### Блок 2.1: Multi-Stage Docker Build (45 мин)

**Файлы:** `Dockerfile.production`

- [ ] #50, #137 - Multi-stage build
- [ ] #52 - Улучшить health check (curl вместо python)

**Тесты:** docker build, размер образа

---

### Блок 2.2: Logging & Resource Limits (1 час)

**Файлы:** `docker-compose.production.yml`, `Dockerfile.production`

- [ ] #51, #81, #135 - Логи в stdout (убрать volume /app/logs)
- [ ] #56, #138 - Resource limits (memory/CPU)
- [ ] #55, #139 - Log rotation config для Docker

**Тесты:** docker-compose up, проверка логов

---

### Блок 2.3: Postgres Production Config (30 мин)

**Файлы:** `docker-compose.production.yml`

- [ ] #57 - Postgres production параметры (shared_buffers, max_connections, etc)

**Тесты:** docker-compose up postgres

---

### Блок 2.4: Nginx Hardening (45 мин)

**Файлы:** `nginx.conf`

- [ ] #66 - Modern SSL ciphers
- [ ] #67 - SSL session caching
- [ ] #68 - HSTS header
- [ ] #69 - Gzip compression
- [ ] #71 - SSE-specific настройки (proxy_buffering off для /api/ui/stream)

**Тесты:** nginx -t, curl проверка headers

---

## ФАЗА 3: OBSERVABILITY (2-3 часа)

### Блок 3.1: Health Endpoints (45 мин)

**Файлы:** `src/api_server.py`

- [ ] #83 - /ready endpoint (проверка DB, Redis)
- [ ] #84 - /startup endpoint
- [ ] #85 - Health check с Redis проверкой

**Тесты:** `curl http://localhost:8000/ready`, `curl http://localhost:8000/startup`

---

### Блок 3.2: Correlation ID (30 мин)

**Файлы:** `src/api_server.py`, `src/logger.py`

- [ ] #82 - Request correlation ID middleware
- [ ] Добавить correlation_id в логи

**Тесты:** `python3 -m unittest tests.test_ui_api`, проверка логов

---

### Блок 3.3: Prometheus Alerts (1 час)

**Файлы:** `observability/alert.rules.yml`

- [ ] #76 - Добавить 10+ алертов:
  - High error rate
  - OutboxWorker not processing
  - Redis down
  - Postgres connections high
  - Telegram FloodWait errors
  - High latency
  - Memory usage
  - CPU usage
  - Disk usage
  - Failed auth attempts

**Тесты:** promtool check rules

---

### Блок 3.4: Alertmanager & Dashboards (1 час)

**Файлы:** `observability/alertmanager.yml`, `observability/dashboards/`

- [ ] #77 - Alertmanager webhook на production URL
- [ ] #80 - Создать Grafana dashboards (API, Outbox, Telegram)
- [ ] #78 - Prometheus persistence volume

**Тесты:** docker-compose up observability stack

---

## ФАЗА 4: DATABASE SCHEMA SAFE (1-2 часа)

### Блок 4.1: Индексы и Constraints (1 час)

**Файлы:** `alembic/versions/20260120_safe_schema_improvements.py` (новый)

- [ ] #34 - Индекс на (account_id, created_at) для MessageHistory
- [ ] #35 - Композитный индекс (status, next_attempt_at) для MessageOutbox
- [ ] #108 - Композитный индекс (status, next_attempt_at, chat_id)
- [ ] #109 - Индекс на (direction, created_at) для MessageHistory
- [ ] #107, #32 - CHECK constraints для статусов (queued/processing/sent/failed/dead)
- [ ] #106 - Убрать дублирование индексов (удалить index=True если есть в __table_args__)

**Тесты:** `python3 -m alembic upgrade head`, `python3 -m unittest`

---

### Блок 4.2: Updated_at Triggers (30 мин)

**Файлы:** `alembic/versions/20260120_add_onupdate_triggers.py` (новый)

- [ ] #104, #33 - Добавить onupdate=datetime.utcnow для TelegramSession.updated_at

**Тесты:** `python3 -m alembic upgrade head`

---

## ФАЗА 5: ERROR HANDLING (1-2 часа)

### Блок 5.1: HTTP Error Handling (45 мин)

**Файлы:** `src/api_server.py`

- [ ] #25 - Generic HTTP ошибки (не выдавать str(e))
- [ ] #26 - JSON parsing try-except в webhooks (строки 879, 1135)
- [ ] #24 - Убрать bare except (строки 676, 3147)

**Тесты:** `python3 -m unittest tests.test_ui_api`

---

### Блок 5.2: CRM Error Handling (45 мин)

**Файлы:** `src/amocrm_client.py`, `src/bitrix24_client.py`

- [ ] #46, #127 - Обработка 429 Too Many Requests (retry с exponential backoff)
- [ ] #47 - Обработка пустого ответа API
- [ ] #48 - Validation структуры ответа
- [ ] #49 - Парсинг URL exception

**Тесты:** мануальные тесты с mock CRM API

---

### Блок 5.3: Other Error Handling (30 мин)

**Файлы:** `src/redis_client.py`, `src/retention.py`

- [ ] #125 - Убрать bare except в redis_client
- [ ] #126 - Добавить rollback в retention при ошибке

**Тесты:** `python3 -m unittest`

---

## ФАЗА 6: KUBERNETES & CI/CD (2-3 часа)

### Блок 6.1: K8s Manifests (2 часа)

**Файлы:** `k8s/deployment.yaml` (новый), `k8s/service.yaml` (новый), `k8s/ingress.yaml` (новый)

- [ ] #58 - Service/Ingress manifests
- [ ] #59 - livenessProbe, readinessProbe, startupProbe
- [ ] #60 - Resource limits/requests
- [ ] #61 - Убрать :latest tag, использовать semantic versioning
- [ ] #62 - securityContext (runAsNonRoot, readOnlyRootFilesystem)
- [ ] #63 - PVC с StorageClass
- [ ] #64 - Worker pod deployment
- [ ] #65 - HPA (Horizontal Pod Autoscaler), PDB (Pod Disruption Budget)

**Тесты:** kubectl apply --dry-run

---

### Блок 6.2: CI/CD Pipeline (1 час)

**Файлы:** `.github/workflows/ci.yml`

- [ ] #72 - Тесты на PostgreSQL в CI
- [ ] #73 - Docker build & push в registry
- [ ] #74 - Security scanning (bandit для Python, trivy для Docker)
- [ ] #75 - Deployment stage (опционально)

**Тесты:** git push, проверка GitHub Actions

---

## ФАЗА 7: BACKUP & SECURITY (1 час)

### Блок 7.1: Backup Improvements (1 час)

**Файлы:** `scripts/backup.sh`, `scripts/restore.sh` (новый)

- [ ] #87 - Инкрементальные бэкапы (pg_basebackup + WAL архивирование)
- [ ] #88 - Проверка integrity (pg_verifybackup)
- [ ] #89 - Retention policy (удаление старых > 30 дней)
- [ ] #90 - Шифрование бэкапов (gpg)

**Тесты:** ручной запуск backup.sh, restore.sh

---

### Блок 7.2: Data Encryption at Rest (опционально, 2 часа)

**Файлы:** `src/crypto.py` (новый), `src/app_settings.py`, `src/database.py`

- [ ] #38 - Шифрование токенов CRM в БД (Fernet)
- [ ] #39, #133 - Шифрование session_string в БД (Fernet)
- [ ] #44 - Валидация типов при hot-reload

**Тесты:** `python3 -m unittest`, проверка что старые данные читаются

---

## ФАЗА 8: CODE QUALITY (опционально, 2-3 часа)

### Блок 8.1: Enum для статусов (1 час)

**Файлы:** `src/models.py` (новый), все файлы использующие статусы

- [ ] Создать Enum для MessageStatus, Direction

**Тесты:** `python3 -m unittest`

---

### Блок 8.2: Type Hints & Docstrings (2 часа)

**Файлы:** все src/*.py

- [ ] Добавить type hints для функций без них
- [ ] Добавить docstrings для публичных функций

**Тесты:** mypy src/

---

## ИТОГОВОЕ ТЕСТИРОВАНИЕ

### Блок 9.1: Unit Tests

```bash
# SQLite
python3 -m unittest discover -s tests

# PostgreSQL
DATABASE_URL=postgresql://postgres:pass@localhost:5432/test \
DB_ALLOW_CREATE_ALL=true \
DB_USE_NULL_POOL=true \
python3 -m unittest discover -s tests
```

---

### Блок 9.2: Integration Tests

```bash
# Запуск всего стека
docker-compose -f docker-compose.production.yml up -d

# Проверка health
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/startup

# Проверка metrics
curl http://localhost:8000/metrics

# Проверка worker logs
docker-compose logs -f worker
```

---

### Блок 9.3: Load Tests

```bash
locust -f tests/load/locustfile.py --host http://localhost:8000
```

---

## ДОКУМЕНТАЦИЯ ИЗМЕНЕНИЙ

**Файл:** `CHANGELOG.md` (обновить)

Все изменения документировать в формате:

```markdown
## [Unreleased]

### Security
- Убраны exposed ports для Redis и Postgres (#130, #131)
- Добавлен rate limiting на UI auth (#37)
- Добавлен CORS и CSRF protection (#41, #42)

### Infrastructure
- Добавлен worker service (#53, #134)
- Multi-stage Docker build (#50, #137)
- Resource limits для контейнеров (#56, #138)

### Observability
- Добавлены /ready и /startup endpoints (#83, #84)
- Correlation ID для request tracing (#82)
- 10+ Prometheus alerts (#76)

### Database
- Оптимизированы индексы (#34, #35, #108, #109)
- Добавлены CHECK constraints (#107)

### Fixes
- Generic HTTP errors (#25)
- CRM API retry logic (#46, #127)
```

---

## СТАТУС ВЫПОЛНЕНИЯ

| Фаза | Блоки | Проблем | Время | Статус |
|------|-------|---------|-------|--------|
| 1. Critical Security | 4 | 11 | 2-3ч | ⏳ TODO |
| 2. Docker & Infra | 4 | 15 | 2-3ч | ⏳ TODO |
| 3. Observability | 4 | 11 | 2-3ч | ⏳ TODO |
| 4. DB Schema Safe | 2 | 12 | 1-2ч | ⏳ TODO |
| 5. Error Handling | 3 | 12 | 1-2ч | ⏳ TODO |
| 6. K8s & CI/CD | 2 | 12 | 2-3ч | ⏳ TODO |
| 7. Backup & Security | 2 | 5 | 1ч | ⏳ TODO |
| 8. Code Quality | 2 | - | 2-3ч | 📋 Optional |
| **ИТОГО** | **23** | **73+** | **12-18ч** | |

---

## ПОРЯДОК ВЫПОЛНЕНИЯ

**Рекомендуемый порядок (по приоритету):**

1. ✅ Фаза 1: Critical Security (MUST - критичные уязвимости)
2. ✅ Фаза 2.2: Worker Service (MUST - очередь не работает)
3. ✅ Фаза 3: Observability (HIGH - нужна видимость)
4. ✅ Фаза 2: Docker & Infra (HIGH)
5. ✅ Фаза 4: DB Schema (MEDIUM)
6. ✅ Фаза 5: Error Handling (MEDIUM)
7. ⚠️ Фаза 6: K8s & CI/CD (OPTIONAL - если используется K8s)
8. ⚠️ Фаза 7: Backup (MEDIUM)
9. ⚠️ Фаза 8: Code Quality (LOW - nice to have)

---

*Создано: 2026-01-20*
*Статус: В процессе*
