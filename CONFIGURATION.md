# Конфигурация (.env)

Ниже полный справочник переменных окружения. Все значения читаются из `.env` (см. `env.template`).

Поддерживаются переменные формата `*_FILE`: если указан путь к файлу, значение берётся из него.
Например: `API_SECRET_KEY_FILE=/run/secrets/api_secret_key`.
Приоритет: явная переменная > `*_FILE`.

## Минимальный набор (обязателен)
| Переменная | Описание | Пример |
| --- | --- | --- |
| `TELEGRAM_API_ID` | API ID из https://my.telegram.org | `12345678` |
| `TELEGRAM_API_HASH` | API Hash из https://my.telegram.org | `0123abcd...` |
| `TELEGRAM_PHONE` | Телефон Telegram‑аккаунта (с `+`) | `+79991234567` |
| `API_SECRET_KEY` | Секретный ключ для внешнего API | `CHANGE_ME` |
| `DATABASE_URL` | Строка подключения Postgres | `postgresql://postgres:pass@localhost:5432/telegram_bot` |

## Telegram / MTProto
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `TELEGRAM_API_ID` | да | API ID | `12345678` |
| `TELEGRAM_API_HASH` | да | API Hash | `0123abcd...` |
| `TELEGRAM_PHONE` | да | Телефон аккаунта | `+79991234567` |
| `TELEGRAM_SESSION_NAME` | нет | Имя файла сессии Telethon | `amocrm_session` |
| `TELEGRAM_STRING_SESSION` | нет | StringSession (если храните в БД) | `1A...` |

Примечания:
- Файл сессии хранится рядом с корнем проекта как `<TELEGRAM_SESSION_NAME>.session`.
- Если включен `TELEGRAM_STRING_SESSION`, сессия хранится в таблице `telegram_sessions`.
- Для мульти‑аккаунтов используется таблица `telegram_accounts` (phone, session_string). `TELEGRAM_PHONE`/`TELEGRAM_STRING_SESSION` применяются к default‑аккаунту.

## AmoCRM (опционально)
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `AMOCRM_DOMAIN` | нет | Домен AmoCRM | `example.amocrm.ru` |
| `AMOCRM_CLIENT_ID` | нет | Client ID OAuth | `client_id` |
| `AMOCRM_CLIENT_SECRET` | нет | Client Secret OAuth | `client_secret` |
| `AMOCRM_REDIRECT_URI` | нет | Redirect URI | `https://your-app.example.com/oauth/callback` |
| `AMOCRM_ACCESS_TOKEN` | нет | Access token | `access_token` |
| `AMOCRM_REFRESH_TOKEN` | нет | Refresh token | `refresh_token` |
| `AMOCRM_TOKEN_EXPIRES_AT` | нет | ISO timestamp истечения токена | `2026-01-16T12:00:00` |
| `AMOCRM_WEBHOOK_SECRET` | нет | Secret для webhook | `secret` |
| `AMOCRM_FIELD_TELEGRAM_USERNAME` | нет | ID поля username | `123456` |
| `AMOCRM_FIELD_TELEGRAM_CHAT_ID` | нет | ID поля chat_id | `123457` |
| `AMOCRM_FIELD_TELEGRAM_CONSENT` | нет | ID поля consent | `123458` |

## Database
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `DATABASE_URL` | да | Postgres URL | `postgresql://postgres:pass@localhost:5432/telegram_bot` |
| `DB_ALLOW_CREATE_ALL` | нет | Разрешить `create_all` (dev) | `false` |

## Redis
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `REDIS_URL` | нет | URL Redis | `redis://localhost:6379/0` |
| `REDIS_PASSWORD` | нет | Пароль Redis (docker) | `changeme` |
| `REDIS_PORT` | нет | Порт Redis (docker) | `6379` |

Redis используется для:
- anti‑spam счетчиков,
- временного хранения `phone_code_hash` для 2FA.

## MinIO (media storage)
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `MINIO_ENDPOINT` | нет | Endpoint MinIO | `localhost:9000` |
| `MINIO_ACCESS_KEY` | нет | Access key | `minioadmin` |
| `MINIO_SECRET_KEY` | нет | Secret key | `minioadmin` |
| `MINIO_BUCKET` | нет | Bucket | `telegram-media` |
| `MINIO_SECURE` | нет | HTTPS | `false` |
| `MINIO_PUBLIC_URL` | нет | Публичный URL | `http://localhost:9000` |

Если MinIO не настроен, медиа будут пропущены, но текстовые сообщения работают.

## API сервер
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `API_HOST` | нет | Хост FastAPI | `0.0.0.0` |
| `API_PORT` | нет | Порт FastAPI | `8000` |
| `API_SECRET_KEY` | да | API ключ для `/api/*` | `CHANGE_ME` |
| `API_ALLOWED_IPS` | нет | CSV белый список IP | `1.2.3.4,5.6.7.8` |

`API_ALLOWED_IPS` сейчас **не используется в коде**, оставлено под будущие ограничения.

## UI Basic Auth
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `UI_BASIC_AUTH_ENABLED` | нет | Включить Basic Auth | `true` |
| `UI_BASIC_AUTH_USERS` | нет | `user:pass:role` | `admin:pass:admin,operator:pass:operator` |

Примечания:
- Операторы создаются автоматически из логинов Basic Auth после первого отправленного сообщения.
- Лимиты операторов (hourly/daily) задаются в БД и редактируются через `/ui/operators` (нужна роль `admin`).

## Admin settings overrides
Admin UI (`/admin/settings`) может сохранять значения в таблицу `app_settings`.
- Эти значения переопределяют `.env` при старте приложения/worker.
- Для некоторых параметров требуется рестарт worker (указано в UI).
- Через `/admin/settings` можно выполнить OAuth для AmoCRM и сохранить токены в БД.

## Compliance
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `DEFAULT_TIMEZONE` | нет | Таймзона по умолчанию | `UTC` |

## Anti‑spam
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `MAX_MESSAGES_PER_HOUR` | нет | Лимит сообщений/час | `50` |
| `MAX_NEW_CHATS_PER_DAY` | нет | Лимит новых чатов/день | `20` |
| `MIN_DELAY_BETWEEN_MESSAGES` | нет | Минимальная задержка, сек | `5` |

Per-operator лимиты хранятся в таблице `operators` и применяются поверх глобальных лимитов.

## Outbox / Worker
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `OUTBOX_PROCESS_INLINE` | нет | Отправлять в основном процессе | `true` |
| `OUTBOX_MAX_ATTEMPTS` | нет | Максимум попыток | `5` |
| `OUTBOX_RETRY_BASE_SECONDS` | нет | База для backoff (сек) | `10` |
| `OUTBOX_POLL_INTERVAL` | нет | Пауза worker между проверками | `2` |

Если `OUTBOX_PROCESS_INLINE=false`, нужно запускать `python3 -m src.outbox_worker`.

## Data retention
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `UI_MESSAGE_RETENTION_DAYS` | нет | Хранение ui_message_history (дни, 0 = отключить) | `365` |
| `UI_EVENT_RETENTION_DAYS` | нет | Хранение ui_event_log (дни, 0 = отключить) | `90` |
| `AUDIT_LOG_RETENTION_DAYS` | нет | Хранение audit_log (дни, 0 = отключить) | `365` |
| `MESSAGE_INBOX_RETENTION_DAYS` | нет | Хранение message_inbox (дни, 0 = отключить) | `30` |

## Logging
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `LOG_LEVEL` | нет | Уровень логов | `INFO` |
| `LOG_FILE` | нет | Путь к логам | `logs/app.log` |
| `LOG_MAX_BYTES` | нет | Ротация, байты | `10485760` |
| `LOG_BACKUP_COUNT` | нет | Кол-во ротаций | `5` |

## Observability
| Переменная | Обязательная | Описание | Пример |
| --- | --- | --- | --- |
| `ENABLE_METRICS` | нет | Включить `/metrics` | `true` |
| `ALERT_TELEGRAM_BOT_TOKEN` | нет | Токен бота для алертов | `123:token` |
| `ALERT_TELEGRAM_CHAT_ID` | нет | Chat ID для алертов | `12345678` |
| `ALERT_EMAIL` | нет | Email для алертов | `ops@example.com` |
| `ERROR_TRACKING_DSN` | нет | Sentry‑совместимый DSN | `http://...` |
| `ERROR_TRACKING_ENV` | нет | Окружение | `production` |
| `ERROR_TRACKING_SAMPLE_RATE` | нет | Доля трассировки | `0.1` |

## Docker Compose (переменные контейнеров)
| Переменная | Описание | Пример |
| --- | --- | --- |
| `POSTGRES_USER` | Пользователь Postgres | `postgres` |
| `POSTGRES_PASSWORD` | Пароль Postgres | `changeme` |
| `POSTGRES_DB` | База Postgres | `telegram_bot` |
| `POSTGRES_PORT` | Порт Postgres | `5432` |
| `REDIS_PASSWORD` | Пароль Redis | `changeme` |
| `REDIS_PORT` | Порт Redis | `6379` |
