"""
This file is refactored from packages/core_ts/src/tools/tools.ts.

It defines the base interface (Tool) and abstract base class (BaseTool)
for all tools in the system, establishing a common contract for tool behavior.
"""

from abc import ABC, abstractmethod
from typing import Any, Generic, Protocol, TypeVar

from pydantic import BaseModel

from .common import ToolCallConfirmationDetails

# --- Type Variables for Generics ---
TParams = TypeVar("TParams", bound=BaseModel)
TResult = TypeVar("TResult", bound="ToolResult")


# --- Tool Result and Display Models ---
class FileDiff(BaseModel):
    """Represents a diff for a file change."""

    file_diff: str
    file_name: str


ToolResultDisplay = str | FileDiff


class ToolResult(BaseModel, Generic[TParams]):
    """Defines the structure for the result of a tool execution."""

    llm_content: Any  # Corresponds to PartListUnion, flexible for now
    return_display: ToolResultDisplay

    class Config:
        arbitrary_types_allowed = True


# --- Tool Protocol (Interface) ---
class Tool(Protocol[TParams, TResult]):
    """
    Protocol defining the basic contract for all tools.
    """

    name: str
    display_name: str
    description: str
    schema: dict[str, Any]
    is_output_markdown: bool
    can_update_output: bool

    def validate_tool_params(self, params: TParams) -> str | None: ...

    def get_description(self, params: TParams) -> str: ...

    async def should_confirm_execute(
        self, params: TParams, abort_signal: Any | None = None
    ) -> ToolCallConfirmationDetails | bool: ...

    async def execute(
        self,
        params: TParams,
        signal: Any | None = None,
        update_output: callable | None = None,
    ) -> TResult: ...


# --- Abstract Base Tool Class ---
class BaseTool(ABC, Generic[TParams, TResult]):
    """
    Abstract base class providing common functionality for tools.
    """

    def __init__(
        self,
        name: str,
        display_name: str,
        description: str,
        parameter_schema: dict[str, Any],
        is_output_markdown: bool = True,
        can_update_output: bool = False,
    ):
        self.name = name
        self.display_name = display_name
        self.description = description
        self.parameter_schema = parameter_schema
        self.is_output_markdown = is_output_markdown
        self.can_update_output = can_update_output

    @property
    def schema(self) -> dict[str, Any]:
        """The function declaration schema for the tool."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameter_schema,
        }

    def validate_tool_params(self, params: TParams) -> str | None:
        """Placeholder for parameter validation."""
        # A real implementation would typically use a JSON Schema validator.
        return None

    def get_description(self, params: TParams) -> str:
        """Default description generator."""
        return params.model_dump_json()

    async def should_confirm_execute(
        self, params: TParams, abort_signal: Any | None = None
    ) -> ToolCallConfirmationDetails | bool:
        """Default confirmation behavior: no confirmation needed."""
        return False

    @abstractmethod
    async def execute(
        self,
        params: TParams,
        signal: Any | None = None,
        update_output: callable | None = None,
    ) -> TResult:
        """Abstract method for the core tool logic."""
        raise NotImplementedError
