"""
Core type definitions for Gemini CLI
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal, TypedDict

from pydantic import BaseModel


# Event Types - 保持与TypeScript兼容
class GeminiEventType(str, Enum):
    """事件类型枚举 - 与TypeScript保持一致"""

    MODEL_THINKING = "model_thinking"
    MODEL_RESPONSE = "model_response"
    TOOL_CALLS_UPDATE = "tool_calls_update"
    ERROR = "error"
    TURN_COMPLETE = "turn_complete"
    CHAT_COMPRESSED = "chat_compressed"

    # WebSocket消息类型
    USER_INPUT = "user_input"
    TOOL_CONFIRMATION_RESPONSE = "tool_confirmation_response"
    CANCEL_STREAM = "cancel_stream"


# Tool Related Types
class ToolConfirmationOutcome(str, Enum):
    """工具确认结果"""

    PROCEED = "proceed"
    PROCEED_ALWAYS_TOOL = "proceed_always_tool"
    PROCEED_ALWAYS_SERVER = "proceed_always_server"  # MCP特有
    CANCEL = "cancel"
    MODIFY_WITH_EDITOR = "modify_with_editor"


class ApprovalMode(str, Enum):
    """批准模式"""

    DEFAULT = "default"  # 需要确认
    AUTO_EDIT = "autoEdit"  # 编辑类自动批准
    YOLO = "yolo"  # 全部自动批准


class ToolStatus(str, Enum):
    """工具调用状态"""

    VALIDATING = "validating"
    AWAITING_APPROVAL = "awaiting_approval"
    SCHEDULED = "scheduled"
    EXECUTING = "executing"
    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


# Message Types
class Part(TypedDict, total=False):
    """消息部分 - 与Gemini API兼容"""

    text: str | None
    inline_data: dict[str, Any] | None
    file_data: dict[str, Any] | None
    executable_code: dict[str, Any] | None
    code_execution_result: dict[str, Any] | None
    function_call: dict[str, Any] | None
    function_response: dict[str, Any] | None
    thought: bool | None


class Content(TypedDict):
    """对话内容"""

    role: Literal["user", "model", "function"]
    parts: list[Part]


# Tool Call Types
class ToolCallRequest(BaseModel):
    """工具调用请求"""

    call_id: str = field(default_factory=lambda: "")
    name: str
    args: dict[str, Any] = field(default_factory=dict)


class ToolCallResponse(BaseModel):
    """工具调用响应"""

    call_id: str
    response_parts: Part | list[Part]
    result_display: str | None = None
    error: str | None = None


class ToolCallInfo(BaseModel):
    """工具调用信息 - 用于前端显示"""

    call_id: str
    name: str
    display_name: str
    args: dict[str, Any]
    status: ToolStatus
    outcome: ToolConfirmationOutcome | None = None
    duration_ms: int | None = None
    error: str | None = None
    result: Any | None = None


# Configuration Types
@dataclass
class SandboxConfig:
    """沙箱配置"""

    command: Literal["docker", "podman", "sandbox-exec"]
    image: str = "gemini-cli-sandbox:latest"
    mounts: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    network: str | None = None


@dataclass
class MCPServerConfig:
    """MCP服务器配置"""

    # For stdio transport
    command: str | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    cwd: str | None = None

    # For SSE transport
    url: str | None = None

    # For HTTP transport
    http_url: str | None = None
    headers: dict[str, str] | None = None

    # For WebSocket transport
    tcp: str | None = None

    # Common
    timeout: int = 600000  # 10 minutes default
    trust: bool = False
    description: str | None = None


@dataclass
class BugCommandSettings:
    """Bug报告命令设置"""

    url_template: str


@dataclass
class TelemetrySettings:
    """遥测设置"""

    enabled: bool = False
    target: str = "local"
    otlp_endpoint: str = "localhost:4317"
    log_prompts: bool = True


@dataclass
class AccessibilitySettings:
    """可访问性设置"""

    disable_loading_phrases: bool = False


# Error Types
class GeminiError(Exception):
    """基础错误类"""

    def __init__(
        self,
        message: str,
        error_type: str = "unknown",
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.error_type = error_type
        self.details = details or {}


class ToolExecutionError(GeminiError):
    """工具执行错误"""

    def __init__(
        self,
        message: str,
        tool_name: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, "tool_execution", details)
        self.tool_name = tool_name


class ModelError(GeminiError):
    """模型调用错误"""

    def __init__(
        self, message: str, model: str, details: dict[str, Any] | None = None
    ):
        super().__init__(message, "model_error", details)
        self.model = model


class AuthenticationError(GeminiError):
    """认证错误"""

    def __init__(
        self,
        message: str,
        auth_type: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, "authentication", details)
        self.auth_type = auth_type


# WebSocket Message Types
class WebSocketMessage(BaseModel):
    """WebSocket消息基类"""

    type: str


class UserInputMessage(WebSocketMessage):
    """用户输入消息"""

    type: Literal["user_input"] = "user_input"
    value: str


class ToolConfirmationMessage(WebSocketMessage):
    """工具确认消息"""

    type: Literal["tool_confirmation_response"] = "tool_confirmation_response"
    call_id: str
    outcome: ToolConfirmationOutcome


class CancelStreamMessage(WebSocketMessage):
    """取消流消息"""

    type: Literal["cancel_stream"] = "cancel_stream"


# Server Event Types
class ServerGeminiStreamEvent(BaseModel):
    """服务器流事件 - 保持驼峰命名以兼容前端"""

    type: GeminiEventType
    value: Any

    class Config:
        # 保持驼峰命名
        alias_generator = lambda field_name: "".join(
            word.capitalize() if i > 0 else word
            for i, word in enumerate(field_name.split("_"))
        )
        populate_by_name = True


# Compression Types
class ChatCompressionInfo(BaseModel):
    """聊天压缩信息"""

    original_token_count: int
    new_token_count: int


# Next Speaker Types
class NextSpeakerResponse(BaseModel):
    """下一个发言者响应"""

    reasoning: str
    next_speaker: Literal["user", "model"]
