"""
This file is refactored from packages/core_ts/src/utils/generateContentResponseUtilities.ts.
"""

from typing import Any


def get_response_text(response: dict[str, Any]) -> str | None:
    """Extracts text from a GenerateContentResponse."""
    try:
        parts = response["candidates"][0]["content"]["parts"]
        text_segments = [part["text"] for part in parts if "text" in part]
        return "".join(text_segments) if text_segments else None
    except (KeyError, IndexError, TypeError):
        return None


def get_function_calls(response: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Extracts function calls from a GenerateContentResponse."""
    try:
        parts = response["candidates"][0]["content"]["parts"]
        function_calls = [
            part["functionCall"] for part in parts if "functionCall" in part
        ]
        return function_calls if function_calls else None
    except (KeyError, IndexError, TypeError):
        return None


def get_structured_response(response: dict[str, Any]) -> str | None:
    """Extracts both text and function calls into a structured string."""
    text_content = get_response_text(response)
    function_calls = get_function_calls(response)

    if text_content and function_calls:
        import json

        return f"{text_content}\n{json.dumps(function_calls, indent=2)}"
    if text_content:
        return text_content
    if function_calls:
        import json

        return json.dumps(function_calls, indent=2)
    return None
