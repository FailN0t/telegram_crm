# Performance / Load Test Report

**Статус:** черновик (UI baseline прогнан локально)

## Контекст
- **Цель:** проверить устойчивость UI API под нагрузкой и зафиксировать baseline.
- **Инструмент:** Locust (`tests/load/locustfile.py`)
- **Дата:** 2026-01-16

## Окружение (заполнить)
- Host: `http://127.0.0.1:8001`
- Версия приложения: `git 506b459`
- База данных: `sqlite:///./locust.db` (создана через `init_db`)
- Конфигурация: `OUTBOX_PROCESS_INLINE=false`, `UI_BASIC_AUTH_ENABLED=false`, `UI_LOAD_CHAT_ID=0`
- Данные: пустая локальная БД, дефолтный Telegram аккаунт, шаблоны/теги без сидов

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
| UI baseline | 50 | 5 | 2m | 26.9 | 720 ms | 9.0% |
| 1k сообщений | TBD | TBD | TBD | TBD | TBD | TBD |
| 10k сообщений | TBD | TBD | TBD | TBD | TBD | TBD |

## Выводы
- Локальный прогон на dummy bridge дал ~26.9 RPS и p95 ~720 ms.
- Ошибки 9.0% связаны с ответами 404 по `/api/ui/templates` и `/api/ui/tags` в ходе нагрузки.

## Рекомендации
- Перепроверить 404 по `/api/ui/templates` и `/api/ui/tags` под нагрузкой и повторить прогон.
