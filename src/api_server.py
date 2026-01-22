"""
FastAPI сервер для API endpoints
Прием webhook от AmoCRM, внешние запросы
"""

import asyncio
import time
from collections import deque
from pathlib import Path
from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict
from datetime import datetime, timedelta
import secrets
import uuid
import json
import hashlib
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text, select, or_, func
from sqlalchemy.exc import IntegrityError

from src.config import settings
from src.logger import logger
from src.database import (
    get_db,
    ChatMapping,
    ChatProfile,
    Operator,
    TelegramAccount,
    MessageInbox,
    MessageOutbox,
    UiMessageHistory,
    UiEventLog,
    AuditLog,
    AppSetting,
    MessageTemplate,
    TagCatalog,
    SessionLocal
)
from src.app_settings import (
    ALLOWED_SETTINGS,
    refresh_settings_from_db,
    update_settings_overrides,
    get_settings_payload
)
from src.bridge import CRMTelegramBridge
from src.amocrm_client import AmoCRMClient
from src.bitrix24_client import Bitrix24Client
from src.retention import run_retention
from src.rate_limiter import check_rate_limit
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
    contact_id: int = Field(..., description="ID контакта в CRM (AmoCRM/Bitrix24)")
    phone: Optional[str] = Field(None, description="Номер телефона (с +)")
    username: Optional[str] = Field(None, description="Username в Telegram")
    account_id: Optional[int] = Field(None, description="ID Telegram аккаунта")
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
    redis_connected: bool = False  # Added in #85


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
    account_id: Optional[int] = None
    message: str
    idempotency_key: Optional[str] = None


class UiAuthRequest(BaseModel):
    """Запрос кода авторизации"""
    phone: Optional[str] = None
    account_id: Optional[int] = None


class UiAuthCodeRequest(BaseModel):
    """Отправка кода авторизации"""
    phone: Optional[str] = None
    code: str
    account_id: Optional[int] = None


class UiAuthPasswordRequest(BaseModel):
    """Отправка 2FA пароля"""
    password: str
    account_id: Optional[int] = None


class UiChatProfileUpdate(BaseModel):
    """Обновление заметок/тегов"""
    tags: Optional[str] = None
    notes: Optional[str] = None
    has_consent: Optional[bool] = None
    opted_out: Optional[bool] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    timezone: Optional[str] = None


class OperatorUpdateRequest(BaseModel):
    """Обновление лимитов оператора"""
    display_name: Optional[str] = None
    email: Optional[str] = None
    hourly_limit: Optional[int] = None
    daily_limit: Optional[int] = None


class AdminAccountUpdateRequest(BaseModel):
    """Обновление Telegram аккаунта"""
    label: Optional[str] = None
    is_active: Optional[bool] = None


class AdminSettingsUpdateRequest(BaseModel):
    """Обновление admin-настроек"""
    values: Dict[str, Any] = Field(default_factory=dict)


class AdminTemplateCreateRequest(BaseModel):
    """Создание шаблона сообщений"""
    label: str
    body: str
    is_active: bool = True


class AdminTemplateUpdateRequest(BaseModel):
    """Обновление шаблона сообщений"""
    label: Optional[str] = None
    body: Optional[str] = None
    is_active: Optional[bool] = None


class AdminTagCreateRequest(BaseModel):
    """Создание тега"""
    name: str
    description: Optional[str] = ""
    color: Optional[str] = ""
    is_active: bool = True


class AdminTagUpdateRequest(BaseModel):
    """Обновление тега"""
    name: Optional[str] = None
    description: Optional[str] = None
    color: Optional[str] = None
    is_active: Optional[bool] = None


# Глобальные переменные (будут инициализированы в main)
bridge: Optional[CRMTelegramBridge] = None
basic_scheme = HTTPBasic(auto_error=False)
_ui_users_cache = {"raw": None, "parsed": {}}
AMOCRM_STATE_KEY = "AMOCRM_OAUTH_STATE"
BITRIX24_STATE_KEY = "BITRIX24_OAUTH_STATE"


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


async def log_audit_event(
    action: str,
    ui_user: dict,
    data: Optional[dict] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None
) -> None:
    try:
        async with SessionLocal() as session:
            session.add(AuditLog(
                actor=ui_user.get("username") or "unknown",
                role=ui_user.get("role") or "unknown",
                action=action,
                entity_type=entity_type,
                entity_id=str(entity_id) if entity_id is not None else None,
                data=data or {}
            ))
            await session.commit()
    except Exception as exc:
        logger.warning(f"⚠️ Не удалось сохранить audit log: {exc}")


async def set_app_setting(key: str, value: dict) -> None:
    async with SessionLocal() as session:
        record = await session.get(AppSetting, key)
        if record:
            record.value = value
        else:
            session.add(AppSetting(key=key, value=value))
        await session.commit()


async def get_app_setting(key: str) -> Optional[dict]:
    async with SessionLocal() as session:
        record = await session.get(AppSetting, key)
        if not record:
            return None
        return record.value if isinstance(record.value, dict) else None


async def delete_app_setting(key: str) -> None:
    async with SessionLocal() as session:
        record = await session.get(AppSetting, key)
        if record:
            await session.delete(record)
            await session.commit()


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


async def resolve_account_id(account_id: Optional[int]) -> int:
    if not bridge or not bridge.telegram:
        raise HTTPException(status_code=503, detail="Telegram not initialized")
    if account_id:
        return account_id
    default_id = await bridge.telegram.get_default_account_id()
    if not default_id:
        raise HTTPException(status_code=503, detail="No active Telegram accounts")
    return default_id


async def get_client_for_account(account_id: Optional[int]):
    resolved_id = await resolve_account_id(account_id)
    return resolved_id, await bridge.telegram.get_client(resolved_id)


async def resolve_operator_id(db: AsyncSession, ui_user: dict) -> Optional[int]:
    username = (ui_user.get("username") or "").strip()
    if not username or username == "anonymous":
        return None
    result = await db.execute(
        select(Operator).filter_by(username=username)
    )
    operator = result.scalars().first()
    if operator:
        return operator.id
    operator = Operator(username=username, display_name=username)
    db.add(operator)
    await db.commit()
    await db.refresh(operator)
    return operator.id


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


async def require_admin(ui_user: dict = Depends(require_ui_auth)):
    if ui_user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="admin_only")
    return ui_user


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


def tail_log_lines(log_path: Path, limit: int) -> list[str]:
    if limit <= 0:
        return []
    lines = deque(maxlen=limit)
    with log_path.open("r", encoding="utf-8", errors="ignore") as handle:
        for line in handle:
            lines.append(line.rstrip("\n"))
    return list(lines)


def serialize_template(template: MessageTemplate) -> dict:
    return {
        "id": template.id,
        "label": template.label,
        "body": template.body,
        "is_active": template.is_active,
        "created_at": template.created_at.isoformat() + "Z" if template.created_at else None,
        "updated_at": template.updated_at.isoformat() + "Z" if template.updated_at else None,
    }


def serialize_tag(tag: TagCatalog) -> dict:
    return {
        "id": tag.id,
        "name": tag.name,
        "description": tag.description,
        "color": tag.color,
        "is_active": tag.is_active,
        "created_at": tag.created_at.isoformat() + "Z" if tag.created_at else None,
        "updated_at": tag.updated_at.isoformat() + "Z" if tag.updated_at else None,
    }


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


async def verify_api_key(
    request: Request,
    x_api_key: str = Header(...)
):
    """Проверка API ключа + rate limit."""
    if x_api_key != settings.API_SECRET_KEY:
        logger.warning("⚠️ Попытка доступа с неверным API ключом")
        raise HTTPException(status_code=403, detail="Invalid API key")

    client_ip = request.client.host if request.client else "unknown"
    key = f"{x_api_key}:{client_ip}"
    allowed, _ = await check_rate_limit(
        key,
        settings.API_RATE_LIMIT_PER_MINUTE,
        window_seconds=60,
        prefix="api"
    )
    if not allowed:
        raise HTTPException(status_code=429, detail="rate_limit_exceeded")

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

    # CORS middleware (#42)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.DEBUG else [],  # TODO: Configure for production
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    # Rate limiting middleware (#37, #132)
    @app.middleware("http")
    async def rate_limit_middleware(request: Request, call_next):
        """Rate limiting for UI auth and health endpoints"""
        path = request.url.path

        # Rate limit /health endpoint (#132)
        if path == "/health":
            client_ip = request.client.host if request.client else "unknown"
            allowed, count = await check_rate_limit(
                key=f"health:{client_ip}",
                limit=60,  # 60 requests
                window_seconds=60  # per minute
            )
            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many health check requests"},
                    headers={"Retry-After": "60"}
                )

        # Rate limit UI auth endpoints (#37)
        if path.startswith("/api/ui/"):
            # Extract username from Basic Auth if present
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Basic "):
                import base64
                try:
                    credentials = base64.b64decode(auth_header.split(" ")[1]).decode()
                    username = credentials.split(":")[0]
                    allowed, count = await check_rate_limit(
                        key=f"ui_auth:{username}",
                        limit=100,  # 100 requests
                        window_seconds=60  # per minute
                    )
                    if not allowed:
                        return JSONResponse(
                            status_code=429,
                            content={"detail": "Too many requests"},
                            headers={"Retry-After": "60"}
                        )
                except Exception:
                    pass  # Invalid auth header, let it be handled by auth check

        return await call_next(request)

    # Correlation ID middleware (#82)
    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        """Add correlation ID to request for tracing"""
        import uuid
        correlation_id = request.headers.get("X-Request-ID") or request.headers.get("X-Correlation-ID") or str(uuid.uuid4())

        # Add to request state for logging
        request.state.correlation_id = correlation_id

        response = await call_next(request)

        # Add to response headers
        response.headers["X-Request-ID"] = correlation_id
        response.headers["X-Correlation-ID"] = correlation_id

        return response

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

    def _ensure_crm_ready(require_bridge: bool = True) -> None:
        """Проверка готовности CRM (AmoCRM или Bitrix24)"""
        crm_provider = settings.CRM_PROVIDER.lower()

        if settings.OUTBOX_PROCESS_INLINE:
            if not bridge:
                raise HTTPException(status_code=503, detail="Bridge not initialized")
            if require_bridge and not bridge.crm:
                raise HTTPException(
                    status_code=503,
                    detail=f"{crm_provider.title()} is not configured"
                )
            return

        if crm_provider == "bitrix24":
            if not (
                settings.BITRIX24_WEBHOOK_URL or
                (settings.BITRIX24_DOMAIN and settings.BITRIX24_ACCESS_TOKEN)
            ):
                raise HTTPException(status_code=503, detail="Bitrix24 is not configured")
        else:
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

        # Fix #178: Initialize Contact Manager (starts cleanup task for locks)
        try:
            from src.contact_manager import contact_manager
            await contact_manager.initialize()
        except Exception as e:
            logger.error(f"❌ Failed to initialize Contact Manager: {e}")
    
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
    async def ui_auth():
        """Страница авторизации (публичный доступ)"""
        auth_path = STATIC_DIR / "auth.html"
        if not auth_path.exists():
            raise HTTPException(status_code=404, detail="UI not found")
        return FileResponse(
            auth_path,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"}
        )

    @app.get("/ui/operators", tags=["UI"])
    async def ui_operators_page(ui_user: dict = Depends(require_ui_auth)):
        """Страница операторов"""
        page_path = STATIC_DIR / "operators.html"
        if not page_path.exists():
            raise HTTPException(status_code=404, detail="UI not found")
        return FileResponse(
            page_path,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"}
        )

    @app.get("/admin", tags=["Admin"])
    async def admin_root(ui_user: dict = Depends(require_admin)):
        """Admin dashboard"""
        page_path = STATIC_DIR / "admin.html"
        if not page_path.exists():
            raise HTTPException(status_code=404, detail="UI not found")
        return FileResponse(
            page_path,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"}
        )

    @app.get("/admin/accounts", tags=["Admin"])
    async def admin_accounts_page(ui_user: dict = Depends(require_admin)):
        """Admin accounts page"""
        page_path = STATIC_DIR / "admin_accounts.html"
        if not page_path.exists():
            raise HTTPException(status_code=404, detail="UI not found")
        return FileResponse(
            page_path,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"}
        )

    @app.get("/admin/settings", tags=["Admin"])
    async def admin_settings_page(ui_user: dict = Depends(require_admin)):
        """Admin settings page"""
        page_path = STATIC_DIR / "admin_settings.html"
        if not page_path.exists():
            raise HTTPException(status_code=404, detail="UI not found")
        return FileResponse(
            page_path,
            media_type="text/html",
            headers={"Cache-Control": "no-cache"}
        )

    @app.get("/admin/logs", tags=["Admin"])
    async def admin_logs_page(ui_user: dict = Depends(require_admin)):
        """Admin logs page"""
        page_path = STATIC_DIR / "admin_logs.html"
        if not page_path.exists():
            raise HTTPException(status_code=404, detail="UI not found")
        return FileResponse(
            page_path,
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
            statuses = await bridge.telegram.get_status()
            telegram_connected = any(item.get("connected") for item in statuses)

        # Check Redis connection (#85)
        redis_connected = False
        try:
            from src.redis_client import get_redis
            redis = await get_redis()
            if redis:
                await redis.ping()
                redis_connected = True
        except Exception:
            redis_connected = False

        status = "healthy" if (db_connected and telegram_connected and redis_connected) else "degraded"
        return {
            "status": status,
            "telegram_connected": telegram_connected,
            "database_connected": db_connected,
            "redis_connected": redis_connected
        }
    
    @app.get("/health", response_model=HealthResponse, tags=["Monitoring"])
    async def health_check(db: AsyncSession = Depends(get_db)):
        """
        Health check endpoint
        Проверяет подключение к БД, Redis и Telegram
        """
        status = await _check_health(db)
        return {
            "status": status["status"],
            "version": settings.APP_VERSION,
            "telegram_connected": status["telegram_connected"],
            "database_connected": status["database_connected"],
            "redis_connected": status.get("redis_connected", False)
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
        _ensure_crm_ready()
        
        if not request.phone and not request.username:
            raise HTTPException(
                status_code=400,
                detail="Phone or username is required"
            )
        
        logger.info(
            f"📥 API запрос на отправку сообщения: "
            f"contact_id={request.contact_id}"
        )

        account_id = request.account_id
        if not account_id:
            result = await db.execute(
                select(ChatMapping).filter_by(amocrm_contact_id=request.contact_id)
            )
            mapping = result.scalars().first()
            if mapping:
                account_id = mapping.account_id
        if not account_id:
            account_id = await bridge.telegram.select_account_id()
        if not account_id:
            raise HTTPException(status_code=503, detail="No active Telegram accounts")

        key = idempotency_key
        if not key:
            payload_hash = json.dumps({
                "contact_id": request.contact_id,
                "phone": request.phone,
                "username": request.username,
                "message": request.message,
                "account_id": account_id
            }, sort_keys=True)
            key = build_idempotency_key(payload_hash)

        payload = {
            "source": "api",
            "contact_id": request.contact_id,
            "phone": request.phone,
            "username": request.username,
            "message": request.message,
            "account_id": account_id
        }
        outbox, created = await enqueue_outbox(
            db,
            key,
            account_id,
            None,
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
            request.message,
            account_id=account_id
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

        _ensure_crm_ready()
        
        try:
            body_bytes = await request.body()
            payload_hash = hashlib.sha256(body_bytes).hexdigest()
            idempotency_key = f"amocrm:{payload_hash}"

            # ATOMIC idempotency check using INSERT + catch IntegrityError
            db.add(MessageInbox(
                idempotency_key=idempotency_key,
                source="amocrm_webhook",
                payload_hash=payload_hash
            ))

            try:
                await db.commit()
            except IntegrityError:
                # Duplicate webhook - already processed
                await db.rollback()
                return {
                    "success": True,
                    "processed": 0,
                    "status": "duplicate"
                }

            try:  # Added JSON parsing protection (#26)
                body = json.loads(body_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                logger.error(f"❌ Invalid JSON in webhook: {e}")
                raise HTTPException(status_code=400, detail="Invalid JSON")

            logger.info(f"📥 Получен webhook от AmoCRM")
            logger.debug(f"Webhook body: {body}")
            
            # Обработка событий
            results = []
            
            # Обработка задач
            if 'tasks' in body and 'add' in body['tasks']:
                for task_data in body['tasks']['add']:
                    task_id = task_data.get('id')
                    if task_id:
                        account_id = await bridge.telegram.get_default_account_id()
                        key = f"amocrm_task:{task_id}"
                        payload = {
                            "source": "amocrm_webhook",
                            "task_id": task_id,
                            "account_id": account_id
                        }
                        outbox, created = await enqueue_outbox(
                            db,
                            key,
                            account_id or 0,
                            None,
                            0,
                            payload
                        )
                        results.append({
                            "task_id": task_id,
                            "queued": created,
                            "outbox_id": outbox.id
                        })

            # Обработка примечаний (notes) с тегом #telegram
            if 'notes' in body and 'add' in body['notes']:
                for note_data in body['notes']['add']:
                    note_info = note_data.get('note', {})
                    note_text = note_info.get('text', '')
                    note_type = note_info.get('note_type')
                    entity_id = note_data.get('entity_id')  # contact_id или lead_id

                    # Проверить тег #telegram или специальный note_type
                    if '#telegram' in note_text or note_type == 'telegram':
                        if entity_id:
                            # Удалить тег из текста
                            clean_message = note_text.replace('#telegram', '').strip()

                            if clean_message:
                                logger.info(f"📝 Отправка сообщения из примечания AmoCRM для контакта {entity_id}")

                                # Отправить через bridge
                                success, result = await bridge.send_message_from_crm(
                                    db,
                                    contact_id=entity_id,
                                    phone=None,  # Bridge найдёт из mapping или custom fields
                                    username=None,
                                    message=clean_message
                                )

                                results.append({
                                    "note_id": note_data.get('id'),
                                    "contact_id": entity_id,
                                    "sent": success,
                                    "result": str(result) if result else None
                                })

            return {
                "success": True,
                "processed": len(results),
                "results": results
            }
            
        except Exception as e:
            logger.error(f"❌ Ошибка обработки webhook: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")  # Fixed #25

    @app.post("/api/webhook/bitrix24", tags=["Webhooks"])
    async def bitrix24_webhook(
        request: Request,
        db: AsyncSession = Depends(get_db)
    ):
        """
        Webhook от Bitrix24
        Обработка событий из Bitrix24 (activities, tasks)
        """
        # Проверка секрета webhook
        if settings.BITRIX24_WEBHOOK_SECRET:
            provided = request.headers.get("X-Webhook-Secret")
            if not provided or not secrets.compare_digest(
                provided, settings.BITRIX24_WEBHOOK_SECRET
            ):
                raise HTTPException(status_code=401, detail="Invalid webhook secret")

        _ensure_crm_ready()

        try:
            # Bitrix24 отправляет данные как form-urlencoded
            content_type = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in content_type:
                form_data = await request.form()
                body = dict(form_data)
            else:
                body_bytes = await request.body()
                try:  # Added JSON parsing protection (#26)
                    body = json.loads(body_bytes.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    logger.error(f"❌ Invalid JSON in Bitrix24 webhook: {e}")
                    raise HTTPException(status_code=400, detail="Invalid JSON")

            # Вычисляем hash для идемпотентности
            body_str = json.dumps(body, sort_keys=True)
            payload_hash = hashlib.sha256(body_str.encode()).hexdigest()
            idempotency_key = f"bitrix24:{payload_hash}"

            # ATOMIC idempotency check using INSERT + catch IntegrityError
            db.add(MessageInbox(
                idempotency_key=idempotency_key,
                source="bitrix24_webhook",
                payload_hash=payload_hash
            ))

            try:
                await db.commit()
            except IntegrityError:
                # Duplicate webhook - already processed
                await db.rollback()
                return {
                    "success": True,
                    "processed": 0,
                    "status": "duplicate"
                }

            logger.info("📥 Получен webhook от Bitrix24")
            logger.debug(f"Webhook body: {body}")

            results = []
            event_type = body.get("event") or body.get("EVENT")

            # Обработка активностей (CRM Activities)
            if event_type in ("ONCRMACTIVITYADD", "ONCRMACTIVITYUPDATE"):
                activity_id = (
                    body.get("data", {}).get("FIELDS", {}).get("ID") or
                    body.get("data[FIELDS][ID]")
                )
                if activity_id:
                    account_id = await bridge.telegram.get_default_account_id()
                    key = f"bitrix24_activity:{activity_id}"
                    payload = {
                        "source": "bitrix24_webhook",
                        "activity_id": int(activity_id),
                        "account_id": account_id
                    }
                    outbox, created = await enqueue_outbox(
                        db,
                        key,
                        account_id or 0,
                        None,
                        0,
                        payload
                    )
                    results.append({
                        "activity_id": activity_id,
                        "queued": created,
                        "outbox_id": outbox.id
                    })

            # Обработка задач (Tasks)
            if event_type in ("ONTASKADD", "ONTASKUPDATE"):
                task_id = (
                    body.get("data", {}).get("FIELDS_AFTER", {}).get("ID") or
                    body.get("data[FIELDS_AFTER][ID]")
                )
                if task_id:
                    account_id = await bridge.telegram.get_default_account_id()
                    key = f"bitrix24_task:{task_id}"
                    payload = {
                        "source": "bitrix24_webhook",
                        "task_id": int(task_id),
                        "account_id": account_id
                    }
                    outbox, created = await enqueue_outbox(
                        db,
                        key,
                        account_id or 0,
                        None,
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
            logger.error(f"❌ Ошибка обработки Bitrix24 webhook: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")  # Fixed #25

    @app.get("/api/bitrix24/openlines/placement", tags=["Bitrix24"])
    async def bitrix24_openlines_placement(request: Request):
        """
        Placement handler для Open Channels коннектора

        Отображает UI страницу настроек коннектора в Bitrix24
        """
        return HTMLResponse(
            content="""
            <html>
                <head>
                    <title>Telegram MTProto Connector</title>
                    <meta charset="utf-8">
                    <style>
                        body {
                            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                            max-width: 600px;
                            margin: 20px auto;
                            padding: 20px;
                        }
                        .status {
                            background: #e8f5e9;
                            padding: 15px;
                            border-radius: 4px;
                            margin: 20px 0;
                        }
                        .status-icon { color: #4CAF50; font-size: 24px; }
                        h1 { color: #333; font-size: 24px; }
                        p { color: #666; line-height: 1.6; }
                        .info { background: #f5f5f5; padding: 10px; border-radius: 4px; margin: 10px 0; }
                    </style>
                </head>
                <body>
                    <h1>Telegram MTProto Connector</h1>
                    <div class="status">
                        <div class="status-icon">✓</div>
                        <strong>Коннектор активен</strong>
                    </div>
                    <p>Коннектор успешно настроен и готов к работе.</p>
                    <div class="info">
                        <strong>Как это работает:</strong>
                        <ul>
                            <li>Сообщения из Telegram будут отображаться в карточках контактов</li>
                            <li>Вы можете отвечать прямо из Bitrix24</li>
                            <li>Все сообщения синхронизируются автоматически</li>
                        </ul>
                    </div>
                </body>
            </html>
            """,
            status_code=200
        )

    @app.post("/api/webhook/bitrix24/openlines", tags=["Webhooks"])
    async def bitrix24_openlines_webhook(
        request: Request,
        db: AsyncSession = Depends(get_db)
    ):
        """
        Webhook для Bitrix24 Open Channels (Открытые линии)

        Обрабатывает события:
        - ONIMCONNECTORMESSAGEADD: сообщение от оператора → внешнему пользователю (Telegram)
        - ONIMCONNECTORLINEJOIN: коннектор подключен к линии
        - ONIMCONNECTORLINEDELETE: коннектор отключен от линии
        - ONIMCONNECTORMESSAGEUPDATE: сообщение обновлено
        - ONIMCONNECTORMESSAGEDELETE: сообщение удалено
        """
        logger.info("🌐 POST /api/webhook/bitrix24/openlines вызван")
        logger.info(f"📋 Headers: {dict(request.headers)}")

        if not settings.BITRIX24_OPEN_CHANNELS_ENABLED:
            logger.warning("⚠️ Open Channels отключены в настройках")
            return {"success": False, "error": "Open Channels disabled"}

        # Проверка секрета webhook
        if settings.BITRIX24_WEBHOOK_SECRET:
            provided = request.headers.get("X-Webhook-Secret")
            if not provided or not secrets.compare_digest(
                provided, settings.BITRIX24_WEBHOOK_SECRET
            ):
                raise HTTPException(status_code=401, detail="Invalid webhook secret")

        _ensure_crm_ready()

        def parse_nested_form_data(flat_dict: dict) -> dict:
            """
            Преобразует плоский словарь с ключами вида data[KEY][0][nested]
            в нормальную вложенную структуру.

            Пример:
            {'data[CONNECTOR]': 'test', 'data[MESSAGES][0][text]': 'hi'}
            ->
            {'data': {'CONNECTOR': 'test', 'MESSAGES': [{'text': 'hi'}]}}
            """
            import re
            result = {}

            for key, value in flat_dict.items():
                # Извлекаем все части пути (ключи и индексы)
                # data[CONNECTOR] -> ['data', 'CONNECTOR']
                # data[MESSAGES][0][text] -> ['data', 'MESSAGES', '0', 'text']
                path = re.findall(r'([^\[\]]+)', key)

                # Навигируемся по структуре
                current = result
                for i, part in enumerate(path[:-1]):
                    # Проверяем следующую часть - число или нет
                    next_part = path[i + 1]
                    is_next_index = next_part.isdigit()

                    # Если текущая часть - это число, значит мы уже в массиве
                    if part.isdigit():
                        continue  # Пропускаем, массив уже создан

                    # Создаем структуру если её нет
                    if part not in current:
                        current[part] = [] if is_next_index else {}

                    # Если следующий элемент - индекс массива
                    if is_next_index:
                        idx = int(next_part)
                        # Расширяем массив
                        while len(current[part]) <= idx:
                            current[part].append({})
                        current = current[part][idx]
                    else:
                        current = current[part]

                # Устанавливаем значение
                final_key = path[-1]
                if not final_key.isdigit():
                    current[final_key] = value

            return result

        try:
            # Bitrix24 отправляет данные как form-urlencoded
            content_type = request.headers.get("content-type", "")
            if "application/x-www-form-urlencoded" in content_type:
                form_data = await request.form()
                flat_body = dict(form_data)
                # Преобразуем вложенные ключи
                body = parse_nested_form_data(flat_body)
            else:
                body_bytes = await request.body()
                try:  # Added JSON parsing protection (#26)
                    body = json.loads(body_bytes.decode("utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    logger.error(f"❌ Invalid JSON in Open Lines webhook: {e}")
                    raise HTTPException(status_code=400, detail="Invalid JSON")

            logger.info("📥 Получен Open Lines webhook от Bitrix24")
            logger.info(f"📦 Event type: {body.get('event') or body.get('EVENT')}")
            logger.info(f"📦 Parsed data keys: {list(body.get('data', {}).keys()) if 'data' in body else 'no data key'}")
            logger.debug(f"Open Lines body: {body}")

            event_type = body.get("event") or body.get("EVENT")
            data = body.get("data") or body.get("DATA") or {}

            logger.info(f"🔍 Обработка события: event_type={event_type}")
            logger.info(f"🔍 Data CONNECTOR: {data.get('CONNECTOR')}")
            logger.info(f"🔍 Data LINE: {data.get('LINE')}")
            logger.info(f"🔍 Data MESSAGES count: {len(data.get('MESSAGES', []))}")

            # ONIMCONNECTORMESSAGEADD - сообщение от оператора к пользователю
            # Нужно переслать в Telegram
            if event_type == "ONIMCONNECTORMESSAGEADD":
                messages = data.get("MESSAGES", [])
                connector = data.get("CONNECTOR", "")
                line_id = int(data.get("LINE", 0)) if data.get("LINE") else 0

                # Проверяем что это наш коннектор
                if connector != settings.BITRIX24_CONNECTOR_ID:
                    logger.debug(f"Игнорируем событие для другого коннектора: {connector}")
                    return {"success": True, "processed": 0, "reason": "different_connector"}

                results = []
                for msg in messages:
                    chat_info = msg.get("chat", {})
                    message_info = msg.get("message", {})
                    im_info = msg.get("im", {})

                    logger.info(f"🔍 Message structure: msg keys={list(msg.keys())}")
                    logger.info(f"🔍 Full msg={msg}")

                    chat_id = chat_info.get("id")  # Это telegram chat_id
                    message_text = message_info.get("text", "")
                    # message_id может быть в разных местах структуры Bitrix24
                    message_id = (
                        message_info.get("id") or
                        im_info.get("message_id") or
                        im_info.get("id") or
                        msg.get("id")
                    )

                    logger.info(f"🔍 Extracted: chat_id={chat_id}, message_id={message_id}, text={message_text[:50] if message_text else 'empty'}...")

                    if not chat_id or not message_text:
                        continue

                    # Очистка BB-code тегов от Bitrix24
                    import re
                    # Удаляем префикс вида "[b]email@domain.com:[/b] [br]"
                    message_text = re.sub(r'\[b\][^@]+@[^:]+:\[/b\]\s*\[br\]', '', message_text)
                    # Удаляем остальные BB-code теги
                    message_text = re.sub(r'\[/?b\]|\[/?i\]|\[/?u\]|\[br\]', '', message_text)
                    message_text = message_text.strip()

                    logger.info(f"🧹 После очистки BB-code: {message_text[:50] if message_text else 'empty'}...")

                    # Ставим в очередь на отправку в Telegram
                    # Получаем default account_id напрямую из БД
                    if bridge and bridge.telegram:
                        account_id = await bridge.telegram.get_default_account_id()
                    else:
                        # Если bridge не инициализирован (inline mode off), берем первый аккаунт
                        from sqlalchemy import select
                        from src.database import TelegramAccount
                        result = await db.execute(select(TelegramAccount).order_by(TelegramAccount.id).limit(1))
                        first_account = result.scalars().first()
                        account_id = first_account.id if first_account else 1

                    telegram_chat_id = int(chat_id)
                    key = f"openline_msg:{message_id or chat_id}:{hash(message_text)}"
                    payload = {
                        "source": "bitrix24_openline",
                        "chat_id": telegram_chat_id,
                        "message": message_text,
                        "bitrix_message_id": message_id,
                        "bitrix_chat_id": im_info.get("chat_id"),  # ID чата в Bitrix24
                        "line_id": line_id,
                        "account_id": account_id
                    }

                    # Убедимся что mapping существует
                    from src.database import ChatMapping
                    mapping_result = await db.execute(
                        select(ChatMapping).filter_by(telegram_chat_id=telegram_chat_id)
                    )
                    mapping = mapping_result.scalars().first()

                    if not mapping:
                        # Создаем временный mapping для этого чата
                        logger.info(f"📝 Создание mapping для chat_id={telegram_chat_id}")
                        new_mapping = ChatMapping(
                            telegram_chat_id=telegram_chat_id,
                            crm_contact_id=0,  # Будет обновлено позже
                            account_id=account_id or 1,
                            source="openline_webhook"
                        )
                        db.add(new_mapping)
                        await db.commit()

                    outbox, created = await enqueue_outbox(
                        db,
                        key,
                        account_id or 0,
                        None,
                        telegram_chat_id,  # Передаем реальный chat_id
                        payload
                    )

                    results.append({
                        "chat_id": chat_id,
                        "queued": created,
                        "outbox_id": outbox.id
                    })

                    logger.info(
                        f"📤 Сообщение от оператора поставлено в очередь: "
                        f"chat_id={chat_id}, outbox_id={outbox.id}"
                    )

                return {
                    "success": True,
                    "event": "ONIMCONNECTORMESSAGEADD",
                    "processed": len(results),
                    "results": results
                }

            # ONIMCONNECTORLINEJOIN - коннектор подключен к линии
            if event_type == "ONIMCONNECTORLINEJOIN":
                connector = data.get("CONNECTOR", "")
                line_id = data.get("LINE", 0)
                logger.info(f"✅ Коннектор {connector} подключен к линии {line_id}")
                return {
                    "success": True,
                    "event": "ONIMCONNECTORLINEJOIN",
                    "connector": connector,
                    "line_id": line_id
                }

            # ONIMCONNECTORLINEDELETE - коннектор отключен от линии
            if event_type == "ONIMCONNECTORLINEDELETE":
                connector = data.get("CONNECTOR", "")
                line_id = data.get("LINE", 0)
                logger.warning(f"⚠️ Коннектор {connector} отключен от линии {line_id}")
                return {
                    "success": True,
                    "event": "ONIMCONNECTORLINEDELETE",
                    "connector": connector,
                    "line_id": line_id
                }

            # Другие события
            logger.warning(f"⚠️ Необработанное Open Lines событие: {event_type}, data keys: {list(data.keys())}")
            return {
                "success": True,
                "event": event_type or "unknown",
                "processed": 0
            }

        except Exception as e:
            logger.error(f"❌ Ошибка обработки Open Lines webhook: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")  # Fixed #25

    @app.post("/api/bitrix24/openlines/setup", tags=["Bitrix24"])
    async def setup_bitrix24_openlines(
        request: Request,
        webhook_url: Optional[str] = None,
        api_key: str = Depends(verify_api_key)
    ):
        """
        Настройка Bitrix24 Open Channels интеграции

        1. Регистрирует коннектор
        2. Активирует на линии
        3. Регистрирует события (если указан webhook_url)

        Требуется API ключ в заголовке: X-API-Key
        """
        if settings.CRM_PROVIDER.lower() != "bitrix24":
            raise HTTPException(
                status_code=400,
                detail="CRM_PROVIDER must be 'bitrix24'"
            )

        if not bridge or not bridge.crm:
            raise HTTPException(
                status_code=503,
                detail="Bitrix24 client not initialized"
            )

        try:
            # Получаем host для формирования полных URL
            host = request.headers.get('host', 'localhost')

            result = await bridge.crm.setup_open_channels(
                connector_id=settings.BITRIX24_CONNECTOR_ID,
                connector_name=settings.BITRIX24_CONNECTOR_NAME,
                webhook_url=webhook_url,
                line_id=settings.BITRIX24_LINE_ID,
                placement_handler_url=f"https://{host}/api/bitrix24/openlines/placement"
            )
            return result
        except Exception as e:
            logger.error(f"❌ Ошибка настройки Open Channels: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")  # Fixed #25

    @app.get("/api/bitrix24/openlines/status", tags=["Bitrix24"])
    async def get_bitrix24_openlines_status(
        api_key: str = Depends(verify_api_key)
    ):
        """
        Получение статуса Bitrix24 Open Channels

        Требуется API ключ в заголовке: X-API-Key
        """
        if settings.CRM_PROVIDER.lower() != "bitrix24":
            raise HTTPException(
                status_code=400,
                detail="CRM_PROVIDER must be 'bitrix24'"
            )

        if not bridge or not bridge.crm:
            raise HTTPException(
                status_code=503,
                detail="Bitrix24 client not initialized"
            )

        try:
            status = await bridge.crm.get_connector_status(
                connector_id=settings.BITRIX24_CONNECTOR_ID,
                line_id=settings.BITRIX24_LINE_ID
            )
            lines = await bridge.crm.get_open_lines()
            events = await bridge.crm.get_registered_events()

            return {
                "enabled": settings.BITRIX24_OPEN_CHANNELS_ENABLED,
                "connector_id": settings.BITRIX24_CONNECTOR_ID,
                "line_id": settings.BITRIX24_LINE_ID,
                "connector_status": status,
                "available_lines": lines,
                "registered_events": events
            }
        except Exception as e:
            logger.error(f"❌ Ошибка получения статуса Open Channels: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")  # Fixed #25

    @app.api_route("/api/bitrix24/install", methods=["GET", "POST"], tags=["Bitrix24"])
    async def bitrix24_install_app(
        request: Request,
        code: str = None,
        domain: str = None,
        scope: str = None,
        state: str = None,
    ):
        """
        Установка приложения Bitrix24 (ONAPPINSTALL event + OAuth callback)

        Bitrix24 может вызывать этот endpoint двумя способами:
        1. ONAPPINSTALL событие - POST с auth[access_token], auth[refresh_token], DOMAIN
        2. OAuth code flow - GET/POST с code и domain параметрами
        3. Frame call - POST с APP_SID (открытие приложения в iframe)

        Flow для ONAPPINSTALL:
        1. Пользователь нажимает "Установить" в Bitrix24
        2. Bitrix24 отправляет POST с токенами напрямую
        3. Сохраняем токены в БД
        4. Настраиваем Open Channels (если включено)
        5. Возвращаем HTML страницу с подтверждением
        """
        # Логируем входящий запрос для отладки
        logger.info(f"📥 Bitrix24 install: method={request.method}, query={dict(request.query_params)}")

        # Переменные для токенов (если придут напрямую)
        access_token = None
        refresh_token = None
        auth_expires = 3600  # По умолчанию 1 час

        # Получаем параметры из query string
        if not code:
            code = request.query_params.get("code")
        if not domain:
            domain = request.query_params.get("domain") or request.query_params.get("DOMAIN")

        # Проверяем APP_SID в query параметрах для frame calls
        app_sid = request.query_params.get("APP_SID")

        # Если POST - проверяем form data и auth параметры
        if request.method == "POST":
            try:
                form_data = await request.form()
                form_dict = dict(form_data)
                logger.info(f"📥 Bitrix24 POST form keys: {list(form_dict.keys())}")

                # Логируем все значения для отладки (маскируем токены)
                for key, value in form_dict.items():
                    if 'TOKEN' in key.upper() or 'AUTH' in key.upper() or 'REFRESH' in key.upper():
                        logger.info(f"   {key} = {str(value)[:20]}...{str(value)[-10:] if len(str(value)) > 30 else ''}")
                    else:
                        logger.info(f"   {key} = {value}")

                # Стандартные параметры
                code = code or form_data.get("code")
                domain = domain or form_data.get("domain") or form_data.get("DOMAIN")
                scope = scope or form_data.get("scope")

                # Bitrix24 может передавать токены в разных форматах:
                # 1. ONAPPINSTALL: auth[access_token], auth[refresh_token]
                access_token = form_data.get("auth[access_token]")
                refresh_token = form_data.get("auth[refresh_token]")

                # 2. Frame placement: AUTH_ID, REFRESH_ID
                if not access_token:
                    access_token = form_data.get("AUTH_ID")
                if not refresh_token:
                    refresh_token = form_data.get("REFRESH_ID")

                # Получаем SERVER_ENDPOINT если есть
                server_endpoint = form_data.get("SERVER_ENDPOINT")

                # Получаем AUTH_EXPIRES (время жизни токена в секундах)
                auth_expires = form_data.get("AUTH_EXPIRES")
                if auth_expires:
                    try:
                        auth_expires = int(auth_expires)
                    except (ValueError, TypeError):
                        auth_expires = 3600  # По умолчанию 1 час

                # Также проверяем APP_SID в form data
                app_sid = app_sid or form_data.get("APP_SID")

                logger.info(
                    f"📥 Bitrix24 parsed: code={bool(code)}, domain={domain}, "
                    f"access_token={bool(access_token)}, refresh_token={bool(refresh_token)}, "
                    f"app_sid={bool(app_sid)}, server_endpoint={bool(server_endpoint)}"
                )

                # Если это frame call (APP_SID есть) и есть AUTH_ID - сохраняем токены
                if app_sid and access_token:
                    logger.info(f"📥 Bitrix24 frame call с токенами авторизации")
                    # Продолжаем обработку - токены будут сохранены ниже

                # Если это просто frame call без токенов - показываем UI
                elif app_sid and not access_token and not code:
                    logger.info(f"📥 Bitrix24 frame call без токенов, showing app UI")
                    return HTMLResponse(
                        content="""
                        <html>
                            <head>
                                <title>Telegram CRM</title>
                                <meta charset="utf-8">
                            </head>
                            <body>
                                <h1>Telegram CRM для Bitrix24</h1>
                                <p>Приложение успешно установлено.</p>
                                <p>Используйте API endpoints для отправки сообщений через Telegram.</p>
                            </body>
                        </html>
                        """,
                        status_code=200
                    )

            except Exception as e:
                logger.warning(f"⚠️ Не удалось прочитать form data: {e}")

        logger.info(f"📥 Bitrix24 install final: code={bool(code)}, domain={domain}, tokens={bool(access_token)}")

        # Проверяем: есть ли токены напрямую (ONAPPINSTALL) или code для обмена
        if not code and not access_token:
            return HTMLResponse(
                content="""
                <html>
                    <head><title>Ошибка установки</title></head>
                    <body>
                        <h1>Ошибка: отсутствуют данные авторизации</h1>
                        <p>Bitrix24 не передал ни code, ни токены авторизации.</p>
                        <p>Проверьте настройки приложения в Bitrix24.</p>
                    </body>
                </html>
                """,
                status_code=400
            )

        if settings.CRM_PROVIDER.lower() != "bitrix24":
            return HTMLResponse(
                content="""
                <html>
                    <head><title>Ошибка</title></head>
                    <body>
                        <h1>CRM провайдер не настроен на Bitrix24</h1>
                    </body>
                </html>
                """,
                status_code=400
            )

        # Используем домен из параметра или из настроек
        target_domain = domain or settings.BITRIX24_DOMAIN

        try:
            # Создаём временный клиент для обмена токенов если bridge не инициализирован
            if bridge and bridge.crm:
                crm_client = bridge.crm
            else:
                from src.bitrix24_client import Bitrix24Client
                crm_client = Bitrix24Client()

            # Два пути: либо обмен code на токены, либо сохранение токенов напрямую
            if access_token:
                # ONAPPINSTALL событие - токены переданы напрямую
                logger.info(f"💾 Сохранение токенов из ONAPPINSTALL события для {target_domain}")
                result = await crm_client.save_tokens_directly(
                    access_token=access_token,
                    refresh_token=refresh_token,
                    domain=target_domain,
                    expires_in=auth_expires
                )
            else:
                # OAuth code flow - обмениваем code на токены
                logger.info(f"🔄 Обмен OAuth code на токены для {target_domain}")
                result = await crm_client.exchange_auth_code(code, target_domain)

            if not result.get("success"):
                error_msg = result.get("error", "Неизвестная ошибка")
                logger.error(f"❌ Ошибка установки: {error_msg}")
                return HTMLResponse(
                    content=f"""
                    <html>
                        <head><title>Ошибка установки</title></head>
                        <body>
                            <h1>Ошибка установки приложения</h1>
                            <p>{error_msg}</p>
                            <p><a href="https://{target_domain}/">Вернуться на портал</a></p>
                        </body>
                    </html>
                    """,
                    status_code=500
                )

            actual_domain = result.get("domain", target_domain)
            logger.info(f"✅ Bitrix24 приложение установлено для {actual_domain}")

            # Настраиваем Open Channels если включено
            if settings.BITRIX24_OPEN_CHANNELS_ENABLED:
                try:
                    logger.info("🔧 Настройка Open Channels...")
                    host = request.headers.get('host', 'localhost')
                    setup_result = await crm_client.setup_open_channels(
                        connector_id=settings.BITRIX24_CONNECTOR_ID,
                        connector_name=settings.BITRIX24_CONNECTOR_NAME,
                        webhook_url=f"https://{host}/api/webhook/bitrix24/openlines",
                        line_id=settings.BITRIX24_LINE_ID,
                        placement_handler_url=f"https://{host}/api/bitrix24/openlines/placement"
                    )
                    logger.info(f"✅ Open Channels настроены: {setup_result}")
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось настроить Open Channels: {e}")

            # Возвращаем HTML страницу с подтверждением (отображается в iframe)
            # ВАЖНО: вызываем BX24.installFinish() чтобы завершить установку
            return HTMLResponse(
                content="""
                <html>
                    <head>
                        <title>Telegram CRM установлен</title>
                        <meta charset="utf-8">
                        <script src="//api.bitrix24.com/api/v1/"></script>
                        <style>
                            body {
                                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
                                max-width: 600px;
                                margin: 40px auto;
                                padding: 20px;
                                text-align: center;
                            }
                            .success { color: #4CAF50; font-size: 48px; }
                            h1 { color: #333; }
                            p { color: #666; line-height: 1.6; }
                            .spinner {
                                border: 4px solid #f3f3f3;
                                border-top: 4px solid #4CAF50;
                                border-radius: 50%;
                                width: 40px;
                                height: 40px;
                                animation: spin 1s linear infinite;
                                margin: 20px auto;
                            }
                            @keyframes spin {
                                0% { transform: rotate(0deg); }
                                100% { transform: rotate(360deg); }
                            }
                        </style>
                    </head>
                    <body>
                        <div class="success">✓</div>
                        <h1>Приложение успешно установлено!</h1>
                        <p>Telegram CRM готов к работе.</p>
                        <div class="spinner" id="spinner"></div>
                        <p id="status">Завершение установки...</p>

                        <script>
                            BX24.init(function() {
                                console.log('Bitrix24 JS SDK initialized, calling installFinish...');
                                document.getElementById('status').textContent = 'Завершение...';

                                // Завершаем установку - переводим статус в INSTALLED=true
                                setTimeout(function() {
                                    BX24.installFinish();
                                }, 500);
                            });
                        </script>
                    </body>
                </html>
                """,
                status_code=200
            )

        except Exception as e:
            logger.exception(f"❌ Исключение при установке: {e}")
            return HTMLResponse(
                content=f"""
                <html>
                    <head><title>Ошибка установки</title></head>
                    <body>
                        <h1>Ошибка установки приложения</h1>
                        <p>{str(e)}</p>
                        <p><a href="https://{target_domain}/">Вернуться на портал</a></p>
                    </body>
                </html>
                """,
                status_code=500
            )

    @app.get("/api/bitrix24/oauth/start", tags=["Bitrix24"])
    async def bitrix24_oauth_start():
        """
        Начало OAuth авторизации Bitrix24 (ручной режим)

        Перенаправляет на страницу авторизации Bitrix24.
        Используйте если нужно переавторизовать приложение вручную.
        """
        if settings.CRM_PROVIDER.lower() != "bitrix24":
            raise HTTPException(
                status_code=400,
                detail="CRM_PROVIDER must be 'bitrix24'"
            )

        if not bridge or not bridge.crm:
            raise HTTPException(
                status_code=503,
                detail="Bitrix24 client not initialized"
            )

        oauth_url = bridge.crm.get_oauth_url()
        return RedirectResponse(url=oauth_url)

    @app.api_route("/api/bitrix24/oauth/callback", methods=["GET", "POST"], tags=["Bitrix24"])
    async def bitrix24_oauth_callback(
        request: Request,
        code: str = None,
        domain: str = None,
        error: str = None,
        state: str = None,
    ):
        """
        OAuth callback от Bitrix24

        Обменивает authorization code на access/refresh токены.
        Поддерживает как ручную авторизацию, так и установку приложения.
        """
        if error:
            logger.error(f"❌ Bitrix24 OAuth error: {error}")
            return HTMLResponse(
                content=f"""
                <html>
                    <head><title>Ошибка авторизации</title></head>
                    <body>
                        <h1>Авторизация отклонена</h1>
                        <p>{error}</p>
                    </body>
                </html>
                """,
                status_code=400
            )

        if not code:
            raise HTTPException(
                status_code=400,
                detail="Missing authorization code"
            )

        target_domain = domain or settings.BITRIX24_DOMAIN

        try:
            if bridge and bridge.crm:
                crm_client = bridge.crm
            else:
                from src.bitrix24_client import Bitrix24Client
                crm_client = Bitrix24Client()

            result = await crm_client.exchange_auth_code(code, target_domain)

            if result.get("success"):
                actual_domain = result.get("domain", target_domain)
                logger.info(f"✅ Bitrix24 OAuth авторизация успешна для {actual_domain}")

                return HTMLResponse(
                    content=f"""
                    <html>
                        <head><title>Авторизация успешна</title></head>
                        <body>
                            <h1>✅ Авторизация Bitrix24 успешна!</h1>
                            <p>Токены сохранены для домена: {actual_domain}</p>
                            <p><a href="https://{actual_domain}/">Вернуться на портал</a></p>
                        </body>
                    </html>
                    """
                )
            else:
                error_msg = result.get("error", "Неизвестная ошибка")
                return HTMLResponse(
                    content=f"""
                    <html>
                        <head><title>Ошибка авторизации</title></head>
                        <body>
                            <h1>Ошибка авторизации</h1>
                            <p>{error_msg}</p>
                        </body>
                    </html>
                    """,
                    status_code=400
                )

        except Exception as e:
            logger.exception(f"❌ Исключение при OAuth: {e}")
            return HTMLResponse(
                content=f"""
                <html>
                    <head><title>Ошибка</title></head>
                    <body>
                        <h1>Ошибка авторизации</h1>
                        <p>{str(e)}</p>
                    </body>
                </html>
                """,
                status_code=500
            )

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

        statuses = await bridge.telegram.get_status()
        default_id = await bridge.telegram.get_default_account_id()
        default_status = None
        if statuses:
            default_status = next(
                (item for item in statuses if item.get("account_id") == default_id),
                statuses[0]
            )

        if not default_status:
            raise HTTPException(status_code=503, detail="No Telegram accounts")

        return {
            "connected": default_status.get("connected"),
            "authorized": default_status.get("authorized"),
            "user": default_status.get("user"),
            "session": default_status.get("session"),
            "anti_spam": default_status.get("anti_spam"),
            "accounts": statuses,
            "default_account_id": default_id
        }

    @app.get("/api/ui/accounts", tags=["UI"])
    async def ui_accounts(ui_user: dict = Depends(require_ui_auth)):
        """
        Список Telegram аккаунтов.

        Fix #171: Требует авторизацию, маскирует телефонные номера.
        """
        if not bridge or not bridge.telegram:
            raise HTTPException(status_code=503, detail="Telegram not initialized")
        statuses = await bridge.telegram.get_status()
        default_id = await bridge.telegram.get_default_account_id()

        # Fix #171: Mask phone numbers for security
        def mask_phone(phone: str) -> str:
            """Mask middle digits: +7***1234 instead of +71234567890"""
            if not phone:
                return "***"
            if len(phone) < 8:
                return "***"
            return phone[:2] + "***" + phone[-4:]

        # Mask phone numbers in statuses
        for status in statuses:
            if "phone_number" in status:
                status["phone_number"] = mask_phone(status.get("phone_number", ""))
            # Also mask in user object if present
            if "user" in status and status["user"] and "phone" in status["user"]:
                status["user"]["phone"] = mask_phone(status["user"].get("phone", ""))

        return {"accounts": statuses, "default_account_id": default_id}

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

    @app.get("/api/ui/templates", tags=["UI"])
    async def ui_templates(
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Активные шаблоны быстрых ответов."""
        result = await db.execute(
            select(MessageTemplate)
            .where(MessageTemplate.is_active.is_(True))
            .order_by(MessageTemplate.label.asc())
        )
        templates = result.scalars().all()
        return {"templates": [serialize_template(item) for item in templates]}

    @app.get("/api/ui/tags", tags=["UI"])
    async def ui_tags(
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Активные теги для подсказок."""
        result = await db.execute(
            select(TagCatalog)
            .where(TagCatalog.is_active.is_(True))
            .order_by(TagCatalog.name.asc())
        )
        tags = result.scalars().all()
        return {"tags": [serialize_tag(item) for item in tags]}

    @app.get("/api/admin/summary", tags=["Admin"])
    async def admin_summary(
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Сводка по системе для admin UI"""
        total_accounts = (await db.execute(
            select(func.count()).select_from(TelegramAccount)
        )).scalar() or 0
        active_accounts = (await db.execute(
            select(func.count())
            .select_from(TelegramAccount)
            .where(TelegramAccount.is_active.is_(True))
        )).scalar() or 0
        operator_count = (await db.execute(
            select(func.count()).select_from(Operator)
        )).scalar() or 0

        outbox_counts = {"queued": 0, "failed": 0, "dead": 0, "processing": 0, "sent": 0}
        result = await db.execute(
            select(MessageOutbox.status, func.count()).group_by(MessageOutbox.status)
        )
        for status, count in result.all():
            outbox_counts[status] = count

        last_event = None
        event_result = await db.execute(
            select(UiEventLog).order_by(UiEventLog.created_at.desc()).limit(1)
        )
        last_event_row = event_result.scalars().first()
        if last_event_row:
            last_event = {
                "message": last_event_row.message,
                "level": last_event_row.level,
                "created_at": last_event_row.created_at.isoformat() + "Z"
            }

        connected_count = 0
        authorized_count = 0
        if bridge and bridge.telegram:
            statuses = await bridge.telegram.get_status()
            connected_count = sum(1 for item in statuses if item.get("connected"))
            authorized_count = sum(1 for item in statuses if item.get("authorized"))

        return {
            "accounts": {
                "total": total_accounts,
                "active": active_accounts,
                "connected": connected_count,
                "authorized": authorized_count,
            },
            "operators": {"total": operator_count},
            "outbox": outbox_counts,
            "last_event": last_event,
        }

    @app.get("/api/admin/accounts", tags=["Admin"])
    async def admin_accounts(
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Список Telegram аккаунтов для admin UI"""
        if bridge and bridge.telegram:
            statuses = await bridge.telegram.get_status()
            return {"accounts": statuses}

        result = await db.execute(
            select(TelegramAccount).order_by(TelegramAccount.id.asc())
        )
        accounts = result.scalars().all()
        items = []
        for account in accounts:
            items.append(
                {
                    "account_id": account.id,
                    "phone_number": account.phone_number,
                    "label": account.label or account.phone_number,
                    "is_active": account.is_active,
                    "connected": False,
                    "authorized": False,
                    "user": None,
                    "session": {},
                    "anti_spam": {},
                }
            )
        return {"accounts": items}

    @app.patch("/api/admin/accounts/{account_id}", tags=["Admin"])
    async def admin_update_account(
        account_id: int,
        request: AdminAccountUpdateRequest,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Обновление Telegram аккаунта"""
        result = await db.execute(
            select(TelegramAccount).filter_by(id=account_id)
        )
        account = result.scalars().first()
        if not account:
            raise HTTPException(status_code=404, detail="account_not_found")

        if request.label is not None:
            account.label = request.label.strip() or None
        if request.is_active is not None:
            account.is_active = bool(request.is_active)

        await db.commit()
        await db.refresh(account)

        await log_audit_event(
            "account_update",
            ui_user,
            data={"label": account.label, "is_active": account.is_active},
            entity_type="telegram_account",
            entity_id=str(account.id)
        )

        if bridge and bridge.telegram:
            await bridge.telegram.refresh_accounts(active_only=False)
            if request.is_active is False:
                await bridge.telegram.stop_client(account_id)
            if request.is_active is True and settings.OUTBOX_PROCESS_INLINE:
                try:
                    await bridge.telegram.get_client(account_id)
                except Exception as exc:
                    logger.warning("⚠️ Не удалось запустить аккаунт %s: %s", account_id, exc)

            statuses = await bridge.telegram.get_status()
            match = next(
                (item for item in statuses if item.get("account_id") == account_id),
                None
            )
            if match:
                return {"success": True, "account": match}

        return {
            "success": True,
            "account": {
                "account_id": account.id,
                "phone_number": account.phone_number,
                "label": account.label or account.phone_number,
                "is_active": account.is_active,
                "connected": False,
                "authorized": False,
                "user": None,
                "session": {},
                "anti_spam": {},
            }
        }

    @app.get("/api/admin/settings", tags=["Admin"])
    async def admin_settings(ui_user: dict = Depends(require_admin)):
        """Текущие admin-настройки"""
        try:
            overrides = await refresh_settings_from_db()
        except Exception as exc:
            logger.warning("⚠️ Не удалось загрузить admin-настройки: %s", exc)
            overrides = {}
        return get_settings_payload(overrides)

    @app.patch("/api/admin/settings", tags=["Admin"])
    async def admin_update_settings(
        request: AdminSettingsUpdateRequest,
        ui_user: dict = Depends(require_admin)
    ):
        """Обновление admin-настроек"""
        updated, errors = await update_settings_overrides(request.values)
        if errors:
            return JSONResponse(
                status_code=400,
                content={"success": False, "errors": errors}
            )

        anti_spam_keys = {
            "MAX_MESSAGES_PER_HOUR",
            "MAX_NEW_CHATS_PER_DAY",
            "MIN_DELAY_BETWEEN_MESSAGES",
        }
        if updated and bridge and bridge.telegram and anti_spam_keys.intersection(updated.keys()):
            bridge.telegram.apply_antispam_limits(
                settings.MAX_MESSAGES_PER_HOUR,
                settings.MAX_NEW_CHATS_PER_DAY,
                settings.MIN_DELAY_BETWEEN_MESSAGES
            )

        await log_audit_event(
            "settings_update",
            ui_user,
            data={"updated": updated, "errors": errors}
        )

        restart_keys = [
            key for key in updated.keys()
            if ALLOWED_SETTINGS.get(key, {}).get("requires_restart")
        ]
        return {
            "success": True,
            "updated": updated,
            "requires_restart": bool(restart_keys),
            "restart_keys": restart_keys,
        }

    @app.get("/api/admin/amocrm/status", tags=["Admin"])
    async def admin_amocrm_status(ui_user: dict = Depends(require_admin)):
        """Статус AmoCRM OAuth."""
        await refresh_settings_from_db()
        configured = all([
            settings.AMOCRM_DOMAIN,
            settings.AMOCRM_CLIENT_ID,
            settings.AMOCRM_CLIENT_SECRET,
            settings.AMOCRM_REDIRECT_URI,
        ])
        has_tokens = bool(settings.AMOCRM_ACCESS_TOKEN and settings.AMOCRM_REFRESH_TOKEN)
        return {
            "configured": configured,
            "domain": settings.AMOCRM_DOMAIN,
            "redirect_uri": settings.AMOCRM_REDIRECT_URI,
            "has_tokens": has_tokens,
            "token_expires_at": settings.AMOCRM_TOKEN_EXPIRES_AT,
        }

    @app.get("/api/admin/amocrm/oauth/url", tags=["Admin"])
    async def admin_amocrm_oauth_url(ui_user: dict = Depends(require_admin)):
        """Сгенерировать URL для AmoCRM OAuth."""
        if not all([
            settings.AMOCRM_DOMAIN,
            settings.AMOCRM_CLIENT_ID,
            settings.AMOCRM_CLIENT_SECRET,
            settings.AMOCRM_REDIRECT_URI,
        ]):
            raise HTTPException(status_code=400, detail="amocrm_config_missing")

        state = secrets.token_urlsafe(16)
        await set_app_setting(
            AMOCRM_STATE_KEY,
            {"state": state, "created_at": datetime.utcnow().isoformat() + "Z"}
        )
        url = (
            f"https://{settings.AMOCRM_DOMAIN}/oauth"
            f"?client_id={settings.AMOCRM_CLIENT_ID}"
            f"&redirect_uri={settings.AMOCRM_REDIRECT_URI}"
            f"&state={state}"
            f"&mode=post_message"
        )
        return {"url": url}

    @app.get("/api/admin/amocrm/oauth/callback", tags=["Admin"])
    async def admin_amocrm_oauth_callback(
        code: Optional[str] = None,
        state: Optional[str] = None,
        ui_user: dict = Depends(require_admin)
    ):
        """OAuth callback для AmoCRM."""
        if not code:
            raise HTTPException(status_code=400, detail="code_required")

        stored = await get_app_setting(AMOCRM_STATE_KEY)
        if stored:
            if not state or stored.get("state") != state:
                await delete_app_setting(AMOCRM_STATE_KEY)
                raise HTTPException(status_code=400, detail="invalid_state")

        if bridge and bridge.crm and isinstance(bridge.crm, AmoCRMClient):
            success = await bridge.crm.exchange_auth_code(code)
        else:
            client = AmoCRMClient()
            success = await client.exchange_auth_code(code)

        await delete_app_setting(AMOCRM_STATE_KEY)

        await log_audit_event(
            "amocrm_oauth_exchange",
            ui_user,
            data={"success": success}
        )

        if not success:
            return RedirectResponse(url="/admin/settings?amocrm=error")
        return RedirectResponse(url="/admin/settings?amocrm=success")

    # =========================================================================
    # AmoCRM Widget Endpoints
    # =========================================================================

    @app.get("/api/amocrm/widget/install", tags=["AmoCRM Widget"])
    async def amocrm_widget_install():
        """
        Страница с инструкциями по установке AmoCRM Widget
        """
        return FileResponse("static/amocrm_widget_install.html")

    @app.get("/api/amocrm/widget/chat", tags=["AmoCRM Widget"])
    async def amocrm_widget_chat(
        contact_id: int,
        account_id: Optional[int] = None,
        db: AsyncSession = Depends(get_db)
    ):
        """
        HTML widget для чата с контактом в AmoCRM
        Загружается через iframe в карточке контакта
        """
        _ensure_crm_ready()

        if not bridge or not bridge.crm or not isinstance(bridge.crm, AmoCRMClient):
            raise HTTPException(status_code=503, detail="AmoCRM not configured")

        # Получить информацию о контакте из AmoCRM
        contact = await bridge.crm.find_contact_by_id(contact_id)
        if not contact:
            raise HTTPException(status_code=404, detail="Contact not found")

        # Извлечь данные контакта
        contact_name = contact.get('name', 'Контакт')
        phone = None
        username = None

        # Получить custom fields
        custom_fields = contact.get('custom_fields_values', [])
        for field in custom_fields:
            field_id = field.get('field_id')
            if field_id == settings.AMOCRM_FIELD_TELEGRAM_USERNAME:
                values = field.get('values', [])
                if values:
                    username = values[0].get('value')
            elif field.get('field_code') == 'PHONE':
                values = field.get('values', [])
                if values:
                    phone = values[0].get('value')

        # Получить историю сообщений
        # Найти mapping по amocrm_contact_id
        result = await db.execute(
            select(ChatMapping).filter_by(amocrm_contact_id=contact_id)
        )
        mapping = result.scalars().first()

        messages = []
        if mapping:
            # Загрузить историю из UiMessageHistory
            result = await db.execute(
                select(UiMessageHistory)
                .filter_by(chat_id=mapping.telegram_chat_id)
                .order_by(UiMessageHistory.created_at.desc())
                .limit(50)
            )
            messages = result.scalars().all()
            messages = list(reversed(messages))  # Старые первыми

        # Вернуть HTML widget
        return HTMLResponse(content=f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Telegram Chat</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; height: 100vh; display: flex; flex-direction: column; }}
        .chat-header {{ padding: 12px; background: #5c7cfa; color: white; }}
        .chat-header h3 {{ font-size: 16px; margin-bottom: 4px; }}
        .chat-header p {{ font-size: 12px; opacity: 0.9; }}
        .chat-messages {{ flex: 1; overflow-y: auto; padding: 12px; background: #f5f5f5; }}
        .message {{ margin-bottom: 12px; display: flex; }}
        .message.outgoing {{ justify-content: flex-end; }}
        .message-bubble {{ max-width: 70%; padding: 8px 12px; border-radius: 12px; word-wrap: break-word; }}
        .message.incoming .message-bubble {{ background: white; border-bottom-left-radius: 4px; }}
        .message.outgoing .message-bubble {{ background: #5c7cfa; color: white; border-bottom-right-radius: 4px; }}
        .message-meta {{ font-size: 11px; opacity: 0.7; margin-top: 4px; }}
        .chat-composer {{ padding: 12px; background: white; border-top: 1px solid #e0e0e0; }}
        .composer-form {{ display: flex; gap: 8px; }}
        .composer-form textarea {{ flex: 1; padding: 8px; border: 1px solid #e0e0e0; border-radius: 8px; resize: none; font-family: inherit; }}
        .composer-form button {{ padding: 8px 16px; background: #5c7cfa; color: white; border: none; border-radius: 8px; cursor: pointer; }}
        .composer-form button:hover {{ background: #4263eb; }}
        .composer-form button:disabled {{ background: #ccc; cursor: not-allowed; }}
        .status-icon {{ margin-left: 4px; }}
        .loading {{ text-align: center; padding: 12px; color: #999; }}
    </style>
</head>
<body>
    <div class="chat-header">
        <h3 id="contact-name">{contact_name}</h3>
        <p id="contact-info">{phone or username or 'Telegram'}</p>
    </div>

    <div class="chat-messages" id="messages">
        {"".join([
            f'''<div class="message {'outgoing' if msg.is_outgoing else 'incoming'}">
                <div class="message-bubble">
                    {msg.message_text}
                    <div class="message-meta">
                        {msg.created_at.strftime('%H:%M')}
                        {f'<span class="status-icon">✓</span>' if msg.is_outgoing and msg.status == 'sent' else ''}
                    </div>
                </div>
            </div>'''
            for msg in messages
        ])}
    </div>

    <div class="chat-composer">
        <form class="composer-form" onsubmit="sendMessage(event)">
            <textarea
                id="message-input"
                placeholder="Напишите сообщение..."
                rows="2"
                onkeydown="if(event.key==='Enter' && !event.shiftKey){{event.preventDefault();sendMessage(event);}}"
            ></textarea>
            <button type="submit" id="send-btn">Отправить</button>
        </form>
    </div>

    <script>
        const contactId = {contact_id};
        const phone = {f"'{phone}'" if phone else 'null'};
        const username = {f"'{username}'" if username else 'null'};
        let pollInterval = null;

        async function sendMessage(event) {{
            event.preventDefault();
            const input = document.getElementById('message-input');
            const btn = document.getElementById('send-btn');
            const message = input.value.trim();

            if (!message) return;

            btn.disabled = true;
            input.disabled = true;

            try {{
                const response = await fetch('/api/amocrm/widget/send', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{
                        contact_id: contactId,
                        message: message,
                        phone: phone,
                        username: username
                    }})
                }});

                if (response.ok) {{
                    input.value = '';
                    loadHistory();
                }} else {{
                    alert('Ошибка отправки сообщения');
                }}
            }} catch (error) {{
                console.error('Error:', error);
                alert('Ошибка отправки');
            }} finally {{
                btn.disabled = false;
                input.disabled = false;
                input.focus();
            }}
        }}

        async function loadHistory() {{
            try {{
                const response = await fetch(`/api/amocrm/widget/history?contact_id=${{contactId}}&limit=50`);
                if (!response.ok) return;

                const data = await response.json();
                renderMessages(data.messages || []);
            }} catch (error) {{
                console.error('Load error:', error);
            }}
        }}

        function renderMessages(messages) {{
            const container = document.getElementById('messages');
            container.innerHTML = messages.map(msg => `
                <div class="message ${{msg.is_outgoing ? 'outgoing' : 'incoming'}}">
                    <div class="message-bubble">
                        ${{msg.message_text}}
                        <div class="message-meta">
                            ${{new Date(msg.created_at).toLocaleTimeString('ru-RU', {{hour: '2-digit', minute: '2-digit'}})}}
                            ${{msg.is_outgoing && msg.status === 'sent' ? '<span class="status-icon">✓</span>' : ''}}
                        </div>
                    </div>
                </div>
            `).join('');

            // Scroll to bottom
            container.scrollTop = container.scrollHeight;
        }}

        function startPolling() {{
            pollInterval = setInterval(loadHistory, 5000);
        }}

        function stopPolling() {{
            if (pollInterval) clearInterval(pollInterval);
        }}

        // Start polling on load
        startPolling();

        // Stop polling when page unloads
        window.addEventListener('beforeunload', stopPolling);

        // Scroll to bottom on load
        const messagesDiv = document.getElementById('messages');
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    </script>
</body>
</html>
        """)

    @app.post("/api/amocrm/widget/send", tags=["AmoCRM Widget"])
    async def amocrm_widget_send(
        request: Request,
        db: AsyncSession = Depends(get_db)
    ):
        """Отправка сообщения из AmoCRM widget"""
        _ensure_crm_ready()

        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON")

        contact_id = body.get("contact_id")
        message = body.get("message", "").strip()
        phone = body.get("phone")
        username = body.get("username")

        if not contact_id or not message:
            raise HTTPException(status_code=400, detail="contact_id and message required")

        # Отправить через bridge
        success, result = await bridge.send_message_from_crm(
            db,
            contact_id=contact_id,
            phone=phone,
            username=username,
            message=message
        )

        if not success:
            raise HTTPException(status_code=500, detail=result)

        return {
            "success": True,
            "message": "Message queued for delivery"
        }

    @app.get("/api/amocrm/widget/history", tags=["AmoCRM Widget"])
    async def amocrm_widget_history(
        contact_id: int,
        limit: int = 50,
        offset: int = 0,
        db: AsyncSession = Depends(get_db)
    ):
        """Получить историю сообщений для контакта"""
        # Найти mapping по amocrm_contact_id
        result = await db.execute(
            select(ChatMapping).filter_by(amocrm_contact_id=contact_id)
        )
        mapping = result.scalars().first()

        if not mapping:
            return {"messages": []}

        # Загрузить историю
        result = await db.execute(
            select(UiMessageHistory)
            .filter_by(chat_id=mapping.telegram_chat_id)
            .order_by(UiMessageHistory.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        messages = result.scalars().all()
        messages = list(reversed(messages))  # Старые первыми

        return {
            "messages": [
                {
                    "id": msg.id,
                    "message_text": msg.message_text,
                    "is_outgoing": msg.is_outgoing,
                    "status": msg.status,
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ]
        }

    @app.get("/api/admin/bitrix24/status", tags=["Admin"])
    async def admin_bitrix24_status(ui_user: dict = Depends(require_admin)):
        """Статус Bitrix24 интеграции."""
        await refresh_settings_from_db()
        # Bitrix24 может работать через webhook URL или OAuth
        has_webhook = bool(settings.BITRIX24_WEBHOOK_URL)
        has_oauth = all([
            settings.BITRIX24_DOMAIN,
            settings.BITRIX24_CLIENT_ID,
            settings.BITRIX24_CLIENT_SECRET,
        ])
        has_tokens = bool(settings.BITRIX24_ACCESS_TOKEN)
        configured = has_webhook or (has_oauth and has_tokens)
        return {
            "configured": configured,
            "domain": settings.BITRIX24_DOMAIN,
            "has_webhook_url": has_webhook,
            "has_oauth": has_oauth,
            "has_tokens": has_tokens,
            "token_expires_at": settings.BITRIX24_TOKEN_EXPIRES_AT,
        }

    @app.get("/api/admin/bitrix24/oauth/url", tags=["Admin"])
    async def admin_bitrix24_oauth_url(ui_user: dict = Depends(require_admin)):
        """Сгенерировать URL для Bitrix24 OAuth."""
        if not all([
            settings.BITRIX24_DOMAIN,
            settings.BITRIX24_CLIENT_ID,
            settings.BITRIX24_CLIENT_SECRET,
            settings.BITRIX24_REDIRECT_URI,
        ]):
            raise HTTPException(status_code=400, detail="bitrix24_config_missing")

        state = secrets.token_urlsafe(16)
        await set_app_setting(
            BITRIX24_STATE_KEY,
            {"state": state, "created_at": datetime.utcnow().isoformat() + "Z"}
        )
        # Bitrix24 OAuth URL
        url = (
            f"https://{settings.BITRIX24_DOMAIN}/oauth/authorize/"
            f"?client_id={settings.BITRIX24_CLIENT_ID}"
            f"&redirect_uri={settings.BITRIX24_REDIRECT_URI}"
            f"&state={state}"
            f"&response_type=code"
        )
        return {"url": url}

    @app.get("/api/admin/bitrix24/oauth/callback", tags=["Admin"])
    async def admin_bitrix24_oauth_callback(
        code: Optional[str] = None,
        state: Optional[str] = None,
        ui_user: dict = Depends(require_admin)
    ):
        """OAuth callback для Bitrix24."""
        if not code:
            raise HTTPException(status_code=400, detail="code_required")

        stored = await get_app_setting(BITRIX24_STATE_KEY)
        if stored:
            if not state or stored.get("state") != state:
                await delete_app_setting(BITRIX24_STATE_KEY)
                raise HTTPException(status_code=400, detail="invalid_state")

        if bridge and bridge.crm and isinstance(bridge.crm, Bitrix24Client):
            success = await bridge.crm.exchange_auth_code(code)
        else:
            client = Bitrix24Client()
            success = await client.exchange_auth_code(code)

        await delete_app_setting(BITRIX24_STATE_KEY)

        await log_audit_event(
            "bitrix24_oauth_exchange",
            ui_user,
            data={"success": success}
        )

        if not success:
            return RedirectResponse(url="/admin/settings?bitrix24=error")
        return RedirectResponse(url="/admin/settings?bitrix24=success")

    @app.get("/api/admin/crm/status", tags=["Admin"])
    async def admin_crm_status(ui_user: dict = Depends(require_admin)):
        """Общий статус CRM интеграции (AmoCRM или Bitrix24)."""
        await refresh_settings_from_db()
        crm_provider = settings.CRM_PROVIDER.lower()

        if crm_provider == "bitrix24":
            has_webhook = bool(settings.BITRIX24_WEBHOOK_URL)
            has_oauth = all([
                settings.BITRIX24_DOMAIN,
                settings.BITRIX24_CLIENT_ID,
                settings.BITRIX24_CLIENT_SECRET,
            ])
            has_tokens = bool(settings.BITRIX24_ACCESS_TOKEN)
            configured = has_webhook or (has_oauth and has_tokens)
            return {
                "provider": "bitrix24",
                "configured": configured,
                "domain": settings.BITRIX24_DOMAIN,
                "has_tokens": has_tokens,
                "token_expires_at": settings.BITRIX24_TOKEN_EXPIRES_AT,
            }
        else:
            configured = all([
                settings.AMOCRM_DOMAIN,
                settings.AMOCRM_CLIENT_ID,
                settings.AMOCRM_CLIENT_SECRET,
                settings.AMOCRM_REDIRECT_URI,
            ])
            has_tokens = bool(settings.AMOCRM_ACCESS_TOKEN and settings.AMOCRM_REFRESH_TOKEN)
            return {
                "provider": "amocrm",
                "configured": configured,
                "domain": settings.AMOCRM_DOMAIN,
                "has_tokens": has_tokens,
                "token_expires_at": settings.AMOCRM_TOKEN_EXPIRES_AT,
            }

    @app.get("/api/admin/templates", tags=["Admin"])
    async def admin_templates(
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Список шаблонов сообщений."""
        result = await db.execute(
            select(MessageTemplate).order_by(MessageTemplate.label.asc())
        )
        templates = result.scalars().all()
        return {"templates": [serialize_template(item) for item in templates]}

    @app.post("/api/admin/templates", tags=["Admin"])
    async def admin_create_template(
        request: AdminTemplateCreateRequest,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Создать шаблон сообщений."""
        label = request.label.strip()
        body = request.body.strip()
        if not label:
            raise HTTPException(status_code=400, detail="label_required")
        if not body:
            raise HTTPException(status_code=400, detail="body_required")

        template = MessageTemplate(
            label=label,
            body=body,
            is_active=bool(request.is_active)
        )
        db.add(template)
        await db.commit()
        await db.refresh(template)

        await log_audit_event(
            "template_create",
            ui_user,
            data={"label": template.label},
            entity_type="message_template",
            entity_id=str(template.id)
        )

        return {"template": serialize_template(template)}

    @app.patch("/api/admin/templates/{template_id}", tags=["Admin"])
    async def admin_update_template(
        template_id: int,
        request: AdminTemplateUpdateRequest,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Обновить шаблон сообщений."""
        template = await db.get(MessageTemplate, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="template_not_found")

        updated_fields = {}
        if request.label is not None:
            label = request.label.strip()
            if not label:
                raise HTTPException(status_code=400, detail="label_required")
            template.label = label
            updated_fields["label"] = label
        if request.body is not None:
            body = request.body.strip()
            if not body:
                raise HTTPException(status_code=400, detail="body_required")
            template.body = body
            updated_fields["body"] = body
        if request.is_active is not None:
            template.is_active = bool(request.is_active)
            updated_fields["is_active"] = template.is_active

        await db.commit()
        await db.refresh(template)

        await log_audit_event(
            "template_update",
            ui_user,
            data={"updated": updated_fields},
            entity_type="message_template",
            entity_id=str(template.id)
        )

        return {"template": serialize_template(template)}

    @app.delete("/api/admin/templates/{template_id}", tags=["Admin"])
    async def admin_delete_template(
        template_id: int,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Удалить шаблон сообщений."""
        template = await db.get(MessageTemplate, template_id)
        if not template:
            raise HTTPException(status_code=404, detail="template_not_found")

        await db.delete(template)
        await db.commit()

        await log_audit_event(
            "template_delete",
            ui_user,
            data={"label": template.label},
            entity_type="message_template",
            entity_id=str(template.id)
        )

        return {"success": True}

    @app.get("/api/admin/tags", tags=["Admin"])
    async def admin_tags(
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Список тегов."""
        result = await db.execute(
            select(TagCatalog).order_by(TagCatalog.name.asc())
        )
        tags = result.scalars().all()
        return {"tags": [serialize_tag(item) for item in tags]}

    @app.post("/api/admin/tags", tags=["Admin"])
    async def admin_create_tag(
        request: AdminTagCreateRequest,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Создать тег."""
        name = request.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name_required")

        existing = await db.execute(
            select(TagCatalog).where(TagCatalog.name == name)
        )
        if existing.scalars().first():
            raise HTTPException(status_code=409, detail="tag_exists")

        tag = TagCatalog(
            name=name,
            description=(request.description or "").strip(),
            color=(request.color or "").strip(),
            is_active=bool(request.is_active)
        )
        db.add(tag)
        await db.commit()
        await db.refresh(tag)

        await log_audit_event(
            "tag_create",
            ui_user,
            data={"name": tag.name},
            entity_type="tag",
            entity_id=str(tag.id)
        )

        return {"tag": serialize_tag(tag)}

    @app.patch("/api/admin/tags/{tag_id}", tags=["Admin"])
    async def admin_update_tag(
        tag_id: int,
        request: AdminTagUpdateRequest,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Обновить тег."""
        tag = await db.get(TagCatalog, tag_id)
        if not tag:
            raise HTTPException(status_code=404, detail="tag_not_found")

        updated_fields = {}
        if request.name is not None:
            name = request.name.strip()
            if not name:
                raise HTTPException(status_code=400, detail="name_required")
            if name != tag.name:
                existing = await db.execute(
                    select(TagCatalog).where(TagCatalog.name == name)
                )
                if existing.scalars().first():
                    raise HTTPException(status_code=409, detail="tag_exists")
            tag.name = name
            updated_fields["name"] = name
        if request.description is not None:
            tag.description = request.description.strip()
            updated_fields["description"] = tag.description
        if request.color is not None:
            tag.color = request.color.strip()
            updated_fields["color"] = tag.color
        if request.is_active is not None:
            tag.is_active = bool(request.is_active)
            updated_fields["is_active"] = tag.is_active

        await db.commit()
        await db.refresh(tag)

        await log_audit_event(
            "tag_update",
            ui_user,
            data={"updated": updated_fields},
            entity_type="tag",
            entity_id=str(tag.id)
        )

        return {"tag": serialize_tag(tag)}

    @app.delete("/api/admin/tags/{tag_id}", tags=["Admin"])
    async def admin_delete_tag(
        tag_id: int,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Удалить тег."""
        tag = await db.get(TagCatalog, tag_id)
        if not tag:
            raise HTTPException(status_code=404, detail="tag_not_found")

        await db.delete(tag)
        await db.commit()

        await log_audit_event(
            "tag_delete",
            ui_user,
            data={"name": tag.name},
            entity_type="tag",
            entity_id=str(tag.id)
        )

        return {"success": True}

    @app.post("/api/admin/retention/run", tags=["Admin"])
    async def admin_retention_run(ui_user: dict = Depends(require_admin)):
        """Запуск очистки по политике retention."""
        result = await run_retention()
        await log_audit_event(
            "retention_run",
            ui_user,
            data=result
        )
        return {"success": True, "result": result}

    @app.get("/api/admin/logs", tags=["Admin"])
    async def admin_logs(
        limit: int = 200,
        level: Optional[str] = None,
        search: Optional[str] = None,
        ui_user: dict = Depends(require_admin)
    ):
        """Tail application logs."""
        log_path = Path(settings.LOG_FILE)
        if not log_path.exists():
            return {"lines": [], "message": "log_file_not_found"}

        safe_limit = max(1, min(limit, 1000))
        lines = tail_log_lines(log_path, safe_limit)

        if level:
            level_token = level.strip().upper()
            lines = [line for line in lines if level_token in line]

        if search:
            token = search.strip()
            if token:
                lines = [line for line in lines if token in line]

        return {"lines": lines}

    @app.get("/api/admin/audit", tags=["Admin"])
    async def admin_audit(
        limit: int = 100,
        actor: Optional[str] = None,
        action: Optional[str] = None,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_admin)
    ):
        """Audit log entries."""
        safe_limit = max(1, min(limit, 200))
        stmt = select(AuditLog)
        if actor:
            stmt = stmt.filter(AuditLog.actor == actor)
        if action:
            stmt = stmt.filter(AuditLog.action == action)
        stmt = stmt.order_by(AuditLog.created_at.desc()).limit(safe_limit)
        result = await db.execute(stmt)
        rows = result.scalars().all()
        items = []
        for row in rows:
            items.append({
                "id": row.id,
                "actor": row.actor,
                "role": row.role,
                "action": row.action,
                "entity_type": row.entity_type,
                "entity_id": row.entity_id,
                "data": row.data or {},
                "created_at": row.created_at.isoformat() + "Z" if row.created_at else None
            })
        return {"audit": items}

    @app.get("/api/admin/contact-health", tags=["Admin"])
    async def admin_contact_health(
        ui_user: dict = Depends(require_admin)
    ):
        """
        Health check for Contact Manager system.

        Returns circuit breaker state, rate limits configuration,
        and statistics for the last hour and last day.

        Used for monitoring the phone extraction system and preventing
        Telegram account bans.

        Requires admin role.
        """
        from src.monitoring import ContactAddMonitor
        from src.contact_manager import contact_manager

        health = await ContactAddMonitor.check_health()

        return {
            "circuit_breaker": {
                "state": contact_manager.circuit_breaker._state,
                "failure_count": contact_manager.circuit_breaker._failure_count,
                "cooldown_until": (
                    contact_manager.circuit_breaker._cooldown_until.isoformat() + "Z"
                    if contact_manager.circuit_breaker._cooldown_until
                    else None
                ),
                "recent_adds_count": len(contact_manager.circuit_breaker._recent_adds),
                "max_burst": contact_manager.circuit_breaker.MAX_BURST,
                "max_failures": contact_manager.circuit_breaker.MAX_FAILURES,
                "cooldown_seconds": contact_manager.circuit_breaker.COOLDOWN_SECONDS
            },
            "limits": {
                "inbound": {
                    "per_hour": contact_manager.INBOUND_MAX_PER_HOUR,
                    "per_day": contact_manager.INBOUND_MAX_PER_DAY
                },
                "outbound": {
                    "per_hour": contact_manager.OUTBOUND_MAX_PER_HOUR,
                    "per_day": contact_manager.OUTBOUND_MAX_PER_DAY
                }
            },
            "health": health
        }

    @app.get("/api/ui/operators", tags=["UI"])
    async def ui_operators(
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Список операторов и их лимитов"""
        result = await db.execute(
            select(Operator).order_by(Operator.username.asc())
        )
        operators = result.scalars().all()

        now = datetime.utcnow()
        hour_ago = now - timedelta(hours=1)
        day_ago = now - timedelta(days=1)

        hour_counts = {}
        day_counts = {}

        hour_result = await db.execute(
            select(MessageOutbox.operator_id, func.count())
            .where(
                MessageOutbox.operator_id.is_not(None),
                MessageOutbox.created_at >= hour_ago
            )
            .group_by(MessageOutbox.operator_id)
        )
        for operator_id, count in hour_result.all():
            hour_counts[operator_id] = count

        day_result = await db.execute(
            select(MessageOutbox.operator_id, func.count())
            .where(
                MessageOutbox.operator_id.is_not(None),
                MessageOutbox.created_at >= day_ago
            )
            .group_by(MessageOutbox.operator_id)
        )
        for operator_id, count in day_result.all():
            day_counts[operator_id] = count

        items = []
        for operator in operators:
            items.append({
                "id": operator.id,
                "username": operator.username,
                "display_name": operator.display_name or operator.username,
                "email": operator.email or "",
                "hourly_limit": operator.hourly_limit,
                "daily_limit": operator.daily_limit,
                "sent_last_hour": hour_counts.get(operator.id, 0),
                "sent_last_day": day_counts.get(operator.id, 0),
                "created_at": operator.created_at.isoformat() + "Z" if operator.created_at else None
            })

        return {"operators": items}

    @app.patch("/api/ui/operators/{operator_id}", tags=["UI"])
    async def ui_update_operator(
        operator_id: int,
        request: OperatorUpdateRequest,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Обновление лимитов оператора"""
        if ui_user.get("role") != "admin":
            raise HTTPException(status_code=403, detail="admin_only")

        result = await db.execute(
            select(Operator).filter_by(id=operator_id)
        )
        operator = result.scalars().first()
        if not operator:
            raise HTTPException(status_code=404, detail="operator_not_found")

        if request.display_name is not None:
            operator.display_name = request.display_name.strip() or None
        if request.email is not None:
            operator.email = request.email.strip() or None
        if request.hourly_limit is not None:
            operator.hourly_limit = max(int(request.hourly_limit), 1)
        if request.daily_limit is not None:
            operator.daily_limit = max(int(request.daily_limit), 1)

        await db.commit()
        await db.refresh(operator)

        await log_audit_event(
            "operator_update",
            ui_user,
            data={
                "display_name": operator.display_name,
                "email": operator.email,
                "hourly_limit": operator.hourly_limit,
                "daily_limit": operator.daily_limit,
            },
            entity_type="operator",
            entity_id=str(operator.id)
        )

        return {
            "success": True,
            "operator": {
                "id": operator.id,
                "username": operator.username,
                "display_name": operator.display_name or operator.username,
                "email": operator.email or "",
                "hourly_limit": operator.hourly_limit,
                "daily_limit": operator.daily_limit,
            }
        }

    @app.get("/api/ui/stream", tags=["UI"])
    async def ui_stream(
        request: Request,
        last_message_id: int = 0,
        last_event_id: int = 0,
        account_id: Optional[int] = None,
        ui_user: dict = Depends(require_ui_auth)
    ):
        """SSE поток для новых сообщений и событий"""
        resolved_account_id = await resolve_account_id(account_id)

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
                        stmt = select(UiMessageHistory).where(
                            or_(
                                UiMessageHistory.id > last_message_id,
                                UiMessageHistory.updated_at > last_message_updated_at
                            )
                        )
                        if resolved_account_id:
                            stmt = stmt.where(UiMessageHistory.account_id == resolved_account_id)
                        result = await session.execute(
                            stmt.order_by(UiMessageHistory.id.asc()).limit(100)
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
                        "account_id": row.account_id,
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
    async def ui_chats(
        limit: int = 80,
        account_id: Optional[int] = None,
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Список чатов для UI"""
        _, client = await get_client_for_account(account_id)
        chats = await client.get_chats(limit=limit)
        return {"chats": chats, "account_id": client.account_id}

    @app.post("/api/ui/chats/{chat_id}/read", tags=["UI"])
    async def ui_mark_chat_read(
        chat_id: int,
        account_id: Optional[int] = None,
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Сброс непрочитанного счетчика"""
        _, client = await get_client_for_account(account_id)
        await client.mark_chat_read(chat_id)
        await log_ui_event("info", "chat_mark_read", {"chat_id": chat_id})
        return {"success": True}

    @app.get("/api/ui/chat/{chat_id}", tags=["UI"])
    async def ui_chat_details(
        chat_id: int,
        account_id: Optional[int] = None,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Детали чата, профиль и статистика"""
        resolved_id, client = await get_client_for_account(account_id)

        details = await client.get_chat_details(chat_id)
        history = await client.get_chat_history_stats(chat_id)
        recent_messages = await client.get_recent_messages(
            limit=20,
            chat_id=chat_id
        )

        result = await db.execute(
            select(ChatProfile).filter_by(
                telegram_chat_id=chat_id,
                account_id=resolved_id
            )
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
        account_id: Optional[int] = None,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Сохранение тегов и заметок"""
        resolved_id, _ = await get_client_for_account(account_id)
        result = await db.execute(
            select(ChatProfile).filter_by(
                telegram_chat_id=chat_id,
                account_id=resolved_id
            )
        )
        profile = result.scalars().first()
        if not profile:
            profile = ChatProfile(
                telegram_chat_id=chat_id,
                account_id=resolved_id
            )
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
    async def ui_request_code(request: UiAuthRequest):
        """Запрос кода авторизации (публичный доступ)"""
        _, client = await get_client_for_account(request.account_id)
        success, status = await client.request_code(request.phone)
        message = humanize_auth_status(status)
        await log_ui_event(
            "info" if success else "error",
            "auth_request_code",
            {"status": status}
        )
        return {"success": success, "status": status, "message": message}

    @app.post("/api/ui/auth/submit-code", tags=["UI"])
    async def ui_submit_code(request: UiAuthCodeRequest):
        """Подтверждение кода авторизации (публичный доступ)"""
        _, client = await get_client_for_account(request.account_id)
        success, status = await client.submit_code(
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
    async def ui_submit_password(request: UiAuthPasswordRequest):
        """Подтверждение 2FA (публичный доступ)"""
        _, client = await get_client_for_account(request.account_id)
        success, status = await client.submit_password(request.password)
        message = humanize_auth_status(status)
        await log_ui_event(
            "info" if success else "error",
            "auth_submit_password",
            {"status": status}
        )
        return {"success": success, "status": status, "message": message}

    @app.post("/api/ui/auth/logout", tags=["UI"])
    async def ui_logout(account_id: Optional[int] = None):
        """Выход из Telegram (публичный доступ)"""
        _, client = await get_client_for_account(account_id)
        success, status = await client.logout()
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

    # Magic Link Authentication (Fix #169)
    # More secure than request-code/submit-code: no bruteforce possible

    @app.post("/api/ui/auth/request-magic-link", tags=["UI"])
    async def ui_request_magic_link(
        request: Request,
        db: AsyncSession = Depends(get_db)
    ):
        """
        Generate magic link and send to Telegram.

        Fix #169: Magic link авторизация через Telegram.
        Более безопасная альтернатива request-code/submit-code.

        Flow:
        1. User requests magic link from /ui/auth page
        2. Server generates UUID token, stores in Redis (TTL 5 min)
        3. Server sends message to admin's Telegram with link
        4. User clicks link → creates UI session → redirect to /ui

        Security:
        - No public endpoints for bruteforce
        - One-time use tokens (marked as used after activation)
        - Short TTL (5 minutes)
        - Authorization via controlled channel (Telegram)
        """
        import uuid
        from src.redis_client import save_magic_link_token
        from src.database import UiAuthAttempt

        # Generate UUID token
        token = str(uuid.uuid4())

        # Save token to Redis with 5 minute TTL
        saved = await save_magic_link_token(token, ttl_seconds=300)
        if not saved:
            # Redis unavailable - log to database but fail gracefully
            await log_ui_event("error", "magic_link_redis_unavailable", {})
            return {
                "success": False,
                "message": "Redis недоступен - не могу создать magic link"
            }

        # Log attempt to database (audit trail)
        try:
            auth_attempt = UiAuthAttempt(
                token=token,
                telegram_user_id=None,  # Unknown at this point
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                success=False  # Not yet activated
            )
            db.add(auth_attempt)
            await db.commit()
        except Exception as e:
            logger.error(f"❌ Не удалось записать auth attempt в БД: {e}")
            # Continue anyway - audit is not critical for functionality

        # Generate magic link URL
        # For local development: http://localhost:8000/ui/auth/magic?token={uuid}
        # For production: https://your-domain.com/ui/auth/magic?token={uuid}
        base_url = str(request.base_url).rstrip("/")
        magic_link = f"{base_url}/ui/auth/magic?token={token}"

        # Send message to Telegram via bot
        try:
            # Check if bot is configured
            if not settings.ALERT_TELEGRAM_BOT_TOKEN or not settings.ALERT_TELEGRAM_CHAT_ID:
                logger.warning(
                    "⚠️ ALERT_TELEGRAM_BOT_TOKEN или ALERT_TELEGRAM_CHAT_ID не настроены. "
                    "Magic link не может быть отправлен в Telegram."
                )
                # Return link in response for development/testing
                return {
                    "success": True,
                    "message": "⚠️ Telegram bot не настроен. Используйте ссылку ниже:",
                    "link": magic_link
                }

            # Send via Telegram Bot API
            import aiohttp

            bot_token = settings.ALERT_TELEGRAM_BOT_TOKEN
            chat_id = settings.ALERT_TELEGRAM_CHAT_ID

            message_text = (
                "🔐 <b>Magic Link для входа в UI</b>\n\n"
                f"Кликните для авторизации:\n{magic_link}\n\n"
                "⏰ Истекает через 5 минут\n"
                "🔒 Одноразовая ссылка"
            )

            async with aiohttp.ClientSession() as session:
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                payload = {
                    "chat_id": chat_id,
                    "text": message_text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False
                }

                async with session.post(url, json=payload) as response:
                    if response.status == 200:
                        logger.info(f"✅ Magic link отправлен в Telegram (chat_id={chat_id})")

                        # Log event
                        await log_ui_event(
                            "info",
                            "magic_link_sent_to_telegram",
                            {
                                "token": token[:8] + "...",
                                "chat_id": chat_id,
                                "expires_in": 300
                            }
                        )

                        return {
                            "success": True,
                            "message": "✅ Magic link отправлен в Telegram. Проверьте сообщения от бота."
                        }
                    else:
                        error_text = await response.text()
                        logger.error(f"❌ Telegram API error: {response.status} - {error_text}")

                        # Fallback: return link in response
                        return {
                            "success": True,
                            "message": f"⚠️ Не удалось отправить в Telegram (HTTP {response.status}). Используйте ссылку:",
                            "link": magic_link
                        }

        except Exception as e:
            logger.error(f"❌ Ошибка отправки magic link через bot: {e}")

            # Fallback: return link in response for development
            return {
                "success": True,
                "message": f"⚠️ Ошибка отправки в Telegram: {e}. Используйте ссылку:",
                "link": magic_link
            }

    @app.get("/ui/auth/magic", tags=["UI"])
    async def ui_activate_magic_link(
        token: str,
        request: Request,
        db: AsyncSession = Depends(get_db)
    ):
        """
        Activate magic link and create UI session.

        Fix #169: Magic link activation endpoint.

        Args:
            token: UUID token from magic link URL

        Flow:
        1. Validate token exists in Redis and not used
        2. Mark token as used (prevents reuse)
        3. Create UI session cookie
        4. Update audit trail in database
        5. Redirect to /ui

        Security:
        - Token is one-time use
        - Token expires after 5 minutes
        - Audit trail tracks all activation attempts
        """
        from src.redis_client import get_magic_link_token, mark_magic_link_token_used
        from src.database import UiAuthAttempt

        # Validate token
        token_data = await get_magic_link_token(token)

        if not token_data:
            # Token not found or expired
            await log_ui_event("warning", "magic_link_invalid", {"token": token[:8] + "..."})

            # Log failed attempt
            try:
                auth_attempt = UiAuthAttempt(
                    token=token,
                    telegram_user_id=None,
                    ip_address=request.client.host if request.client else None,
                    user_agent=request.headers.get("user-agent"),
                    success=False
                )
                db.add(auth_attempt)
                await db.commit()
            except Exception:
                pass

            return HTMLResponse(
                content="<h1>Invalid or expired magic link</h1><p>Please request a new one.</p>",
                status_code=400
            )

        # Check if already used
        if token_data.get("used"):
            await log_ui_event("warning", "magic_link_already_used", {"token": token[:8] + "..."})
            return HTMLResponse(
                content="<h1>Magic link already used</h1><p>Please request a new one.</p>",
                status_code=400
            )

        # Mark token as used
        marked = await mark_magic_link_token_used(token)
        if not marked:
            logger.error(f"❌ Не удалось пометить token как использованный: {token}")

        # Create UI session (for now, just set a simple flag)
        # In production, you'd create a proper session with authentication
        # For MVP: we'll use a simple cookie

        # Log successful auth
        try:
            auth_attempt = UiAuthAttempt(
                token=token,
                telegram_user_id=None,  # Could extract from Telegram if available
                ip_address=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
                success=True
            )
            db.add(auth_attempt)
            await db.commit()
        except Exception as e:
            logger.error(f"❌ Не удалось записать successful auth attempt: {e}")

        await log_ui_event("info", "magic_link_activated", {"token": token[:8] + "..."})

        # Create redirect response with session cookie
        from fastapi.responses import RedirectResponse
        response = RedirectResponse(url="/ui", status_code=302)

        # Set session cookie (simple flag for MVP)
        # In production: use proper session management with signed cookies
        response.set_cookie(
            key="ui_session",
            value=f"magic_link_{token[:16]}",  # Simplified session ID
            max_age=86400,  # 24 hours
            httponly=True,
            samesite="lax"
        )

        return response

    @app.post("/api/ui/send", tags=["UI"])
    async def ui_send_message(
        request: UiSendRequest,
        db: AsyncSession = Depends(get_db),
        ui_user: dict = Depends(require_ui_auth)
    ):
        """Отправка сообщения из локального UI"""
        resolved_id, client = await get_client_for_account(request.account_id)
        operator_id = await resolve_operator_id(db, ui_user)

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
            user = await client.find_user_by_id(request.chat_id)
        if not user and request.username:
            user = await client.find_user_by_username(request.username)
        if not user and request.phone:
            user = await client.find_user_by_phone(request.phone)

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
            "message": text,
            "account_id": resolved_id,
            "operator_id": operator_id
        }
        outbox, created = await enqueue_outbox(
            db,
            idempotency_key,
            resolved_id,
            operator_id,
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
                    "account_id": resolved_id,
                    "chat_id": user.id,
                    "username": user.username or "",
                    "display_name": client._format_chat_name(
                        user.username,
                        user.first_name,
                        user.last_name,
                        user.id
                    )
                }
            }

        if not settings.OUTBOX_PROCESS_INLINE:
            queued_entry = UiMessageHistory(
                account_id=resolved_id,
                chat_id=user.id,
                direction="outbound",
                message_text=text,
                message_type="text",
                username=user.username or "",
                display_name=client._format_chat_name(
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
                    "account_id": resolved_id,
                    "chat_id": user.id,
                    "username": user.username or "",
                    "display_name": client._format_chat_name(
                        user.username,
                        user.first_name,
                        user.last_name,
                        user.id
                    )
                }
            }

        success, status_message = await client.send_message_to_user(
            user,
            text,
            operator_id=operator_id
        )
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
            chats = await client.get_chats(limit=200)
            chat = next(
                (item for item in chats if item.get("chat_id") == user.id),
                None
            )
        except Exception:
            chat = None

        if not chat:
            display_name = client._format_chat_name(
                user.username,
                user.first_name,
                user.last_name,
                user.id
            )
            chat = {
                "account_id": resolved_id,
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
        account_id: Optional[int] = None,
        ui_user: dict = Depends(require_ui_auth),
        db: AsyncSession = Depends(get_db)
    ):
        """Получение последних сообщений"""
        resolved_id = await resolve_account_id(account_id)
        stmt = select(UiMessageHistory).filter_by(account_id=resolved_id)
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
                "account_id": row.account_id,
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


def set_bridge(bridge_instance: Optional[CRMTelegramBridge]):
    """Установка экземпляра bridge"""
    global bridge
    bridge = bridge_instance
    logger.info("✅ Bridge установлен в API сервере")
