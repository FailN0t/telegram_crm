# Release Notes

## Unreleased

### Added
- Подробная документация: `CONFIGURATION.md`, `ARCHITECTURE.md`, `API.md`, `UI_GUIDE.md`, `TESTING.md`.
- `DB_USE_NULL_POOL` для отключения пула соединений (полезно для тестов/CLI).

### Changed
- README и QUICKSTART обновлены и синхронизированы с текущей архитектурой.
- `TESTING.md` дополнен инструкцией по запуску тестов на PostgreSQL.

### Fixed
- —

## 1.0.0 — 2026-01-14

### Added
- Локальная UI-консоль: онбординг, статусы подключения/сессии, список чатов, карточка контакта, шаблоны, журнал событий.
- Страница авторизации `/ui/auth` и logout.
- API для UI: чаты, события, профиль контакта, отправка с ретраями.
- Техничка и прод‑бэклог.
- SSE realtime UI, outbox/worker доставка, anti-spam и compliance.
- Observability стек: Prometheus/Grafana, Loki/Promtail, error tracking.
- Runbook, бэкапы и восстановление.

### Changed
- Документация обновлена под MTProto‑only сценарий, AmoCRM — опционально.
- Структура UI/доков унифицирована.
- UI вынесен в `static/` и минифицирован для production.

### Fixed
- Улучшены человекочитаемые ошибки отправки.
- Исправлены race conditions и потеря данных при рестарте.
