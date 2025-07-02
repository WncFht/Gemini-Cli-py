"""
This file is refactored from packages/core_ts/src/tools/mcp-tool.ts.
"""

import json
from typing import Any, ClassVar

from mcp import ClientSession
from pydantic import BaseModel

from gemini_cli_core.tools.base.tool_base import BaseTool, ToolResult
from gemini_cli_core.tools.common import (
    ToolCallConfirmationDetails,
    ToolMcpConfirmationDetails,
)


class DiscoveredMCPToolParams(BaseModel):
    # This is a generic model for any MCP tool params
    class Config:
        extra = "allow"


class DiscoveredMCPTool(BaseTool[DiscoveredMCPToolParams, ToolResult]):
    """
    An adapter for a remote tool discovered via MCP (Model-Context Protocol)
    to conform to the local Tool interface.
    """

    allowlist: ClassVar[set[str]] = set()

    def __init__(
        self,
        mcp_session: ClientSession,
        server_name: str,
        name: str,
        description: str,
        parameter_schema: dict[str, Any],
        server_tool_name: str,
        timeout: int | None = None,
        trust: bool = False,
    ):
        super().__init__(
            name=name,
            display_name=f"{server_tool_name} ({server_name} MCP Server)",
            description=description,
            parameter_schema=parameter_schema,
            is_output_markdown=True,
            can_update_output=False,
        )
        self.mcp_session = mcp_session
        self.server_name = server_name
        self.server_tool_name = server_tool_name
        self.timeout = timeout
        self.trust = trust

    async def should_confirm_execute(
        self, params: DiscoveredMCPToolParams, abort_signal: Any | None = None
    ) -> ToolCallConfirmationDetails | bool:
        server_allowlist_key = self.server_name
        tool_allowlist_key = f"{self.server_name}.{self.server_tool_name}"

        if (
            self.trust
            or server_allowlist_key in self.allowlist
            or tool_allowlist_key in self.allowlist
        ):
            return False

        return ToolMcpConfirmationDetails(
            title="Confirm MCP Tool Execution",
            server_name=self.server_name,
            tool_name=self.server_tool_name,
            tool_display_name=self.name,
        )

    async def execute(
        self,
        params: DiscoveredMCPToolParams,
        signal: Any | None = None,
        **kwargs,
    ) -> ToolResult:
        tool_result = await self.mcp_session.call_tool(
            name=self.server_tool_name,
            arguments=params.model_dump(),
        )

        # The result from the Python SDK might be a dict or a tuple
        # (content, structured_data). We need to handle this.
        if isinstance(tool_result, tuple):
            result_parts = tool_result[0] or tool_result[1]
        else:
            result_parts = tool_result

        return ToolResult(
            llm_content=result_parts,
            return_display=self._stringify_result_for_display(result_parts),
        )

    def _stringify_result_for_display(self, result: Any) -> str:
        if not result:
            return "```json\n[]\n```"

        # Simplified version of the JS logic.
        try:
            return f"```json\n{json.dumps(result, indent=2)}\n```"
        except TypeError:
            return str(result)
