"""
Configuration management for Gemini CLI
"""

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.types import (
    AccessibilitySettings,
    ApprovalMode,
    BugCommandSettings,
    MCPServerConfig,
    SandboxConfig,
    TelemetrySettings,
)

# Default model constants
DEFAULT_GEMINI_MODEL = "gemini-2.0-flash-exp"
DEFAULT_GEMINI_FLASH_MODEL = "gemini-2.0-flash"
DEFAULT_EMBEDDING_MODEL = "text-embedding-004"

# Directory constants
GEMINI_CONFIG_DIR = ".gemini"
SETTINGS_DIRECTORY_NAME = ".gemini"


@dataclass
class Config:
    """完整的配置定义 - 与TypeScript Config类对应"""

    # 核心配置
    session_id: str
    model: str = DEFAULT_GEMINI_MODEL
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    target_dir: str = field(default_factory=os.getcwd)
    debug_mode: bool = False

    # 工具配置
    core_tools: list[str] | None = None
    exclude_tools: list[str] | None = None
    tool_discovery_command: str | None = None
    tool_call_command: str | None = None

    # MCP配置
    mcp_servers: dict[str, MCPServerConfig] = field(default_factory=dict)
    mcp_server_command: str | None = None

    # 用户界面
    approval_mode: ApprovalMode = ApprovalMode.DEFAULT
    show_memory_usage: bool = False
    accessibility: AccessibilitySettings = field(
        default_factory=AccessibilitySettings
    )

    # 文件处理
    file_filtering: dict[str, bool] = field(
        default_factory=lambda: {
            "respect_git_ignore": True,
            "enable_recursive_file_search": True,
        },
    )
    context_file_name: str | list[str] | None = None

    # 遥测
    telemetry: TelemetrySettings = field(default_factory=TelemetrySettings)
    usage_statistics_enabled: bool = True

    # 其他配置
    question: str | None = None
    full_context: bool = False
    checkpointing: bool = False
    proxy: str | None = None
    sandbox: SandboxConfig | None = None
    bug_command: BugCommandSettings | None = None
    extension_context_file_paths: list[str] = field(default_factory=list)

    # 运行时状态
    user_memory: str = ""
    gemini_md_file_count: int = 0
    model_switched_during_session: bool = False
    flash_fallback_handler: Callable[[str, str], bool] | None = None

    # 工作目录
    cwd: str = field(default_factory=os.getcwd)

    # 私有属性 - 使用post_init初始化
    _tool_registry: Any | None = field(default=None, init=False)
    _gemini_client: Any | None = field(default=None, init=False)
    _content_generator_config: Any | None = field(default=None, init=False)
    _file_discovery_service: Any | None = field(default=None, init=False)
    _git_service: Any | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        """初始化后处理"""
        # 确保target_dir是绝对路径
        self.target_dir = os.path.abspath(self.target_dir)

        # 设置GEMINI_MD文件名
        if self.context_file_name:
            # TODO: 调用setGeminiMdFilename
            pass

    # Session ID
    def get_session_id(self) -> str:
        """获取会话ID"""
        return self.session_id

    # Model Management
    def get_model(self) -> str:
        """获取当前模型"""
        if self._content_generator_config:
            return getattr(self._content_generator_config, "model", self.model)
        return self.model

    def set_model(self, new_model: str) -> None:
        """设置模型"""
        if self._content_generator_config:
            self._content_generator_config.model = new_model
        self.model_switched_during_session = True

    def is_model_switched_during_session(self) -> bool:
        """检查会话期间是否切换了模型"""
        return self.model_switched_during_session

    def reset_model_to_default(self) -> None:
        """重置模型到默认值"""
        if self._content_generator_config:
            self._content_generator_config.model = DEFAULT_GEMINI_MODEL
        self.model_switched_during_session = False

    def set_flash_fallback_handler(
        self, handler: Callable[[str, str], bool]
    ) -> None:
        """设置Flash回退处理器"""
        self.flash_fallback_handler = handler

    def get_embedding_model(self) -> str:
        """获取嵌入模型"""
        return self.embedding_model

    # Directory and Path Methods
    def get_target_dir(self) -> str:
        """获取目标目录"""
        return self.target_dir

    def get_project_root(self) -> str:
        """获取项目根目录"""
        return self.target_dir

    def get_working_dir(self) -> str:
        """获取工作目录"""
        return self.cwd

    def get_gemini_dir(self) -> str:
        """获取Gemini配置目录"""
        return os.path.join(self.target_dir, GEMINI_CONFIG_DIR)

    def get_project_temp_dir(self) -> str:
        """获取项目临时目录"""
        return os.path.join(self.target_dir, ".tmp")

    # Tool Configuration
    def get_core_tools(self) -> list[str] | None:
        """获取核心工具列表"""
        return self.core_tools

    def get_exclude_tools(self) -> list[str] | None:
        """获取排除工具列表"""
        return self.exclude_tools

    def get_tool_discovery_command(self) -> str | None:
        """获取工具发现命令"""
        return self.tool_discovery_command

    def get_tool_call_command(self) -> str | None:
        """获取工具调用命令"""
        return self.tool_call_command

    async def get_tool_registry(self) -> Any:
        """获取工具注册表 - 延迟加载"""
        if not self._tool_registry:
            from ..tools.tool_registry import create_tool_registry

            self._tool_registry = await create_tool_registry(self)
        return self._tool_registry

    # MCP Configuration
    def get_mcp_servers(self) -> dict[str, MCPServerConfig]:
        """获取MCP服务器配置"""
        return self.mcp_servers

    def get_mcp_server_command(self) -> str | None:
        """获取MCP服务器命令"""
        return self.mcp_server_command

    # UI Configuration
    def get_approval_mode(self) -> ApprovalMode:
        """获取批准模式"""
        return self.approval_mode

    def set_approval_mode(self, mode: ApprovalMode) -> None:
        """设置批准模式"""
        self.approval_mode = mode

    def get_show_memory_usage(self) -> bool:
        """获取是否显示内存使用"""
        return self.show_memory_usage

    def get_accessibility(self) -> AccessibilitySettings:
        """获取可访问性设置"""
        return self.accessibility

    # File Configuration
    def get_enable_recursive_file_search(self) -> bool:
        """获取是否启用递归文件搜索"""
        return self.file_filtering.get("enable_recursive_file_search", True)

    def get_file_filtering_respect_git_ignore(self) -> bool:
        """获取是否遵守gitignore"""
        return self.file_filtering.get("respect_git_ignore", True)

    # Telemetry Configuration
    def get_telemetry_enabled(self) -> bool:
        """获取是否启用遥测"""
        return self.telemetry.enabled

    def get_telemetry_log_prompts_enabled(self) -> bool:
        """获取是否记录提示词"""
        return self.telemetry.log_prompts

    def get_telemetry_otlp_endpoint(self) -> str:
        """获取OTLP端点"""
        return self.telemetry.otlp_endpoint

    def get_telemetry_target(self) -> str:
        """获取遥测目标"""
        return self.telemetry.target

    def get_usage_statistics_enabled(self) -> bool:
        """获取是否启用使用统计"""
        return self.usage_statistics_enabled

    # Memory Management
    def get_user_memory(self) -> str:
        """获取用户记忆"""
        return self.user_memory

    def set_user_memory(self, memory: str) -> None:
        """设置用户记忆"""
        self.user_memory = memory

    def get_gemini_md_file_count(self) -> int:
        """获取GEMINI.md文件数量"""
        return self.gemini_md_file_count

    def set_gemini_md_file_count(self, count: int) -> None:
        """设置GEMINI.md文件数量"""
        self.gemini_md_file_count = count

    # Other Configuration
    def get_debug_mode(self) -> bool:
        """获取调试模式"""
        return self.debug_mode

    def get_question(self) -> str | None:
        """获取问题"""
        return self.question

    def get_full_context(self) -> bool:
        """获取是否使用完整上下文"""
        return self.full_context

    def get_checkpointing_enabled(self) -> bool:
        """获取是否启用检查点"""
        return self.checkpointing

    def get_proxy(self) -> str | None:
        """获取代理设置"""
        return self.proxy

    def get_sandbox(self) -> SandboxConfig | None:
        """获取沙箱配置"""
        return self.sandbox

    def get_bug_command(self) -> BugCommandSettings | None:
        """获取bug命令设置"""
        return self.bug_command

    def get_extension_context_file_paths(self) -> list[str]:
        """获取扩展上下文文件路径"""
        return self.extension_context_file_paths

    # Service Methods
    def get_gemini_client(self) -> Any:
        """获取Gemini客户端"""
        return self._gemini_client

    def set_gemini_client(self, client: Any) -> None:
        """设置Gemini客户端"""
        self._gemini_client = client

    def get_content_generator_config(self) -> Any:
        """获取内容生成器配置"""
        return self._content_generator_config

    def set_content_generator_config(self, config: Any) -> None:
        """设置内容生成器配置"""
        self._content_generator_config = config

    def get_file_service(self) -> Any:
        """获取文件服务 - 延迟加载"""
        if not self._file_discovery_service:
            from ..services.file_discovery_service import FileDiscoveryService

            self._file_discovery_service = FileDiscoveryService(self.target_dir)
        return self._file_discovery_service

    async def get_git_service(self) -> Any:
        """获取Git服务 - 延迟加载"""
        if not self._git_service:
            from ..services.git_service import GitService

            self._git_service = GitService(self.target_dir)
            await self._git_service.initialize()
        return self._git_service
