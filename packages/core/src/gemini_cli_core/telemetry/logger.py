"""
遥测日志记录器 - 从 logger.ts 迁移
提供 API 调用的日志记录功能
"""

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ApiEvent:
    """API 事件基类"""

    def __init__(self, model: str):
        self.model = model
        self.timestamp = time.time()


class ApiRequestEvent(ApiEvent):
    """API 请求事件"""

    def __init__(self, model: str, request_text: str):
        super().__init__(model)
        self.request_text = request_text


class ApiResponseEvent(ApiEvent):
    """API 响应事件"""

    def __init__(
        self,
        model: str,
        duration_ms: int,
        usage_metadata: dict[str, Any] | None = None,
        response_text: str | None = None,
    ):
        super().__init__(model)
        self.duration_ms = duration_ms
        self.usage_metadata = usage_metadata
        self.response_text = response_text


class ApiErrorEvent(ApiEvent):
    """API 错误事件"""

    def __init__(
        self,
        model: str,
        error_message: str,
        duration_ms: int,
        error_type: str = "unknown",
    ):
        super().__init__(model)
        self.error_message = error_message
        self.duration_ms = duration_ms
        self.error_type = error_type


async def log_api_request(
    config: Any,
    model: str,
    request_text: str,
) -> None:
    """
    记录 API 请求

    Args:
        config: 配置对象
        model: 模型名称
        request_text: 请求文本

    """
    event = ApiRequestEvent(model, request_text)

    logger.info(
        f"API Request to {model}",
        extra={
            "event_type": "api_request",
            "model": model,
            "request_length": len(request_text),
            "timestamp": event.timestamp,
        },
    )

    # TODO: 集成到遥测系统
    if hasattr(config, "telemetry") and config.telemetry:
        # 发送到遥测系统
        pass


async def log_api_response(
    config: Any,
    model: str,
    duration_ms: int,
    usage_metadata: dict[str, Any] | None = None,
    response_text: str | None = None,
) -> None:
    """
    记录 API 响应

    Args:
        config: 配置对象
        model: 模型名称
        duration_ms: 响应时间（毫秒）
        usage_metadata: 使用元数据
        response_text: 响应文本

    """
    event = ApiResponseEvent(model, duration_ms, usage_metadata, response_text)

    logger.info(
        f"API Response from {model} in {duration_ms}ms",
        extra={
            "event_type": "api_response",
            "model": model,
            "duration_ms": duration_ms,
            "usage_metadata": usage_metadata,
            "response_length": len(response_text) if response_text else 0,
            "timestamp": event.timestamp,
        },
    )

    # TODO: 集成到遥测系统
    if hasattr(config, "telemetry") and config.telemetry:
        # 发送到遥测系统
        pass


async def log_api_error(
    config: Any,
    model: str,
    duration_ms: int,
    error: Exception,
) -> None:
    """
    记录 API 错误

    Args:
        config: 配置对象
        model: 模型名称
        duration_ms: 响应时间（毫秒）
        error: 错误对象

    """
    error_message = str(error)
    error_type = type(error).__name__

    event = ApiErrorEvent(model, error_message, duration_ms, error_type)

    logger.error(
        f"API Error from {model} after {duration_ms}ms: {error_message}",
        extra={
            "event_type": "api_error",
            "model": model,
            "duration_ms": duration_ms,
            "error_type": error_type,
            "error_message": error_message,
            "timestamp": event.timestamp,
        },
        exc_info=True,
    )

    # TODO: 集成到遥测系统
    if hasattr(config, "telemetry") and config.telemetry:
        # 发送到遥测系统
        pass
