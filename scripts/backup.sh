#!/bin/bash
# Скрипт резервного копирования БД и session файлов

set -e

BACKUP_DIR="backups/$(date +%Y%m%d_%H%M%S)"

echo "💾 Создание резервной копии..."
mkdir -p "$BACKUP_DIR"

# Подхватываем переменные из .env (если есть)
if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

DB_NAME="${POSTGRES_DB:-telegram_bot}"
DB_USER="${POSTGRES_USER:-postgres}"

# Бэкап БД
echo "📊 Резервная копия базы данных..."
docker-compose -f docker-compose.production.yml exec -T postgres pg_dump -U "$DB_USER" "$DB_NAME" > "$BACKUP_DIR/database.sql"

# Бэкап session файлов
echo "📁 Резервная копия session файлов..."
cp -r sessions "$BACKUP_DIR/"

# .env НЕ копируется в бэкап из соображений безопасности (#86)
# Credentials и secrets должны храниться в secret management системе

# Сжатие
echo "📦 Сжатие резервной копии..."
tar -czf "$BACKUP_DIR.tar.gz" "$BACKUP_DIR"
rm -rf "$BACKUP_DIR"

echo "✅ Резервная копия создана: $BACKUP_DIR.tar.gz"
