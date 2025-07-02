"""
重试机制 - 从 retry.ts 迁移
提供带指数退避的重试功能
"""

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, TypeVar

from .errors import report_error, to_friendly_error

logger = logging.getLogger(__name__)

T = TypeVar("T")


def default_should_retry(error: Exception) -> bool:
    """Default predicate to check if a retry should be attempted."""
    from .errors import BadRequestError, ForbiddenError, UnauthorizedError

    # Do not retry on user errors or auth errors
    if isinstance(error, (BadRequestError, UnauthorizedError, ForbiddenError)):
        return False
    # A simple check for common transient errors, can be made more robust
    if "429" in str(error) or "50" in str(error):
        return True
    return False


def retry_with_backoff(
    max_attempts: int = 5,
    initial_delay_ms: int = 5000,
    max_delay_ms: int = 30000,
    should_retry: Callable[[Exception], bool] = default_should_retry,
    on_persistent_429: Callable[[str], Awaitable[str | None]] | None = None,
    auth_type: str | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """
    A decorator to retry an async function with exponential backoff and jitter.
    """

    def decorator(
        fn: Callable[..., Awaitable[T]],
    ) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            attempt = 0
            current_delay = initial_delay_ms
            consecutive_429_count = 0
            last_error: Exception | None = None

            while attempt < max_attempts:
                attempt += 1
                try:
                    return await fn(*args, **kwargs)
                except Exception as e:
                    friendly_error = to_friendly_error(e)
                    last_error = friendly_error

                    if "429" in str(friendly_error):
                        consecutive_429_count += 1
                    else:
                        consecutive_429_count = 0

                    if (
                        consecutive_429_count >= 2
                        and on_persistent_429
                        and auth_type
                    ):
                        try:
                            fallback_model = await on_persistent_429(auth_type)
                            if fallback_model:
                                logger.info(
                                    f"Switched to fallback model: {fallback_model}"
                                )
                                attempt = 0
                                consecutive_429_count = 0
                                current_delay = initial_delay_ms
                                continue
                        except Exception as fallback_error:
                            logger.warning(
                                f"Fallback handler failed: {fallback_error}"
                            )

                    if attempt >= max_attempts or not should_retry(
                        friendly_error
                    ):
                        break

                    jitter = current_delay * 0.3 * (random.random() * 2 - 1)
                    delay_with_jitter = max(0, current_delay + jitter)

                    logger.warning(
                        f"Attempt {attempt} failed for {fn.__name__}. Retrying in {delay_with_jitter / 1000:.2f}s...",
                        exc_info=True,
                    )

                    await asyncio.sleep(delay_with_jitter / 1000)
                    current_delay = min(max_delay_ms, current_delay * 2)

            await report_error(
                last_error,
                f"Function {fn.__name__} failed after {max_attempts} attempts.",
            )
            raise last_error from None

        return wrapper

    return decorator
