# План очистки и реорганизации документации

**Дата:** 2026-01-21
**Текущее состояние:** 62 markdown файла в корне проекта
**Цель:** Упростить навигацию и убрать устаревшее/дублирующееся

---

## 📊 Текущая ситуация

**Всего файлов:** 62
**Проблемы:**
- ❌ Слишком много временных "fixes" и "reports" (30+ файлов)
- ❌ Множество дубликатов информации
- ❌ Устаревшие планы и trackers
- ❌ Нет структуры (всё в корне)
- ❌ Сложно найти актуальную документацию

---

## ✅ ЧТО ОСТАВИТЬ (16 файлов)

### Основная документация (13 файлов)
*Эти файлы нужны пользователям и разработчикам*

| Файл | Описание | Статус | Дата |
|------|----------|--------|------|
| `README.md` | Главная страница проекта | ✅ Актуален | Jan 16 |
| `START_HERE.md` | Точка входа для новых пользователей | ✅ Актуален | - |
| `QUICKSTART.md` | Быстрый старт | ✅ Актуален | Jan 16 |
| `ARCHITECTURE.md` | Архитектура системы | ✅ Актуален | Jan 16 |
| `CONFIGURATION.md` | Конфигурация env vars | ✅ Актуален | Jan 16 |
| `DEPLOYMENT.md` | Деплой на production | ✅ Актуален | Jan 19 |
| `API.md` | API endpoints документация | ✅ Актуален | Jan 20 |
| `TESTING.md` | Тестирование | ✅ Актуален | Jan 16 |
| `OBSERVABILITY.md` | Метрики и мониторинг | ✅ Актуален | Jan 15 |
| `RUNBOOK.md` | Операционные процедуры | ✅ Актуален | Jan 16 |
| `MTPROTO_GUIDE.md` | MTProto специфика | ✅ Актуален | Jan 15 |
| `CLAUDE.md` | Инструкции для Claude Code | ✅ Актуален | Jan 20 |
| `UI_GUIDE.md` | UI документация | ✅ Актуален | Jan 16 |

### Change Management (3 файла)
*Релизы и изменения*

| Файл | Описание | Статус |
|------|----------|--------|
| `CHANGELOG.md` | История изменений | ✅ Актуален |
| `RELEASE_NOTES.md` | Заметки к релизам | ✅ Актуален |
| `RELEASE_CHECKLIST.md` | Чеклист релиза | ✅ Актуален |

---

## 📦 АРХИВИРОВАТЬ (30+ файлов)

### Создать: `docs/archive/fixes/`

**Все временные fixes/reports/plans (30 файлов):**

```bash
docs/archive/fixes/
├── contact_manager/
│   ├── CONTACT_MANAGER_FIXES.md
│   ├── CONTACT_MANAGER_FIXES_LOG.md
│   ├── CONTACT_MANAGER_FIXES_ROUND2.md
│   ├── CONTACT_MANAGER_ISSUES.md
│   ├── CONTACT_MANAGER_NEW_ISSUES.md
│   ├── CONTACT_MANAGER_REFACTORING_FINAL.md
│   └── CONTACT_MANAGER_REVIEW_ROUND3.md
├── security/
│   ├── SECURITY_FIXES_PLAN.md
│   ├── SECURITY_FIXES_PROGRESS.md
│   ├── SECURITY_FIXES_REPORT.md
│   └── SECURITY_FIXES_FINAL_REPORT.md
├── critical/
│   ├── CRITICAL_FIXES_PLAN.md
│   ├── CRITICAL_FIXES_REPORT.md
│   ├── CRITICAL_FIXES_FINAL_REPORT.md
│   └── CRITICAL_RACE_FIXES_LOG.md
├── implementation/
│   ├── IMPLEMENTATION_LOG.md
│   ├── IMPLEMENTATION_PLAN.md
│   └── IMPLEMENTATION_PLAN_CONTACT_MANAGER.md
├── quick_fixes/
│   ├── QUICK_FIXES_REPORT.md
│   ├── FIXES_SESSION_REPORT.md
│   ├── CONCURRENCY_FIXES_SUMMARY.md
│   ├── FK_SCHEMA_FIXES_REPORT.md
│   ├── MAPPING_ID_VALIDATION_FIX.md
│   └── HIGH_PRIORITY_FIXES_SESSION_1.md
└── design/
    ├── DESIGN_MIGRATION_PLAN.md
    └── TELEGRAM_CONTACT_MANAGEMENT_DESIGN.md
```

**Команды для архивирования:**
```bash
mkdir -p docs/archive/fixes/{contact_manager,security,critical,implementation,quick_fixes,design}

# Contact Manager
mv CONTACT_MANAGER_*.md docs/archive/fixes/contact_manager/

# Security
mv SECURITY_FIXES_*.md docs/archive/fixes/security/

# Critical
mv CRITICAL_*.md docs/archive/fixes/critical/

# Implementation
mv IMPLEMENTATION_*.md docs/archive/fixes/implementation/

# Quick fixes
mv QUICK_FIXES_REPORT.md FIXES_SESSION_REPORT.md CONCURRENCY_FIXES_SUMMARY.md \
   FK_SCHEMA_FIXES_REPORT.md MAPPING_ID_VALIDATION_FIX.md \
   HIGH_PRIORITY_FIXES_SESSION_1.md docs/archive/fixes/quick_fixes/

# Design
mv DESIGN_MIGRATION_PLAN.md TELEGRAM_CONTACT_MANAGEMENT_DESIGN.md docs/archive/fixes/design/
```

---

## 📂 ПЕРЕМЕСТИТЬ В docs/bitrix24/ (6 файлов)

**Все Bitrix24-специфичные:**

```bash
mkdir -p docs/bitrix24

mv BITRIX24_*.md docs/bitrix24/
```

**Файлы:**
- BITRIX24_MIGRATION_PLAN.md
- BITRIX24_OPENLINES_TROUBLESHOOTING.md
- BITRIX24_OPEN_CHANNELS_SETUP.md
- BITRIX24_READING_STATUS_ISSUE.md
- BITRIX24_STATUS_DELIVERY_FIX.md
- BITRIX24_TROUBLESHOOTING.md

---

## 🗑️ УДАЛИТЬ (5 файлов)

**Устаревшие и дубликаты:**

| Файл | Причина удаления | Заменен на |
|------|-----------------|-----------|
| `IMPROVEMENT_PLAN.md` | Устарел (2886 строк!), создан Jan 16 | `NEED_TO_FIX.md` (актуальный tracker) |
| `PRODUCTION_BLOCKERS.md` | Устарел (449 строк), проблемы уже исправлены | `NEED_TO_FIX.md` |
| `SAFE_TO_FIX.md` | Временный файл | `NEED_TO_FIX.md` |
| `PROD_READY_BACKLOG.md` | Дубликат NEED_TO_FIX.md | `NEED_TO_FIX.md` |
| `TEST_ERRORS_LOG.md` | Временный лог ошибок тестов | Больше не нужен |

**Команда:**
```bash
rm IMPROVEMENT_PLAN.md PRODUCTION_BLOCKERS.md SAFE_TO_FIX.md \
   PROD_READY_BACKLOG.md TEST_ERRORS_LOG.md
```

---

## ⚠️ ПРОВЕРИТЬ НЕОБХОДИМОСТЬ (8 файлов)

**Специальные документы - решить оставить или архивировать:**

| Файл | Размер | Описание | Рекомендация |
|------|--------|----------|--------------|
| `AI_AGENT_SYSTEM_PROMPT.md` | 1298 строк | System prompt для AI агентов | 🔄 Переместить в `docs/agent/` |
| `GLUE_CODING_METHODOLOGY.md` | 1214 строк | Методология разработки | 🔄 Переместить в `docs/methodology/` |
| `AGENT_PERF_ASYNC_SQL_REPORT.md` | ~500 строк | Performance report | 📦 Архивировать в `docs/archive/reports/` |
| `PERF_REPORT.md` | ~300 строк | Performance report | 📦 Архивировать в `docs/archive/reports/` |
| `DR_DRILL.md` | ~200 строк | Disaster Recovery drill | ✅ Оставить или → `docs/operations/` |
| `EXECUTIVE_SUMMARY.md` | ~200 строк | Executive summary | ✅ Оставить (полезен для менеджмента) |
| `TECHNICAL.md` | ~300 строк | Техническая документация | ❓ Проверить дублирует ли ARCHITECTURE.md |
| `FIXES_CHANGELOG.md` | 369 строк | История фиксов | 📦 Слить в CHANGELOG.md или архивировать |

**Рекомендуемые команды:**
```bash
# Agent & Methodology
mkdir -p docs/{agent,methodology,operations,reports}
mv AI_AGENT_SYSTEM_PROMPT.md docs/agent/
mv GLUE_CODING_METHODOLOGY.md docs/methodology/

# Performance reports
mkdir -p docs/archive/reports
mv AGENT_PERF_ASYNC_SQL_REPORT.md PERF_REPORT.md docs/archive/reports/

# Operations
mv DR_DRILL.md docs/operations/

# Проверить вручную:
# - TECHNICAL.md (дубликат ARCHITECTURE.md?)
# - FIXES_CHANGELOG.md (слить в CHANGELOG.md?)
# - EXECUTIVE_SUMMARY.md (оставить в корне?)
```

---

## 🎯 ИТОГОВАЯ СТРУКТУРА

После очистки в корне проекта останется **19-22 файла:**

```
telegram_crm/
├── README.md                    # ✅ Главная страница
├── START_HERE.md               # ✅ Точка входа
├── EXECUTIVE_SUMMARY.md        # ⚠️ Решить оставить?
├── QUICKSTART.md               # ✅ Быстрый старт
├── ARCHITECTURE.md             # ✅ Архитектура
├── CONFIGURATION.md            # ✅ Конфигурация
├── DEPLOYMENT.md               # ✅ Деплой
├── API.md                      # ✅ API docs
├── TESTING.md                  # ✅ Тестирование
├── OBSERVABILITY.md            # ✅ Мониторинг
├── RUNBOOK.md                  # ✅ Операции
├── MTPROTO_GUIDE.md            # ✅ MTProto
├── CLAUDE.md                   # ✅ Claude Code
├── UI_GUIDE.md                 # ✅ UI
├── CHANGELOG.md                # ✅ История изменений
├── RELEASE_NOTES.md            # ✅ Релизы
├── RELEASE_CHECKLIST.md        # ✅ Чеклист
├── NEED_TO_FIX.md              # ✅ Актуальный tracker
├── TECHNICAL.md                # ⚠️ Решить оставить?
├── FIXES_CHANGELOG.md          # ⚠️ Слить в CHANGELOG?
├── docs/
│   ├── agent/
│   │   └── AI_AGENT_SYSTEM_PROMPT.md
│   ├── methodology/
│   │   └── GLUE_CODING_METHODOLOGY.md
│   ├── operations/
│   │   └── DR_DRILL.md
│   ├── bitrix24/
│   │   ├── BITRIX24_MIGRATION_PLAN.md
│   │   ├── BITRIX24_TROUBLESHOOTING.md
│   │   ├── BITRIX24_OPENLINES_TROUBLESHOOTING.md
│   │   ├── BITRIX24_OPEN_CHANNELS_SETUP.md
│   │   ├── BITRIX24_READING_STATUS_ISSUE.md
│   │   └── BITRIX24_STATUS_DELIVERY_FIX.md
│   └── archive/
│       ├── reports/
│       │   ├── AGENT_PERF_ASYNC_SQL_REPORT.md
│       │   └── PERF_REPORT.md
│       └── fixes/
│           ├── contact_manager/ (7 файлов)
│           ├── security/ (4 файла)
│           ├── critical/ (4 файла)
│           ├── implementation/ (3 файла)
│           ├── quick_fixes/ (6 файлов)
│           └── design/ (2 файла)
└── src/
```

---

## 📝 ИТОГО

| Категория | Количество файлов | Действие |
|-----------|-------------------|----------|
| **Оставить в корне** | 16-19 | ✅ Основная документация |
| **Архивировать** | ~30 | 📦 docs/archive/fixes/ |
| **Переместить** | 6 | 📂 docs/bitrix24/ |
| **Удалить** | 5 | 🗑️ Устаревшие дубликаты |
| **Проверить** | 8 | ⚠️ Решить индивидуально |

**Сокращение:** С 62 до 19-22 файлов в корне (**-65%**)

---

## 🚀 План выполнения

### Шаг 1: Создать структуру папок
```bash
mkdir -p docs/{agent,methodology,operations,bitrix24,archive/{reports,fixes/{contact_manager,security,critical,implementation,quick_fixes,design}}}
```

### Шаг 2: Переместить файлы (см. команды выше в каждой секции)

### Шаг 3: Удалить устаревшие
```bash
rm IMPROVEMENT_PLAN.md PRODUCTION_BLOCKERS.md SAFE_TO_FIX.md \
   PROD_READY_BACKLOG.md TEST_ERRORS_LOG.md
```

### Шаг 4: Обновить README.md
Добавить раздел "Документация" с ссылками на основные документы:
```markdown
## 📚 Документация

- [START_HERE.md](START_HERE.md) - Начните здесь
- [QUICKSTART.md](QUICKSTART.md) - Быстрый старт
- [ARCHITECTURE.md](ARCHITECTURE.md) - Архитектура системы
- [CONFIGURATION.md](CONFIGURATION.md) - Конфигурация
- [DEPLOYMENT.md](DEPLOYMENT.md) - Деплой
- [API.md](API.md) - API endpoints
- [UI_GUIDE.md](UI_GUIDE.md) - UI руководство

**Дополнительно:**
- [docs/bitrix24/](docs/bitrix24/) - Bitrix24 интеграция
- [docs/agent/](docs/agent/) - AI Agent документация
- [NEED_TO_FIX.md](NEED_TO_FIX.md) - Известные проблемы и план улучшений
```

### Шаг 5: Проверить ссылки
После перемещения проверить что все внутренние ссылки в документах работают.

---

## ✅ Критерии успеха

- ✅ В корне проекта ≤20 markdown файлов
- ✅ Все основные документы легко найти
- ✅ Временные fixes/reports в архиве
- ✅ Bitrix24 документация в отдельной папке
- ✅ Устаревшие дубликаты удалены
- ✅ README.md обновлен со ссылками

---

**Время выполнения:** ~15-20 минут
**Риски:** Низкие (только перемещение/удаление файлов, код не меняется)
