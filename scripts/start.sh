#!/bin/bash
# Скрипт запуска приложения

set -e

echo "🚀 Запуск AmoCRM Telegram MTProto Integration..."

# Проверка .env файла
if [ ! -f ".env" ]; then
    echo "❌ Файл .env не найден!"
    echo "Скопируйте env.template в .env и заполните"
    exit 1
fi

# Создание директорий
mkdir -p logs sessions

# Активация виртуального окружения (если есть)
if [ -d "venv" ]; then
    source venv/bin/activate
fi

# Установка зависимостей
echo "📦 Установка зависимостей..."
pip install -r requirements-production.txt

# Применение миграций
echo "🗄️ Применение миграций..."
python -m alembic upgrade head

# Запуск приложения
echo "✅ Запуск приложения..."
python -m src.main
