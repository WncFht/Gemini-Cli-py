"""
This file is refactored from packages/core_ts/src/core/coreToolScheduler.ts.

It defines the data models for the states of a tool call and the overall
state for the tool execution graph.
"""

from typing import Literal, Union

from pydantic import BaseModel, Field

from ..api.events import ToolCallRequestInfo, ToolCallResponseInfo
from ..tools.base import Tool, ToolConfirmationOutcome
from ..tools.common import ToolCallConfirmationDetails


class BaseToolCall(BaseModel):
    """Base model for a tool call, containing common fields."""

    request: ToolCallRequestInfo
    tool: Tool
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

    status: Literal["success"] = "success"
    request: ToolCallRequestInfo
    tool: Tool
    response: ToolCallResponseInfo
    duration_ms: float | None = None
    outcome: ToolConfirmationOutcome | None = None


class CancelledToolCall(BaseModel):
    """Status: cancelled. A terminal state."""

    status: Literal["cancelled"] = "cancelled"
    request: ToolCallRequestInfo
    tool: Tool
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
