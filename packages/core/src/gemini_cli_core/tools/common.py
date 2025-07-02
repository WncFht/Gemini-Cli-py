"""
This file contains common data models and enums for the tool system,
refactored from parts of packages/core_ts/src/tools/tools.ts.
"""

from enum import Enum
from typing import Literal, Union

from pydantic import BaseModel


class ToolConfirmationOutcome(str, Enum):
    """Defines the possible outcomes of a user confirmation for a tool call."""

    APPROVE = "approve"
    CANCEL = "cancel"
    MODIFY_WITH_EDITOR = "modify_with_editor"
    # Note: ProceedAlways... variants from TS are handled by client-side
    # logic that leads to an 'approve' outcome for the tool.


# --- Tool Call Confirmation Details ---
# These models correspond to the Tool...ConfirmationDetails interfaces in tools.ts.
# The `onConfirm` callback from the TS version is omitted, as its logic is
# handled by the graph's interruption and resumption flow.


class ToolEditConfirmationDetails(BaseModel):
    """Confirmation details for 'edit' or 'write' type tools."""

    type: Literal["edit"] = "edit"
    title: str
    file_name: str
    file_diff: str
    is_modifying: bool = False


class ToolExecuteConfirmationDetails(BaseModel):
    """Confirmation details for 'execute command' type tools."""

    type: Literal["exec"] = "exec"
    title: str
    command: str
    root_command: str


class ToolMcpConfirmationDetails(BaseModel):
    """Confirmation details for MCP (Model-side Code Pre-execution) tools."""

    type: Literal["mcp"] = "mcp"
    title: str
    server_name: str
    tool_name: str
    tool_display_name: str


class ToolInfoConfirmationDetails(BaseModel):
    """Confirmation details for displaying general information."""

    type: Literal["info"] = "info"
    title: str
    prompt: str
    urls: list[str] | None = None


# A discriminated union of all possible tool call confirmation detail types.
# Corresponds to the `ToolCallConfirmationDetails` union type in tools.ts.
ToolCallConfirmationDetails = Union[
    ToolEditConfirmationDetails,
    ToolExecuteConfirmationDetails,
    ToolMcpConfirmationDetails,
    ToolInfoConfirmationDetails,
]
