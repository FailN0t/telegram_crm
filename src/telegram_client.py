"""
MTProto Telegram клиент
Подключение к Telegram через личный аккаунт
"""

import os
import tempfile
import asyncio
from datetime import datetime, time
from zoneinfo import ZoneInfo
from pathlib import Path
from typing import Optional, Tuple
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from sqlalchemy import select, func
from telethon.tl.functions.contacts import ImportContactsRequest
from telethon.tl.types import InputPhoneContact, User
from telethon.errors import (
    FloodWaitError,
    UserPrivacyRestrictedError,
    PeerIdInvalidError,
    PhoneNumberBannedError,
    SessionPasswordNeededError
)

from src.config import settings
from src.logger import logger
from src.antispam import AntiSpamManager
from src.redis_client import get_redis
from src.media_storage import upload_file
from src.retry_utils import retry_telegram
from src.database import (
    ChatMapping,
    ChatProfile,
    MessageHistory,
    TelegramAccount,
    TelegramSession,
    UiChat,
    UiMessageHistory,
    SessionLocal
)


class MTProtoClient:
    """
    Клиент для работы с Telegram через MTProto API
    Использует личный аккаунт (не бота)
    """
    
    def __init__(
        self,
        account_id: int,
        phone_number: Optional[str] = None,
        session_string: Optional[str] = None,
        session_name: Optional[str] = None,
        bridge=None
    ):
        self.account_id = account_id
        self.phone_number = phone_number or settings.TELEGRAM_PHONE
        self.session_name = session_name or f"{settings.TELEGRAM_SESSION_NAME}_{account_id}"
        self.bridge = bridge

        # ВАЖНО: ВСЕГДА используем StringSession для сохранения в БД
        # Даже если session_string пустой - создаем пустой StringSession
        self.client = TelegramClient(
            StringSession(session_string or ""),
            settings.TELEGRAM_API_ID,
            settings.TELEGRAM_API_HASH
        )
        self._using_string_session = True
        self.anti_spam = AntiSpamManager(account_id=self.account_id)
        self.me = None
        self._handlers_registered = False
        self._auth_phone = None
        self._session_paths = None
        self._recent_chat_ids: set[int] = set()

        # Lock to prevent race conditions during initialization
        # Protects: self.me assignment, event handlers registration
        self._init_lock = asyncio.Lock()

        # Fix #2: Lock to prevent race conditions during connection
        # Protects: concurrent calls to client.connect()
        self._connect_lock = asyncio.Lock()

        # Fix #4: Lock to prevent race conditions in _warm_ui_chats
        # Protects: self._recent_chat_ids modifications
        self._chats_lock = asyncio.Lock()

    async def _load_string_session(self) -> Optional[str]:
        if (
            settings.TELEGRAM_STRING_SESSION
            and self.phone_number == settings.TELEGRAM_PHONE
        ):
            return settings.TELEGRAM_STRING_SESSION

        async with SessionLocal() as session:
            try:
                result = await session.execute(
                    select(TelegramAccount).filter_by(id=self.account_id)
                )
                account = result.scalars().first()
                if account and account.session_string:
                    return account.session_string

                result = await session.execute(
                    select(TelegramSession).filter_by(phone=self.phone_number)
                )
                record = result.scalars().first()
                if record:
                    return record.session_string
            except Exception as e:
                logger.warning(f"⚠️ Не удалось загрузить StringSession из БД: {e}")
        return None

    async def _persist_string_session(self) -> None:
        logger.info(f"💾 Сохранение session_string для account_id={self.account_id}")

        # Проверка состояния клиента
        try:
            is_connected = self.client.is_connected()
            is_authorized = await self.client.is_user_authorized()
            logger.info(f"📊 Статус клиента: connected={is_connected}, authorized={is_authorized}")
        except Exception as e:
            logger.warning(f"⚠️ Не удалось проверить статус клиента: {e}")

        # Получение StringSession
        try:
            session_string = self.client.session.save()
            logger.info(f"✅ StringSession получен, длина: {len(session_string) if session_string else 0}")

            # Fix #173: НЕ логируем содержимое session_string (утечка секретов)
            if session_string:
                logger.info(f"🔍 StringSession валиден (содержимое скрыто для безопасности)")
            else:
                logger.error(f"❌ StringSession ПУСТОЙ! Проверка session object:")
                logger.error(f"   - session type: {type(self.client.session)}")
                logger.error(f"   - session class: {self.client.session.__class__.__name__}")
                if hasattr(self.client.session, '_dc_id'):
                    logger.error(f"   - dc_id: {self.client.session._dc_id}")
                if hasattr(self.client.session, '_auth_key'):
                    logger.error(f"   - auth_key exists: {self.client.session._auth_key is not None}")

        except Exception as e:
            logger.error(f"❌ Исключение при получении StringSession: {e}", exc_info=True)
            return

        if not session_string:
            logger.warning("⚠️ StringSession пустой, пропускаем сохранение")
            logger.warning("⚠️ ВАЖНО: Это означает что авторизация НЕ будет сохранена!")
            return

        # Сохранение в БД
        async with SessionLocal() as session:
            try:
                result = await session.execute(
                    select(TelegramAccount).filter_by(id=self.account_id)
                )
                account = result.scalars().first()
                if account:
                    logger.info(f"📝 Обновление session_string для существующего аккаунта {self.account_id}")
                    old_len = len(account.session_string or "")
                    account.session_string = session_string
                    account.updated_at = datetime.utcnow()
                    logger.info(f"📏 Размер session_string: {old_len} → {len(session_string)}")
                else:
                    logger.info(f"➕ Создание нового аккаунта {self.account_id} с session_string")
                    account = TelegramAccount(
                        id=self.account_id,
                        phone_number=self.phone_number,
                        session_string=session_string,
                        label=self.phone_number,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    session.add(account)

                # Дублируем в telegram_sessions для совместимости
                result = await session.execute(
                    select(TelegramSession).filter_by(phone=self.phone_number)
                )
                record = result.scalars().first()
                if record:
                    record.session_string = session_string
                    record.updated_at = datetime.utcnow()
                    logger.info(f"📝 Обновлен TelegramSession для {self.phone_number}")
                else:
                    record = TelegramSession(
                        phone=self.phone_number,
                        session_string=session_string,
                        created_at=datetime.utcnow(),
                        updated_at=datetime.utcnow()
                    )
                    session.add(record)
                    logger.info(f"➕ Создан TelegramSession для {self.phone_number}")

                await session.commit()
                logger.info(f"✅ StringSession успешно сохранен в БД для account_id={self.account_id}")

                # Проверка сохранения
                result = await session.execute(
                    select(TelegramAccount).filter_by(id=self.account_id)
                )
                check_account = result.scalars().first()
                if check_account and check_account.session_string:
                    logger.info(f"✅ Проверка: session_string в БД, длина={len(check_account.session_string)}")
                else:
                    logger.error(f"❌ Проверка провалена: session_string НЕ сохранился в БД!")

            except Exception as e:
                logger.error(f"❌ Ошибка записи StringSession в БД: {e}", exc_info=True)
                await session.rollback()

    async def connect(self):
        """
        Подключение клиента (без интерактивной авторизации).

        Fix #2: Double-checked locking to prevent race condition
        when multiple threads call connect() simultaneously.
        """
        # Fast path: check without lock
        if self.client.is_connected():
            return

        # Slow path: acquire lock and check again
        async with self._connect_lock:
            # Double-check inside lock (another thread may have connected)
            if not self.client.is_connected():
                await self.client.connect()
                logger.debug(f"✅ Telegram client connected (account_id={self.account_id})")
        
    async def start(self):
        """Запуск клиента и авторизация"""
        try:
            logger.info("🚀 Запуск MTProto клиента...")
            if not self._using_string_session:
                session_string = await self._load_string_session()
                if session_string:
                    self.client = TelegramClient(
                        StringSession(session_string),
                        settings.TELEGRAM_API_ID,
                        settings.TELEGRAM_API_HASH
                    )
                    self._using_string_session = True

            await self.connect()
            await self.anti_spam.initialize()
            await self._warm_ui_chats()
            if await self.client.is_user_authorized():
                await self._on_authorized()
            else:
                logger.warning(
                    "⚠️ Клиент не авторизован. "
                    "Откройте /ui/auth и выполните вход."
                )
            
        except SessionPasswordNeededError:
            logger.error("🔐 Требуется 2FA пароль! Настройте 2FA или введите пароль")
            raise
        except PhoneNumberBannedError:
            logger.critical("🚨 ВАШ НОМЕР ЗАБЛОКИРОВАН TELEGRAM!")
            raise
        except Exception as e:
            logger.error(f"❌ Ошибка запуска клиента: {e}")
            raise

    async def _on_authorized(self):
        """
        Действия после успешной авторизации.

        Thread-safe: Uses lock to prevent race conditions during concurrent start() calls.
        Protects against duplicate event handler registration and multiple get_me() calls.
        """
        # CRITICAL SECTION - protected by lock to prevent race conditions
        async with self._init_lock:
            # Double-check pattern: verify again after acquiring lock
            if not self.me:
                self.me = await self.client.get_me()
                logger.info(
                    f"✅ Авторизован как: {self.me.first_name} "
                    f"(@{self.me.username or 'no username'})"
                )
                logger.info(f"📱 Телефон: {self.me.phone}")
                logger.info(f"🆔 User ID: {self.me.id}")

            if not self._handlers_registered:
                self.client.add_event_handler(
                    self._handle_incoming_message,
                    events.NewMessage(incoming=True)
                )
                # MessageRead обработчик отключен - reading status не отправляется
                # В Bitrix24 будет показываться только "доставлено", без "просмотрено"
                # self.client.add_event_handler(
                #     self._handle_message_read,
                #     events.MessageRead()
                # )
                self._handlers_registered = True

        # Session persist can be done outside lock - not critical
        await self._persist_string_session()
        logger.info("✅ MTProto клиент успешно запущен!")

    async def _warm_ui_chats(self, limit: int = 200) -> None:
        """
        Load recent chats from database into memory.

        Fix #4: Uses lock to prevent race condition when multiple
        threads call this method simultaneously.
        """
        try:
            async with SessionLocal() as session:
                result = await session.execute(
                    select(UiChat.chat_id)
                    .filter_by(account_id=self.account_id)
                    .order_by(UiChat.last_timestamp.desc().nullslast())
                    .limit(limit)
                )
                chat_ids = set(result.scalars().all())

                # Fix #4: Protect assignment with lock
                async with self._chats_lock:
                    self._recent_chat_ids = chat_ids
        except Exception as exc:
            logger.warning(f"⚠️ Не удалось загрузить чаты UI из БД: {exc}")

    def _get_session_paths(self) -> tuple[Path, Path]:
        if self._session_paths:
            return self._session_paths

        base = Path(self.session_name)
        if base.suffix == ".session":
            session_path = base
        else:
            session_path = base.with_suffix(".session")
        journal_path = session_path.with_suffix(".session-journal")
        self._session_paths = (session_path, journal_path)
        return self._session_paths

    def get_session_info(self) -> dict:
        session_path, journal_path = self._get_session_paths()
        info = {
            "name": session_path.stem,
            "path": str(session_path),
            "exists": session_path.exists(),
            "journal_exists": journal_path.exists(),
        }
        if session_path.exists():
            stat = session_path.stat()
            info["size_bytes"] = stat.st_size
            info["updated_at"] = datetime.utcfromtimestamp(
                stat.st_mtime
            ).isoformat() + "Z"
        return info

    async def reset_local_state(self):
        """
        Reset local state (chats, auth phone).

        Fix #4: Uses lock to prevent race condition with _warm_ui_chats().
        """
        async with self._chats_lock:
            self._recent_chat_ids.clear()
        self._auth_phone = None

    async def logout(self) -> Tuple[bool, str]:
        """Выход из аккаунта и очистка локальной сессии"""
        await self.connect()
        try:
            await self.client.log_out()
            await self.client.disconnect()
        except Exception as exc:
            logger.error(f"❌ Ошибка выхода из аккаунта: {exc}")
            return False, str(exc)

        self.me = None
        try:
            self.client.remove_event_handler(self._handle_incoming_message)
        except Exception:
            pass
        self._handlers_registered = False
        await self.reset_local_state()  # Fix #4: await async method

        session_path, journal_path = self._get_session_paths()
        for path in (session_path, journal_path):
            try:
                if path.exists():
                    path.unlink()
            except Exception as exc:
                logger.warning(f"⚠️ Не удалось удалить {path}: {exc}")

        return True, "logged_out"

    async def is_authorized(self) -> bool:
        """Проверка авторизации"""
        await self.connect()
        authorized = await self.client.is_user_authorized()
        if authorized and not self.me:
            await self._on_authorized()
        return authorized

    async def request_code(self, phone: Optional[str] = None) -> Tuple[bool, str]:
        """Запрос кода авторизации"""
        await self.connect()

        if await self.client.is_user_authorized():
            return True, "already_authorized"

        phone = phone or self.phone_number
        if not phone:
            return False, "phone_required"

        if not phone.startswith('+'):
            phone = '+' + phone

        self._auth_phone = phone

        try:
            sent = await self.client.send_code_request(phone)
            phone_code_hash = getattr(sent, "phone_code_hash", None)
            if phone_code_hash:
                redis = await get_redis()
                if redis:
                    key = f"auth:phone_code_hash:{phone}"
                    await redis.setex(key, 300, phone_code_hash)
            return True, "code_sent"
        except Exception as e:
            logger.error(f"❌ Ошибка запроса кода: {e}")
            return False, str(e)

    async def submit_code(self, code: str, phone: Optional[str] = None) -> Tuple[bool, str]:
        """Подтверждение кода авторизации"""
        await self.connect()
        phone = phone or self._auth_phone or self.phone_number

        if not phone:
            return False, "phone_required"

        try:
            redis = await get_redis()
            phone_code_hash = None
            if redis:
                key = f"auth:phone_code_hash:{phone}"
                phone_code_hash = await redis.get(key)
            sign_in_args = {"phone": phone, "code": code}
            if phone_code_hash:
                sign_in_args["phone_code_hash"] = phone_code_hash
            await self.client.sign_in(**sign_in_args)
            if redis:
                await redis.delete(f"auth:phone_code_hash:{phone}")
            await self._on_authorized()
            return True, "authorized"
        except SessionPasswordNeededError:
            return False, "2fa_required"
        except Exception as e:
            logger.error(f"❌ Ошибка подтверждения кода: {e}")
            return False, str(e)

    async def submit_password(self, password: str) -> Tuple[bool, str]:
        """Подтверждение 2FA пароля"""
        await self.connect()

        try:
            await self.client.sign_in(password=password)
            redis = await get_redis()
            if redis:
                phone = self._auth_phone or self.phone_number
                if phone:
                    await redis.delete(f"auth:phone_code_hash:{phone}")
            await self._on_authorized()
            return True, "authorized"
        except Exception as e:
            logger.error(f"❌ Ошибка 2FA: {e}")
            return False, str(e)

    async def _store_message(
        self,
        direction: str,
        chat_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        text: str,
        increment_unread: bool,
        status: str = "sent",
        error_message: Optional[str] = None,
        media_url: Optional[str] = None,
        media_name: Optional[str] = None,
        media_mime: Optional[str] = None,
        media_size: Optional[int] = None
    ):
        timestamp = datetime.utcnow()
        message_type = "media" if media_url or text == "[media]" else "text"
        if text == "[media]" and not media_url:
            message_type = "media"
        display_name = self._format_chat_name(
            username,
            first_name,
            last_name,
            chat_id
        )

        logger.info(f"💾 Сохранение UI сообщения: direction={direction}, chat_id={chat_id}, text={text[:50]}...")
        async with SessionLocal() as session:
            try:
                # Проверяем наличие chat_mapping
                from sqlalchemy import select
                from src.database import ChatMapping
                result = await session.execute(
                    select(ChatMapping).filter_by(telegram_chat_id=chat_id)
                )
                mapping = result.scalars().first()
                if not mapping:
                    logger.warning(f"⚠️ ChatMapping не найден для chat_id={chat_id}, создаем...")
                    mapping = ChatMapping(
                        account_id=self.account_id,
                        telegram_chat_id=chat_id,
                        telegram_username=username,
                        telegram_first_name=first_name,
                        telegram_last_name=last_name,
                        amocrm_contact_id=0,  # Временный ID, будет обновлен позже
                        is_active=True
                    )
                    session.add(mapping)
                    await session.flush()
                    logger.info(f"✅ ChatMapping создан для chat_id={chat_id}")

                history = UiMessageHistory(
                    account_id=self.account_id,
                    chat_id=chat_id,
                    direction=direction,
                    message_text=text,
                    message_type=message_type,
                    username=username or "",
                    display_name=display_name,
                    status=status,
                    error_message=error_message,
                    media_url=media_url,
                    media_name=media_name,
                    media_mime=media_mime,
                    media_size=media_size
                )
                session.add(history)
                logger.info(f"✅ UiMessageHistory добавлен в сессию")

                await self._upsert_ui_chat(
                    session,
                    chat_id=chat_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    display_name=display_name,
                    phone=None,
                    last_message=text,
                    last_direction=direction,
                    last_timestamp=timestamp,
                    increment_unread=increment_unread
                )
                await session.commit()
                logger.info(f"✅ UI сообщение сохранено: direction={direction}, chat_id={chat_id}")
            except Exception as e:
                logger.error(f"❌ Не удалось сохранить UI историю: {e}", exc_info=True)
                await session.rollback()

    async def _upsert_ui_chat(
        self,
        session,
        chat_id: int,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        display_name: Optional[str],
        phone: Optional[str],
        last_message: Optional[str],
        last_direction: Optional[str],
        last_timestamp: Optional[datetime],
        increment_unread: bool
    ) -> None:
        result = await session.execute(
            select(UiChat).filter_by(chat_id=chat_id, account_id=self.account_id)
        )
        chat = result.scalars().first()
        if not chat:
            chat = UiChat(chat_id=chat_id, account_id=self.account_id)
            session.add(chat)

        if username:
            chat.username = username
        if first_name:
            chat.first_name = first_name
        if last_name:
            chat.last_name = last_name
        if display_name:
            chat.display_name = display_name
        if phone:
            chat.phone = phone

        if last_message is not None:
            chat.last_message = last_message
        if last_direction is not None:
            chat.last_direction = last_direction
        if last_timestamp is not None:
            chat.last_timestamp = last_timestamp

        if increment_unread:
            chat.unread_count = (chat.unread_count or 0) + 1

    def _format_chat_name(
        self,
        username: Optional[str],
        first_name: Optional[str],
        last_name: Optional[str],
        chat_id: int
    ) -> str:
        parts = [first_name or "", last_name or ""]
        name = " ".join(part for part in parts if part).strip()
        if name:
            return name
        if username:
            return f"@{username}"
        return f"User {chat_id}"

    async def _upload_media(
        self,
        message,
        chat_id: int
    ) -> tuple[Optional[str], Optional[str], Optional[str], Optional[int]]:
        if not message or not message.media:
            return None, None, None, None
        if not settings.MINIO_ENDPOINT:
            return None, None, None, None

        file_name = None
        mime_type = None
        file_size = None
        if message.file:
            file_name = message.file.name
            mime_type = message.file.mime_type
            file_size = message.file.size

        if not file_name:
            file_name = f"media_{chat_id}_{message.id}"

        suffix = Path(file_name).suffix or ""
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
                temp_path = tmp.name
            await message.download_media(file=temp_path)
            object_name = f"telegram/{chat_id}/{message.id}/{Path(file_name).name}"
            media_url = await upload_file(temp_path, object_name, content_type=mime_type)
            return media_url, file_name, mime_type, file_size
        except Exception as exc:
            logger.warning(f"⚠️ Не удалось сохранить медиа: {exc}")
            return None, None, None, None
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except OSError:
                    pass

    async def get_recent_messages(
        self,
        limit: int = 50,
        chat_id: Optional[int] = None
    ) -> list[dict]:
        async with SessionLocal() as session:
            stmt = select(UiMessageHistory).filter_by(account_id=self.account_id)
            if chat_id is not None:
                stmt = stmt.filter_by(chat_id=chat_id)
            stmt = stmt.order_by(UiMessageHistory.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
            rows.reverse()
            return [
                {
                    "account_id": self.account_id,
                    "id": row.id,
                    "direction": row.direction,
                    "chat_id": row.chat_id,
                    "username": row.username,
                    "display_name": row.display_name,
                    "text": row.message_text,
                    "timestamp": row.created_at.isoformat() + "Z",
                    "status": row.status,
                    "error_message": row.error_message,
                    "media_url": row.media_url,
                    "media_name": row.media_name,
                    "media_mime": row.media_mime,
                    "media_size": row.media_size
                }
                for row in rows
            ]

    async def find_user_by_id(self, user_id: int) -> Optional[User]:
        """Поиск пользователя по ID"""
        try:
            if not await self.is_authorized():
                logger.warning("⚠️ Клиент не авторизован")
                return None

            user = await self.client.get_entity(user_id)
            logger.info(f"✅ Найден пользователь по ID: {user_id}")
            return user
        except ValueError:
            logger.warning(f"⚠️ Пользователь с ID {user_id} не найден")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка поиска по ID {user_id}: {e}")
            return None

    async def get_chats(self, limit: int = 50) -> list[dict]:
        async with SessionLocal() as session:
            stmt = (
                select(UiChat)
                .filter_by(account_id=self.account_id)
                .order_by(
                    UiChat.last_timestamp.desc().nullslast(),
                    UiChat.updated_at.desc()
                )
                .limit(limit)
            )
            result = await session.execute(stmt)
            rows = result.scalars().all()
            chats = []
            for row in rows:
                timestamp = row.last_timestamp.isoformat() + "Z" if row.last_timestamp else None
                chats.append({
                    "account_id": self.account_id,
                    "chat_id": row.chat_id,
                    "username": row.username or "",
                    "display_name": row.display_name or self._format_chat_name(
                        row.username,
                        row.first_name,
                        row.last_name,
                        row.chat_id
                    ),
                    "first_name": row.first_name or "",
                    "last_name": row.last_name or "",
                    "phone": row.phone or "",
                    "last_message": row.last_message or "",
                    "last_direction": row.last_direction or "",
                    "last_timestamp": timestamp,
                    "last_timestamp_epoch": row.last_timestamp.timestamp() if row.last_timestamp else None,
                    "unread_count": row.unread_count or 0
                })
            return chats

    async def get_chat_details(self, chat_id: int) -> dict:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UiChat).filter_by(chat_id=chat_id, account_id=self.account_id)
            )
            chat = result.scalars().first()

        base = {"chat_id": chat_id, "account_id": self.account_id}
        if chat:
            base.update({
                "chat_id": chat.chat_id,
                "username": chat.username,
                "display_name": chat.display_name,
                "first_name": chat.first_name,
                "last_name": chat.last_name,
                "phone": chat.phone,
                "last_message": chat.last_message,
                "last_direction": chat.last_direction,
                "last_timestamp": chat.last_timestamp.isoformat() + "Z" if chat.last_timestamp else None,
                "unread_count": chat.unread_count or 0
            })

        username = base.get("username") or None
        first_name = base.get("first_name") or None
        last_name = base.get("last_name") or None
        phone = base.get("phone") or None

        if await self.is_authorized():
            try:
                user = await self.client.get_entity(chat_id)
                username = user.username or username
                first_name = user.first_name or first_name
                last_name = user.last_name or last_name
                phone = getattr(user, "phone", None) or phone
            except Exception:
                pass

        display_name = self._format_chat_name(
            username,
            first_name,
            last_name,
            chat_id
        )
        details = dict(base)
        details.update({
            "chat_id": chat_id,
            "account_id": self.account_id,
            "username": username or "",
            "first_name": first_name or "",
            "last_name": last_name or "",
            "phone": phone or "",
            "display_name": display_name
        })

        if chat_id and (username or first_name or last_name or phone):
            async with SessionLocal() as session:
                await self._upsert_ui_chat(
                    session,
                    chat_id=chat_id,
                    username=username,
                    first_name=first_name,
                    last_name=last_name,
                    display_name=display_name,
                    phone=phone,
                    last_message=None,
                    last_direction=None,
                    last_timestamp=None,
                    increment_unread=False
                )
                await session.commit()
        return details

    async def get_chat_history_stats(self, chat_id: int) -> dict:
        async with SessionLocal() as session:
            total_result = await session.execute(
                select(func.count())
                .select_from(UiMessageHistory)
                .filter_by(chat_id=chat_id, account_id=self.account_id)
            )
            total = total_result.scalar() or 0
            inbound_result = await session.execute(
                select(func.count()).select_from(UiMessageHistory).filter_by(
                    chat_id=chat_id,
                    account_id=self.account_id,
                    direction="inbound"
                )
            )
            inbound_count = inbound_result.scalar() or 0
            outbound_result = await session.execute(
                select(func.count()).select_from(UiMessageHistory).filter_by(
                    chat_id=chat_id,
                    account_id=self.account_id,
                    direction="outbound"
                )
            )
            outbound_count = outbound_result.scalar() or 0
            last_inbound_result = await session.execute(
                select(func.max(UiMessageHistory.created_at)).filter_by(
                    chat_id=chat_id,
                    account_id=self.account_id,
                    direction="inbound"
                )
            )
            last_outbound_result = await session.execute(
                select(func.max(UiMessageHistory.created_at)).filter_by(
                    chat_id=chat_id,
                    account_id=self.account_id,
                    direction="outbound"
                )
            )
            last_inbound_at = last_inbound_result.scalar()
            last_outbound_at = last_outbound_result.scalar()

        return {
            "messages_total": total,
            "inbound_count": inbound_count,
            "outbound_count": outbound_count,
            "last_inbound_at": last_inbound_at.isoformat() + "Z" if last_inbound_at else None,
            "last_outbound_at": last_outbound_at.isoformat() + "Z" if last_outbound_at else None
        }

    async def mark_chat_read(self, chat_id: int) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(UiChat).filter_by(chat_id=chat_id, account_id=self.account_id)
            )
            chat = result.scalars().first()
            if chat:
                chat.unread_count = 0
                await session.commit()
    
    async def find_user_by_phone(self, phone: str) -> Optional[User]:
        """
        Поиск пользователя по номеру телефона
        
        Args:
            phone: Номер телефона (с +)
            
        Returns:
            User объект или None если не найден
        """
        try:
            if not await self.is_authorized():
                logger.warning("⚠️ Клиент не авторизован")
                return None

            # Нормализуем номер
            if not phone.startswith('+'):
                phone = '+' + phone
            
            logger.info(f"🔍 Поиск пользователя по телефону: {phone}")
            
            # Импортируем контакт
            result = await self.client(ImportContactsRequest([
                InputPhoneContact(
                    client_id=0,
                    phone=phone,
                    first_name="Contact",
                    last_name=""
                )
            ]))
            
            if result.users:
                user = result.users[0]
                logger.info(
                    f"✅ Найден пользователь: {user.first_name} "
                    f"(@{user.username or user.id})"
                )
                display_name = self._format_chat_name(
                    user.username,
                    user.first_name,
                    user.last_name,
                    user.id
                )
                async with SessionLocal() as session:
                    await self._upsert_ui_chat(
                        session,
                        chat_id=user.id,
                        username=user.username,
                        first_name=user.first_name,
                        last_name=user.last_name,
                        display_name=display_name,
                        phone=phone,
                        last_message=None,
                        last_direction=None,
                        last_timestamp=None,
                        increment_unread=False
                    )
                    await session.commit()
                return user
            else:
                logger.warning(
                    f"⚠️ Пользователь с номером {phone} не найден "
                    f"или скрыл номер в настройках приватности"
                )
                return None
                
        except Exception as e:
            logger.error(f"❌ Ошибка поиска по номеру {phone}: {e}")
            return None
    
    async def find_user_by_username(self, username: str) -> Optional[User]:
        """
        Поиск пользователя по username
        
        Args:
            username: Username (с @ или без)
            
        Returns:
            User объект или None если не найден
        """
        try:
            if not await self.is_authorized():
                logger.warning("⚠️ Клиент не авторизован")
                return None

            # Убираем @ если есть
            username = username.lstrip('@')
            
            logger.info(f"🔍 Поиск пользователя по username: @{username}")
            
            user = await self.client.get_entity(username)
            logger.info(f"✅ Найден пользователь: {user.first_name} (@{user.username})")
            return user
            
        except ValueError:
            logger.warning(f"⚠️ Пользователь @{username} не найден")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка поиска по username @{username}: {e}")
            return None

    def _parse_time(self, value: str) -> Optional[time]:
        if not value:
            return None
        try:
            parts = value.strip().split(":")
            if len(parts) < 2:
                return None
            hour = int(parts[0])
            minute = int(parts[1])
            return time(hour=hour, minute=minute)
        except Exception:
            return None

    async def _check_compliance(self, chat_id: int) -> Tuple[bool, str]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(ChatProfile).filter_by(
                    telegram_chat_id=chat_id,
                    account_id=self.account_id
                )
            )
            profile = result.scalars().first()

        if not profile:
            return True, "ok"

        if profile.opted_out:
            return False, "opted_out"

        start = self._parse_time(profile.quiet_hours_start or "")
        end = self._parse_time(profile.quiet_hours_end or "")
        if start and end:
            tz_name = profile.timezone or settings.DEFAULT_TIMEZONE
            try:
                tz = ZoneInfo(tz_name)
            except Exception:
                tz = ZoneInfo("UTC")
            now = datetime.now(tz=tz).time()

            if start < end:
                in_quiet = start <= now < end
            else:
                in_quiet = now >= start or now < end

            if in_quiet:
                return False, "quiet_hours"

        return True, "ok"

    @retry_telegram(log_prefix="Telegram send_message")
    async def _send_telegram_message_with_retry(self, user: User, message: str):
        """
        Low-level Telegram API call with automatic retry on FloodWait and network errors.

        This method is decorated with @retry_telegram to handle:
        - FloodWaitError: Respects exact wait time from Telegram (up to 5 minutes)
        - Network errors: Exponential backoff retry
        - Other RPCError: Re-raised immediately (non-retryable)

        Args:
            user: Telegram User object
            message: Message text to send

        Returns:
            Sent message object from Telethon

        Raises:
            FloodWaitError: After max retries exhausted
            RPCError: Non-retryable Telegram errors
            Network errors: After max retries exhausted
        """
        return await self.client.send_message(user, message)

    async def send_message_to_user(
        self,
        user: User,
        message: str,
        is_new_chat: Optional[bool] = None,
        operator_id: Optional[int] = None,
        skip_quiet_hours: bool = False
    ) -> Tuple[bool, str]:
        """
        Отправка сообщения пользователю

        Args:
            user: User объект получателя
            message: Текст сообщения
            is_new_chat: Первое ли это сообщение пользователю
            operator_id: ID оператора (если есть)
            skip_quiet_hours: Пропустить проверку тихих часов (для Open Channels)

        Returns:
            (success, message): (успешно ли, сообщение о результате)
        """
        if not await self.is_authorized():
            return False, "client_not_authorized"

        compliant, compliance_reason = await self._check_compliance(user.id)
        if not compliant:
            error_msg = "Контакт отказался от сообщений" if compliance_reason == "opted_out" else "Quiet hours"
            await self._store_message(
                "outbound",
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                message,
                False,
                status="failed",
                error_message=error_msg
            )
            return False, error_msg

        # Fix #5: Проверка anti-spam с АТОМАРНОЙ проверкой is_new_chat
        # Передаем chat_id и account_id чтобы try_register_send сам проверил
        # is_new_chat внутри своего lock (без race condition)
        can_send, reason = await self.anti_spam.try_register_send(
            user.id,
            is_new_chat=is_new_chat,
            operator_id=operator_id,
            skip_quiet_hours=skip_quiet_hours,
            chat_id=user.id,
            account_id=self.account_id
        )
        if not can_send:
            logger.warning(f"⚠️ Anti-spam блокировка: {reason}")
            await self._store_message(
                "outbound",
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                message,
                False,
                status="failed",
                error_message=reason
            )
            return False, reason
        
        try:
            logger.info(
                f"📤 Отправка сообщения пользователю "
                f"@{user.username or user.id}"
            )

            # Отправляем сообщение с автоматическим retry на FloodWait/network errors
            sent_message = await self._send_telegram_message_with_retry(user, message)
            
            logger.info(
                f"✅ Сообщение отправлено пользователю "
                f"@{user.username or user.id}"
            )

            await self._store_message(
                "outbound",
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                message,
                False
            )
            
            return True, "Успешно отправлено"
            
        except FloodWaitError as e:
            # FloodWait после всех автоматических попыток retry
            # (retry decorator уже пытался 3 раза с ожиданием)
            wait_time = e.seconds
            error_msg = f"FloodWait после всех retry: нужно подождать {wait_time}s"
            logger.error(f"🚫 {error_msg}")

            # Критический алерт - это означает очень высокую нагрузку
            logger.critical(
                f"🚨 КРИТИЧЕСКИЙ FloodWait после retry: {wait_time}s! "
                f"Telegram серьезно ограничивает отправку. Снизьте нагрузку!"
            )
            await self._store_message(
                "outbound",
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                message,
                False,
                status="failed",
                error_message=error_msg
            )
            return False, error_msg
            
        except UserPrivacyRestrictedError:
            error_msg = "Пользователь запретил сообщения от незнакомцев"
            logger.error(
                f"🔒 {error_msg} для @{user.username or user.id}"
            )
            await self._store_message(
                "outbound",
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                message,
                False,
                status="failed",
                error_message=error_msg
            )
            return False, error_msg
            
        except PeerIdInvalidError:
            error_msg = "Невалидный peer ID"
            logger.error(f"❌ {error_msg}")
            await self._store_message(
                "outbound",
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                message,
                False,
                status="failed",
                error_message=error_msg
            )
            return False, error_msg
            
        except PhoneNumberBannedError:
            error_msg = "НОМЕР ЗАБЛОКИРОВАН TELEGRAM"
            logger.critical(f"🚨 {error_msg}")
            await self._store_message(
                "outbound",
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                message,
                False,
                status="failed",
                error_message=error_msg
            )
            return False, error_msg
            
        except Exception as e:
            error_msg = f"Ошибка отправки: {str(e)}"
            logger.error(f"❌ {error_msg}")
            await self._store_message(
                "outbound",
                user.id,
                user.username,
                user.first_name,
                user.last_name,
                message,
                False,
                status="failed",
                error_message=error_msg
            )
            return False, error_msg
    
    async def _handle_incoming_message(self, event):
        """Обработка входящих сообщений"""
        try:
            message = event.message
            sender = await event.get_sender()

            # Извлечь phone (может быть None если пользователь не в контактах)
            phone_number = getattr(sender, 'phone', None)

            # Если телефона нет - попробовать добавить в контакты для извлечения phone
            if not phone_number and sender.username:
                try:
                    from src.contact_manager import contact_manager

                    logger.info(
                        f"📞 Телефон не доступен для @{sender.username}, "
                        f"пробуем добавить в контакты"
                    )

                    success, phone_number = await contact_manager.add_to_contacts_with_protection(
                        client=self.client,
                        telegram_user_id=sender.id,
                        first_name=sender.first_name or "Клиент",
                        last_name=sender.last_name,
                        username=sender.username,
                        direction='inbound',  # ВХОДЯЩИЙ - безопасно
                        source='incoming_message'
                    )

                    if success and phone_number:
                        logger.info(f"✅ Телефон получен: {phone_number}")
                    elif success:
                        logger.info("ℹ️ Контакт добавлен, но телефон скрыт настройками приватности")
                    else:
                        logger.warning("⚠️ Не удалось добавить контакт (проверьте лимиты)")

                except Exception as e:
                    logger.error(
                        f"❌ Ошибка Contact Manager для @{sender.username}: {e}",
                        exc_info=True
                    )
                    # Продолжаем обработку сообщения БЕЗ телефона
                    phone_number = None

            logger.info(
                f"📨 Получено сообщение от @{sender.username or sender.id}: "
                f"{message.text[:50] if message.text else '[медиа]'}..."
            )

            media_url, media_name, media_mime, media_size = await self._upload_media(
                message,
                sender.id
            )
            await self._store_message(
                "inbound",
                sender.id,
                sender.username,
                sender.first_name,
                sender.last_name,
                message.text or "[media]",
                True,
                status="received",
                media_url=media_url,
                media_name=media_name,
                media_mime=media_mime,
                media_size=media_size
            )
            
            # Обработка через Bridge (для CRM интеграции и Open Channels)
            if self.bridge:
                try:
                    async with SessionLocal() as db:
                        await self.bridge.handle_incoming_message(
                            db=db,
                            telegram_chat_id=sender.id,
                            telegram_user_id=sender.id,
                            user_first_name=sender.first_name or "",
                            user_last_name=sender.last_name,
                            username=sender.username,
                            phone=phone_number,  # Передаём телефон (может быть None)
                            message_text=message.text or "[медиа]",
                            message_id=message.id,
                            account_id=self.account_id  # Передаём account_id для multi-account
                        )
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка обработки через Bridge: {e}")
            else:
                # Fallback: сохраняем только если есть маппинг
                try:
                    async with SessionLocal() as db:
                        result = await db.execute(
                            select(ChatMapping).filter_by(
                                telegram_chat_id=sender.id,
                                account_id=self.account_id
                            )
                        )
                        mapping = result.scalars().first()

                        # Validate mapping.id before creating history (prevent FK constraint violation)
                        if mapping and mapping.id and mapping.id > 0:
                            history = MessageHistory(
                                account_id=self.account_id,
                                chat_mapping_id=mapping.id,
                                amocrm_contact_id=mapping.amocrm_contact_id,
                                direction='inbound',
                                message_text=message.text or '[медиа]',
                                message_type='text' if message.text else 'media',
                                telegram_message_id=message.id,
                                telegram_chat_id=sender.id,
                                status='received'
                            )
                            db.add(history)
                            await db.commit()
                            logger.info(
                                f"✅ Сообщение сохранено в БД "
                                f"(contact_id: {mapping.amocrm_contact_id})"
                            )
                        elif mapping:
                            logger.error(
                                f"❌ Cannot create MessageHistory: invalid mapping.id={mapping.id}"
                            )
                        else:
                            logger.warning(
                                f"⚠️ Пользователь @{sender.username or sender.id} "
                                f"не связан с CRM"
                            )
                except Exception as e:
                    logger.warning(f"⚠️ БД недоступна для входящего сообщения: {e}")
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки входящего сообщения: {e}")

    async def _handle_message_read(self, event):
        """Обработка события прочтения сообщений.

        Вызывается когда получатель прочитал наши сообщения в Telegram.
        Отправляет reading status в Bitrix24 для соответствующих сообщений.
        """
        try:
            # Event содержит информацию о прочитанных сообщениях
            # event.chat_id - ID чата где сообщения прочитаны
            # event.max_id - ID последнего прочитанного сообщения
            # event.inbox - True если прочитаны входящие, False если исходящие

            # Нас интересуют только исходящие сообщения (inbox=False)
            # т.е. когда получатель прочитал НАШИ сообщения
            if event.inbox:
                return

            chat_id = event.chat_id
            max_id = event.max_id

            logger.info(f"📖 Сообщения прочитаны в чате {chat_id} до message_id {max_id}")

            # Найти непрочитанные сообщения из outbox для этого чата
            # которые были успешно отправлены и ещё не отмечены как прочитанные
            async with SessionLocal() as db:
                from src.database import MessageOutbox
                from sqlalchemy import and_

                # Получить все непрочитанные сообщения для этого чата
                # которые связаны с Bitrix24 (имеют bitrix_message_id)
                result = await db.execute(
                    select(MessageOutbox).where(
                        and_(
                            MessageOutbox.chat_id == chat_id,
                            MessageOutbox.account_id == self.account_id,
                            MessageOutbox.status == 'sent',
                            MessageOutbox.read_at.is_(None),
                            MessageOutbox.payload['bitrix_message_id'].isnot(None),
                            MessageOutbox.payload['bitrix_chat_id'].isnot(None)
                        )
                    ).order_by(MessageOutbox.id)
                )
                unread_messages = result.scalars().all()

                if not unread_messages:
                    logger.debug(f"Нет непрочитанных сообщений для чата {chat_id}")
                    return

                logger.info(f"Найдено {len(unread_messages)} непрочитанных сообщений для отправки reading status")

                # Отправить reading status для каждого сообщения
                if self.bridge and self.bridge.crm:
                    from src.config import settings
                    from datetime import datetime

                    for msg in unread_messages:
                        payload = msg.payload
                        bitrix_msg_id = payload.get("bitrix_message_id")
                        bitrix_chat_id = payload.get("bitrix_chat_id")
                        line_id = payload.get("line_id", 0)

                        if not bitrix_msg_id or not bitrix_chat_id:
                            continue

                        try:
                            # Формат согласно документации Bitrix24
                            messages = [{
                                "im": {
                                    "chat_id": str(bitrix_chat_id),
                                    "message_id": str(bitrix_msg_id)
                                },
                                "message": {
                                    "id": str(bitrix_msg_id)
                                },
                                "chat": {
                                    "id": str(chat_id)
                                }
                            }]

                            # Отправить reading status в Bitrix24
                            reading_result = await self.bridge.crm.send_status_reading(
                                connector_id=settings.BITRIX24_CONNECTOR_ID,
                                line_id=line_id,
                                messages=messages
                            )

                            # Отметить сообщение как прочитанное в БД
                            msg.read_at = datetime.utcnow()
                            await db.commit()

                            logger.info(
                                f"✅ Reading status отправлен для message_id={bitrix_msg_id}, "
                                f"chat_id={chat_id}, result={reading_result}"
                            )
                        except Exception as e:
                            logger.warning(
                                f"⚠️ Не удалось отправить reading status для "
                                f"message_id={bitrix_msg_id}: {e}"
                            )
                else:
                    logger.debug("Bridge или CRM не инициализирован, reading status не отправляется")

        except Exception as e:
            logger.error(f"❌ Ошибка обработки события MessageRead: {e}")
            import traceback
            logger.error(traceback.format_exc())

    async def run(self):
        """Запуск клиента в режиме ожидания"""
        logger.info("🔄 Клиент работает в режиме ожидания...")
        await self.client.run_until_disconnected()
    
    async def stop(self):
        """Остановка клиента"""
        logger.info("👋 Остановка клиента...")
        await self.client.disconnect()
    
    def get_stats(self) -> dict:
        """Получить статистику"""
        return {
            "account_id": self.account_id,
            "client_status": "connected" if self.client.is_connected() else "disconnected",
            "user": {
                "id": self.me.id if self.me else None,
                "username": self.me.username if self.me else None,
                "phone": self.me.phone if self.me else None,
            },
            "anti_spam": self.anti_spam.get_stats()
        }
