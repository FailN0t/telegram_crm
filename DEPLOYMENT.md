# Deployment (production)

Цель: развернуть сервис в production с использованием **только бесплатных/opensource** компонентов.

## Production Server Access

**Current Production Server:**
- Host: `your-server-ip`
- SSH: `ssh root@your-server-ip`
- Location: `/root/app` (or `/home/appuser/app` if using appuser)

**Quick Commands:**
```bash
# Подключиться к серверу
ssh root@your-server-ip

# Проверить статус контейнеров
docker-compose -f docker-compose.production.yml ps

# Просмотр логов
docker-compose -f docker-compose.production.yml logs -f app
docker-compose -f docker-compose.production.yml logs -f worker

# Перезапуск после изменений
cd /root/app
git pull
docker-compose -f docker-compose.production.yml down
docker-compose -f docker-compose.production.yml up -d --build
```

## Требования
- Сервер: 2 CPU / 2 GB RAM / 20+ GB SSD (минимум).
- ОС: Ubuntu 22.04 LTS (или совместимый Linux).
- Домен + DNS на IP сервера.
- Отдельный Telegram‑аккаунт + `api_id`/`api_hash`.
- Docker + docker‑compose.

## 1) Подготовка сервера
```bash
ssh root@your-server-ip
apt update && apt upgrade -y
curl -fsSL https://get.docker.com -o get-docker.sh
sh get-docker.sh
apt install docker-compose -y

useradd -m -s /bin/bash appuser
usermod -aG docker appuser
su - appuser
```

## 2) Развертывание проекта
```bash
cd ~
git clone your-repo-url app
cd app
cp env.template .env
nano .env
chmod 600 .env
```

Для секретов можно использовать `*_FILE` переменные (Docker/K8s secrets), например:
```
API_SECRET_KEY_FILE=/run/secrets/api_secret_key
AMOCRM_CLIENT_SECRET_FILE=/run/secrets/amocrm_client_secret
```

Заполните минимум:
- `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE`
- `API_SECRET_KEY`
- `DATABASE_URL` (в docker‑compose перезаписывается на внутренний Postgres)

Рекомендуется:
- `UI_BASIC_AUTH_ENABLED=true` + `UI_BASIC_AUTH_USERS=...`
- `OUTBOX_PROCESS_INLINE=false` (разделить API и отправку)

## 3) TLS сертификат (опционально)
```bash
sudo apt install certbot -y
sudo certbot certonly --standalone -d your-domain.com
sudo mkdir -p ssl
sudo cp /etc/letsencrypt/live/your-domain.com/fullchain.pem ssl/
sudo cp /etc/letsencrypt/live/your-domain.com/privkey.pem ssl/
sudo chown -R appuser:appuser ssl/
chmod 600 ssl/*.pem
```

Отредактируйте `nginx.conf` под ваш домен.

## 4) Запуск контейнеров
```bash
chmod +x scripts/*.sh
./scripts/deploy.sh
```

Скрипт:
- Собирает образы
- Запускает Postgres + Redis + App
- Применяет миграции

Проверка:
```bash
docker-compose -f docker-compose.production.yml ps
```

## 5) Outbox worker (если `OUTBOX_PROCESS_INLINE=false`)
В текущем docker‑compose worker не описан. Запуск отдельно:
```bash
docker-compose -f docker-compose.production.yml exec -T app python -m src.outbox_worker
```

Для постоянного запуска рекомендуется добавить отдельный сервис `worker` в compose (пример):
```yaml
worker:
  build:
    context: .
    dockerfile: Dockerfile.production
  command: python -m src.outbox_worker
  env_file: [ .env ]
  environment:
    - DATABASE_URL=postgresql://postgres:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
    - REDIS_URL=redis://redis:6379/0
  depends_on: [ postgres, redis ]
  volumes:
    - ./logs:/app/logs
    - ./sessions:/app/sessions
```

## 6) Авторизация Telegram
Откройте в браузере:
- `https://your-domain.com/ui/auth`
- Нажмите **Send code** → введите код → **Submit code**
- Если 2FA — введите пароль

## 7) Защита UI
UI можно защитить двумя способами:
1) Встроенный Basic Auth:
   - `UI_BASIC_AUTH_ENABLED=true`
   - `UI_BASIC_AUTH_USERS=admin:pass:admin,operator:pass:operator`
2) Basic Auth в Nginx (дополнительный периметр).

```bash
sudo apt install apache2-utils -y
sudo htpasswd -c /etc/nginx/.htpasswd admin
```

В `nginx.conf` добавьте:
```nginx
location /ui {
  auth_basic "Restricted";
  auth_basic_user_file /etc/nginx/.htpasswd;
  proxy_pass http://app:8000;
}

location /admin {
  auth_basic "Restricted";
  auth_basic_user_file /etc/nginx/.htpasswd;
  proxy_pass http://app:8000;
}
```

## 8) Проверка
```bash
curl https://your-domain.com/health
curl https://your-domain.com/ready
curl https://your-domain.com/startup
```

## 9) Наблюдаемость
Стек наблюдаемости в `OBSERVABILITY.md`.

## 10) Бэкапы
См. `RUNBOOK.md`.
