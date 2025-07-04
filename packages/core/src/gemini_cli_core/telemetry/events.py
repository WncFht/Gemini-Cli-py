"""
This file is refactored from packages/core_ts/src/telemetry/types.ts.
It defines the Pydantic models for various telemetry events.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolCallDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    MODIFY = "modify"


class TelemetryEventBase(BaseModel):
    event_timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat()
    )


class StartSessionEvent(TelemetryEventBase):
    event_name: Literal["cli_config"] = "cli_config"
    model: str
    embedding_model: str
    sandbox_enabled: bool
    core_tools_enabled: str
    approval_mode: str
    api_key_enabled: bool
    vertex_ai_enabled: bool
    debug_enabled: bool
    mcp_servers: str
    telemetry_enabled: bool
    telemetry_log_user_prompts_enabled: bool
    file_filtering_respect_git_ignore: bool


class EndSessionEvent(TelemetryEventBase):
    event_name: Literal["end_session"] = "end_session"
    session_id: str | None = None


class UserPromptEvent(TelemetryEventBase):
    event_name: Literal["user_prompt"] = "user_prompt"
    prompt_length: int
    prompt: str | None = None


class ToolCallEvent(TelemetryEventBase):
    event_name: Literal["tool_call"] = "tool_call"
    function_name: str
    function_args: dict[str, Any]
    duration_ms: int
    success: bool
    decision: ToolCallDecision | None = None
    error: str | None = None
    error_type: str | None = None


class ApiRequestEvent(TelemetryEventBase):
    event_name: Literal["api_request"] = "api_request"
    model: str
    request_text: str | None = None


class ApiErrorEvent(TelemetryEventBase):
    event_name: Literal["api_error"] = "api_error"
    model: str
    error: str
    error_type: str | None = None
    status_code: int | str | None = None
    duration_ms: int


class ApiResponseEvent(TelemetryEventBase):
    event_name: Literal["api_response"] = "api_response"
    model: str
    status_code: int | str | None = 200
    duration_ms: int
    error: str | None = None
    input_token_count: int = 0
    output_token_count: int = 0
    cached_content_token_count: int = 0
    thoughts_token_count: int = 0
    tool_token_count: int = 0
    total_token_count: int = 0
    response_text: str | None = None


TelemetryEvent = (
    StartSessionEvent
    | EndSessionEvent
    | UserPromptEvent
    | ToolCallEvent
    | ApiRequestEvent
    | ApiErrorEvent
    | ApiResponseEvent
)
