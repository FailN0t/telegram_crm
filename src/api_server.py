"""
FastAPI сервер для API endpoints
Прием webhook от AmoCRM, внешние запросы
"""

import asyncio
import time
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import secrets
import uuid
import json
import hashlib
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, or_

from src.config import settings
from src.logger import logger
from src.database import (
    get_db,
    ChatProfile,
    MessageInbox,
    UiMessageHistory,
    UiEventLog,
    SessionLocal
)
from src.bridge import AmoCRMTelegramBridge
from src.outbox import (
    build_idempotency_key,
    enqueue_outbox,
    mark_outbox_result
)
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST


STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


class CacheControlStaticFiles(StaticFiles):
    def __init__(self, *args, cache_control: str = "public, max-age=3600", **kwargs):
        super().__init__(*args, **kwargs)
        self.cache_control = cache_control

    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200 and path.endswith((".css", ".js")):
            response.headers["Cache-Control"] = self.cache_control
        return response


REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path"]
)





# Pydantic модели для API
class SendMessageRequest(BaseModel):
    """Запрос на отправку сообщения"""
    contact_id: int = Field(..., description="ID контакта в AmoCRM")
    phone: Optional[str] = Field(None, description="Номер телефона (с +)")
    username: Optional[str] = Field(None, description="Username в Telegram")
    message: str = Field(..., description="Текст сообщения")


class SendMessageResponse(BaseModel):
    """Ответ на отправку сообщения"""
    success: bool
    message: str
    contact_id: int


class HealthResponse(BaseModel):
    """Ответ health check"""
    status: str
    version: str
    telegram_connected: bool
    database_connected: bool


class StatsResponse(BaseModel):
    """Ответ со статистикой"""
    telegram: dict
    mappings: dict
    messages: dict


class UiSendRequest(BaseModel):
    """Отправка сообщения из локального UI"""
    chat_id: Optional[int] = None
    username: Optional[str] = None
    phone: Optional[str] = None
    message: str
    idempotency_key: Optional[str] = None


class UiAuthRequest(BaseModel):
    """Запрос кода авторизации"""
    phone: Optional[str] = None


class UiAuthCodeRequest(BaseModel):
    """Отправка кода авторизации"""
    phone: Optional[str] = None
    code: str


class UiAuthPasswordRequest(BaseModel):
    """Отправка 2FA пароля"""
    password: str


class UiChatProfileUpdate(BaseModel):
    """Обновление заметок/тегов"""
    tags: Optional[str] = None
    notes: Optional[str] = None
    has_consent: Optional[bool] = None
    opted_out: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    timezone: Optional[str] = None


# Глобальные переменные (будут инициализированы в main)
bridge: Optional[AmoCRMTelegramBridge] = None
basic_scheme = HTTPBasic(auto_error=False)
_ui_users_cache = {"raw": None, "parsed": {}}


async def log_ui_event(level: str, message: str, data: Optional[dict] = None) -> dict:
    entry = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "level": level,
        "message": message,
        "data": data or {}
    }
    try:
        async with SessionLocal() as session:
            session.add(UiEventLog(
                level=level,
                message=message,
                data=entry["data"]
            ))
            await session.commit()
    except Exception as exc:
        logger.warning(f"⚠️ Не удалось сохранить UI событие в БД: {exc}")
    return entry


def get_ui_users() -> dict:
    raw = settings.UI_BASIC_AUTH_USERS or ""
    if raw == _ui_users_cache["raw"]:
        return _ui_users_cache["parsed"]

    parsed = {}
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(":")
        if len(parts) < 2:
            continue
        username = parts[0].strip()
        password = parts[1]
        role = parts[2].strip() if len(parts) > 2 else "operator"
        if username:
            parsed[username] = {"password": password, "role": role}

    _ui_users_cache["raw"] = raw
    _ui_users_cache["parsed"] = parsed
    return parsed


async def require_ui_auth(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(basic_scheme)
):
    if not settings.UI_BASIC_AUTH_ENABLED:
        return {"username": "anonymous", "role": "anonymous"}

    users = get_ui_users()
    if not users:
        await log_ui_event("error", "ui_auth_config_missing", {"path": request.url.path})
        raise HTTPException(
            status_code=500,
            detail="UI auth enabled but no users configured"
        )

    if not credentials or credentials.username not in users:
        await log_ui_event(
            "error",
            "ui_auth_failed",
            {"path": request.url.path, "username": credentials.username if credentials else ""}
        )
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"}
        )

    record = users[credentials.username]
    if not secrets.compare_digest(credentials.password or "", record["password"]):
        await log_ui_event(
            "error",
            "ui_auth_failed",
            {"path": request.url.path, "username": credentials.username}
        )
        raise HTTPException(
            status_code=401,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"}
        )

    await log_ui_event(
        "info",
        "ui_auth_ok",
        {"path": request.url.path, "username": credentials.username}
    )
    return {"username": credentials.username, "role": record["role"]}


def ui_error_response(
    status_code: int,
    message: str,
    code: Optional[str] = None,
    retryable: bool = False
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "success": False,
            "message": message,
            "code": code,
            "retryable": retryable
        }
    )


def humanize_auth_status(status: str) -> str:
    mapping = {
        "already_authorized": "Уже авторизован",
        "phone_required": "Укажите номер телефона или настройте TELEGRAM_PHONE",
        "code_sent": "Код отправлен. Введите его ниже.",
        "authorized": "Успешная авторизация",
        "2fa_required": "Требуется пароль 2FA"
    }
    return mapping.get(status, status)


def humanize_send_error(status: str) -> tuple[str, bool]:
    if "FloodWait" in status:
        return "Лимит Telegram. Подождите и повторите отправку.", True
    if "Подождите" in status:
        return status, True
    if "client_not_authorized" in status:
        return "Клиент не авторизован. Сначала войдите через /ui/auth.", False
    if "privacy" in status.lower() or "приват" in status.lower():
        return "Пользователь запретил сообщения от незнакомцев.", False
    if "Неподходящее время" in status:
        return status, True
    if "лимит" in status.lower():
        return status, True
    if "НОМЕР ЗАБЛОКИРОВАН" in status or "banned" in status.lower():
        return "Номер Telegram заблокирован. Нужен новый аккаунт.", False
    return status, False


def verify_api_key(x_api_key: str = Header(...)):
    """Проверка API ключа"""
    if x_api_key != settings.API_SECRET_KEY:
        logger.warning(f"⚠️ Попытка доступа с неверным API ключом")
        raise HTTPException(status_code=403, detail="Invalid API key")
    return x_api_key


def create_app() -> FastAPI:
    """Создание FastAPI приложения"""
    
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="MTProto integration between AmoCRM and Telegram",
        docs_url="/docs" if settings.DEBUG else None,
        redoc_url="/redoc" if settings.DEBUG else None,
    )

    if STATIC_DIR.exists():
        app.mount(
            "/static",
            CacheControlStaticFiles(directory=STATIC_DIR),
            name="static"
        )
    else:
        logger.warning(f"⚠️ Static directory not found: {STATIC_DIR}")

    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        if not settings.ENABLE_METRICS:
            return await call_next(request)
        start = time.time()
        response = await call_next(request)
        path = request.url.path
        if path != "/metrics":
            REQUEST_COUNT.labels(
                request.method,
                path,
                response.status_code
            ).inc()
            REQUEST_LATENCY.labels(
                request.method,
                path
            ).observe(time.time() - start)
        return response

    def _ensure_amocrm_ready(require_bridge: bool = True) -> None:
        if settings.OUTBOX_PROCESS_INLINE:
            if not bridge:
                raise HTTPException(status_code=503, detail="Bridge not initialized")
            if require_bridge and not bridge.amocrm:
                raise HTTPException(status_code=503, detail="AmoCRM is not configured")
            return

        if not (
            settings.AMOCRM_DOMAIN
            and settings.AMOCRM_CLIENT_ID
            and settings.AMOCRM_CLIENT_SECRET
            and settings.AMOCRM_REDIRECT_URI
        ):
            raise HTTPException(status_code=503, detail="AmoCRM is not configured")
    
    @app.on_event("startup")
    async def startup():
        """Действия при запуске"""
        logger.info("🚀 API сервер запускается...")
    
    @app.on_event("shutdown")
    async def shutdown():
        """Действия при остановке"""
        logger.info("👋 API сервер останавливается...")
    
    @app.get("/", tags=["Root"])
    async def root():
        """Корневой endpoint"""
        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "status": "running"
        }

    @app.get("/ui", tags=["UI"])
    async def ui(ui_user: dict = Depends(require_ui_auth)):
        """Простой локальный UI для тестирования"""
        ui_path = STATIC_DIR / "ui.html"
        if not ui_path.exists():
            raise HTTPException(status_code=404, detail="UI not found")
        return FileResponse(
            ui_path,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"}
        )
    
    @app.get("/ui/auth", tags=["UI"])
    async def ui_auth(ui_user: dict = Depends(require_ui_auth)):
        """Страница авторизации"""
        auth_path = STATIC_DIR / "auth.html"
        if not auth_path.exists():
            raise HTTPException(status_code=404, detail="UI not found")
        return FileResponse(
            auth_path,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"}
        )

    async def _check_health(db: AsyncSession) -> dict:
        db_connected = True
        try:
            await db.execute(text("SELECT 1"))
        except Exception:
            db_connected = False

        telegram_connected = False
        if bridge and bridge.telegram:
            telegram_connected = bridge.telegram.client.is_connected()

        status = "healthy" if (db_connected and telegram_connected) else "degraded"
        return {
            "status": status,
            "telegram_connected": telegram_connected,
            "database_connected": db_connected
        }
    
    @app.get("/health", response_model=HealthResponse, tags=["Monitoring"])
    async def health_check(db: AsyncSession = Depends(get_db)):
        """
        Health check endpoint
        Проверяет подключение к БД и Telegram
        """
        status = await _check_health(db)
        return {
            "status": status["status"],
            "version": settings.APP_VERSION,
            "telegram_connected": status["telegram_connected"],
            "database_connected": status["database_connected"]
        }

    @app.get("/metrics", tags=["Monitoring"])
    async def metrics():
        """Prometheus metrics endpoint"""
        if not settings.ENABLE_METRICS:
            raise HTTPException(status_code=404, detail="Metrics disabled")
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/live", tags=["Monitoring"])
    async def liveness_check():
        """Liveness probe"""
        return {"status": "alive"}

    @app.get("/ready", tags=["Monitoring"])
    async def readiness_check(db: AsyncSession = Depends(get_db)):
        """Readiness probe"""
        return await _check_health(db)

    @app.get("/startup", tags=["Monitoring"])
    async def startup_check():
        """Startup probe"""
        if bridge and bridge.telegram:
            return {"status": "started"}
        raise HTTPException(status_code=503, detail="starting")
    
    @app.post("/api/send-message", response_model=SendMessageResponse, tags=["Messages"])
    async def send_message(
        request: SendMessageRequest,
        db: AsyncSession = Depends(get_db),
        api_key: str = Depends(verify_api_key),
        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")
    ):
        """
        Отправка сообщения клиенту в Telegram
        
        Требуется API ключ в заголовке: X-API-Key
        """
        _ensure_amocrm_ready()
        
        if not request.phone and not request.username:
            raise HTTPException(
                status_code=400,
                detail="Phone or username is required"
            )
        
        logger.info(
            f"📥 API запрос на отправку сообщения: "
            f"contact_id={request.contact_id}"
        )
        
        key = idempotency_key
        if not key:
            payload_hash = json.dumps({
                "contact_id": request.contact_id,
                "phone": request.phone,
                "username": request.username,
                "message": request.message
            }, sort_keys=True)
            key = build_idempotency_key(payload_hash)

        payload = {
            "source": "api",
            "contact_id": request.contact_id,
            "phone": request.phone,
            "username": request.username,
            "message": request.message
        }
        outbox, created = await enqueue_outbox(
            db,
            key,
            0,
            payload
        )

        if not created:
            return {
                "success": True,
                "message": "Already queued",
                "contact_id": request.contact_id,
                "status": outbox.status,
                "outbox_id": outbox.id,
                "idempotency_key": outbox.idempotency_key
            }

        if not settings.OUTBOX_PROCESS_INLINE:
            return {
                "success": True,
                "message": "Queued",
                "contact_id": request.contact_id,
                "status": outbox.status,
                "outbox_id": outbox.id,
                "idempotency_key": outbox.idempotency_key
            }

        success, message = await bridge.send_message_from_amocrm(
            db,
            request.contact_id,
            request.phone,
            request.username,
            request.message
        )

        await mark_outbox_result(db, outbox, success, None if success else message)

        if not success:
            raise HTTPException(status_code=500, detail=message)

        return {
            "success": True,
            "message": message,
            "contact_id": request.contact_id,
            "status": outbox.status,
            "outbox_id": outbox.id,
            "idempotency_key": outbox.idempotency_key
        }
    
    @app.post("/api/webhook/amocrm", tags=["Webhooks"])
    async def amocrm_webhook(
        request: Request,
        db: AsyncSession = Depends(get_db)
    ):
        """
        Webhook от AmoCRM
        Обработка событий из AmoCRM
        """
        if settings.AMOCRM_WEBHOOK_SECRET:
            provided = request.headers.get("X-Webhook-Secret")
            if not provided or not secrets.compare_digest(
                provided, settings.AMOCRM_WEBHOOK_SECRET
            ):
                raise HTTPException(status_code=401, detail="Invalid webhook secret")

        _ensure_amocrm_ready()
        
        try:
            body_bytes = await request.body()
            payload_hash = hashlib.sha256(body_bytes).hexdigest()
            idempotency_key = f"amocrm:{payload_hash}"

            result = await db.execute(
                select(MessageInbox).filter_by(idempotency_key=idempotency_key)
            )
            existing = result.scalars().first()
            if existing:
                return {
                    "success": True,
                    "processed": 0,
                    "status": "duplicate"
                }

            db.add(MessageInbox(
                idempotency_key=idempotency_key,
                source="amocrm_webhook",
                payload_hash=payload_hash
            ))
            await db.commit()

            body = json.loads(body_bytes.decode("utf-8"))
            logger.info(f"📥 Получен webhook от AmoCRM")
            logger.debug(f"Webhook body: {body}")
            
            # Обработка событий
            results = []
            
            # Обработка задач
            if 'tasks' in body and 'add' in body['tasks']:
                for task_data in body['tasks']['add']:
                    task_id = task_data.get('id')
                    if task_id:
                        key = f"amocrm_task:{task_id}"
                        payload = {
                            "source": "amocrm_webhook",
                            "task_id": task_id
                        }
                        outbox, created = await enqueue_outbox(
                            db,
                            key,
                            0,
                            payload
                        )
                        results.append({
                            "task_id": task_id,
                            "queued": created,
                            "outbox_id": outbox.id
                        })
            
            return {
                "success": True,
                "processed": len(results),
                "results": results
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки webhook: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    @app.get("/api/stats", response_model=StatsResponse, tags=["Monitoring"])
    async def get_stats(
        db: AsyncSession = Depends(get_db),
        api_key: str = Depends(verify_api_key)
    ):
        """
        Получение статистики работы системы
        
        Требуется API ключ в заголовке: X-API-Key
        """
        if not bridge:
            raise HTTPException(
                status_code=503,
                detail="Bridge not initialized"
            )
        
        stats = await bridge.get_stats(db)
        return stats
    
    @app.get("/api/contact/{contact_id}/status", tags=["Contacts"])
    async def get_contact_status(
        contact_id: int,
        db: AsyncSession = Depends(get_db),
        api_key: str = Depends(verify_api_key)
    ):
        """
        Проверка статуса контакта в системе
        
        Требуется API ключ в заголовке: X-API-Key
        """
        from src.database import ChatMapping
        
        result = await db.execute(
            select(ChatMapping).filter_by(amocrm_contact_id=contact_id)
        )
        mapping = result.scalars().first()
        
        if not mapping:
            return {
                "connected": False,
                "contact_id": contact_id,
                "message": "Контакт не подключен к Telegram"
            }
        
        return {
            "connected": True,
            "contact_id": contact_id,
            "telegram_chat_id": mapping.telegram_chat_id,
            "telegram_username": mapping.telegram_username,
            "is_active": mapping.is_active,
            "has_consent": mapping.has_consent,
            "last_message_at": mapping.last_message_at.isoformat() if mapping.last_message_at else None
        }

    @app.get("/api/ui/status", tags=["UI"])
    async def ui_status(ui_user: dict = Depends(require_ui_auth)):
        """Статус Telegram клиента для UI"""
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")

        telegram = bridge.telegram
        authorized = await telegram.is_authorized()
        user = None
        if authorized and telegram.me:
            user = {
                "id": telegram.me.id,
                "username": telegram.me.username,
                "phone": telegram.me.phone,
            }

        return {
            "connected": telegram.client.is_connected(),
            "authorized": authorized,
            "user": user,
            "session": telegram.get_session_info(),
            "anti_spam": telegram.anti_spam.get_stats()
        }

    @app.get("/api/ui/events", tags=["UI"])
    async def ui_events(
        limit: int = 50,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Список последних событий UI"""
        stmt = select(UiEventLog).order_by(
            UiEventLog.created_at.desc()
        ).limit(limit)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        rows.reverse()
        events = [
            {
                "timestamp": row.created_at.isoformat() + "Z",
                "level": row.level,
                "message": row.message,
                "data": row.data or {}
            }
            for row in rows
        ]
        return {"events": events}

    @app.get("/api/ui/stream", tags=["UI"])
    async def ui_stream(
        request: Request,
        last_message_id: int = 0,
        last_event_id: int = 0,
        ui_user: dict = Depends(require_ui_auth)
    ):
        """SSE поток для новых сообщений и событий"""
        async def event_generator():
            nonlocal last_message_id, last_event_id
            last_message_updated_at = datetime.min
            while True:
                if await request.is_disconnected():
                    break

                messages = []
                events = []
                async with SessionLocal() as session:
                    if last_message_id is not None:
                        result = await session.execute(
                            select(UiMessageHistory)
                            .where(
                                or_(
                                    UiMessageHistory.id > last_message_id,
                                    UiMessageHistory.updated_at > last_message_updated_at
                                )
                            )
                            .order_by(UiMessageHistory.id.asc())
                            .limit(100)
                        )
                        messages = result.scalars().all()
                    if last_event_id is not None:
                        result = await session.execute(
                            select(UiEventLog)
                            .where(UiEventLog.id > last_event_id)
                            .order_by(UiEventLog.id.asc())
                            .limit(100)
                        )
                        events = result.scalars().all()

                for row in messages:
                    last_message_id = row.id
                    if row.updated_at and row.updated_at > last_message_updated_at:
                        last_message_updated_at = row.updated_at
                    payload = {
                        "id": row.id,
                        "chat_id": row.chat_id,
                        "direction": row.direction,
                        "status": row.status,
                        "text": row.message_text or "",
                        "timestamp": row.created_at.isoformat() + "Z",
                        "media_url": row.media_url,
                        "media_name": row.media_name,
                        "media_mime": row.media_mime,
                        "media_size": row.media_size
                    }
                    yield f"event: ui_message\ndata: {json.dumps(payload)}\n\n"

                for row in events:
                    last_event_id = row.id
                    payload = {
                        "id": row.id,
                        "timestamp": row.created_at.isoformat() + "Z",
                        "level": row.level,
                        "message": row.message,
                        "data": row.data or {}
                    }
                    yield f"event: ui_event\ndata: {json.dumps(payload)}\n\n"

                if not messages and not events:
                    yield ": keepalive\n\n"

                await asyncio.sleep(1)

        headers = {"Cache-Control": "no-cache"}
        return StreamingResponse(event_generator(), media_type="text/event-stream", headers=headers)

    @app.get("/api/ui/chats", tags=["UI"])
    async def ui_chats(limit: int = 80, ui_user: dict = Depends(require_ui_auth)):
        """Список чатов для UI"""
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")

        chats = await bridge.telegram.get_chats(limit=limit)
        return {"chats": chats}

    @app.post("/api/ui/chats/{chat_id}/read", tags=["UI"])
    async def ui_mark_chat_read(chat_id: int, ui_user: dict = Depends(require_ui_auth)):
        """Сброс непрочитанного счетчика"""
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")

        await bridge.telegram.mark_chat_read(chat_id)
        await log_ui_event("info", "chat_mark_read", {"chat_id": chat_id})
        return {"success": True}

    @app.get("/api/ui/chat/{chat_id}", tags=["UI"])
    async def ui_chat_details(
        chat_id: int,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Детали чата, профиль и статистика"""
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")

        details = await bridge.telegram.get_chat_details(chat_id)
        history = await bridge.telegram.get_chat_history_stats(chat_id)
        recent_messages = await bridge.telegram.get_recent_messages(
            limit=20,
            chat_id=chat_id
        )

        result = await db.execute(
            select(ChatProfile).filter_by(telegram_chat_id=chat_id)
        )
        profile = result.scalars().first()
        profile_data = {
            "tags": profile.tags if profile else "",
            "notes": profile.notes if profile else "",
            "has_consent": profile.has_consent if profile else False,
            "opted_out": profile.opted_out if profile else False,
            "quiet_hours_start": profile.quiet_hours_start if profile else "",
            "quiet_hours_end": profile.quiet_hours_end if profile else "",
            "timezone": profile.timezone if profile else settings.DEFAULT_TIMEZONE
        }

        return {
            "chat": details,
            "history": history,
            "profile": profile_data,
            "recent_messages": recent_messages[-5:]
        }

    @app.post("/api/ui/chat/{chat_id}/profile", tags=["UI"])
    async def ui_update_chat_profile(
        chat_id: int,
        request: UiChatProfileUpdate,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Сохранение тегов и заметок"""
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")

        result = await db.execute(
            select(ChatProfile).filter_by(telegram_chat_id=chat_id)
        )
        profile = result.scalars().first()
        if not profile:
            profile = ChatProfile(telegram_chat_id=chat_id)
            db.add(profile)

        if request.tags is not None:
            profile.tags = request.tags.strip()
        if request.notes is not None:
            profile.notes = request.notes.strip()
        if request.has_consent is not None:
            profile.has_consent = bool(request.has_consent)
        if request.opted_out is not None:
            profile.opted_out = bool(request.opted_out)
        if request.quiet_hours_start is not None:
            profile.quiet_hours_start = request.quiet_hours_start.strip() or None
        if request.quiet_hours_end is not None:
            profile.quiet_hours_end = request.quiet_hours_end.strip() or None
        if request.timezone is not None:
            profile.timezone = request.timezone.strip() or settings.DEFAULT_TIMEZONE

        await db.commit()
        await db.refresh(profile)

        await log_ui_event(
            "info",
            "chat_profile_saved",
            {"chat_id": chat_id}
        )

        return {
            "success": True,
            "profile": {"tags": profile.tags, "notes": profile.notes}
        }

    @app.post("/api/ui/auth/request-code", tags=["UI"])
    async def ui_request_code(
        request: UiAuthRequest,
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Запрос кода авторизации"""
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")

        success, status = await bridge.telegram.request_code(request.phone)
        message = humanize_auth_status(status)
        await log_ui_event(
            "info" if success else "error",
            "auth_request_code",
            {"status": status}
        )
        return {"success": success, "status": status, "message": message}

    @app.post("/api/ui/auth/submit-code", tags=["UI"])
    async def ui_submit_code(
        request: UiAuthCodeRequest,
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Подтверждение кода авторизации"""
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")

        success, status = await bridge.telegram.submit_code(
            request.code,
            request.phone
        )
        message = humanize_auth_status(status)
        await log_ui_event(
            "info" if success else "error",
            "auth_submit_code",
            {"status": status}
        )
        return {"success": success, "status": status, "message": message}

    @app.post("/api/ui/auth/submit-password", tags=["UI"])
    async def ui_submit_password(
        request: UiAuthPasswordRequest,
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Подтверждение 2FA"""
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")

        success, status = await bridge.telegram.submit_password(request.password)
        message = humanize_auth_status(status)
        await log_ui_event(
            "info" if success else "error",
            "auth_submit_password",
            {"status": status}
        )
        return {"success": success, "status": status, "message": message}

    @app.post("/api/ui/auth/logout", tags=["UI"])
    async def ui_logout(ui_user: dict = Depends(require_ui_auth)):
        """Выход из Telegram"""
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")

        success, status = await bridge.telegram.logout()
        message = "Сессия очищена" if success else "Ошибка выхода"
        await log_ui_event(
            "info" if success else "error",
            "auth_logout",
            {"status": status}
        )
        return {
            "success": success,
            "status": status,
            "message": message
        }

    @app.post("/api/ui/send", tags=["UI"])
    async def ui_send_message(
        request: UiSendRequest,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Отправка сообщения из локального UI"""
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")

        text = request.message.strip()
        if not text:
            return ui_error_response(400, "Сообщение пустое", "empty_message")

        if not request.chat_id and not request.username and not request.phone:
            return ui_error_response(
                400,
                "Нужен chat_id, username или телефон",
                "missing_target"
            )

        user = None
        if request.chat_id:
            user = await bridge.telegram.find_user_by_id(request.chat_id)
        if not user and request.username:
            user = await bridge.telegram.find_user_by_username(request.username)
        if not user and request.phone:
            user = await bridge.telegram.find_user_by_phone(request.phone)

        if not user:
            return ui_error_response(
                404,
                "Пользователь не найден в Telegram",
                "user_not_found"
            )

        idempotency_key = request.idempotency_key
        if not idempotency_key:
            idempotency_key = uuid.uuid4().hex

        payload = {
            "source": "ui",
            "chat_id": user.id,
            "username": user.username,
            "phone": request.phone,
            "message": text
        }
        outbox, created = await enqueue_outbox(
            db,
            idempotency_key,
            user.id,
            payload
        )
        if not created:
            return {
                "success": True,
                "message": "Already queued",
                "status": outbox.status,
                "outbox_id": outbox.id,
                "chat": {
                    "chat_id": user.id,
                    "username": user.username or "",
                    "display_name": bridge.telegram._format_chat_name(
                        user.username,
                        user.first_name,
                        user.last_name,
                        user.id
                    )
                }
            }

        if not settings.OUTBOX_PROCESS_INLINE:
            queued_entry = UiMessageHistory(
                chat_id=user.id,
                direction="outbound",
                message_text=text,
                message_type="text",
                username=user.username or "",
                display_name=bridge.telegram._format_chat_name(
                    user.username,
                    user.first_name,
                    user.last_name,
                    user.id
                ),
                status="queued"
            )
            db.add(queued_entry)
            await db.commit()
            return {
                "success": True,
                "message": "Queued",
                "status": outbox.status,
                "outbox_id": outbox.id,
                "chat": {
                    "chat_id": user.id,
                    "username": user.username or "",
                    "display_name": bridge.telegram._format_chat_name(
                        user.username,
                        user.first_name,
                        user.last_name,
                        user.id
                    )
                }
            }

        success, status_message = await bridge.telegram.send_message_to_user(user, text)
        await mark_outbox_result(db, outbox, success, None if success else status_message)

        if not success:
            friendly, retryable = humanize_send_error(status_message)
            await log_ui_event(
                "error",
                "send_failed",
                {
                    "chat_id": user.id,
                    "reason": status_message
                }
            )
            return ui_error_response(
                500,
                friendly,
                status_message,
                retryable
            )

        chat = None
        try:
            chats = await bridge.telegram.get_chats(limit=200)
            chat = next(
                (item for item in chats if item.get("chat_id") == user.id),
                None
            )
        except Exception:
            chat = None

        if not chat:
            display_name = bridge.telegram._format_chat_name(
                user.username,
                user.first_name,
                user.last_name,
                user.id
            )
            chat = {
                "chat_id": user.id,
                "username": user.username or "",
                "display_name": display_name
            }

        await log_ui_event(
            "info",
            "send_success",
            {"chat_id": user.id}
        )

        return {
            "success": True,
            "message": status_message,
            "chat": chat,
            "status": outbox.status,
            "outbox_id": outbox.id
        }

    @app.get("/api/ui/messages", tags=["UI"])
    async def ui_messages(
        limit: int = 50,
        chat_id: Optional[int] = None,
        ui_user: dict = Depends(require_ui_auth),
        db: AsyncSession = Depends(get_db)
    ):
        """Получение последних сообщений"""
        stmt = select(UiMessageHistory)
        if chat_id is not None:
            stmt = stmt.filter_by(chat_id=chat_id)
        stmt = stmt.order_by(UiMessageHistory.created_at.desc()).limit(limit)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        rows.reverse()
        messages = []
        for row in rows:
            timestamp = row.created_at.isoformat() + "Z" if row.created_at else None
            messages.append({
                "id": row.id,
                "direction": row.direction,
                "chat_id": row.chat_id,
                "username": row.username or "",
                "display_name": row.display_name or "",
                "text": row.message_text or "",
                "timestamp": timestamp,
                "status": row.status,
                "error_message": row.error_message,
                "media_url": row.media_url,
                "media_name": row.media_name,
                "media_mime": row.media_mime,
                "media_size": row.media_size
            })
        return {"messages": messages}
    
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        """Глобальный обработчик исключений"""
        logger.error(f"❌ Необработанное исключение: {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )
    
    return app


# Создаем приложение
app = create_app()


def set_bridge(bridge_instance: AmoCRMTelegramBridge):
    """Установка экземпляра bridge"""
    global bridge
    bridge = bridge_instance
    logger.info("✅ Bridge установлен в API сервере")
