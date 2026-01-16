#!/usr/bin/env python3
"""
Скрипт проверки готовности к запуску
Проверяет все необходимые компоненты перед запуском приложения
"""

import os
import sys
from pathlib import Path

# Цвета для вывода
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def check_mark(condition):
    return f"{GREEN}✓{RESET}" if condition else f"{RED}✗{RESET}"

def print_header(text):
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{text:^60}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")

def check_files():
    """Проверка наличия необходимых файлов"""
    print_header("1. Проверка файлов проекта")
    
    required_files = {
        'src/__init__.py': 'Инициализация пакета',
        'src/config.py': 'Конфигурация',
        'src/database.py': 'Модели БД',
        'src/logger.py': 'Логирование',
        'src/antispam.py': 'Anti-Spam менеджер',
        'src/telegram_client.py': 'MTProto клиент',
        'src/amocrm_client.py': 'AmoCRM клиент',
        'src/bridge.py': 'Bridge',
        'src/api_server.py': 'API сервер',
        'src/main.py': 'Главное приложение',
        'requirements-production.txt': 'Зависимости',
        'alembic.ini': 'Конфигурация миграций',
    }
    
    all_present = True
    for file_path, description in required_files.items():
        exists = Path(file_path).exists()
        all_present = all_present and exists
        print(f"{check_mark(exists)} {file_path:<40} - {description}")
    
    return all_present

def check_env_file():
    """Проверка .env файла"""
    print_header("2. Проверка .env файла")
    
    env_exists = Path('.env').exists()
    print(f"{check_mark(env_exists)} .env файл {'существует' if env_exists else 'НЕ НАЙДЕН'}")
    
    if not env_exists:
        print(f"\n{YELLOW}⚠️  Создайте .env файл:{RESET}")
        print("   cp env.template .env")
        print("   nano .env  # Заполните все параметры")
        return False
    
    # Проверка обязательных переменных
    required_vars = [
        'TELEGRAM_API_ID',
        'TELEGRAM_API_HASH',
        'TELEGRAM_PHONE',
        'API_SECRET_KEY',
    ]

    optional_vars = [
        'AMOCRM_DOMAIN',
        'AMOCRM_CLIENT_ID',
        'AMOCRM_CLIENT_SECRET',
        'AMOCRM_REDIRECT_URI',
        'AMOCRM_ACCESS_TOKEN',
        'AMOCRM_REFRESH_TOKEN',
    ]
    
    print(f"\n{BLUE}Проверка переменных окружения:{RESET}")
    
    missing_vars = []
    for var in required_vars:
        value = os.getenv(var)
        is_set = value and value.strip() and not value.startswith('your_') and not value.startswith('CHANGE_ME')
        print(f"{check_mark(is_set)} {var:<30} {'настроена' if is_set else 'НЕ НАСТРОЕНА'}")
        if not is_set:
            missing_vars.append(var)

    print(f"\n{BLUE}Опциональные переменные (для AmoCRM):{RESET}")
    for var in optional_vars:
        value = os.getenv(var)
        is_set = value and value.strip() and not value.startswith('your_') and not value.startswith('CHANGE_ME')
        print(f"{check_mark(is_set)} {var:<30} {'настроена' if is_set else 'НЕ НАСТРОЕНА'}")
    
    if missing_vars:
        print(f"\n{RED}❌ Не настроены переменные:{RESET}")
        for var in missing_vars:
            print(f"   - {var}")
        return False
    
    return True

def check_python_syntax():
    """Проверка синтаксиса Python файлов"""
    print_header("3. Проверка синтаксиса Python")
    
    python_files = list(Path('src').glob('*.py'))
    all_valid = True
    
    for py_file in python_files:
        try:
            with open(py_file, 'r', encoding='utf-8') as f:
                compile(f.read(), py_file, 'exec')
            print(f"{GREEN}✓{RESET} {py_file}")
        except SyntaxError as e:
            print(f"{RED}✗{RESET} {py_file}: {e}")
            all_valid = False
    
    return all_valid

def check_dependencies():
    """Проверка установленных зависимостей"""
    print_header("4. Проверка зависимостей")
    
    required_packages = [
        ('telethon', 'Telethon'),
        ('fastapi', 'FastAPI'),
        ('uvicorn', 'Uvicorn'),
        ('sqlalchemy', 'SQLAlchemy'),
        ('pydantic', 'Pydantic'),
        ('aiohttp', 'aiohttp'),
    ]
    
    all_installed = True
    for package, name in required_packages:
        try:
            __import__(package)
            print(f"{GREEN}✓{RESET} {name}")
        except ImportError:
            print(f"{RED}✗{RESET} {name} - НЕ УСТАНОВЛЕН")
            all_installed = False
    
    if not all_installed:
        print(f"\n{YELLOW}⚠️  Установите зависимости:{RESET}")
        print("   pip install -r requirements-production.txt")
        return False
    
    return True

def check_directories():
    """Проверка необходимых директорий"""
    print_header("5. Проверка директорий")
    
    required_dirs = ['logs', 'sessions']
    all_exist = True
    
    for dir_name in required_dirs:
        dir_path = Path(dir_name)
        exists = dir_path.exists()
        
        if not exists:
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
                print(f"{GREEN}✓{RESET} {dir_name}/ - создана")
            except Exception as e:
                print(f"{RED}✗{RESET} {dir_name}/ - ошибка создания: {e}")
                all_exist = False
        else:
            print(f"{GREEN}✓{RESET} {dir_name}/ - существует")
    
    return all_exist

def check_database():
    """Проверка подключения к БД"""
    print_header("6. Проверка базы данных")
    
    db_url = os.getenv('DATABASE_URL')
    
    if not db_url or db_url == 'postgresql://postgres:password@localhost:5432/telegram_bot':
        print(f"{YELLOW}⚠️{RESET}  DATABASE_URL не настроен или использует значение по умолчанию")
        print(f"\n{YELLOW}Для локального тестирования запустите PostgreSQL:{RESET}")
        print("   docker run -d -p 5432:5432 \\")
        print("     -e POSTGRES_PASSWORD=password \\")
        print("     -e POSTGRES_DB=telegram_bot \\")
        print("     postgres:15-alpine")
        return False
    
    try:
        from sqlalchemy import create_engine
        engine = create_engine(db_url)
        with engine.connect() as conn:
            conn.execute("SELECT 1")
        print(f"{GREEN}✓{RESET} Подключение к БД успешно")
        return True
    except ImportError:
        print(f"{YELLOW}⚠️{RESET}  SQLAlchemy не установлена")
        return False
    except Exception as e:
        print(f"{RED}✗{RESET} Ошибка подключения к БД: {e}")
        print(f"\n{YELLOW}Проверьте:{RESET}")
        print("   1. PostgreSQL запущен")
        print("   2. DATABASE_URL правильный")
        print("   3. Учетные данные верные")
        return False

def print_summary(results):
    """Вывод итогов"""
    print_header("ИТОГОВАЯ ПРОВЕРКА")
    
    all_checks = [
        ("Файлы проекта", results['files']),
        ("Конфигурация (.env)", results['env']),
        ("Синтаксис Python", results['syntax']),
        ("Зависимости", results['dependencies']),
        ("Директории", results['directories']),
        ("База данных", results['database']),
    ]
    
    all_passed = all(result for _, result in all_checks)
    
    for check_name, passed in all_checks:
        status = f"{GREEN}PASSED{RESET}" if passed else f"{RED}FAILED{RESET}"
        print(f"{check_mark(passed)} {check_name:<30} {status}")
    
    print(f"\n{'='*60}\n")
    
    if all_passed:
        print(f"{GREEN}✅ ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ!{RESET}")
        print(f"\n{GREEN}Готово к запуску:{RESET}")
        print(f"   python -m src.main")
        print(f"\n{BLUE}Или через Docker:{RESET}")
        print(f"   ./scripts/deploy.sh")
    else:
        print(f"{RED}❌ ЕСТЬ ПРОБЛЕМЫ!{RESET}")
        print(f"\n{YELLOW}Исправьте ошибки выше и запустите снова:{RESET}")
        print(f"   python check_readiness.py")
    
    print()
    return all_passed

def main():
    """Главная функция"""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{'ПРОВЕРКА ГОТОВНОСТИ К ЗАПУСКУ':^60}{RESET}")
    print(f"{BLUE}{'AmoCRM Telegram MTProto Integration':^60}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    
    # Загружаем .env если есть
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    # Запускаем проверки
    results = {
        'files': check_files(),
        'env': check_env_file(),
        'syntax': check_python_syntax(),
        'dependencies': check_dependencies(),
        'directories': check_directories(),
        'database': check_database(),
    }
    
    # Выводим итоги
    all_passed = print_summary(results)
    
    sys.exit(0 if all_passed else 1)

if __name__ == '__main__':
    main()
