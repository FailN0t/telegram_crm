# Техничка: окружение, диагностика и эксплуатация

## 1) Полная таблица `.env`

| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `TELEGRAM_API_ID` | да | API ID из https://my.telegram.org | `12345678` |
| `TELEGRAM_API_HASH` | да | API Hash из https://my.telegram.org | `0123456789abcdef0123456789abcdef` |
| `TELEGRAM_PHONE` | да | Телефон аккаунта Telegram (с `+`) | `+79991234567` |
| `TELEGRAM_SESSION_NAME` | нет | Имя файла сессии Telethon | `amocrm_session` |
| `TELEGRAM_STRING_SESSION` | нет | StringSession (опционально, если храните в БД) | `1A...` |
| `AMOCRM_DOMAIN` | нет | Домен AmoCRM | `example.amocrm.ru` |
| `AMOCRM_CLIENT_ID` | нет | Client ID AmoCRM OAuth | `client_id` |
| `AMOCRM_CLIENT_SECRET` | нет | Client Secret AmoCRM OAuth | `client_secret` |
| `AMOCRM_REDIRECT_URI` | нет | Redirect URI для OAuth | `https://your-app.example.com/oauth/callback` |
| `AMOCRM_ACCESS_TOKEN` | нет | Access token AmoCRM | `access_token` |
| `AMOCRM_REFRESH_TOKEN` | нет | Refresh token AmoCRM | `refresh_token` |
| `AMOCRM_WEBHOOK_SECRET` | нет | Secret для проверки webhook | `secret` |
| `AMOCRM_FIELD_TELEGRAM_USERNAME` | нет | ID поля username в AmoCRM | `123456` |
| `AMOCRM_FIELD_TELEGRAM_CHAT_ID` | нет | ID поля chat_id в AmoCRM | `123457` |
| `AMOCRM_FIELD_TELEGRAM_CONSENT` | нет | ID поля consent в AmoCRM | `123458` |
| `DATABASE_URL` | да | Строка подключения Postgres | `postgresql://postgres:password@localhost:5432/telegram_bot` |
| `DB_ALLOW_CREATE_ALL` | нет | Разрешить `create_all` (только для dev/SQLite) | `false` |
| `POSTGRES_USER` | нет | Пользователь Postgres (docker) | `postgres` |
| `POSTGRES_PASSWORD` | нет | Пароль Postgres (docker) | `changeme` |
| `POSTGRES_DB` | нет | База Postgres (docker) | `telegram_bot` |
| `POSTGRES_PORT` | нет | Порт Postgres (docker) | `5432` |
| `REDIS_PASSWORD` | нет | Пароль Redis (docker) | `changeme` |
| `REDIS_PORT` | нет | Порт Redis (docker) | `6379` |
| `REDIS_URL` | нет | Подключение к Redis | `redis://localhost:6379/0` |
| `MINIO_ENDPOINT` | нет | Endpoint MinIO | `localhost:9000` |
| `MINIO_ACCESS_KEY` | нет | Access key MinIO | `minioadmin` |
| `MINIO_SECRET_KEY` | нет | Secret key MinIO | `minioadmin` |
| `MINIO_BUCKET` | нет | Bucket для медиа | `telegram-media` |
| `MINIO_SECURE` | нет | Использовать HTTPS | `false` |
| `MINIO_PUBLIC_URL` | нет | Публичный URL MinIO | `http://localhost:9000` |
| `API_HOST` | нет | Хост FastAPI | `0.0.0.0` |
| `API_PORT` | нет | Порт FastAPI | `8000` |
| `API_SECRET_KEY` | да | Ключ API для внешних запросов | `CHANGE_ME` |
| `API_ALLOWED_IPS` | нет | Белый список IP (CSV) | `1.2.3.4,5.6.7.8` |
| `UI_BASIC_AUTH_ENABLED` | нет | Включить Basic Auth для UI | `true` |
| `UI_BASIC_AUTH_USERS` | нет | Пользователи UI (`user:pass:role`) | `admin:pass:admin,operator:pass:operator` |
| `DEFAULT_TIMEZONE` | нет | Таймзона по умолчанию | `UTC` |
| `MAX_MESSAGES_PER_HOUR` | нет | Лимит сообщений в час | `50` |
| `MAX_NEW_CHATS_PER_DAY` | нет | Лимит новых чатов в день | `20` |
| `MIN_DELAY_BETWEEN_MESSAGES` | нет | Минимальная задержка между сообщениями (сек) | `5` |
| `LOG_LEVEL` | нет | Уровень логов | `INFO` |
| `LOG_FILE` | нет | Файл логов | `logs/app.log` |
| `LOG_MAX_BYTES` | нет | Ротация логов (байты) | `10485760` |
| `LOG_BACKUP_COUNT` | нет | Кол-во ротаций логов | `5` |
| `ENABLE_METRICS` | нет | Включить метрики | `true` |
| `ALERT_TELEGRAM_BOT_TOKEN` | нет | Токен бота для алертов | `123:token` |
| `ALERT_TELEGRAM_CHAT_ID` | нет | Chat ID для алертов | `12345678` |
| `ALERT_EMAIL` | нет | Email для алертов | `ops@example.com` |
| `ERROR_TRACKING_DSN` | нет | DSN для self-hosted error tracking | `http://...` |
| `ERROR_TRACKING_ENV` | нет | Окружение | `production` |
| `ERROR_TRACKING_SAMPLE_RATE` | нет | Доля трассировки | `0.1` |
| `DEBUG` | нет | Включить debug режим | `false` |

Примечание:
- `/metrics` активен при `ENABLE_METRICS=true`.
- `ALERT_*` и `ERROR_TRACKING_*` опциональны и используются при подключении observability-стека.

---

## 2) Runbook

### Сервис не отвечает
1. Проверьте контейнеры: `docker-compose -f docker-compose.production.yml ps`.
2. Посмотрите логи: `docker-compose -f docker-compose.production.yml logs -f app`.
3. Проверка здоровья: `curl http://localhost:8000/health`, readiness: `curl http://localhost:8000/ready`, startup: `curl http://localhost:8000/startup`.
4. Если `database_connected=false` — проверьте Postgres (см. ниже).

### Telegram не авторизован
1. Откройте `http://localhost:8000/ui/auth`.
2. Нажмите **Send code**, введите код из Telegram.
3. Если включен 2FA — введите пароль.
4. В консоли `http://localhost:8000/ui` проверьте статус.
5. Admin UI доступен на `http://localhost:8000/admin` (нужна роль `admin`).

### Ошибки БД (PostgreSQL)
1. Убедитесь, что Postgres запущен.
2. Проверьте `DATABASE_URL` в `.env`.
3. Для Docker: `docker-compose -f docker-compose.production.yml logs -f postgres`.
4. Если база пуста — примените миграции: `python3 -m alembic upgrade head`.

---

## 3) Observability

- Метрики: `/metrics` (Prometheus).
- Логи: `logs/app.log` → Loki через Promtail.
- Error tracking: Sentry‑совместимый DSN.

Подробности и запуск стека — `OBSERVABILITY.md`.

---

## 4) UI assets

- Исходники: `static/ui.html`, `static/auth.html`, `static/operators.html`, `static/admin*.html`, `static/styles.css`,
  `static/app.js`, `static/auth.js`, `static/operators.js`, `static/admin.js`.
- Минификация: `python3 scripts/minify_assets.py` (обновляет `*.min.css/js`).

### Ошибки Redis
1. Убедитесь, что Redis запущен.
2. Проверьте `REDIS_URL` в `.env`.
3. Для Docker: `docker-compose -f docker-compose.production.yml logs -f redis`.
4. Redis хранит антиспам-счетчики и `phone_code_hash` для 2FA. При недоступности есть fallback, но персистентность и стабильность авторизации ухудшаются.

### Ошибки MinIO
1. Убедитесь, что MinIO запущен и доступен на `MINIO_ENDPOINT`.
2. Проверьте `MINIO_ACCESS_KEY` и `MINIO_SECRET_KEY`.
3. Убедитесь, что `MINIO_BUCKET` существует (создаётся автоматически при первом upload).
4. Если `MINIO_PUBLIC_URL` не указан — ссылки строятся от `MINIO_ENDPOINT`.

### Блокировка аккаунта Telegram
1. Немедленно остановите рассылку.
2. Проверьте лимиты антиспама и частоту сообщений.
3. Используйте отдельный номер. При блокировке — новый аккаунт.
4. Проверьте тексты и наличие согласий клиентов.

---

## 3) Диагностика

### Частые ошибки и что делать

| Симптом | Где смотреть | Действия |
| --- | --- | --- |
| `connection refused` к Postgres | `logs/app.log`, `docker-compose logs postgres` | Проверьте `DATABASE_URL`, запустите Postgres |
| `client_not_authorized` | UI `/ui`, логи | Авторизуйтесь через `/ui/auth` |
| `2fa_required` | UI `/ui/auth` | Введите пароль 2FA |
| `FloodWait` / лимиты | UI (anti-spam), логи | Подождать, снизить скорость |
| `UserPrivacyRestricted` | UI отправки | Контакт запретил личные сообщения |
| `PhoneNumberBanned` | логи | Нужен новый аккаунт |

### Проверки
- Health: `curl http://localhost:8000/health`
- Readiness: `curl http://localhost:8000/ready`
- Liveness: `curl http://localhost:8000/live`
- Startup: `curl http://localhost:8000/startup`
- Статус Telegram: `http://localhost:8000/ui` → верхняя панель
- Логи: `logs/app.log` или `docker-compose logs -f app`

---

## 4) Схема архитектуры

```
                ┌──────────────┐
UI (/ui, /ui/auth) ───────────▶│ FastAPI API  │
                │             │  (src/api)   │
                │             └──────┬───────┘
                │                    │
                │                    ▼
                │             ┌──────────────┐
                └────────────▶│ Telegram MTProto │
                              │ (Telethon)   │
                              └──────┬───────┘
                                     │
                                     ▼
                               Telegram API

                   ┌─────────────────────────┐
                   │ PostgreSQL (mappings,   │
                   │ history, profiles)      │
                   └─────────────────────────┘
```

### Где хранится сессия
- Сессия Telethon хранится в файле `<TELEGRAM_SESSION_NAME>.session`.
- Это **секрет**, его нельзя публиковать или пересылать.

### Критично для безопасности
- Сессия Telethon = полный доступ к аккаунту.
- `API_SECRET_KEY` должен быть уникальным и секретным.
- Отправка сообщений без согласия клиентов повышает риск блокировки.

---

## 5) Процедуры

### Миграции БД
- Проект использует `Base.metadata.create_all()` — новые таблицы создаются при старте.
- При изменении схемы: перезапустите `app`.
- Если используете Alembic, применяйте миграции перед запуском.

### Бэкапы и восстановление
```bash
# backup
pg_dump -h localhost -U postgres -d telegram_bot > backup.sql

# restore
psql -h localhost -U postgres -d telegram_bot < backup.sql
```

### Обновление версии
```bash
git pull
docker-compose -f docker-compose.production.yml up -d --build app
```

### Откат
```bash
git checkout <previous_tag_or_commit>
docker-compose -f docker-compose.production.yml up -d --build app
```
