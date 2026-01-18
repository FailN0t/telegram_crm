# План Миграции: AmoCRM → Bitrix24 CRM

**Дата создания:** 2026-01-17
**Оценка времени:** 2-3 дня
**Сложность:** Средняя

---

## Содержание

1. [Обзор изменений](#1-обзор-изменений)
2. [Различия API](#2-различия-api)
3. [Детальный план по файлам](#3-детальный-план-по-файлам)
4. [Порядок выполнения](#4-порядок-выполнения)
5. [Миграция данных](#5-миграция-данных)
6. [Тестирование](#6-тестирование)
7. [Rollback план](#7-rollback-план)

---

## 1. Обзор изменений

### Файлы для изменения

| Файл | Действие | Сложность | Время |
|------|----------|-----------|-------|
| `src/bitrix24_client.py` | **Создать** | Высокая | 3-4 ч |
| `src/config.py` | Изменить | Низкая | 30 мин |
| `src/bridge.py` | Изменить | Средняя | 2 ч |
| `src/api_server.py` | Изменить | Средняя | 2 ч |
| `src/database.py` | Изменить | Низкая | 1 ч |
| `src/main.py` | Изменить | Низкая | 30 мин |
| `src/outbox_worker.py` | Изменить | Низкая | 30 мин |
| `alembic/versions/xxx_bitrix24_migration.py` | **Создать** | Низкая | 30 мин |
| `tests/test_bitrix24_*.py` | **Создать** | Средняя | 2 ч |

**Итого:** ~12-14 часов работы

### Что сохраняется без изменений

- `src/telegram_manager.py` - Telegram логика не меняется
- `src/telegram_client.py` - MTProto клиент остаётся
- `src/antispam.py` - Rate limiting остаётся
- `src/redis_client.py` - Redis остаётся
- `src/logger.py` - Логирование остаётся

---

## 2. Различия API

### Аутентификация

| Аспект | AmoCRM | Bitrix24 |
|--------|--------|----------|
| OAuth Flow | Standard OAuth 2.0 | OAuth 2.0 + Webhook |
| Token URL | `/oauth2/access_token` | `/oauth/token/` |
| API Base | `/api/v4/` | `/rest/` |
| Auth Header | `Bearer {token}` | `?auth={token}` или Header |

### Контакты

```
AmoCRM:
  GET  /api/v4/contacts?query={phone}
  GET  /api/v4/contacts/{id}
  PATCH /api/v4/contacts/{id}

Bitrix24:
  POST /rest/crm.contact.list (filter, select)
  POST /rest/crm.contact.get (id)
  POST /rest/crm.contact.update (id, fields)
```

### Задачи / Активности

```
AmoCRM:
  GET  /api/v4/tasks/{id}
  PATCH /api/v4/tasks/{id} (is_completed: true)

Bitrix24 (CRM Activities):
  POST /rest/crm.activity.get (id)
  POST /rest/crm.activity.update (id, fields)
  # или Tasks API:
  POST /rest/tasks.task.get (taskId)
  POST /rest/tasks.task.complete (taskId)
```

### Примечания / Timeline

```
AmoCRM:
  POST /api/v4/contacts/{id}/notes

Bitrix24:
  POST /rest/crm.timeline.comment.add
  {
    "fields": {
      "ENTITY_ID": contact_id,
      "ENTITY_TYPE": "contact",
      "COMMENT": "text"
    }
  }
```

### Custom Fields

```
AmoCRM:
  custom_fields_values: [
    { field_id: 123, values: [{ value: "..." }] }
  ]

Bitrix24:
  UF_CRM_TELEGRAM_USERNAME: "..."
  UF_CRM_TELEGRAM_CHAT_ID: "..."
  # User Fields с префиксом UF_
```

### Webhooks

```
AmoCRM:
  Content-Type: application/json
  Body: { "tasks": { "add": [...] } }

Bitrix24:
  Content-Type: application/x-www-form-urlencoded
  Body: event=ONCRMACTIVITYADD&data[FIELDS][ID]=123&...
  # или JSON в некоторых случаях
```

---

## 3. Детальный план по файлам

### 3.1 src/config.py

**Действие:** Добавить Bitrix24 настройки, убрать AmoCRM

```python
# УДАЛИТЬ (строки 50-63):
AMOCRM_DOMAIN: Optional[str]
AMOCRM_CLIENT_ID: Optional[str]
AMOCRM_CLIENT_SECRET: Optional[str]
AMOCRM_REDIRECT_URI: Optional[str]
AMOCRM_ACCESS_TOKEN: Optional[str]
AMOCRM_REFRESH_TOKEN: Optional[str]
AMOCRM_TOKEN_EXPIRES_AT: Optional[str]
AMOCRM_WEBHOOK_SECRET: Optional[str]
AMOCRM_FIELD_TELEGRAM_USERNAME: int
AMOCRM_FIELD_TELEGRAM_CHAT_ID: int
AMOCRM_FIELD_TELEGRAM_CONSENT: int

# ДОБАВИТЬ:
# Bitrix24 CRM
BITRIX24_DOMAIN: Optional[str] = Field(default=None, env="BITRIX24_DOMAIN")
BITRIX24_CLIENT_ID: Optional[str] = Field(default=None, env="BITRIX24_CLIENT_ID")
BITRIX24_CLIENT_SECRET: Optional[str] = Field(default=None, env="BITRIX24_CLIENT_SECRET")
BITRIX24_REDIRECT_URI: Optional[str] = Field(default=None, env="BITRIX24_REDIRECT_URI")
BITRIX24_ACCESS_TOKEN: Optional[str] = Field(default=None, env="BITRIX24_ACCESS_TOKEN")
BITRIX24_REFRESH_TOKEN: Optional[str] = Field(default=None, env="BITRIX24_REFRESH_TOKEN")
BITRIX24_TOKEN_EXPIRES_AT: Optional[str] = Field(default=None, env="BITRIX24_TOKEN_EXPIRES_AT")
BITRIX24_WEBHOOK_SECRET: Optional[str] = Field(default=None, env="BITRIX24_WEBHOOK_SECRET")

# Bitrix24 может использовать входящий webhook вместо OAuth
BITRIX24_WEBHOOK_URL: Optional[str] = Field(default=None, env="BITRIX24_WEBHOOK_URL")

# Bitrix24 User Fields (UF_*)
BITRIX24_FIELD_TELEGRAM_USERNAME: str = Field(
    default="UF_CRM_TELEGRAM_USERNAME",
    env="BITRIX24_FIELD_TELEGRAM_USERNAME"
)
BITRIX24_FIELD_TELEGRAM_CHAT_ID: str = Field(
    default="UF_CRM_TELEGRAM_CHAT_ID",
    env="BITRIX24_FIELD_TELEGRAM_CHAT_ID"
)
BITRIX24_FIELD_TELEGRAM_CONSENT: str = Field(
    default="UF_CRM_TELEGRAM_CONSENT",
    env="BITRIX24_FIELD_TELEGRAM_CONSENT"
)

# Также изменить APP_NAME:
APP_NAME: str = "Bitrix24-Telegram-MTProto"
```

---

### 3.2 src/bitrix24_client.py (СОЗДАТЬ)

**Полная структура нового клиента:**

```python
"""
Bitrix24 CRM API клиент
Интеграция с Bitrix24 для работы с контактами и активностями
"""

import asyncio
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from urllib.parse import urlencode
import aiohttp

from src.config import settings
from src.logger import logger


class Bitrix24Client:
    """
    Клиент для работы с Bitrix24 REST API
    Поддерживает OAuth 2.0 и входящие webhooks
    """

    def __init__(self):
        self.domain = settings.BITRIX24_DOMAIN
        self.client_id = settings.BITRIX24_CLIENT_ID
        self.client_secret = settings.BITRIX24_CLIENT_SECRET
        self.redirect_uri = settings.BITRIX24_REDIRECT_URI
        self.webhook_url = settings.BITRIX24_WEBHOOK_URL

        self.access_token = settings.BITRIX24_ACCESS_TOKEN
        self.refresh_token = settings.BITRIX24_REFRESH_TOKEN
        self.token_expires_at = None

        if settings.BITRIX24_TOKEN_EXPIRES_AT:
            try:
                self.token_expires_at = datetime.fromisoformat(
                    settings.BITRIX24_TOKEN_EXPIRES_AT.replace("Z", "")
                )
            except ValueError:
                pass

        # Базовый URL зависит от режима (OAuth или Webhook)
        if self.webhook_url:
            self.base_url = self.webhook_url
            self.use_webhook = True
        else:
            self.base_url = f"https://{self.domain}/rest"
            self.use_webhook = False

        logger.info(f"🔗 Bitrix24 клиент инициализирован: {self.domain}")

    # === OAuth методы ===

    async def _save_tokens(self) -> None:
        """Сохранение токенов в настройки"""
        ...

    async def ensure_token_valid(self) -> bool:
        """Проверка и обновление токена"""
        ...

    async def refresh_access_token(self) -> bool:
        """Обновление access token через refresh token"""
        ...

    async def exchange_auth_code(self, code: str) -> bool:
        """Обмен authorization code на токены"""
        ...

    # === API методы ===

    async def _call_method(self, method: str, params: Dict = None) -> Optional[Dict]:
        """
        Универсальный вызов Bitrix24 REST API

        Args:
            method: Название метода (например, "crm.contact.get")
            params: Параметры запроса

        Returns:
            Dict с результатом или None при ошибке
        """
        ...

    async def find_contact_by_phone(self, phone: str) -> Optional[Dict]:
        """
        Поиск контакта по телефону

        Bitrix24 API: crm.contact.list
        """
        return await self._call_method("crm.contact.list", {
            "filter": {"PHONE": phone},
            "select": ["ID", "NAME", "LAST_NAME", "PHONE", "EMAIL",
                       settings.BITRIX24_FIELD_TELEGRAM_USERNAME,
                       settings.BITRIX24_FIELD_TELEGRAM_CHAT_ID]
        })

    async def find_contact_by_id(self, contact_id: int) -> Optional[Dict]:
        """
        Получение контакта по ID

        Bitrix24 API: crm.contact.get
        """
        return await self._call_method("crm.contact.get", {"id": contact_id})

    async def get_contact_field(self, contact_id: int, field_name: str) -> Optional[str]:
        """
        Получение значения user field контакта

        Args:
            contact_id: ID контакта
            field_name: Название UF поля (например, "UF_CRM_TELEGRAM")
        """
        contact = await self.find_contact_by_id(contact_id)
        if contact:
            return contact.get("result", {}).get(field_name)
        return None

    async def update_contact_field(
        self,
        contact_id: int,
        field_name: str,
        value: str
    ) -> bool:
        """
        Обновление user field контакта

        Bitrix24 API: crm.contact.update
        """
        result = await self._call_method("crm.contact.update", {
            "id": contact_id,
            "fields": {field_name: value}
        })
        return result is not None and result.get("result", False)

    async def add_timeline_comment(self, contact_id: int, text: str) -> bool:
        """
        Добавление комментария в timeline контакта

        Bitrix24 API: crm.timeline.comment.add
        """
        result = await self._call_method("crm.timeline.comment.add", {
            "fields": {
                "ENTITY_ID": contact_id,
                "ENTITY_TYPE": "contact",
                "COMMENT": f"📱 Telegram (MTProto): {text}"
            }
        })
        return result is not None and result.get("result", 0) > 0

    async def get_activity(self, activity_id: int) -> Optional[Dict]:
        """
        Получение CRM активности по ID

        Bitrix24 API: crm.activity.get
        """
        return await self._call_method("crm.activity.get", {"id": activity_id})

    async def complete_activity(self, activity_id: int) -> bool:
        """
        Завершение CRM активности

        Bitrix24 API: crm.activity.update
        """
        result = await self._call_method("crm.activity.update", {
            "id": activity_id,
            "fields": {"COMPLETED": "Y"}
        })
        return result is not None and result.get("result", False)

    # === Альтернативно: Tasks API ===

    async def get_task(self, task_id: int) -> Optional[Dict]:
        """
        Получение задачи по ID (Tasks module)

        Bitrix24 API: tasks.task.get
        """
        return await self._call_method("tasks.task.get", {"taskId": task_id})

    async def complete_task(self, task_id: int) -> bool:
        """
        Завершение задачи

        Bitrix24 API: tasks.task.complete
        """
        result = await self._call_method("tasks.task.complete", {"taskId": task_id})
        return result is not None
```

---

### 3.3 src/bridge.py

**Изменения:**

```python
# ЗАМЕНИТЬ импорт:
- from src.amocrm_client import AmoCRMClient
+ from src.bitrix24_client import Bitrix24Client

# ЗАМЕНИТЬ в __init__:
- self.amocrm = amocrm
+ self.bitrix24 = bitrix24

# ЗАМЕНИТЬ в методах:
- await self.amocrm.find_contact_by_id(contact_id)
+ await self.bitrix24.find_contact_by_id(contact_id)

- await self.amocrm.create_note(contact_id, text)
+ await self.bitrix24.add_timeline_comment(contact_id, text)

- await self.amocrm.get_task(task_id)
+ await self.bitrix24.get_activity(task_id)

- await self.amocrm.complete_task(task_id)
+ await self.bitrix24.complete_activity(task_id)

# ИЗМЕНИТЬ извлечение полей контакта:
# AmoCRM использует custom_fields_values[{field_id: X}]
# Bitrix24 использует прямые поля UF_*

- phone = self._extract_custom_field(contact, settings.AMOCRM_FIELD_TELEGRAM_USERNAME)
+ phone = contact.get(settings.BITRIX24_FIELD_TELEGRAM_USERNAME)
```

---

### 3.4 src/api_server.py

**Изменения:**

```python
# 1. Переименовать endpoint:
- @app.post("/api/webhook/amocrm")
+ @app.post("/api/webhook/bitrix24")

# 2. Изменить парсинг webhook:
# Bitrix24 отправляет form-urlencoded или JSON

async def webhook_bitrix24(request: Request):
    content_type = request.headers.get("content-type", "")

    if "application/x-www-form-urlencoded" in content_type:
        form_data = await request.form()
        event = form_data.get("event")
        data = dict(form_data)
    else:
        data = await request.json()
        event = data.get("event")

    # Обработка событий:
    # - ONCRMACTIVITYADD - новая активность
    # - ONTASKADD - новая задача

# 3. OAuth endpoints:
- /api/admin/amocrm/status
- /api/admin/amocrm/oauth/url
- /api/admin/amocrm/oauth/callback
+ /api/admin/bitrix24/status
+ /api/admin/bitrix24/oauth/url
+ /api/admin/bitrix24/oauth/callback
```

---

### 3.5 src/database.py

**Изменения в моделях:**

```python
# ChatMapping:
- amocrm_contact_id = Column(Integer, unique=True, index=True)
+ bitrix24_contact_id = Column(Integer, unique=True, index=True)

# MessageHistory:
- amocrm_contact_id = Column(Integer, index=True)
- amocrm_note_id = Column(Integer, nullable=True)
- amocrm_task_id = Column(Integer, nullable=True)
+ bitrix24_contact_id = Column(Integer, index=True)
+ bitrix24_comment_id = Column(Integer, nullable=True)
+ bitrix24_activity_id = Column(Integer, nullable=True)
```

---

### 3.6 src/main.py

**Изменения:**

```python
# ЗАМЕНИТЬ импорт:
- from src.amocrm_client import AmoCRMClient
+ from src.bitrix24_client import Bitrix24Client

# ЗАМЕНИТЬ инициализацию:
- if settings.AMOCRM_DOMAIN and settings.AMOCRM_CLIENT_ID:
-     self.amocrm = AmoCRMClient()
+ if settings.BITRIX24_DOMAIN or settings.BITRIX24_WEBHOOK_URL:
+     self.bitrix24 = Bitrix24Client()
```

---

### 3.7 src/outbox_worker.py

**Изменения:**

```python
# ЗАМЕНИТЬ импорт:
- from src.amocrm_client import AmoCRMClient
+ from src.bitrix24_client import Bitrix24Client

# ЗАМЕНИТЬ инициализацию:
- self.amocrm = AmoCRMClient()
+ self.bitrix24 = Bitrix24Client()

# ЗАМЕНИТЬ в process_payload:
- if source == "amocrm_webhook":
+ if source == "bitrix24_webhook":
```

---

### 3.8 Alembic миграция

**Создать:** `alembic/versions/20260117_bitrix24_migration.py`

```python
"""Migrate from AmoCRM to Bitrix24 field names.

Revision ID: 20260117_bitrix24_migration
Revises: 20260116_add_foreign_key_constraints
"""

from alembic import op
import sqlalchemy as sa


def upgrade():
    # Переименование колонок
    op.alter_column('chat_mappings', 'amocrm_contact_id',
                    new_column_name='bitrix24_contact_id')

    op.alter_column('message_history', 'amocrm_contact_id',
                    new_column_name='bitrix24_contact_id')

    op.alter_column('message_history', 'amocrm_note_id',
                    new_column_name='bitrix24_comment_id')

    op.alter_column('message_history', 'amocrm_task_id',
                    new_column_name='bitrix24_activity_id')

    # Переименование индексов (опционально)
    # op.drop_index('idx_chat_mappings_amocrm_contact_id')
    # op.create_index('idx_chat_mappings_bitrix24_contact_id', ...)


def downgrade():
    op.alter_column('chat_mappings', 'bitrix24_contact_id',
                    new_column_name='amocrm_contact_id')

    op.alter_column('message_history', 'bitrix24_contact_id',
                    new_column_name='amocrm_contact_id')

    op.alter_column('message_history', 'bitrix24_comment_id',
                    new_column_name='amocrm_note_id')

    op.alter_column('message_history', 'bitrix24_activity_id',
                    new_column_name='amocrm_task_id')
```

---

## 4. Порядок выполнения

### Фаза 1: Подготовка (1-2 часа)

1. [ ] Создать ветку `feature/bitrix24-migration`
2. [ ] Обновить `src/config.py` с Bitrix24 настройками
3. [ ] Создать `.env.example` с новыми переменными

### Фаза 2: Клиент Bitrix24 (3-4 часа)

4. [ ] Создать `src/bitrix24_client.py`
5. [ ] Реализовать OAuth flow
6. [ ] Реализовать методы контактов
7. [ ] Реализовать методы активностей/задач
8. [ ] Реализовать timeline comments
9. [ ] Написать unit тесты для клиента

### Фаза 3: Интеграция (3-4 часа)

10. [ ] Обновить `src/bridge.py`
11. [ ] Обновить `src/api_server.py` endpoints
12. [ ] Обновить `src/main.py`
13. [ ] Обновить `src/outbox_worker.py`

### Фаза 4: База данных (1 час)

14. [ ] Обновить `src/database.py` модели
15. [ ] Создать Alembic миграцию
16. [ ] Протестировать миграцию на тестовой БД

### Фаза 5: Тестирование (2-3 часа)

17. [ ] Создать `tests/test_bitrix24_client.py`
18. [ ] Создать `tests/test_bitrix24_webhook.py`
19. [ ] Обновить существующие тесты
20. [ ] Integration testing с реальным Bitrix24

### Фаза 6: Документация (1 час)

21. [ ] Обновить README.md
22. [ ] Обновить IMPROVEMENT_PLAN.md
23. [ ] Создать BITRIX24_SETUP.md

---

## 5. Миграция данных

### Если есть production данные:

```sql
-- Шаг 1: Backup
pg_dump -t chat_mappings -t message_history > backup_before_bitrix24.sql

-- Шаг 2: Проверить данные
SELECT COUNT(*) FROM chat_mappings WHERE amocrm_contact_id IS NOT NULL;
SELECT COUNT(*) FROM message_history WHERE amocrm_contact_id IS NOT NULL;

-- Шаг 3: Миграция (через Alembic)
alembic upgrade head
```

### Очистка (если начинаем с нуля):

```sql
-- Удалить AmoCRM данные
UPDATE chat_mappings SET amocrm_contact_id = NULL;
TRUNCATE message_history;
```

---

## 6. Тестирование

### Unit тесты

```python
# tests/test_bitrix24_client.py

class TestBitrix24Client:
    async def test_find_contact_by_phone(self):
        ...

    async def test_find_contact_by_id(self):
        ...

    async def test_add_timeline_comment(self):
        ...

    async def test_complete_activity(self):
        ...
```

### Integration тесты

```python
# tests/test_bitrix24_webhook.py

class TestBitrix24Webhook:
    def test_webhook_activity_add(self):
        """Тест обработки ONCRMACTIVITYADD"""
        ...

    def test_webhook_deduplication(self):
        """Тест дедупликации webhook"""
        ...
```

### Manual тесты

1. [ ] OAuth авторизация в Bitrix24
2. [ ] Создание активности в Bitrix24 → получение в webhook
3. [ ] Отправка сообщения → появление в timeline Bitrix24
4. [ ] Поиск контакта по телефону
5. [ ] Обновление UF полей

---

## 7. Rollback план

### Если нужно откатить:

```bash
# 1. Откатить миграцию БД
alembic downgrade -1

# 2. Вернуть код
git checkout main -- src/

# 3. Перезапустить сервис
systemctl restart telegram-crm
```

### Точка невозврата

После выполнения Alembic миграции на production, откат потребует:
- Восстановление данных из backup
- Откат кода

**Рекомендация:** Делать migration на staging первым.

---

## Переменные окружения

### Новый .env файл:

```bash
# === Bitrix24 CRM ===

# Домен (xxx.bitrix24.ru или xxx.bitrix24.com)
BITRIX24_DOMAIN=mycompany.bitrix24.ru

# OAuth приложение (если используется)
BITRIX24_CLIENT_ID=local.xxxxx
BITRIX24_CLIENT_SECRET=xxxxx
BITRIX24_REDIRECT_URI=https://myapp.com/api/admin/bitrix24/oauth/callback

# Токены (заполняются после OAuth)
BITRIX24_ACCESS_TOKEN=
BITRIX24_REFRESH_TOKEN=
BITRIX24_TOKEN_EXPIRES_AT=

# ИЛИ Входящий webhook (проще настроить)
BITRIX24_WEBHOOK_URL=https://mycompany.bitrix24.ru/rest/1/xxxxx/

# Webhook secret для исходящих webhook
BITRIX24_WEBHOOK_SECRET=your-secret-key

# User Fields (UF) для Telegram данных
BITRIX24_FIELD_TELEGRAM_USERNAME=UF_CRM_TELEGRAM_USERNAME
BITRIX24_FIELD_TELEGRAM_CHAT_ID=UF_CRM_TELEGRAM_CHAT_ID
BITRIX24_FIELD_TELEGRAM_CONSENT=UF_CRM_TELEGRAM_CONSENT
```

---

## Готово к реализации

План создан. Следующий шаг: создание `src/bitrix24_client.py`.
