"""
Admin-configurable settings stored in DB.
"""

from typing import Any, Dict, Optional, Tuple

from sqlalchemy import select

from src.config import settings
from src.database import SessionLocal, AppSetting
from src.logger import logger


ALLOWED_SETTINGS: Dict[str, Dict[str, Any]] = {
    "MAX_MESSAGES_PER_HOUR": {
        "type": int,
        "min": 1,
        "max": 100000,
        "description": "Максимум сообщений в час (глобально).",
        "requires_restart": False,
    },
    "MAX_NEW_CHATS_PER_DAY": {
        "type": int,
        "min": 1,
        "max": 100000,
        "description": "Максимум новых чатов в день (глобально).",
        "requires_restart": False,
    },
    "MIN_DELAY_BETWEEN_MESSAGES": {
        "type": int,
        "min": 0,
        "max": 3600,
        "description": "Минимальная задержка между сообщениями (сек).",
        "requires_restart": False,
    },
    "OUTBOX_PROCESS_INLINE": {
        "type": bool,
        "description": "Отправлять сообщения inline (без отдельного worker).",
        "requires_restart": True,
    },
    "OUTBOX_MAX_ATTEMPTS": {
        "type": int,
        "min": 1,
        "max": 100,
        "description": "Максимум попыток отправки в outbox.",
        "requires_restart": True,
    },
    "OUTBOX_RETRY_BASE_SECONDS": {
        "type": int,
        "min": 1,
        "max": 3600,
        "description": "База для экспоненциального backoff (сек).",
        "requires_restart": True,
    },
    "OUTBOX_POLL_INTERVAL": {
        "type": int,
        "min": 1,
        "max": 60,
        "description": "Пауза worker между проверками outbox (сек).",
        "requires_restart": True,
    },
    "API_RATE_LIMIT_PER_MINUTE": {
        "type": int,
        "min": 0,
        "max": 100000,
        "description": "Лимит запросов к /api/* в минуту (0 = отключить).",
        "requires_restart": False,
    },
    "UI_MESSAGE_RETENTION_DAYS": {
        "type": int,
        "min": 0,
        "max": 3650,
        "description": "Срок хранения ui_message_history (дни, 0 = отключить).",
        "requires_restart": False,
    },
    "UI_EVENT_RETENTION_DAYS": {
        "type": int,
        "min": 0,
        "max": 3650,
        "description": "Срок хранения ui_event_log (дни, 0 = отключить).",
        "requires_restart": False,
    },
    "AUDIT_LOG_RETENTION_DAYS": {
        "type": int,
        "min": 0,
        "max": 3650,
        "description": "Срок хранения audit_log (дни, 0 = отключить).",
        "requires_restart": False,
    },
    "MESSAGE_INBOX_RETENTION_DAYS": {
        "type": int,
        "min": 0,
        "max": 3650,
        "description": "Срок хранения message_inbox (дни, 0 = отключить).",
        "requires_restart": False,
    },
    "AMOCRM_ACCESS_TOKEN": {
        "type": str,
        "description": "AmoCRM access token (OAuth).",
        "requires_restart": False,
    },
    "AMOCRM_REFRESH_TOKEN": {
        "type": str,
        "description": "AmoCRM refresh token (OAuth).",
        "requires_restart": False,
    },
    "AMOCRM_TOKEN_EXPIRES_AT": {
        "type": str,
        "description": "AmoCRM token expiry timestamp (ISO8601).",
        "requires_restart": False,
    },
}

BASELINE_VALUES = {key: getattr(settings, key) for key in ALLOWED_SETTINGS.keys()}


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in ("1", "true", "yes", "on"):
            return True
        if lowered in ("0", "false", "no", "off"):
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    raise ValueError("invalid boolean value")


def normalize_setting_value(key: str, value: Any) -> Tuple[Optional[Any], Optional[str]]:
    rule = ALLOWED_SETTINGS.get(key)
    if not rule:
        return None, "unsupported_setting"

    if value in ("", "null"):
        value = None

    if value is None:
        return None, None

    expected_type = rule["type"]
    try:
        if expected_type is bool:
            coerced = _coerce_bool(value)
        elif expected_type is int:
            if isinstance(value, bool):
                raise ValueError("bool is not valid int")
            if isinstance(value, (int, float, str)):
                coerced = int(value)
            else:
                raise ValueError("invalid int value")
        elif expected_type is str:
            coerced = str(value).strip()
        else:
            return None, "unsupported_type"
    except ValueError:
        return None, "invalid_value"

    minimum = rule.get("min")
    maximum = rule.get("max")
    if minimum is not None and coerced < minimum:
        return None, "below_min"
    if maximum is not None and coerced > maximum:
        return None, "above_max"

    return coerced, None


def apply_setting_value(key: str, value: Optional[Any]) -> None:
    if key not in ALLOWED_SETTINGS:
        return
    if value is None:
        setattr(settings, key, BASELINE_VALUES[key])
    else:
        setattr(settings, key, value)


async def load_settings_overrides() -> Dict[str, Any]:
    async with SessionLocal() as session:
        result = await session.execute(select(AppSetting))
        items = result.scalars().all()
    return {item.key: item.value for item in items}


async def refresh_settings_from_db() -> Dict[str, Any]:
    overrides = await load_settings_overrides()
    for key, value in overrides.items():
        apply_setting_value(key, value)
    for key in ALLOWED_SETTINGS.keys():
        if key not in overrides:
            apply_setting_value(key, None)
    return overrides


async def update_settings_overrides(
    values: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, str]]:
    normalized: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    for key, raw_value in values.items():
        if key not in ALLOWED_SETTINGS:
            errors[key] = "unsupported_setting"
            continue
        coerced, error = normalize_setting_value(key, raw_value)
        if error:
            errors[key] = error
            continue
        normalized[key] = coerced

    if errors:
        return {}, errors

    async with SessionLocal() as session:
        for key, value in normalized.items():
            record = await session.get(AppSetting, key)
            if value is None:
                if record:
                    await session.delete(record)
            else:
                if record:
                    record.value = value
                else:
                    session.add(AppSetting(key=key, value=value))
        await session.commit()

    for key, value in normalized.items():
        apply_setting_value(key, value)

    logger.info("✅ Admin settings updated: %s", ", ".join(normalized.keys()))
    return normalized, {}


def get_settings_payload(overrides: Dict[str, Any]) -> Dict[str, Any]:
    items = []
    for key, rule in ALLOWED_SETTINGS.items():
        default_value = BASELINE_VALUES.get(key)
        override_value = overrides.get(key)
        current_value = override_value if key in overrides else default_value
        items.append(
            {
                "key": key,
                "type": rule["type"].__name__,
                "description": rule.get("description", ""),
                "requires_restart": bool(rule.get("requires_restart")),
                "default_value": default_value,
                "override_value": override_value,
                "current_value": current_value,
            }
        )
    return {"settings": items}
