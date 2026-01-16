# Observability

Компоненты:
- **Метрики**: Prometheus (`/metrics`).
- **Логи**: файл `logs/app.log`, сбор через Promtail → Loki.
- **Error tracking**: Sentry‑совместимый сервис (self‑hosted).

## Метрики
Включается переменной `ENABLE_METRICS=true`.

Проверка:
```bash
curl http://localhost:8000/metrics | head -n 20
```

## Логи
- Файл логов: `logs/app.log`.
- Для docker‑compose лог доступен через `docker-compose logs -f app`.

## Error tracking
Переменные:
```
ERROR_TRACKING_DSN=
ERROR_TRACKING_ENV=production
ERROR_TRACKING_SAMPLE_RATE=0.1
```

## Observability‑стек
1) Поднимите основной стек:
```bash
docker-compose -f docker-compose.production.yml up -d
```

2) Поднимите observability:
```bash
docker-compose -f docker-compose.observability.yml up -d
```

Grafana: `http://localhost:3000` (логин/пароль `admin/admin`).

## Алерты
- Правила: `observability/alert.rules.yml`.
- Alertmanager: `observability/alertmanager.yml` (настройте webhook).
