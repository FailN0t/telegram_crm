"""
Retry utilities for external API calls.

Provides retry logic with exponential backoff for:
- 429 Too Many Requests
- 5xx Server Errors
- Network timeouts and connection errors
- Telegram FloodWait errors
"""

import asyncio
import functools
from typing import TypeVar, Callable, Any, Optional, Tuple, Type, TYPE_CHECKING
from aiohttp import ClientResponseError, ClientError, ServerTimeoutError
from src.logger import logger

if TYPE_CHECKING:
    from telethon.errors import FloodWaitError, RPCError

T = TypeVar('T')


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retry_on_status: Tuple[int, ...] = (429, 500, 502, 503, 504),
        retry_on_exceptions: Tuple[Type[Exception], ...] = (
            ServerTimeoutError,
            ClientError,
        ),
    ):
        """
        Initialize retry configuration.

        Args:
            max_attempts: Maximum number of retry attempts (including first try)
            base_delay: Initial delay between retries in seconds
            max_delay: Maximum delay between retries in seconds
            exponential_base: Base for exponential backoff calculation
            retry_on_status: HTTP status codes that trigger retry
            retry_on_exceptions: Exception types that trigger retry
        """
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retry_on_status = retry_on_status
        self.retry_on_exceptions = retry_on_exceptions

    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for given attempt using exponential backoff.

        Args:
            attempt: Current attempt number (0-based)

        Returns:
            Delay in seconds
        """
        delay = self.base_delay * (self.exponential_base ** attempt)
        return min(delay, self.max_delay)


def retry_async(
    config: Optional[RetryConfig] = None,
    log_prefix: str = "API call",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator for async functions to add retry logic with exponential backoff.

    Usage:
        @retry_async()
        async def make_api_call():
            ...

        @retry_async(RetryConfig(max_attempts=5))
        async def critical_api_call():
            ...

    Args:
        config: Retry configuration (uses defaults if None)
        log_prefix: Prefix for log messages

    Returns:
        Decorated function with retry logic
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None

            for attempt in range(config.max_attempts):
                try:
                    return await func(*args, **kwargs)

                except ClientResponseError as e:
                    # Check if status code should trigger retry
                    if e.status not in config.retry_on_status:
                        # Non-retryable status code - re-raise immediately
                        logger.error(
                            f"❌ {log_prefix} failed with non-retryable status {e.status}: {e}"
                        )
                        raise

                    last_exception = e

                    # Last attempt - don't retry
                    if attempt == config.max_attempts - 1:
                        logger.error(
                            f"❌ {log_prefix} failed after {config.max_attempts} attempts "
                            f"with status {e.status}: {e}"
                        )
                        raise

                    # Calculate delay with special handling for 429
                    if e.status == 429:
                        # Try to extract Retry-After header
                        retry_after = e.headers.get('Retry-After')
                        if retry_after:
                            try:
                                delay = float(retry_after)
                            except (ValueError, TypeError):
                                delay = config.calculate_delay(attempt)
                        else:
                            delay = config.calculate_delay(attempt)
                        logger.warning(
                            f"⚠️ {log_prefix} rate limited (429), "
                            f"retrying in {delay:.1f}s (attempt {attempt + 1}/{config.max_attempts})"
                        )
                    else:
                        delay = config.calculate_delay(attempt)
                        logger.warning(
                            f"⚠️ {log_prefix} failed with status {e.status}, "
                            f"retrying in {delay:.1f}s (attempt {attempt + 1}/{config.max_attempts})"
                        )

                    await asyncio.sleep(delay)

                except config.retry_on_exceptions as e:
                    last_exception = e

                    # Last attempt - don't retry
                    if attempt == config.max_attempts - 1:
                        logger.error(
                            f"❌ {log_prefix} failed after {config.max_attempts} attempts "
                            f"with {type(e).__name__}: {e}"
                        )
                        raise

                    delay = config.calculate_delay(attempt)
                    logger.warning(
                        f"⚠️ {log_prefix} failed with {type(e).__name__}, "
                        f"retrying in {delay:.1f}s (attempt {attempt + 1}/{config.max_attempts})"
                    )
                    await asyncio.sleep(delay)

                except Exception as e:
                    # Non-retryable exception - re-raise immediately
                    logger.error(
                        f"❌ {log_prefix} failed with non-retryable error {type(e).__name__}: {e}"
                    )
                    raise

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError(f"{log_prefix} failed after {config.max_attempts} attempts")

        return wrapper

    return decorator


# Predefined configurations for common scenarios

CRM_API_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=30.0,
    exponential_base=2.0,
    retry_on_status=(429, 500, 502, 503, 504),
)

CRITICAL_API_RETRY = RetryConfig(
    max_attempts=5,
    base_delay=2.0,
    max_delay=60.0,
    exponential_base=2.0,
    retry_on_status=(429, 500, 502, 503, 504),
)

TELEGRAM_RETRY = RetryConfig(
    max_attempts=3,
    base_delay=1.0,
    max_delay=300.0,  # FloodWait can be up to 5 minutes
    exponential_base=2.0,
    retry_on_exceptions=(
        ServerTimeoutError,
        ClientError,
    ),
)


def retry_telegram(
    config: Optional[RetryConfig] = None,
    log_prefix: str = "Telegram call",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """
    Decorator for Telegram MTProto calls with FloodWait handling.

    Handles:
    - FloodWaitError: Respects the exact wait time from Telegram
    - RPCError: Generic Telegram errors (non-retryable)
    - Network errors: ServerTimeoutError, ClientError

    Usage:
        @retry_telegram()
        async def send_telegram_message():
            ...

        @retry_telegram(TELEGRAM_RETRY, "Send message")
        async def send_with_custom_config():
            ...

    Args:
        config: Retry configuration (uses TELEGRAM_RETRY if None)
        log_prefix: Prefix for log messages

    Returns:
        Decorated function with Telegram-specific retry logic
    """
    if config is None:
        config = TELEGRAM_RETRY

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            last_exception = None

            for attempt in range(config.max_attempts):
                try:
                    return await func(*args, **kwargs)

                except Exception as e:
                    # Import at runtime to avoid circular imports
                    from telethon.errors import FloodWaitError, RPCError

                    # FloodWaitError: Telegram rate limiting
                    if isinstance(e, FloodWaitError):
                        last_exception = e

                        # Last attempt - don't retry
                        if attempt == config.max_attempts - 1:
                            logger.error(
                                f"❌ {log_prefix} failed after {config.max_attempts} attempts "
                                f"with FloodWait ({e.seconds}s): {e}"
                            )
                            raise

                        # Use exact wait time from Telegram, but cap at max_delay
                        delay = min(float(e.seconds), config.max_delay)
                        logger.warning(
                            f"⚠️ {log_prefix} FloodWait ({e.seconds}s), "
                            f"retrying in {delay:.1f}s (attempt {attempt + 1}/{config.max_attempts})"
                        )
                        await asyncio.sleep(delay)
                        continue

                    # RPCError: Generic Telegram errors (most are non-retryable)
                    if isinstance(e, RPCError):
                        logger.error(
                            f"❌ {log_prefix} failed with non-retryable Telegram error "
                            f"{type(e).__name__}: {e}"
                        )
                        raise

                    # Network errors: retryable
                    if isinstance(e, config.retry_on_exceptions):
                        last_exception = e

                        # Last attempt - don't retry
                        if attempt == config.max_attempts - 1:
                            logger.error(
                                f"❌ {log_prefix} failed after {config.max_attempts} attempts "
                                f"with {type(e).__name__}: {e}"
                            )
                            raise

                        delay = config.calculate_delay(attempt)
                        logger.warning(
                            f"⚠️ {log_prefix} failed with {type(e).__name__}, "
                            f"retrying in {delay:.1f}s (attempt {attempt + 1}/{config.max_attempts})"
                        )
                        await asyncio.sleep(delay)
                        continue

                    # Unknown exception - re-raise immediately
                    logger.error(
                        f"❌ {log_prefix} failed with non-retryable error {type(e).__name__}: {e}"
                    )
                    raise

            # Should never reach here, but just in case
            if last_exception:
                raise last_exception
            raise RuntimeError(f"{log_prefix} failed after {config.max_attempts} attempts")

        return wrapper

    return decorator
