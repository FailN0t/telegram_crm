"""
Модели базы данных
"""

from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, BigInteger, Boolean, DateTime,
    Text, Index, JSON, ForeignKey, ForeignKeyConstraint, CheckConstraint,
    text, select, event
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.pool import NullPool
from typing import AsyncGenerator, Optional
from src.config import settings
from src.logger import logger

# Базовый класс для моделей
Base = declarative_base()

def _make_async_db_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    return url


# Создание async engine
async_db_url = _make_async_db_url(settings.DATABASE_URL)
engine_options = {
    "echo": settings.DEBUG,
    "pool_pre_ping": True,
}
if async_db_url.startswith("sqlite+aiosqlite://"):
    engine_options["connect_args"] = {"check_same_thread": False}
elif settings.DB_USE_NULL_POOL:
    engine_options["poolclass"] = NullPool

engine = create_async_engine(async_db_url, **engine_options)

# Enable foreign keys for SQLite (required for CASCADE deletes)
if async_db_url.startswith("sqlite+aiosqlite://"):
    @event.listens_for(engine.sync_engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

# Создание async session
SessionLocal = async_sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False
)


class ChatMapping(Base):
    """Связь между Telegram chat_id и AmoCRM contact_id"""
    
    __tablename__ = "chat_mappings"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Account binding
    account_id = Column(
        Integer,
        ForeignKey("telegram_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )

    # Telegram данные
    # telegram_chat_id is NOT globally unique (multi-account support)
    # Unique constraint is on (account_id, telegram_chat_id) - see __table_args__
    telegram_chat_id = Column(BigInteger, nullable=False, index=True)
    telegram_username = Column(String(255), index=True)
    telegram_first_name = Column(String(255))
    telegram_last_name = Column(String(255))
    phone_number = Column(String(50), index=True)

    # AmoCRM данные
    # amocrm_contact_id is NOT globally unique (multi-account support)
    # Same CRM contact can be mapped to different Telegram accounts
    amocrm_contact_id = Column(Integer, nullable=False, index=True)

    # Статус
    is_active = Column(Boolean, default=True, index=True)
    is_blocked = Column(Boolean, default=False)
    has_consent = Column(Boolean, default=False)

    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_message_at = Column(DateTime)

    # Индексы и constraints
    __table_args__ = (
        # Unique constraint for multi-account: one chat per account
        Index('idx_chat_mappings_account_chat', 'account_id', 'telegram_chat_id', unique=True),
        # Regular indexes
        Index('idx_chat_mappings_account_id', 'account_id'),
        Index('idx_chat_mappings_telegram_chat_id', 'telegram_chat_id'),
        Index('idx_chat_mappings_amocrm_contact_id', 'amocrm_contact_id'),
        Index('idx_chat_mappings_phone_number', 'phone_number'),
        Index('idx_chat_mappings_telegram_username', 'telegram_username'),
        Index('idx_chat_mappings_active', 'is_active'),
    )


class TelegramAccount(Base):
    """Telegram account metadata for multi-account support"""

    __tablename__ = "telegram_accounts"

    id = Column(Integer, primary_key=True, index=True)
    phone_number = Column(String(32), unique=True, nullable=False, index=True)
    _session_string_encrypted = Column("session_string", Text)  # Encrypted storage
    label = Column(String(128))
    is_active = Column(Boolean, default=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_telegram_accounts_phone', 'phone_number'),
        Index('idx_telegram_accounts_active', 'is_active'),
    )

    @hybrid_property
    def session_string(self) -> Optional[str]:
        """
        Get decrypted session string.

        Automatically decrypts the encrypted value from database.
        Handles backward compatibility with plain text values.
        """
        if not self._session_string_encrypted:
            return None

        from src.crypto import get_session_encryption
        try:
            encryptor = get_session_encryption()
            return encryptor.decrypt(self._session_string_encrypted)
        except RuntimeError:
            # Encryption not initialized (e.g., during migrations)
            # Return as-is for backward compatibility
            return self._session_string_encrypted

    @session_string.setter
    def session_string(self, value: Optional[str]) -> None:
        """
        Set session string with automatic encryption.

        Encrypts the value before storing in database.
        If encryption is disabled, stores plain text.
        """
        if not value:
            self._session_string_encrypted = None
            return

        from src.crypto import get_session_encryption
        try:
            encryptor = get_session_encryption()
            self._session_string_encrypted = encryptor.encrypt(value)
        except RuntimeError:
            # Encryption not initialized (e.g., during migrations)
            # Store as-is for backward compatibility
            self._session_string_encrypted = value


class Operator(Base):
    """UI operator limits and metadata"""

    __tablename__ = "operators"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    display_name = Column(String(128))
    email = Column(String(100), unique=True, index=True)
    hourly_limit = Column(Integer, default=50)
    daily_limit = Column(Integer, default=200)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_operators_username', 'username'),
        Index('idx_operators_email', 'email'),
    )


class AppSetting(Base):
    """Admin-configurable application settings"""

    __tablename__ = "app_settings"

    key = Column(String(100), primary_key=True)
    value = Column(JSON, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_app_settings_key", "key"),
        Index("idx_app_settings_updated_at", "updated_at"),
    )


class MessageTemplate(Base):
    """Шаблоны быстрых ответов для UI"""

    __tablename__ = "message_templates"

    id = Column(Integer, primary_key=True, index=True)
    label = Column(String(120), nullable=False)
    body = Column(Text, nullable=False)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_message_templates_label", "label"),
        Index("idx_message_templates_active", "is_active"),
    )


class TagCatalog(Base):
    """Справочник тегов для UI"""

    __tablename__ = "tag_catalog"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(64), nullable=False, unique=True)
    description = Column(String(255), default="")
    color = Column(String(16), default="")
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index("idx_tag_catalog_name", "name"),
        Index("idx_tag_catalog_active", "is_active"),
    )


class ChatProfile(Base):
    """Локальный профиль чата (теги, заметки)"""

    __tablename__ = "chat_profiles"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(
        Integer,
        ForeignKey("telegram_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    telegram_chat_id = Column(
        BigInteger,
        nullable=False,
        index=True
    )
    tags = Column(String(255), default="")
    notes = Column(Text, default="")
    has_consent = Column(Boolean, default=False)
    opted_out = Column(Boolean, default=False)
    quiet_hours_start = Column(String(8))
    quiet_hours_end = Column(String(8))
    timezone = Column(String(64), default="UTC")

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Composite FK on (account_id, telegram_chat_id) references chat_mappings
        # This works because chat_mappings has unique constraint on (account_id, telegram_chat_id)
        ForeignKeyConstraint(
            ['account_id', 'telegram_chat_id'],
            ['chat_mappings.account_id', 'chat_mappings.telegram_chat_id'],
            ondelete='CASCADE'
        ),
        # Unique constraint: one profile per chat
        Index('idx_chat_profiles_account_chat', 'account_id', 'telegram_chat_id', unique=True),
        # Regular indexes
        Index('idx_chat_profiles_account_id', 'account_id'),
        Index('idx_chat_profiles_telegram_chat_id', 'telegram_chat_id'),
    )


class MessageOutbox(Base):
    """Очередь исходящих сообщений"""

    __tablename__ = "message_outbox"

    id = Column(Integer, primary_key=True, index=True)
    idempotency_key = Column(String(128), unique=True, nullable=False, index=True)
    account_id = Column(
        Integer,
        ForeignKey("telegram_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    operator_id = Column(
        Integer,
        ForeignKey("operators.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    chat_id = Column(
        BigInteger,
        nullable=False,
        index=True
    )
    payload = Column(JSON, nullable=False)
    status = Column(String(32), default="queued", index=True)
    attempts = Column(Integer, default=0)
    next_attempt_at = Column(DateTime)
    read_at = Column(DateTime, nullable=True)  # Timestamp когда сообщение прочитано получателем

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Composite FK on (account_id, chat_id) references chat_mappings(account_id, telegram_chat_id)
        ForeignKeyConstraint(
            ['account_id', 'chat_id'],
            ['chat_mappings.account_id', 'chat_mappings.telegram_chat_id'],
            ondelete='CASCADE'
        ),
        # Indexes
        Index('idx_message_outbox_idempotency_key', 'idempotency_key'),
        Index('idx_message_outbox_account_id', 'account_id'),
        Index('idx_message_outbox_operator_id', 'operator_id'),
        Index('idx_message_outbox_chat_id', 'chat_id'),
        Index('idx_message_outbox_account_chat', 'account_id', 'chat_id'),
        Index('idx_message_outbox_status', 'status'),
        Index('idx_message_outbox_next_attempt_at', 'next_attempt_at'),
        Index('idx_message_outbox_status_next_attempt', 'status', 'next_attempt_at'),
    )


class MessageDeliveryAttempt(Base):
    """Попытки доставки сообщений"""

    __tablename__ = "message_delivery_attempts"

    id = Column(Integer, primary_key=True, index=True)
    outbox_id = Column(
        Integer,
        ForeignKey("message_outbox.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    attempt = Column(Integer, default=1)
    status = Column(String(32), default="failed", index=True)
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_message_delivery_attempts_outbox_id', 'outbox_id'),
        Index('idx_message_delivery_attempts_status', 'status'),
    )


class MessageInbox(Base):
    """Дедупликация входящих событий"""

    __tablename__ = "message_inbox"

    id = Column(Integer, primary_key=True, index=True)
    idempotency_key = Column(String(128), unique=True, nullable=False, index=True)
    source = Column(String(64), nullable=False, index=True)
    payload_hash = Column(String(64), nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_message_inbox_idempotency_key', 'idempotency_key'),
        Index('idx_message_inbox_source', 'source'),
        Index('idx_message_inbox_created_at', 'created_at'),
    )


class TelegramSession(Base):
    """StringSession хранение для Telethon"""

    __tablename__ = "telegram_sessions"

    id = Column(Integer, primary_key=True, index=True)
    phone = Column(String(32), nullable=False, unique=True, index=True)
    _session_string_encrypted = Column("session_string", Text, nullable=False)  # Encrypted storage
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        Index('idx_telegram_sessions_phone', 'phone'),
    )

    @hybrid_property
    def session_string(self) -> str:
        """
        Get decrypted session string.

        Automatically decrypts the encrypted value from database.
        Handles backward compatibility with plain text values.
        """
        from src.crypto import get_session_encryption
        try:
            encryptor = get_session_encryption()
            return encryptor.decrypt(self._session_string_encrypted) or ""
        except RuntimeError:
            # Encryption not initialized (e.g., during migrations)
            # Return as-is for backward compatibility
            return self._session_string_encrypted or ""

    @session_string.setter
    def session_string(self, value: str) -> None:
        """
        Set session string with automatic encryption.

        Encrypts the value before storing in database.
        If encryption is disabled, stores plain text.
        """
        if not value:
            self._session_string_encrypted = ""
            return

        from src.crypto import get_session_encryption
        try:
            encryptor = get_session_encryption()
            self._session_string_encrypted = encryptor.encrypt(value) or value
        except RuntimeError:
            # Encryption not initialized (e.g., during migrations)
            # Store as-is for backward compatibility
            self._session_string_encrypted = value


class MessageHistory(Base):
    """История сообщений"""
    
    __tablename__ = "message_history"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Связи
    account_id = Column(
        Integer,
        ForeignKey("telegram_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    chat_mapping_id = Column(
        Integer,
        ForeignKey("chat_mappings.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    amocrm_contact_id = Column(Integer, nullable=False, index=True)
    
    # Направление
    direction = Column(String(10), nullable=False)  # 'inbound' или 'outbound'
    
    # Содержимое
    message_text = Column(Text)
    message_type = Column(String(50))  # 'text', 'photo', 'document', etc.
    
    # Telegram данные
    telegram_message_id = Column(Integer)
    telegram_chat_id = Column(BigInteger, index=True)
    
    # AmoCRM данные
    amocrm_note_id = Column(Integer)
    amocrm_task_id = Column(Integer)
    
    # Статус
    status = Column(String(20), default='sent')  # 'sent', 'delivered', 'failed'
    error_message = Column(Text)
    
    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    
    # Индексы и ограничения
    __table_args__ = (
        Index('idx_message_history_account_id', 'account_id'),
        Index('idx_message_history_chat_mapping_id', 'chat_mapping_id'),
        Index('idx_message_history_amocrm_contact_id', 'amocrm_contact_id'),
        Index('idx_message_history_telegram_chat_id', 'telegram_chat_id'),
        Index('idx_message_history_created_at', 'created_at'),
        Index('idx_message_history_direction', 'direction'),
        # Fix #117: Prevent chat_mapping_id=0 or negative (invalid FK)
        CheckConstraint('chat_mapping_id > 0', name='check_message_history_valid_mapping_id'),
    )


class UiMessageHistory(Base):
    """История сообщений UI"""

    __tablename__ = "ui_message_history"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(
        Integer,
        ForeignKey("telegram_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    chat_id = Column(
        BigInteger,
        nullable=False,
        index=True
    )
    direction = Column(String(10), nullable=False)
    message_text = Column(Text)
    message_type = Column(String(50))
    username = Column(String(255))
    display_name = Column(String(255))
    status = Column(String(20), default='sent')
    delivery_status = Column(String(20), default='queued')  # queued, sent, delivered, read, failed
    error_message = Column(Text)
    media_url = Column(Text)
    media_name = Column(String(255))
    media_mime = Column(String(255))
    media_size = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    __table_args__ = (
        # Composite FK on (account_id, chat_id) references chat_mappings(account_id, telegram_chat_id)
        ForeignKeyConstraint(
            ['account_id', 'chat_id'],
            ['chat_mappings.account_id', 'chat_mappings.telegram_chat_id'],
            ondelete='CASCADE'
        ),
        # Indexes
        Index('idx_ui_message_history_account_id', 'account_id'),
        Index('idx_ui_message_history_chat_id', 'chat_id'),
        Index('idx_ui_message_history_account_chat', 'account_id', 'chat_id'),
        Index('idx_ui_message_history_direction', 'direction'),
        Index('idx_ui_message_history_status', 'status'),
        Index('idx_ui_message_history_created_at', 'created_at'),
        Index('idx_ui_message_history_updated_at', 'updated_at'),
        Index('idx_ui_message_history_account_chat_created', 'account_id', 'chat_id', 'created_at'),
    )


class UiEventLog(Base):
    """Журнал событий UI"""

    __tablename__ = "ui_event_log"

    id = Column(Integer, primary_key=True, index=True)
    level = Column(String(16), nullable=False, index=True)
    message = Column(String(255), nullable=False, index=True)
    data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index('idx_ui_event_log_level', 'level'),
        Index('idx_ui_event_log_message', 'message'),
        Index('idx_ui_event_log_created_at', 'created_at'),
    )


class AuditLog(Base):
    """Audit log for admin actions"""

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    actor = Column(String(100), nullable=False, index=True)
    role = Column(String(50), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    entity_type = Column(String(100), index=True)
    entity_id = Column(String(100), index=True)
    data = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    __table_args__ = (
        Index('idx_audit_log_actor', 'actor'),
        Index('idx_audit_log_role', 'role'),
        Index('idx_audit_log_action', 'action'),
        Index('idx_audit_log_entity_type', 'entity_type'),
        Index('idx_audit_log_entity_id', 'entity_id'),
        Index('idx_audit_log_created_at', 'created_at'),
    )


class UiChat(Base):
    """Состояние чатов для UI"""

    __tablename__ = "ui_chats"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(
        Integer,
        ForeignKey("telegram_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    chat_id = Column(
        BigInteger,
        nullable=False,
        index=True
    )
    username = Column(String(255), default="")
    display_name = Column(String(255), default="")
    first_name = Column(String(255), default="")
    last_name = Column(String(255), default="")
    phone = Column(String(50), default="")

    last_message = Column(Text, default="")
    last_direction = Column(String(10), default="")
    last_timestamp = Column(DateTime, index=True)
    unread_count = Column(Integer, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    __table_args__ = (
        # Composite FK on (account_id, chat_id) references chat_mappings(account_id, telegram_chat_id)
        ForeignKeyConstraint(
            ['account_id', 'chat_id'],
            ['chat_mappings.account_id', 'chat_mappings.telegram_chat_id'],
            ondelete='CASCADE'
        ),
        # Unique constraint: one UI chat record per account/chat
        Index('idx_ui_chats_account_chat', 'account_id', 'chat_id', unique=True),
        # Regular indexes
        Index('idx_ui_chats_account_id', 'account_id'),
        Index('idx_ui_chats_chat_id', 'chat_id'),
        Index('idx_ui_chats_last_timestamp', 'last_timestamp'),
        Index('idx_ui_chats_unread', 'unread_count'),
        Index('idx_ui_chats_account_last_timestamp', 'account_id', 'last_timestamp'),
    )


class SendingStatistics(Base):
    """Статистика отправок"""

    __tablename__ = "sending_statistics"

    id = Column(Integer, primary_key=True, index=True)

    # Дата
    date = Column(DateTime, default=datetime.utcnow, index=True)

    # Счетчики
    messages_sent = Column(Integer, default=0)
    messages_failed = Column(Integer, default=0)
    new_chats_created = Column(Integer, default=0)
    flood_wait_errors = Column(Integer, default=0)
    privacy_errors = Column(Integer, default=0)

    # Средние значения
    avg_response_time = Column(Integer, default=0)  # в миллисекундах

    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow)

    # Индексы
    __table_args__ = (
        Index('idx_sending_statistics_date', 'date'),
    )


class ContactAddLog(Base):
    """
    Audit log for contact additions to Telegram

    Tracks all attempts to add Telegram users to contacts for phone extraction.
    Used for rate limiting and monitoring to prevent Telegram account bans.
    """

    __tablename__ = "contact_add_log"

    id = Column(Integer, primary_key=True, index=True)

    # User identification
    telegram_user_id = Column(BigInteger, nullable=False, index=True)

    # Direction: 'inbound' (customer writes first) or 'outbound' (we write first)
    direction = Column(String(10), nullable=False, index=True)

    # Source: 'incoming_message', 'crm_request', 'manual_admin', etc.
    source = Column(String(50), nullable=True)

    # Success/failure tracking
    success = Column(Boolean, default=False, nullable=False)

    # Timestamp for rate limiting queries
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Indexes for efficient rate limit queries
    __table_args__ = (
        Index('idx_contact_add_log_user', 'telegram_user_id'),
        Index('idx_contact_add_log_direction', 'direction'),
        Index('idx_contact_add_log_success', 'success'),
        Index('idx_contact_add_log_created', 'created_at'),
        # Composite index for rate limit queries (direction + timestamp)
        Index('idx_contact_add_log_direction_created', 'direction', 'created_at'),
        # Composite index for checking if user was already added
        Index('idx_contact_add_log_user_success', 'telegram_user_id', 'success'),
    )


class UiAuthAttempt(Base):
    """
    Audit trail for UI magic link authentication attempts

    Fix #169: Tracks all magic link auth attempts for security monitoring.
    Stores token, success/failure, IP address, user agent for security audit.
    """

    __tablename__ = "ui_auth_attempts"

    id = Column(Integer, primary_key=True, index=True)

    # Magic link token (UUID)
    token = Column(String(64), nullable=False, comment="Magic link UUID token")

    # Telegram user ID if known
    telegram_user_id = Column(BigInteger, nullable=True, comment="Telegram user ID if known")

    # Client information
    ip_address = Column(String(45), nullable=True, comment="Client IP address")
    user_agent = Column(Text, nullable=True, comment="Client user agent")

    # Success/failure tracking
    success = Column(Boolean, nullable=False, comment="Whether auth attempt was successful")

    # Timestamp
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        Index('ix_ui_auth_attempts_token', 'token'),
        Index('ix_ui_auth_attempts_created_at', 'created_at'),
    )

async def init_db():
    """Инициализация базы данных"""
    async with engine.begin() as conn:
        is_sqlite = engine.dialect.name == "sqlite"
        is_postgres = engine.dialect.name == "postgresql"

        # SQLite: always allow create_all (for testing)
        if is_sqlite:
            logger.info("✅ SQLite detected - creating tables automatically")
            await conn.run_sync(Base.metadata.create_all)
        # PostgreSQL + DEBUG + DB_ALLOW_CREATE_ALL: allow with warning
        elif is_postgres and settings.DEBUG and settings.DB_ALLOW_CREATE_ALL:
            logger.warning(
                "⚠️ DB_ALLOW_CREATE_ALL=true in DEBUG mode - creating tables. "
                "This bypasses Alembic migrations! Use 'alembic upgrade head' instead."
            )
            await conn.run_sync(Base.metadata.create_all)
        # PostgreSQL + production: NEVER allow create_all
        elif is_postgres and settings.DB_ALLOW_CREATE_ALL:
            raise RuntimeError(
                "❌ DB_ALLOW_CREATE_ALL=true is NOT allowed in production with PostgreSQL! "
                "This bypasses Alembic migrations and can cause schema drift. "
                "Use 'alembic upgrade head' to apply migrations properly."
            )
        # PostgreSQL + production: just check connection
        else:
            await conn.execute(text("SELECT 1"))

    try:
        await ensure_default_account()
    except Exception as exc:
        logger.warning(f"⚠️ Не удалось создать default аккаунт: {exc}")


async def ensure_default_account() -> Optional[int]:
    """Ensure a default Telegram account exists and return its id."""
    async with SessionLocal() as session:
        result = await session.execute(
            select(TelegramAccount).order_by(TelegramAccount.id.asc()).limit(1)
        )
        existing = result.scalars().first()
        if existing:
            return existing.id

        phone = settings.TELEGRAM_PHONE or "default"
        session_string = settings.TELEGRAM_STRING_SESSION
        if not session_string:
            result = await session.execute(
                select(TelegramSession).filter_by(phone=phone)
            )
            record = result.scalars().first()
            if record:
                session_string = record.session_string

        account = TelegramAccount(
            phone_number=phone,
            session_string=session_string,
            label=phone,
            is_active=True
        )
        session.add(account)
        await session.commit()
        await session.refresh(account)
        return account.id


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Получение async сессии БД"""
    async with SessionLocal() as db:
        yield db
