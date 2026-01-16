# Быстрый старт (MTProto, пишем первыми)

Этот проект работает **только** через MTProto (личный аккаунт Telegram). Это единственный способ писать клиентам первыми.

## 0) Прочитайте предупреждения
- `MTPROTO_GUIDE.md` — риски, лимиты, безопасность.
- Используйте **отдельный номер** и работайте только с согласиями клиентов.

## 1) Получите Telegram API credentials
1. Откройте https://my.telegram.org
2. Войдите под **отдельным** Telegram‑аккаунтом.
3. Перейдите в **API development tools**.
4. Нажмите **Create application**.
5. Заполните форму:
   - **App title**: любое имя (например, `Telegram CRM Console`).
   - **Short name**: латиница без пробелов (например, `tgcrm`).
   - **Platform**: `Other`.
   - **Description**: кратко, например `Internal MTProto console`.
6. Сохраните `api_id` и `api_hash` — они нужны в `.env`.

## 2) Подготовьте AmoCRM (опционально)
Если AmoCRM не нужен — пропустите шаг.

1. Создайте интеграцию в AmoCRM.
2. Получите `client_id`, `client_secret`, `redirect_uri`.
3. Пройдите OAuth и сохраните `access_token` и `refresh_token`.
4. Создайте custom поля и запишите их ID:
   - Telegram username
   - Telegram chat_id
   - Согласие на контакт (значение `true`)

## 3) Настройте `.env`
```bash
cp env.template .env
```

Минимум для локального запуска:
- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_PHONE`
- `API_SECRET_KEY`
- `DATABASE_URL`

Опционально (AmoCRM):
- `AMOCRM_*` переменные
- `AMOCRM_FIELD_TELEGRAM_*`

Полная таблица переменных: `CONFIGURATION.md`.

## 4) Запустите PostgreSQL и Redis
### Вариант A: Docker (рекомендуется)
```bash
docker-compose -f docker-compose.production.yml up -d postgres redis
```

### Вариант B: вручную (Postgres отдельно)
```bash
docker run -d -p 5432:5432 \
  --name telegram-postgres \
  -e POSTGRES_PASSWORD=password \
  -e POSTGRES_DB=telegram_bot \
  postgres:15
```

Если Redis не нужен, можно работать без него, но anti‑spam и 2FA state станут менее стабильными.

## 5) Установите зависимости
```bash
pip3 install -r requirements-production.txt
```

## 6) Примените миграции
```bash
python3 -m alembic upgrade head
```

## 7) Запустите приложение
```bash
python3 -m src.main
```

Если `OUTBOX_PROCESS_INLINE=false`, запустите worker отдельно:
```bash
python3 -m src.outbox_worker
```

## 8) Авторизация в Telegram
Откройте в браузере:
- Авторизация: `http://localhost:8000/ui/auth`
- Консоль: `http://localhost:8000/ui`

> Порт зависит от `API_PORT` в `.env`.

Шаги в `/ui/auth`:
1. Нажмите **Send code**.
2. Введите код из Telegram → **Submit code**.
3. Если включен 2FA — введите пароль → **Submit 2FA**.
4. После авторизации перейдите в `/ui`.

## 9) Отправка первого сообщения (UI)
1. В правой панели **New Chat** введите `@username` или телефон.
2. Напишите сообщение и отправьте.
3. Сообщения и статусы появятся в истории чата.

## 10) Проверка здоровья
```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/live
curl http://localhost:8000/startup
```

## 11) Отправка через API (пример)
```bash
curl -X POST http://localhost:8000/api/send-message \
  -H "X-API-Key: YOUR_API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "contact_id": 123456,
    "username": "telegram_username",
    "message": "Привет! Пишем первыми через MTProto"
  }'
```

## 12) Дальше
- `ARCHITECTURE.md` — как устроены компоненты.
- `API.md` — все endpoints.
- `DEPLOYMENT.md` — продакшен‑развертывание.
