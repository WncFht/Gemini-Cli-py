import logging
import re
from typing import Any

import httpx

from gemini_cli_core.config.models import (
    DEFAULT_GEMINI_FLASH_MODEL,
    DEFAULT_GEMINI_MODEL,
)

logger = logging.getLogger(__name__)

# 支持的模型列表
SUPPORTED_MODELS = [
    "gemini-2.0-flash-exp",
    "gemini-2.0-flash",
    "gemini-1.5-pro",
    "gemini-1.5-pro-latest",
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.0-pro",
    "gemini-1.0-pro-latest",
]

# 模型别名映射
MODEL_ALIASES = {
    "flash": "gemini-2.0-flash-exp",
    "pro": "gemini-1.5-pro-latest",
    "2.0": "gemini-2.0-flash-exp",
    "1.5": "gemini-1.5-flash-latest",
    "1.0": "gemini-1.0-pro-latest",
}


async def get_effective_model(
    api_key: str, current_configured_model: str
) -> str:
    """
    Checks if the default "pro" model is rate-limited and returns a fallback "flash"
    model if necessary.
    """
    if current_configured_model != DEFAULT_GEMINI_MODEL:
        # Only check if the user is trying to use the specific pro model
        # we want to fallback from.
        return current_configured_model

    model_to_test = DEFAULT_GEMINI_MODEL
    fallback_model = DEFAULT_GEMINI_FLASH_MODEL
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model_to_test}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": "test"}]}],
        "generationConfig": {
            "maxOutputTokens": 1,
            "temperature": 0,
            "topK": 1,
            "thinkingConfig": {"thinkingBudget": 0, "includeThoughts": False},
        },
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(endpoint, json=body, timeout=2.0)

        if response.status_code == 429:
            logger.info(
                f"Your configured model ({model_to_test}) was temporarily unavailable. "
                f"Switched to {fallback_model} for this session."
            )
            return fallback_model

        # For any other case, stick to the original model.
        return current_configured_model
    except (TimeoutError, httpx.RequestError) as e:
        logger.debug(f"Error checking model endpoint, sticking to default: {e}")
        # On timeout or any other fetch error, stick to the original model.
        return current_configured_model


def is_model_supported(model: str) -> bool:
    """
    检查模型是否受支持

    Args:
        model: 模型名称

    Returns:
        是否支持该模型

    """
    # 检查别名
    if model.lower() in MODEL_ALIASES:
        return True

    # 检查完整名称
    return model in SUPPORTED_MODELS


def get_model_info(model: str) -> dict[str, Any]:
    """
    获取模型信息

    Args:
        model: 模型名称

    Returns:
        模型信息字典

    """
    # 标准化模型名称
    effective_model = MODEL_ALIASES.get(model.lower(), model)

    # 解析模型信息
    info = {
        "name": effective_model,
        "version": None,
        "variant": None,
        "is_experimental": False,
    }

    # 使用正则表达式解析模型名称
    pattern = r"gemini-(\d+\.\d+)-(\w+)(?:-(latest|exp))?"
    match = re.match(pattern, effective_model)

    if match:
        info["version"] = match.group(1)
        info["variant"] = match.group(2)  # flash 或 pro
        suffix = match.group(3)
        if suffix == "exp":
            info["is_experimental"] = True

    return info
