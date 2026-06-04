@echo off
set DATABASE_URL=sqlite:///./local_demo.db
set OUTBOX_PROCESS_INLINE=false
set UI_BASIC_AUTH_ENABLED=false
set API_HOST=127.0.0.1
set API_PORT=8000
set ALERT_TELEGRAM_CHAT_ID=0
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

cd /d C:\Users\putya\PycharmProjects\telegram_crm
.venv\Scripts\python.exe -m src.main
