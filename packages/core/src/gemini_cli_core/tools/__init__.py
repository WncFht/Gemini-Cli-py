"""
The tools sub-package provides the framework for defining, discovering, and executing tools within the Gemini CLI agent.

This package exposes the core components for tool development and management:

- `BaseTool`: The abstract base class that all tools must inherit from.
- `ToolResult`: The standardized return type for all tool executions.
- `ToolRegistry`: The central manager that holds and provides access to all available tools.
"""

from .base.registry import ToolRegistry
from .base.tool_base import BaseTool, ToolResult

__all__ = [
    "BaseTool",
    "ToolRegistry",
    "ToolResult",
]
