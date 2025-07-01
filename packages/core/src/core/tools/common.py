"""
This file contains common data models and enums for the tool system,
refactored from parts of packages/core_ts/src/tools/tools.ts.
"""

from enum import Enum
from typing import Any

from pydantic import BaseModel


class ToolConfirmationOutcome(str, Enum):
    """Defines the possible outcomes of a user confirmation for a tool call."""

    APPROVE = "approve"
    CANCEL = "cancel"
    MODIFY_WITH_EDITOR = "modify_with_editor"


class ToolCallConfirmationDetails(BaseModel):
    """
    Contains the details required for a user to confirm a tool call.
    The `onConfirm` callback from the TS version is handled by the graph's
    interruption and resumption flow.
    """

    title: str
    description: str
    params: dict[str, Any]
    file_diff: str | None = None
    is_modifying: bool | None = False

    class Config:
        arbitrary_types_allowed = True
