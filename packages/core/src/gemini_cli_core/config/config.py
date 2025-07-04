import logging
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from gemini_cli_core.config.models import (
    DEFAULT_GEMINI_EMBEDDING_MODEL,
    DEFAULT_GEMINI_MODEL,
)
from gemini_cli_core.core.app import GeminiClient
from gemini_cli_core.services.file_discovery import FileDiscoveryService
from gemini_cli_core.services.git_service import GitService
from gemini_cli_core.tools.base.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ApprovalMode(str, Enum):
    DEFAULT = "default"
    AUTO_EDIT = "autoEdit"
    YOLO = "yolo"


class SandboxConfig(BaseSettings):
    command: str = "docker"
    image: str = "gemini-cli-sandbox"


class TelemetrySettings(BaseSettings):
    enabled: bool = False
    target: str = "stdout"
    otlp_endpoint: str = "http://localhost:4318"
    log_prompts: bool = True


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GEMINI_", case_sensitive=False
    )

    session_id: str = Field(default_factory=__import__("uuid").uuid4)
    model: str = Field(DEFAULT_GEMINI_MODEL, alias="MODEL")
    embedding_model: str = Field(
        DEFAULT_GEMINI_EMBEDDING_MODEL, alias="EMBEDDING_MODEL"
    )
    target_dir: Path = Field(default_factory=Path.cwd, alias="TARGET_DIR")
    debug_mode: bool = Field(False, alias="DEBUG")
    proxy: str | None = Field(None, alias="PROXY")

    # Tool configurations
    core_tools: list[str] | None = None
    exclude_tools: list[str] | None = None
    tool_discovery_command: str | None = None
    tool_call_command: str | None = None
    mcp_servers: dict[str, Any] | None = None

    # Lazy-loaded services
    _file_service: FileDiscoveryService | None = None
    _git_service: GitService | None = None
    _tool_registry: ToolRegistry | None = None
    _gemini_client: GeminiClient | None = None

    def get_file_service(self) -> FileDiscoveryService:
        if not self._file_service:
            self._file_service = FileDiscoveryService(str(self.target_dir))
        return self._file_service

    async def get_git_service(self) -> GitService:
        if not self._git_service:
            self._git_service = GitService(str(self.target_dir))
            await self._git_service.initialize()
        return self._git_service

    async def get_tool_registry(self) -> ToolRegistry:
        if not self._tool_registry:
            self._tool_registry = await create_tool_registry(self)
        return self._tool_registry

    def get_gemini_client(self) -> GeminiClient:
        if not self._gemini_client:
            # This creates a circular dependency if GeminiClient needs full config
            # on init. Refactoring may be needed.
            from gemini_cli_core.core.app import GeminiClient

            self._gemini_client = GeminiClient(self)
        return self._gemini_client


def create_tool_registry(config: Settings) -> ToolRegistry:
    """Creates and populates the tool registry."""
    from gemini_cli_core.tools.file.edit_file import EditTool
    from gemini_cli_core.tools.file.glob import GlobTool
    from gemini_cli_core.tools.file.grep import GrepTool
    from gemini_cli_core.tools.file.list_files import LSTool
    from gemini_cli_core.tools.file.read_file import ReadFileTool
    from gemini_cli_core.tools.file.read_many_files import ReadManyFilesTool
    from gemini_cli_core.tools.file.write_file import WriteFileTool
    from gemini_cli_core.tools.memory.memory_tool import MemoryTool
    from gemini_cli_core.tools.shell.shell_tool import ShellTool
    from gemini_cli_core.tools.web.web_fetch import WebFetchTool
    from gemini_cli_core.tools.web.web_search import WebSearchTool

    registry = ToolRegistry(config)

    # TODO: Implement dynamic tool registration based on config.core_tools
    registry.register_tool(LSTool(config))
    registry.register_tool(ReadFileTool(config))
    registry.register_tool(GrepTool(config))
    registry.register_tool(GlobTool(config))
    registry.register_tool(EditTool(config))
    registry.register_tool(WriteFileTool(config))
    registry.register_tool(ReadManyFilesTool(config))
    registry.register_tool(ShellTool(config))
    registry.register_tool(MemoryTool())
    registry.register_tool(WebFetchTool(config))
    registry.register_tool(WebSearchTool(config))

    # discover_tools is async, but this function is sync.
    # This needs to be called from an async context.
    # await registry.discover_tools()

    return registry


# Global config instance
config = Settings()
