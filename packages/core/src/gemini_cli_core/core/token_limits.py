from gemini_cli_core.config.models import (
    DEFAULT_GEMINI_FLASH_MODEL,
    DEFAULT_GEMINI_PRO_MODEL,
)

GEMINI_FLASH_TOKEN_LIMIT = 1048576
GEMINI_PRO_TOKEN_LIMIT = 1048576
GEMINI_PRO_VISION_TOKEN_LIMIT = 12288
EMBEDDING_TOKEN_LIMIT = 2048

MODEL_TOKEN_LIMITS: dict[str, int] = {
    DEFAULT_GEMINI_PRO_MODEL: GEMINI_PRO_TOKEN_LIMIT,
    "gemini-pro": GEMINI_PRO_TOKEN_LIMIT,
    DEFAULT_GEMINI_FLASH_MODEL: GEMINI_FLASH_TOKEN_LIMIT,
    "gemini-pro-vision": GEMINI_PRO_VISION_TOKEN_LIMIT,
    "embedding-001": EMBEDDING_TOKEN_LIMIT,
}


def token_limit(model: str) -> int | None:
    """
    Returns the token limit for a given model.

    Args:
        model: The model name.

    Returns:
        The token limit, or None if not found.

    """
    return MODEL_TOKEN_LIMITS.get(model)
