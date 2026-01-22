# 🚀 Быстрая настройка AmoCRM для yourdomain

## Данные интеграции

**Домен AmoCRM:** `yourdomain.amocrm.ru`

**Integration ID:** `your-integration-id`

**Secret Key:** (хранится в безопасном месте)

**Долгосрочный токен:** (действителен до 2031 года)

---

## Кастомные поля контактов

В AmoCRM уже созданы 3 кастомных поля:

| Поле | Тип | Field ID | Назначение |
|------|-----|----------|------------|
| **Telegram Username** | Текст | `<field_id>` | Хранит @username клиента |
| **Telegram Chat ID** | Число | `<field_id>` | ID чата в Telegram |
| **Telegram Consent** | Переключатель | `<field_id>` | Согласие на контакт |

---

## Настройка на сервере

### 1. Скопируйте шаблон .env

```bash
cd /путь/к/проекту
cp .env.production.example .env
```

### 2. Заполните .env файл

Откройте `.env` и замените плейсхолдеры на реальные значения:

```bash
# AmoCRM
AMOCRM_DOMAIN=yourdomain.amocrm.ru
AMOCRM_CLIENT_ID=your-integration-id
AMOCRM_CLIENT_SECRET=<ваш_секретный_ключ>
AMOCRM_REDIRECT_URI=https://your-server.example.com/api/admin/amocrm/oauth/callback

# Долгосрочный токен (уже есть!)
AMOCRM_ACCESS_TOKEN=<ваш_долгосрочный_токен>
AMOCRM_TOKEN_EXPIRES_AT=2031-03-20T00:00:00Z

# Field IDs (уже настроены!)
AMOCRM_FIELD_TELEGRAM_USERNAME=0
AMOCRM_FIELD_TELEGRAM_CHAT_ID=0
AMOCRM_FIELD_TELEGRAM_CONSENT=0

# Telegram
TELEGRAM_API_ID=<из my.telegram.org>
TELEGRAM_API_HASH=<из my.telegram.org>
TELEGRAM_PHONE=+7XXXXXXXXXX

# Database
DATABASE_URL=postgresql://telegram_user:пароль@localhost:5432/telegram_crm

# API Secret
API_SECRET_KEY=<сгенерируйте случайную строку>

# Basic Auth
UI_BASIC_AUTH_ENABLED=true
UI_BASIC_AUTH_USERS=admin:безопасный_пароль:admin
```

### 3. Запустите миграции

```bash
python3 -m alembic upgrade head
```

### 4. Запустите приложение

```bash
# Через systemd (рекомендуется)
sudo systemctl start telegram-crm-api
sudo systemctl start telegram-crm-worker

# Или через Docker Compose
docker-compose -f docker-compose.production.yml up -d
```

### 5. Проверьте статус

```bash
curl http://localhost:8000/api/admin/amocrm/status | jq
```

**Ожидается:**
```json
{
  "configured": true,
  "domain": "yourdomain.amocrm.ru",
  "has_tokens": true,
  "token_expires_at": "2031-03-20T00:00:00Z"
}
```

---

## Получение Refresh Token (опционально)

Долгосрочный токен действителен до 2031 года, но для автообновления рекомендуется получить refresh_token:

1. Откройте: `https://your-server.example.com/admin/settings`
2. Войдите с Basic Auth credentials
3. Секция "AmoCRM OAuth" → "Connect AmoCRM"
4. Авторизуйтесь в AmoCRM
5. Refresh token сохранится автоматически

---

## Тестирование

### Проверка создания контакта

```bash
curl -X POST http://localhost:8000/api/send-message \
  -H "X-Api-Secret: ваш_API_SECRET_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "phone": "+79991234567",
    "message": "Тест интеграции AmoCRM"
  }'
```

### Проверка в AmoCRM

1. Откройте `https://yourdomain.amocrm.ru/contacts`
2. Должен появиться новый контакт с:
   - Телефоном: +79991234567
   - Telegram данными в кастомных полях
   - Примечанием с текстом сообщения

---

## Troubleshooting

### Проблема: "Token expired"

**Решение:** Токен действителен до 2031 года. Если видите эту ошибку:
1. Проверьте что `AMOCRM_ACCESS_TOKEN` правильно скопирован в `.env`
2. Повторите OAuth flow для получения нового refresh_token

### Проблема: "Field not found"

**Решение:** Проверьте Field IDs:

```bash
# Получите список полей через API
curl -H "Authorization: Bearer $AMOCRM_ACCESS_TOKEN" \
  "https://yourdomain.amocrm.ru/api/v4/contacts/custom_fields" | jq
```

### Проблема: Контакты не создаются

**Проверьте:**
1. `CRM_PROVIDER=amocrm` (не bitrix24!)
2. Токен не истек
3. Логи: `tail -f logs/app.log | grep AmoCRM`

---

## Безопасность

⚠️ **ВАЖНО:**

- `.env` файл НИКОГДА не коммитится в git (уже в .gitignore)
- Токены и ключи хранятся ТОЛЬКО на сервере
- Используйте безопасные пароли для UI_BASIC_AUTH
- API_SECRET_KEY должен быть случайной строкой минимум 32 символа

Сгенерировать безопасный ключ:
```bash
openssl rand -hex 32
```

---

## Готово! ✅

AmoCRM интеграция настроена и готова к работе.

**Проверьте чеклист:**
- [ ] `.env` файл заполнен на сервере
- [ ] Field IDs корректные (000001, 000002, 000003)
- [ ] Миграции применены
- [ ] Приложение запущено
- [ ] Статус показывает `has_tokens: true`
- [ ] Тестовое сообщение создало контакт в AmoCRM

Нужна помощь? Смотрите полную документацию: [CONFIGURATION.md](../CONFIGURATION.md)
