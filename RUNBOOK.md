# Runbook (аварии, восстановление, бэкапы)

## Цели
- **RPO**: 24 часа
- **RTO**: 2 часа

## 1) Быстрая диагностика
```bash
docker-compose -f docker-compose.production.yml ps

docker-compose -f docker-compose.production.yml logs -f app

curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/startup
```

## 2) Частые инциденты

### Telegram не авторизован
- Откройте `http://localhost:8000/ui/auth`.
- Нажмите **Send code** → введите код → **Submit code**.
- При 2FA — введите пароль.

### Outbox завис/сообщения не уходят
1. Проверьте, запущен ли worker (если `OUTBOX_PROCESS_INLINE=false`).
2. Посмотрите статус в `message_outbox` (queued/failed/dead).
3. Проверьте `OUTBOX_MAX_ATTEMPTS` и `OUTBOX_RETRY_BASE_SECONDS`.
4. Проверьте лимиты anti‑spam (в UI).

### База недоступна
1. Проверьте `DATABASE_URL`.
2. `docker-compose logs -f postgres`.
3. Проверьте место на диске и volume.

### Redis недоступен
1. Проверьте `REDIS_URL`.
2. `docker-compose logs -f redis`.
3. Без Redis anti‑spam и 2FA будут работать в памяти (менее надежно).

### MinIO недоступен
1. Проверьте `MINIO_ENDPOINT`.
2. Проверьте ключи и bucket.
3. При ошибках медиа будут пропущены, но текстовые сообщения продолжат работать.

### FloodWait / Telegram rate limits
1. Немедленно остановите отправку.
2. Уменьшите `MAX_MESSAGES_PER_HOUR`, `MAX_NEW_CHATS_PER_DAY`.
3. Дайте аккаунту «отдохнуть».

### UI не обновляется (нет новых сообщений)
1. Проверьте `/api/ui/stream` (SSE).
2. Убедитесь, что сообщения сохраняются в `ui_message_history`.
3. Проверьте логи приложения.

## 3) Бэкапы
### Полный бэкап (Postgres + sessions + .env)
```bash
./scripts/backup.sh
```

Архив появится в `backups/*.tar.gz`.

### Бэкап‑дрилл (раз в квартал)
1. Создать бэкап.
2. Восстановить на отдельном контуре.
3. Проверить `/health`, `/ui/auth` и отправку тестового сообщения.
4. Зафиксировать RTO/RPO.

## 4) Восстановление
### Из полного бэкапа
```bash
./scripts/restore.sh backups/20260101_120000.tar.gz
```

### Postgres вручную
```bash
pg_restore -d telegram_bot backups/db.dump
```

## 5) Миграции
```bash
python3 -m alembic upgrade head
```

## 6) Data retention
Очистка старых записей (ui_message_history, ui_event_log, audit_log, message_inbox):
```bash
python3 -m src.retention
```

Для регулярного запуска используйте cron (например, ежедневно ночью).

## 7) После восстановления
1. Перезапустите сервис: `docker-compose -f docker-compose.production.yml restart app`.
2. Проверьте `/health` и `/startup`.
3. Авторизуйте MTProto при необходимости.
