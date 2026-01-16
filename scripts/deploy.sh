#!/bin/bash
# Скрипт деплоя на продакшен сервер

set -e

echo "🚀 Деплой приложения на продакшен..."

# Проверка Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker не установлен!"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose не установлен!"
    exit 1
fi

# Проверка .env
if [ ! -f ".env" ]; then
    echo "❌ Файл .env не найден!"
    echo "Скопируйте env.template в .env и заполните"
    exit 1
fi

# Остановка старых контейнеров
echo "🛑 Остановка старых контейнеров..."
docker-compose -f docker-compose.production.yml down

# Сборка образов
echo "🔨 Сборка Docker образов..."
docker-compose -f docker-compose.production.yml build --no-cache

# Запуск контейнеров
echo "🚀 Запуск контейнеров..."
docker-compose -f docker-compose.production.yml up -d

# Применение миграций
echo "🗄️ Применение миграций..."
sleep 5
docker-compose -f docker-compose.production.yml exec -T app python -m alembic upgrade head

# Проверка статуса
echo "✅ Проверка статуса..."
sleep 5
docker-compose -f docker-compose.production.yml ps

echo "✅ Деплой завершен!"
echo "📊 Логи: docker-compose -f docker-compose.production.yml logs -f"
echo "🏥 Health check: curl http://localhost:8000/health"
