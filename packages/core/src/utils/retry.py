"""
重试机制 - 从 retry.ts 迁移
提供带指数退避的重试功能
"""

import asyncio
import logging
from collections.abc import Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def retry_with_backoff(
    func: Callable[[], T | asyncio.Future[T]],
    max_retries: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    should_retry: Callable[[Exception], bool] | None = None,
    on_persistent_429: Callable[[str | None], asyncio.Future[str | None]]
    | None = None,
    auth_type: str | None = None,
) -> T:
    """
    使用指数退避策略重试函数调用

    Args:
        func: 要重试的函数
        max_retries: 最大重试次数
        initial_delay: 初始延迟（秒）
        max_delay: 最大延迟（秒）
        exponential_base: 指数基数
        should_retry: 判断是否应该重试的函数
        on_persistent_429: 处理持续 429 错误的回调
        auth_type: 认证类型

    Returns:
        函数执行结果

    Raises:
        最后一次重试的异常

    """
    delay = initial_delay
    last_error = None
    persistent_429_count = 0

    for attempt in range(max_retries + 1):
        try:
            result = func()
            if asyncio.iscoroutine(result):
                return await result
            return result

        except Exception as e:
            last_error = e

            # 检查是否应该重试
            if should_retry and not should_retry(e):
                raise

            # 检查是否是 429 错误
            error_message = str(e)
            if "429" in error_message:
                persistent_429_count += 1

                # 如果连续遇到多次 429 错误，尝试降级
                if persistent_429_count >= 2 and on_persistent_429:
                    fallback_model = await on_persistent_429(auth_type)
                    if fallback_model:
                        logger.info(f"Falling back to model: {fallback_model}")
                        # 重置计数并继续
                        persistent_429_count = 0
                        continue
            else:
                persistent_429_count = 0

            # 如果是最后一次尝试，直接抛出异常
            if attempt == max_retries:
                raise

            # 计算延迟时间
            delay = min(delay * exponential_base, max_delay)

            logger.warning(
                f"Retry attempt {attempt + 1}/{max_retries} after {delay:.1f}s delay. "
                f"Error: {error_message}"
            )

            # 等待后重试
            await asyncio.sleep(delay)

    # 如果所有重试都失败了
    if last_error:
        raise last_error

    raise RuntimeError("Unexpected error in retry logic")
