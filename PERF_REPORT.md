# Performance / Load Test Report

**Статус:** черновик (метрики пока не заполнены)

## Контекст
- **Цель:** проверить устойчивость UI API под нагрузкой и зафиксировать baseline.
- **Инструмент:** Locust (`tests/load/locustfile.py`)
- **Дата:** 2026-01-16

## Окружение (заполнить)
- Host: `http://localhost:8000`
- Версия приложения: `TBD`
- База данных: `TBD`
- Конфигурация: `OUTBOX_PROCESS_INLINE=false`, `UI_BASIC_AUTH_ENABLED=true`
- Данные: `TBD` (кол-во чатов/сообщений/операторов)

## Сценарии
1. **UI baseline**
   - Цель: статус + чаты + сообщения + events + templates/tags + send
   - Скрипт: `tests/load/locustfile.py`
2. **1k сообщений**
   - Цель: устойчивость очереди и anti-spam в пике
3. **10k сообщений**
   - Цель: оценка деградации и bottlenecks

## Результаты (TBD)
| Сценарий | Users | Spawn rate | Duration | RPS | p95 latency | Error rate |
| --- | --- | --- | --- | --- | --- | --- |
| UI baseline | TBD | TBD | TBD | TBD | TBD | TBD |
| 1k сообщений | TBD | TBD | TBD | TBD | TBD | TBD |
| 10k сообщений | TBD | TBD | TBD | TBD | TBD | TBD |

## Выводы
- TBD

## Рекомендации
- TBD
