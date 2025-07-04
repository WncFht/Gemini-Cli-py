import asyncio
import logging
import re
from collections.abc import Callable
from enum import Enum
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import (
    StdioServerParameters,
    stdio_client,
)
from mcp.client.streamable_http import streamablehttp_client

from gemini_cli_core.core.types import MCPServerConfig
from gemini_cli_core.tools.base.registry import ToolRegistry
from gemini_cli_core.tools.mcp.mcp_tool import DiscoveredMCPTool

logger = logging.getLogger(__name__)
MCP_DEFAULT_TIMEOUT_MSEC = 10 * 60 * 1000  # Python SDK uses seconds


class MCPServerStatus(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"


class MCPDiscoveryState(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"


StatusChangeListener = Callable[[str, MCPServerStatus], None]


class MCPStatusManager:
    def __init__(self):
        self.server_statuses: dict[str, MCPServerStatus] = {}
        self.discovery_state: MCPDiscoveryState = MCPDiscoveryState.NOT_STARTED
        self.listeners: list[StatusChangeListener] = []

    def add_listener(self, listener: StatusChangeListener):
        self.listeners.append(listener)

    def remove_listener(self, listener: StatusChangeListener):
        self.listeners.remove(listener)

    def update_status(self, server_name: str, status: MCPServerStatus):
        self.server_statuses[server_name] = status
        for listener in self.listeners:
            listener(server_name, status)

    def get_status(self, server_name: str) -> MCPServerStatus:
        return self.server_statuses.get(
            server_name, MCPServerStatus.DISCONNECTED
        )


status_manager = MCPStatusManager()


def sanitize_parameters(schema: dict[str, Any] | None):
    if not schema:
        return
    if "anyOf" in schema:
        schema.pop("default", None)
        for item in schema["anyOf"]:
            sanitize_parameters(item)
    if "items" in schema:
        sanitize_parameters(schema["items"])
    if "properties" in schema:
        for item in schema["properties"].values():
            sanitize_parameters(item)


async def connect_and_discover(
    server_name: str,
    server_config: MCPServerConfig,
    tool_registry: ToolRegistry,
):
    status_manager.update_status(server_name, MCPServerStatus.CONNECTING)

    try:
        if server_config.http_url:
            async with streamablehttp_client(server_config.http_url) as (
                read,
                write,
                _,
            ):
                await _discover_with_session(
                    server_name, server_config, tool_registry, read, write
                )
        elif server_config.command:
            params = StdioServerParameters(
                command=server_config.command,
                args=server_config.args or [],
                env=server_config.env,
                cwd=server_config.cwd,
            )
            async with stdio_client(params) as (read, write):
                await _discover_with_session(
                    server_name, server_config, tool_registry, read, write
                )
        else:
            logger.error(f"Invalid MCP config for {server_name}")
            status_manager.update_status(
                server_name, MCPServerStatus.DISCONNECTED
            )
    except Exception as e:
        logger.error(f"Failed to connect to MCP server {server_name}: {e}")
        status_manager.update_status(server_name, MCPServerStatus.DISCONNECTED)


async def _discover_with_session(
    server_name, server_config, tool_registry, read, write
):
    async with ClientSession(read, write) as session:
        await session.initialize()
        status_manager.update_status(server_name, MCPServerStatus.CONNECTED)

        tools_response = await session.list_tools()
        for tool_def in tools_response.tools:
            # MCP Python SDK uses `inputSchema`
            parameter_schema = tool_def.input_schema or {
                "type": "object",
                "properties": {},
            }
            sanitize_parameters(parameter_schema)

            tool_name_for_model = tool_def.name
            if re.search(r"[^a-zA-Z0-9_.-]", tool_name_for_model):
                tool_name_for_model = re.sub(
                    r"[^a-zA-Z0-9_.-]", "_", tool_name_for_model
                )

            if tool_registry.get_tool(tool_name_for_model):
                tool_name_for_model = f"{server_name}__{tool_name_for_model}"

            if len(tool_name_for_model) > 63:
                tool_name_for_model = (
                    tool_name_for_model[:28] + "___" + tool_name_for_model[-32:]
                )

            tool_registry.register_tool(
                DiscoveredMCPTool(
                    mcp_session=session,
                    server_name=server_name,
                    name=tool_name_for_model,
                    description=tool_def.description or "",
                    parameter_schema=parameter_schema,
                    server_tool_name=tool_def.name,
                    timeout=server_config.timeout,
                    trust=server_config.trust or False,
                )
            )


async def discover_mcp_tools(
    mcp_servers: dict[str, MCPServerConfig], tool_registry: ToolRegistry
):
    status_manager.discovery_state = MCPDiscoveryState.IN_PROGRESS
    tasks = [
        connect_and_discover(name, config, tool_registry)
        for name, config in mcp_servers.items()
    ]
    await asyncio.gather(*tasks)
    status_manager.discovery_state = MCPDiscoveryState.COMPLETED
