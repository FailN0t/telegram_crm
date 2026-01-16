#!/bin/bash
# Восстановление из архива бэкапа

set -e

ARCHIVE_PATH="$1"
if [ -z "$ARCHIVE_PATH" ]; then
  echo "Usage: ./scripts/restore.sh backups/YYYYMMDD_HHMMSS.tar.gz"
  exit 1
fi

WORK_DIR="backups/restore_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$WORK_DIR"

echo "📦 Распаковка бэкапа..."
tar -xzf "$ARCHIVE_PATH" -C "$WORK_DIR"

BACKUP_DIR=$(find "$WORK_DIR" -maxdepth 1 -type d -name "20*" | head -n 1)
if [ -z "$BACKUP_DIR" ]; then
  echo "❌ Не найден каталог бэкапа внутри архива"
  exit 1
fi

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

DB_NAME="${POSTGRES_DB:-telegram_bot}"
DB_USER="${POSTGRES_USER:-postgres}"

echo "📊 Восстановление базы данных..."
docker-compose -f docker-compose.production.yml exec -T postgres \
  psql -U "$DB_USER" -d "$DB_NAME" < "$BACKUP_DIR/database.sql"

echo "📁 Восстановление session файлов..."
rm -rf sessions
cp -r "$BACKUP_DIR/sessions" ./sessions

echo "⚙️ Восстановление .env (если требуется)..."
if [ -f "$BACKUP_DIR/.env.backup" ]; then
  cp "$BACKUP_DIR/.env.backup" ./.env
fi

echo "✅ Восстановление завершено"
