# DR / Backup Drill

Цель: регулярно проверять, что бэкапы реально восстанавливаются и сервис стартует без потери критичных данных.

## Частота
- Рекомендуется: 1 раз в квартал

## Подготовка
- Отдельный тестовый/стейджинг контур (НЕ production).
- Доступ к резервным копиям (`backups/*.tar.gz`).
- Последняя версия кода и `.env` (или secrets).

## Процедура
1. Создать свежий бэкап на production:
   ```bash
   ./scripts/backup.sh
   ```
2. На стейджинге остановить сервис:
   ```bash
   docker-compose -f docker-compose.production.yml down
   ```
3. Восстановить из бэкапа:
   ```bash
   ./scripts/restore.sh backups/YYYYMMDD_HHMMSS.tar.gz
   ```
4. Запустить сервис:
   ```bash
   docker-compose -f docker-compose.production.yml up -d
   ```
5. Проверить здоровье:
   ```bash
   curl http://localhost:8000/health
   curl http://localhost:8000/ready
   ```
6. Авторизация Telegram (если нужно):
   - `http://localhost:8000/ui/auth` → Send code → Submit code.
7. Проверить UI:
   - `/ui` открывается, сообщения грузятся.
8. Зафиксировать результаты:
   - RPO (время между последними данными и текущим моментом).
   - RTO (время полного восстановления).

## Чек-лист
- [ ] Бэкап создан
- [ ] Restore прошёл без ошибок
- [ ] `/health` и `/ready` возвращают OK
- [ ] UI доступен
- [ ] Отправка тестового сообщения успешна
- [ ] Зафиксированы RPO/RTO
