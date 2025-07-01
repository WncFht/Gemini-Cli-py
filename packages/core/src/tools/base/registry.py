"""
This file is refactored from packages/core_ts/src/tools/tool-registry.ts.
"""

import asyncio
import json
import logging
import subprocess
from typing import Any

from ....config import Config
from ...mcp.mcp_client import discover_mcp_tools
from ...mcp.mcp_tool import DiscoveredMCPTool
from .tool_base import BaseTool, Tool, ToolResult

logger = logging.getLogger(__name__)


class DiscoveredTool(BaseTool[dict[str, Any], ToolResult]):
    """
    An adapter for an external tool discovered via a command-line
    to conform to the local Tool interface.
    """

    def __init__(
        self,
        config: Config,
        name: str,
        description: str,
        parameter_schema: dict[str, Any],
    ):
        discovery_cmd = config.get_tool_discovery_command()
        call_command = config.get_tool_call_command()
        full_description = f"""{description}

This tool was discovered from the project by running the command `{discovery_cmd}` in the project root.
When called, this tool will execute the command `{call_command} {name}` in the project root.
"""
        super().__init__(
            name=name,
            display_name=name,
            description=full_description,
            parameter_schema=parameter_schema,
        )
        self.config = config

    async def execute(self, params: dict[str, Any], **kwargs) -> ToolResult:
        call_command = self.config.get_tool_call_command()
        if not call_command:
            raise ValueError("Tool call command is not configured.")

        proc = await asyncio.create_subprocess_shell(
            f"{call_command} {self.name}",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.config.get_target_dir(),
        )
        stdout, stderr = await proc.communicate(
            input=json.dumps(params).encode()
        )

        if proc.returncode != 0 or stderr:
            llm_content = f"Stdout: {stdout.decode() or '(empty)'}\nStderr: {stderr.decode() or '(empty)'}\nExit Code: {proc.returncode}"
            return ToolResult(
                llm_content=llm_content, return_display=llm_content
            )

        return ToolResult(
            llm_content=stdout.decode(), return_display=stdout.decode()
        )


class ToolRegistry:
    """A central repository for managing all available tools."""

    def __init__(self, config: Config):
        self.config = config
        self._tools: dict[str, Tool] = {}

    def register_tool(self, tool: Tool):
        if tool.name in self._tools:
            logger.warning(
                f"Tool '{tool.name}' is already registered. Overwriting."
            )
        self._tools[tool.name] = tool

    async def discover_tools(self):
        # Clear previously discovered tools
        for name, tool in list(self._tools.items()):
            if isinstance(tool, (DiscoveredTool, DiscoveredMCPTool)):
                del self._tools[name]

        # Discover from command
        discovery_cmd = self.config.get_tool_discovery_command()
        if discovery_cmd:
            try:
                result = subprocess.run(
                    discovery_cmd,
                    shell=True,
                    capture_output=True,
                    text=True,
                    check=True,
                    cwd=str(self.config.get_target_dir()),
                )
                tool_defs = json.loads(result.stdout.strip())

                functions = []
                for tool_def in tool_defs:
                    if "function_declarations" in tool_def:
                        functions.extend(tool_def["function_declarations"])
                    else:
                        functions.append(tool_def)

                for func in functions:
                    self.register_tool(
                        DiscoveredTool(
                            config=self.config,
                            name=func["name"],
                            description=func["description"],
                            parameter_schema=func["parameters"],
                        )
                    )
            except (
                subprocess.CalledProcessError,
                json.JSONDecodeError,
                KeyError,
            ) as e:
                logger.error(f"Failed to discover tools via command: {e}")

        # Discover from MCP
        mcp_servers = self.config.get_mcp_servers()
        if mcp_servers:
            await discover_mcp_tools(mcp_servers, self)

    def get_function_declarations(self) -> list[dict[str, Any]]:
        return [tool.schema for tool in self._tools.values()]

    def get_all_tools(self) -> list[Tool]:
        return list(self._tools.values())

    def get_tool(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def get_tools_by_server(self, server_name: str) -> list[Tool]:
        return [
            tool
            for tool in self._tools.values()
            if isinstance(tool, DiscoveredMCPTool)
            and tool.server_name == server_name
        ]
