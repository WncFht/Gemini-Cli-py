from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

from gemini_cli_core.api.events import ToolCallRequestInfo, ToolCallResponseInfo
from gemini_cli_core.tools.common import (
    ToolCallConfirmationDetails,
    ToolConfirmationOutcome,
)


class BaseToolCall(BaseModel):
    """Base model for a tool call, containing common fields."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    request: ToolCallRequestInfo
    # Use `Any` here because `Tool` is a Protocol, which Pydantic v2 has trouble
    # creating a validator for at runtime. We rely on static type checking instead.
    tool: Any
    start_time: float | None = None
    outcome: ToolConfirmationOutcome | None = None


class ValidatingToolCall(BaseToolCall):
    """Status: validating. The tool call is being validated."""

    status: Literal["validating"] = "validating"


class ScheduledToolCall(BaseToolCall):
    """Status: scheduled. The tool call is ready for execution."""

    status: Literal["scheduled"] = "scheduled"


class ExecutingToolCall(BaseToolCall):
    """Status: executing. The tool is running."""

    status: Literal["executing"] = "executing"
    live_output: str | None = None


class WaitingToolCall(BaseToolCall):
    """Status: awaiting_approval. Waiting for user confirmation."""

    status: Literal["awaiting_approval"] = "awaiting_approval"
    confirmation_details: ToolCallConfirmationDetails


class ErroredToolCall(BaseModel):
    """Status: error. A terminal state."""

    status: Literal["error"] = "error"
    request: ToolCallRequestInfo
    response: ToolCallResponseInfo
    duration_ms: float | None = None
    outcome: ToolConfirmationOutcome | None = None


class SuccessfulToolCall(BaseModel):
    """Status: success. A terminal state."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Literal["success"] = "success"
    request: ToolCallRequestInfo
    tool: Any
    response: ToolCallResponseInfo
    duration_ms: float | None = None
    outcome: ToolConfirmationOutcome | None = None


class CancelledToolCall(BaseModel):
    """Status: cancelled. A terminal state."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    status: Literal["cancelled"] = "cancelled"
    request: ToolCallRequestInfo
    tool: Any
    response: ToolCallResponseInfo
    duration_ms: float | None = None
    outcome: ToolConfirmationOutcome | None = None


ToolCall = Union[
    ValidatingToolCall,
    ScheduledToolCall,
    ExecutingToolCall,
    WaitingToolCall,
    SuccessfulToolCall,
    ErroredToolCall,
    CancelledToolCall,
]

CompletedToolCall = Union[
    SuccessfulToolCall, ErroredToolCall, CancelledToolCall
]


class ToolExecutionState(BaseModel):
    """The state for the tool execution graph."""

    incoming_requests: list[ToolCallRequestInfo] = Field(
        default_factory=list,
        description="Tool call requests from the model to be processed.",
    )
    tool_calls: list[ToolCall] = Field(
        default_factory=list,
        description="The list of tool calls being managed by the graph.",
    )

    class Config:
        arbitrary_types_allowed = True
