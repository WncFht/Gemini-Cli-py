from gemini_cli_core.config.models import (
    DEFAULT_GEMINI_EMBEDDING_MODEL,
    DEFAULT_GEMINI_FLASH_MODEL,
    DEFAULT_GEMINI_MODEL,
)

# Default token limit from the TypeScript version
DEFAULT_TOKEN_LIMIT = 1_048_576

# Based on https://ai.google.dev/gemini-api/docs/models and synced with tokenLimits.ts
MODEL_TOKEN_LIMITS: dict[str, int] = {
    "gemini-1.5-pro": 2_097_152,
    "gemini-1.5-flash": 1_048_576,
    "gemini-2.5-pro-preview-05-06": 1_048_576,
    "gemini-2.5-pro-preview-06-05": 1_048_576,
    "gemini-2.5-pro": 1_048_576,
    "gemini-2.5-flash-preview-05-20": 1_048_576,
    "gemini-2.5-flash": 1_048_576,
    "gemini-2.0-flash": 1_048_576,
    "gemini-2.0-flash-preview-image-generation": 32_000,
    "gemini-pro": 1_048_576,
    "gemini-pro-vision": 12288,
    "embedding-001": 2048,
    DEFAULT_GEMINI_MODEL: 1_048_576,
    DEFAULT_GEMINI_FLASH_MODEL: 1_048_576,
    DEFAULT_GEMINI_EMBEDDING_MODEL: 2048,
}


def token_limit(model: str) -> int:
    """
    Returns the token limit for a given model.
    This logic is ported from the more up-to-date TypeScript version.
    """
    return MODEL_TOKEN_LIMITS.get(model, DEFAULT_TOKEN_LIMIT)
