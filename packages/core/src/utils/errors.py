"""
错误处理工具函数 - 从 errors.ts 和 errorReporting.ts 迁移
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_error_message(error: Exception | Any) -> str:
    """
    从错误对象中提取错误消息

    Args:
        error: 错误对象

    Returns:
        错误消息字符串

    """
    if isinstance(error, Exception):
        return str(error)
    return str(error)


async def report_error(
    error: Exception | Any,
    context: str,
    additional_data: Any = None,
    error_type: str = "unknown",
) -> None:
    """
    报告错误到日志系统

    Args:
        error: 错误对象
        context: 错误发生的上下文描述
        additional_data: 额外的调试数据
        error_type: 错误类型标识

    """
    error_message = get_error_message(error)

    logger.error(
        f"{context}: {error_message}",
        extra={
            "error_type": error_type,
            "additional_data": additional_data,
        },
        exc_info=isinstance(error, Exception),
    )
