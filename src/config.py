"""
Конфигурация приложения
"""

import os
import logging
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field
from dotenv import load_dotenv


logger = logging.getLogger(__name__)


def _apply_file_secrets() -> None:
    for key, path in list(os.environ.items()):
        if not key.endswith("_FILE"):
            continue
        if not path:
            continue
        target_key = key[:-5]
        if os.environ.get(target_key):
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = handle.read().strip()
        except OSError as exc:
            raise RuntimeError(f"Cannot read secret file for {target_key}: {path}") from exc
        if not value:
            raise RuntimeError(f"Secret file for {target_key} is empty: {path}")
        os.environ[target_key] = value


class Settings(BaseSettings):
    """Настройки приложения"""
    
    # Application
    APP_NAME: str = "AmoCRM-Telegram-MTProto"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False, env="DEBUG")
    
    # Telegram MTProto
    TELEGRAM_API_ID: int = Field(..., env="TELEGRAM_API_ID")
    TELEGRAM_API_HASH: str = Field(..., env="TELEGRAM_API_HASH")
    TELEGRAM_PHONE: str = Field(..., env="TELEGRAM_PHONE")
    TELEGRAM_SESSION_NAME: str = Field(default="amocrm_session", env="TELEGRAM_SESSION_NAME")
    TELEGRAM_STRING_SESSION: Optional[str] = Field(default=None, env="TELEGRAM_STRING_SESSION")
    
    # AmoCRM (optional for local Telegram-only testing)
    AMOCRM_DOMAIN: Optional[str] = Field(default=None, env="AMOCRM_DOMAIN")
    AMOCRM_CLIENT_ID: Optional[str] = Field(default=None, env="AMOCRM_CLIENT_ID")
    AMOCRM_CLIENT_SECRET: Optional[str] = Field(default=None, env="AMOCRM_CLIENT_SECRET")
    AMOCRM_REDIRECT_URI: Optional[str] = Field(default=None, env="AMOCRM_REDIRECT_URI")
    AMOCRM_ACCESS_TOKEN: Optional[str] = Field(default=None, env="AMOCRM_ACCESS_TOKEN")
    AMOCRM_REFRESH_TOKEN: Optional[str] = Field(default=None, env="AMOCRM_REFRESH_TOKEN")
    AMOCRM_TOKEN_EXPIRES_AT: Optional[str] = Field(default=None, env="AMOCRM_TOKEN_EXPIRES_AT")
    AMOCRM_WEBHOOK_SECRET: Optional[str] = Field(default=None, env="AMOCRM_WEBHOOK_SECRET")
    
    # AmoCRM Custom Fields IDs
    AMOCRM_FIELD_TELEGRAM_USERNAME: int = Field(default=0, env="AMOCRM_FIELD_TELEGRAM_USERNAME")
    AMOCRM_FIELD_TELEGRAM_CHAT_ID: int = Field(default=0, env="AMOCRM_FIELD_TELEGRAM_CHAT_ID")
    AMOCRM_FIELD_TELEGRAM_CONSENT: int = Field(default=0, env="AMOCRM_FIELD_TELEGRAM_CONSENT")

    # Bitrix24 CRM (alternative to AmoCRM)
    BITRIX24_DOMAIN: Optional[str] = Field(default=None, env="BITRIX24_DOMAIN")
    BITRIX24_CLIENT_ID: Optional[str] = Field(default=None, env="BITRIX24_CLIENT_ID")
    BITRIX24_CLIENT_SECRET: Optional[str] = Field(default=None, env="BITRIX24_CLIENT_SECRET")
    BITRIX24_REDIRECT_URI: Optional[str] = Field(default=None, env="BITRIX24_REDIRECT_URI")
    BITRIX24_ACCESS_TOKEN: Optional[str] = Field(default=None, env="BITRIX24_ACCESS_TOKEN")
    BITRIX24_REFRESH_TOKEN: Optional[str] = Field(default=None, env="BITRIX24_REFRESH_TOKEN")
    BITRIX24_TOKEN_EXPIRES_AT: Optional[str] = Field(default=None, env="BITRIX24_TOKEN_EXPIRES_AT")
    BITRIX24_WEBHOOK_SECRET: Optional[str] = Field(default=None, env="BITRIX24_WEBHOOK_SECRET")
    # Входящий webhook URL (альтернатива OAuth)
    BITRIX24_WEBHOOK_URL: Optional[str] = Field(default=None, env="BITRIX24_WEBHOOK_URL")

    # Bitrix24 User Fields (UF_*) для Telegram данных
    BITRIX24_FIELD_TELEGRAM_USERNAME: str = Field(
        default="UF_CRM_TELEGRAM_USERNAME",
        env="BITRIX24_FIELD_TELEGRAM_USERNAME"
    )
    BITRIX24_FIELD_TELEGRAM_CHAT_ID: str = Field(
        default="UF_CRM_TELEGRAM_CHAT_ID",
        env="BITRIX24_FIELD_TELEGRAM_CHAT_ID"
    )
    BITRIX24_FIELD_TELEGRAM_CONSENT: str = Field(
        default="UF_CRM_TELEGRAM_CONSENT",
        env="BITRIX24_FIELD_TELEGRAM_CONSENT"
    )

    # Bitrix24 Open Channels (Открытые линии) - двусторонний чат в карточке клиента
    BITRIX24_OPEN_CHANNELS_ENABLED: bool = Field(
        default=False,
        env="BITRIX24_OPEN_CHANNELS_ENABLED"
    )
    BITRIX24_CONNECTOR_ID: str = Field(
        default="telegram_mtproto",
        env="BITRIX24_CONNECTOR_ID"
    )
    BITRIX24_CONNECTOR_NAME: str = Field(
        default="Telegram MTProto",
        env="BITRIX24_CONNECTOR_NAME"
    )
    BITRIX24_LINE_ID: int = Field(
        default=0,
        env="BITRIX24_LINE_ID"
    )

    # CRM Provider: "amocrm" или "bitrix24"
    CRM_PROVIDER: str = Field(default="amocrm", env="CRM_PROVIDER")

    # Database
    DATABASE_URL: str = Field(
        default="postgresql://postgres:password@localhost:5432/telegram_bot",
        env="DATABASE_URL"
    )
    DB_ALLOW_CREATE_ALL: bool = Field(default=False, env="DB_ALLOW_CREATE_ALL")
    DB_USE_NULL_POOL: bool = Field(default=False, env="DB_USE_NULL_POOL")
    
    # Redis
    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        env="REDIS_URL"
    )

    # MinIO (Media storage)
    MINIO_ENDPOINT: Optional[str] = Field(default=None, env="MINIO_ENDPOINT")
    MINIO_ACCESS_KEY: Optional[str] = Field(default=None, env="MINIO_ACCESS_KEY")
    MINIO_SECRET_KEY: Optional[str] = Field(default=None, env="MINIO_SECRET_KEY")
    MINIO_BUCKET: str = Field(default="telegram-media", env="MINIO_BUCKET")
    MINIO_SECURE: bool = Field(default=False, env="MINIO_SECURE")
    MINIO_PUBLIC_URL: Optional[str] = Field(default=None, env="MINIO_PUBLIC_URL")
    
    # API Server
    API_HOST: str = Field(default="0.0.0.0", env="API_HOST")
    API_PORT: int = Field(default=8000, env="API_PORT")
    API_SECRET_KEY: str = Field(..., env="API_SECRET_KEY")
    API_ALLOWED_IPS: list[str] = Field(default=[], env="API_ALLOWED_IPS")
    API_RATE_LIMIT_PER_MINUTE: int = Field(default=120, env="API_RATE_LIMIT_PER_MINUTE")

    # Security - Session Encryption
    SESSION_ENCRYPTION_KEY: Optional[str] = Field(
        default=None,
        env="SESSION_ENCRYPTION_KEY"
    )

    # UI Basic Auth (optional)
    UI_BASIC_AUTH_ENABLED: bool = Field(default=False, env="UI_BASIC_AUTH_ENABLED")
    UI_BASIC_AUTH_USERS: Optional[str] = Field(default=None, env="UI_BASIC_AUTH_USERS")

    # Compliance
    DEFAULT_TIMEZONE: str = Field(default="UTC", env="DEFAULT_TIMEZONE")
    
    # Anti-Spam Limits
    MAX_MESSAGES_PER_HOUR: int = Field(default=50, env="MAX_MESSAGES_PER_HOUR")
    MAX_NEW_CHATS_PER_DAY: int = Field(default=20, env="MAX_NEW_CHATS_PER_DAY")
    MIN_DELAY_BETWEEN_MESSAGES: int = Field(default=5, env="MIN_DELAY_BETWEEN_MESSAGES")

    # Outbox processing
    OUTBOX_PROCESS_INLINE: bool = Field(default=True, env="OUTBOX_PROCESS_INLINE")
    OUTBOX_MAX_ATTEMPTS: int = Field(default=5, env="OUTBOX_MAX_ATTEMPTS")
    OUTBOX_RETRY_BASE_SECONDS: int = Field(default=10, env="OUTBOX_RETRY_BASE_SECONDS")
    OUTBOX_POLL_INTERVAL: int = Field(default=2, env="OUTBOX_POLL_INTERVAL")

    # Data retention (days, 0 = disable)
    UI_MESSAGE_RETENTION_DAYS: int = Field(default=365, env="UI_MESSAGE_RETENTION_DAYS")
    UI_EVENT_RETENTION_DAYS: int = Field(default=90, env="UI_EVENT_RETENTION_DAYS")
    AUDIT_LOG_RETENTION_DAYS: int = Field(default=365, env="AUDIT_LOG_RETENTION_DAYS")
    MESSAGE_INBOX_RETENTION_DAYS: int = Field(default=30, env="MESSAGE_INBOX_RETENTION_DAYS")
    
    # Logging
    LOG_LEVEL: str = Field(default="INFO", env="LOG_LEVEL")
    LOG_FILE: str = Field(default="logs/app.log", env="LOG_FILE")
    LOG_MAX_BYTES: int = Field(default=10485760, env="LOG_MAX_BYTES")  # 10MB
    LOG_BACKUP_COUNT: int = Field(default=5, env="LOG_BACKUP_COUNT")
    
    # Monitoring
    ENABLE_METRICS: bool = Field(default=True, env="ENABLE_METRICS")
    ALERT_TELEGRAM_BOT_TOKEN: Optional[str] = Field(default=None, env="ALERT_TELEGRAM_BOT_TOKEN")
    ALERT_TELEGRAM_CHAT_ID: Optional[int] = Field(default=None, env="ALERT_TELEGRAM_CHAT_ID")
    ALERT_EMAIL: Optional[str] = Field(default=None, env="ALERT_EMAIL")
    ERROR_TRACKING_DSN: Optional[str] = Field(default=None, env="ERROR_TRACKING_DSN")
    ERROR_TRACKING_ENV: str = Field(default="production", env="ERROR_TRACKING_ENV")
    ERROR_TRACKING_SAMPLE_RATE: float = Field(default=0.1, env="ERROR_TRACKING_SAMPLE_RATE")
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
        "extra": "ignore"  # Игнорировать лишние поля
    }


# Глобальный экземпляр настроек
load_dotenv(".env")
_apply_file_secrets()
settings = Settings()

# Initialize session encryption
from src.crypto import init_session_encryption, derive_key_from_secret

# Use SESSION_ENCRYPTION_KEY if provided, otherwise derive from API_SECRET_KEY
encryption_key = settings.SESSION_ENCRYPTION_KEY
if not encryption_key and settings.API_SECRET_KEY:
    # Fallback: derive key from API_SECRET_KEY for backward compatibility
    encryption_key = derive_key_from_secret(settings.API_SECRET_KEY)
    logger.info(
        "ℹ️ SESSION_ENCRYPTION_KEY not set, deriving from API_SECRET_KEY"
    )

init_session_encryption(encryption_key)
