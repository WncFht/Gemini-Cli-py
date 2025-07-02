"""
This file is refactored from packages/core_ts/src/core/turn.ts.
It contains the definitions for events and related data structures used in the system.
"""

from enum import Enum
from typing import Any, Literal, Union

from pydantic import BaseModel, Field


class GeminiEventType(str, Enum):
    """Defines the event types that can occur during an interaction with Gemini."""

    CONTENT = "content"
    TOOL_CALL_REQUEST = "tool_call_request"
    TOOL_CALL_RESPONSE = "tool_call_response"
    TOOL_CALL_CONFIRMATION = "tool_call_confirmation"
    USER_CANCELLED = "user_cancelled"
    ERROR = "error"
    CHAT_COMPRESSED = "chat_compressed"
    USAGE_METADATA = "usage_metadata"
    THOUGHT = "thought"


class StructuredError(BaseModel):
    """Structured error information."""

    message: str
    status: int | None = None


class GeminiErrorEventValue(BaseModel):
    """Value for a Gemini error event."""

    error: StructuredError


class ToolCallRequestInfo(BaseModel):
    """Information about a tool call request."""

    call_id: str = Field(..., alias="callId")
    name: str
    args: dict[str, Any]
    is_client_initiated: bool = Field(..., alias="isClientInitiated")


class ToolResultDisplay(BaseModel):
    """
    Placeholder for how a tool result should be displayed.
    Originally from tools/tools.ts.
    """

    kind: str
    content: str


PartListUnion = list[dict[str, Any]]


class ToolCallResponseInfo(BaseModel):
    """Information about a tool call response."""

    call_id: str = Field(..., alias="callId")
    response_parts: PartListUnion = Field(..., alias="responseParts")
    result_display: ToolResultDisplay | None = Field(
        None, alias="resultDisplay"
    )
    # The original type was `Error | undefined`. We'll store the message.
    error: str | None = None


class ToolCallConfirmationDetails(BaseModel):
    """
    Placeholder for details needed for tool call confirmation.
    Originally from tools/tools.ts.
    """

    title: str
    description: str
    params: dict[str, Any]


class ServerToolCallConfirmationDetails(BaseModel):
    """Details for a server-side tool call confirmation."""

    request: ToolCallRequestInfo
    details: ToolCallConfirmationDetails


class ThoughtSummary(BaseModel):
    """Summary of the model's "thinking" process."""

    subject: str
    description: str


class ServerGeminiContentEvent(BaseModel):
    """Event for model-generated content."""

    type: Literal[GeminiEventType.CONTENT]
    value: str


class ServerGeminiThoughtEvent(BaseModel):
    """Event for a model "thought"."""

    type: Literal[GeminiEventType.THOUGHT]
    value: ThoughtSummary


class ServerGeminiToolCallRequestEvent(BaseModel):
    """Event for a tool call request from the model."""

    type: Literal[GeminiEventType.TOOL_CALL_REQUEST]
    value: ToolCallRequestInfo


class ServerGeminiToolCallResponseEvent(BaseModel):
    """Event for a tool execution response."""

    type: Literal[GeminiEventType.TOOL_CALL_RESPONSE]
    value: ToolCallResponseInfo


class ServerGeminiToolCallConfirmationEvent(BaseModel):
    """Event for waiting for user confirmation of a tool call."""

    type: Literal[GeminiEventType.TOOL_CALL_CONFIRMATION]
    value: ServerToolCallConfirmationDetails


class ServerGeminiUserCancelledEvent(BaseModel):
    """Event for user cancellation."""

    type: Literal[GeminiEventType.USER_CANCELLED]
    value: None = None


class ServerGeminiErrorEvent(BaseModel):
    """Event for an error."""

    type: Literal[GeminiEventType.ERROR]
    value: GeminiErrorEventValue


class ChatCompressionInfo(BaseModel):
    """Information about chat history compression."""

    original_token_count: int = Field(..., alias="originalTokenCount")
    new_token_count: int = Field(..., alias="newTokenCount")


class ServerGeminiChatCompressedEvent(BaseModel):
    """Event for chat history compression."""

    type: Literal[GeminiEventType.CHAT_COMPRESSED]
    value: ChatCompressionInfo | None


class GenerateContentResponseUsageMetadata(BaseModel):
    """
    API usage metadata from the response.
    From @google/genai/index.d.ts
    """

    prompt_token_count: int = Field(..., alias="promptTokenCount")
    candidates_token_count: int = Field(..., alias="candidatesTokenCount")
    total_token_count: int = Field(..., alias="totalTokenCount")
    api_time_ms: int | None = Field(None, alias="apiTimeMs")


class ServerGeminiUsageMetadataEvent(BaseModel):
    """Event for API usage metadata."""

    type: Literal[GeminiEventType.USAGE_METADATA]
    value: GenerateContentResponseUsageMetadata


ServerGeminiStreamEvent = Union[
    ServerGeminiContentEvent,
    ServerGeminiToolCallRequestEvent,
    ServerGeminiToolCallResponseEvent,
    ServerGeminiToolCallConfirmationEvent,
    ServerGeminiUserCancelledEvent,
    ServerGeminiErrorEvent,
    ServerGeminiChatCompressedEvent,
    ServerGeminiThoughtEvent,
    ServerGeminiUsageMetadataEvent,
]
