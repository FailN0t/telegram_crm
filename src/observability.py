"""
Optional observability hooks: error tracking, metrics helpers.
"""

from src.config import settings
from src.logger import logger


def init_error_tracking() -> bool:
    if not settings.ERROR_TRACKING_DSN:
        return False
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.ERROR_TRACKING_DSN,
            environment=settings.ERROR_TRACKING_ENV,
            traces_sample_rate=settings.ERROR_TRACKING_SAMPLE_RATE,
            send_default_pii=False
        )
        logger.info("✅ Error tracking initialized")
        return True
    except Exception as exc:
        logger.warning(f"⚠️ Error tracking init failed: {exc}")
        return False
