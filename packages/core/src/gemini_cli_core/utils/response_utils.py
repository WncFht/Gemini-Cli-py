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


# --- Converters from code_assist/converter.ts ---
# These functions convert between the standard @google/genai format
# and the Vertex AI-specific format used by the Code Assist service.

from pydantic import BaseModel

from gemini_cli_core.core.types import (
    Content,
    GenerateContentConfig,
    Part,
    SafetySetting,
    ToolConfig,
)


# Pydantic models for Vertex AI-specific structures
class VertexGenerationConfig(BaseModel):
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    candidate_count: int | None = None
    max_output_tokens: int | None = None
    stop_sequences: list[str] | None = None
    # Add other fields as needed from the TS definition


class VertexGenerateContentRequest(BaseModel):
    contents: list[Content]
    system_instruction: Content | None = None
    tools: list[dict] | None = None  # Simplified for now
    tool_config: ToolConfig | None = None
    safety_settings: list[SafetySetting] | None = None
    generation_config: VertexGenerationConfig | None = None


class CAGenerateContentRequest(BaseModel):
    model: str
    project: str | None = None
    request: VertexGenerateContentRequest


class VertexCountTokenRequest(BaseModel):
    model: str
    contents: list[Content]


class CaCountTokenRequest(BaseModel):
    request: VertexCountTokenRequest


class CaCountTokenResponse(BaseModel):
    total_tokens: int


class Candidate(BaseModel):
    # Simplified version
    content: Content
    # Add other fields like finish_reason, safety_ratings etc.


class VertexGenerateContentResponse(BaseModel):
    candidates: list[Candidate]
    # Add other fields like prompt_feedback, usage_metadata


class CaGenerateContentResponse(BaseModel):
    response: VertexGenerateContentResponse


# Conversion functions
def to_content(content: Any) -> Content:
    if isinstance(content, str):
        return Content(role="user", parts=[Part(text=content)])
    if isinstance(content, list):
        return Content(
            role="user",
            parts=[Part(text=p) if isinstance(p, str) else p for p in content],
        )
    if isinstance(content, dict) and "parts" in content:
        return Content(**content)
    # Assuming it's a Part-like dict
    return Content(role="user", parts=[Part(**content)])


def to_contents(contents: Any) -> list[Content]:
    if isinstance(contents, list):
        return [to_content(c) for c in contents]
    return [to_content(contents)]


def to_vertex_generation_config(
    config: GenerateContentConfig | None,
) -> VertexGenerationConfig | None:
    if not config:
        return None
    # This assumes GenerateContentConfig and VertexGenerationConfig have compatible fields
    return VertexGenerationConfig(**config.model_dump(exclude_none=True))


def to_vertex_generate_content_request(
    req: Any,
) -> VertexGenerateContentRequest:
    # Assuming req is a Pydantic model or dict with compatible structure
    return VertexGenerateContentRequest(
        contents=to_contents(req.contents),
        system_instruction=to_content(req.config.system_instruction)
        if req.config and req.config.system_instruction
        else None,
        tools=req.config.tools if req.config else None,
        tool_config=req.config.tool_config if req.config else None,
        safety_settings=req.config.safety_settings if req.config else None,
        generation_config=to_vertex_generation_config(req.config),
    )


def to_generate_content_request(
    req: Any, project: str | None = None
) -> CAGenerateContentRequest:
    return CAGenerateContentRequest(
        model=req.model,
        project=project,
        request=to_vertex_generate_content_request(req),
    )


def from_generate_content_response(res: CaGenerateContentResponse) -> dict:
    # This is a simplified conversion, assuming the client can handle the dict
    return res.response.model_dump()


def to_count_token_request(req: Any) -> CaCountTokenRequest:
    return CaCountTokenRequest(
        request=VertexCountTokenRequest(
            model=f"models/{req.model}", contents=to_contents(req.contents)
        )
    )


def from_count_token_response(res: CaCountTokenResponse) -> dict:
    return {"totalTokens": res.total_tokens}
