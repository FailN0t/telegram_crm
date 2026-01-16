# Release Checklist

## Перед релизом

### Код и тесты
- [ ] `python3 -m unittest`
- [ ] Проверка новых миграций (если есть)
- [ ] `python3 scripts/minify_assets.py` (обновить `static/*.min.*`)

### Docker и запуск
- [ ] `docker-compose -f docker-compose.production.yml up -d --build app`
- [ ] `curl http://localhost:8000/health` возвращает `database_connected=true`
- [ ] `/ui/auth` авторизация работает
- [ ] `/ui` открывается и показывает чаты

### Очереди/worker
- [ ] Если `OUTBOX_PROCESS_INLINE=false`, worker запущен
- [ ] Outbox статусы (`queued/sent/failed`) обновляются

### Конфигурация
- [ ] `.env` заполнен (TELEGRAM_*, API_SECRET_KEY, DATABASE_URL)
- [ ] Секреты не попали в репозиторий
- [ ] Лимиты антиспама выставлены консервативно

### Безопасность
- [ ] `/ui` ограничен (Basic Auth или IP allowlist)
- [ ] Сессия Telethon хранится безопасно

### Бэкапы и восстановление
- [ ] Бэкап БД создан
- [ ] Проверка восстановления (backup‑drill, см. `DR_DRILL.md`)

## После релиза
- [ ] Проверить логи `docker-compose -f docker-compose.production.yml logs -f app`
- [ ] Отправка тестового сообщения
- [ ] Входящее сообщение появляется в UI
