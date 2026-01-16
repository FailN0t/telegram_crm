# Начните здесь: AmoCRM + Telegram через MTProto

Этот проект ориентирован на один сценарий: **писать клиентам первыми** через MTProto (личный аккаунт Telegram). Другие варианты здесь не рассматриваются.

---

## ✅ Что нужно заранее

- Отдельный номер телефона и аккаунт Telegram (не личный)
- `api_id` и `api_hash` с https://my.telegram.org
- Интеграция в AmoCRM (optional): client_id, client_secret, redirect_uri, access/refresh tokens
- Custom поля в AmoCRM (optional): username, chat_id, consent и их ID
- Python 3.10+ и PostgreSQL (или Docker + docker-compose)

---

## 📌 Куда идти дальше

1. `QUICKSTART.md` — пошаговая настройка и запуск
2. `MTPROTO_GUIDE.md` — ограничения, риски, безопасная работа
3. `DEPLOYMENT.md` — продакшен-развертывание
4. `TECHNICAL.md` — техничка для эксплуатации
5. `PROD_READY_BACKLOG.md` — продакшен бэклог и архитектура
6. `RELEASE_NOTES.md` и `RELEASE_CHECKLIST.md` — релизная дисциплина

---

## ⚡ Быстрый маршрут

```bash
cp env.template .env
# заполните .env
pip3 install -r requirements-production.txt
python3 -m src.main
curl http://localhost:8000/health
```

---

## ⚠️ Важно

- MTProto = личный аккаунт. Соблюдайте ToS Telegram и лимиты.
- Работайте только с согласиями клиентов.
- Для UI используйте встроенный Basic Auth (`UI_BASIC_AUTH_ENABLED`, `UI_BASIC_AUTH_USERS`) или защиту через reverse proxy.
- `/admin` доступен только пользователям с ролью `admin` из `UI_BASIC_AUTH_USERS`.
