"""
LangGraph state definitions for Gemini CLI
"""

from typing import Any, Literal, TypedDict

from gemini_cli_core.core.types import (
    ApprovalMode,
    Content,
    ToolCallInfo,
    ToolCallRequest,
    ToolCallResponse,
    ToolConfirmationOutcome,
)


class ConversationState(TypedDict):
    """
    主对话状态 - 管理整个对话流程
    """

    # 基础信息
    session_id: str
    user_id: str | None
    model: str

    # 对话历史
    curated_history: list[Content]  # 筛选后的历史（发送给模型）
    comprehensive_history: list[Content]  # 完整历史（包含所有交互）

    # 当前交互
    current_user_input: str | None
    current_model_response: str | None
    current_model_thinking: str | None  # 思考内容

    # 工具调用
    pending_tool_calls: list[ToolCallRequest]
    tool_call_results: list[ToolCallResponse]

    # 控制标志
    needs_compression: bool  # 是否需要压缩历史
    continue_conversation: bool  # 是否继续对话（checkNextSpeaker结果）
    is_streaming: bool  # 是否正在流式输出
    is_cancelled: bool  # 是否已取消

    # 配置
    approval_mode: ApprovalMode
    environment_initialized: bool

    # Token管理
    total_tokens: int
    token_limit: int

    # 错误处理
    error: str | None
    error_details: dict[str, Any] | None

    # 元数据
    turn_count: int
    max_turns: int  # 默认100，防止无限循环


class ToolExecutionState(TypedDict):
    """
    工具执行子图状态 - 管理工具调用的生命周期
    """

    # 工具调用信息
    tool_calls: list[ToolCallInfo]  # 所有工具调用的完整信息

    # 状态映射
    tool_statuses: dict[str, str]  # call_id -> status

    # 批准相关
    awaiting_approval: list[str]  # 需要批准的call_ids
    user_decisions: dict[str, ToolConfirmationOutcome]  # call_id -> decision
    modified_args: dict[str, dict[str, Any]]  # call_id -> 修改后的参数

    # 执行结果
    execution_results: dict[str, ToolCallResponse]  # call_id -> result

    # 错误处理
    errors: dict[str, str]  # call_id -> error message

    # 配置
    approval_mode: ApprovalMode
    yolo_mode: bool  # 是否跳过所有确认

    # 白名单（会话级别）
    tool_allowlist: list[str]  # 永久批准的工具
    server_allowlist: list[str]  # 永久批准的MCP服务器


class CheckpointState(TypedDict):
    """
    检查点状态 - 用于保存和恢复会话
    """

    # 会话标识
    session_id: str
    checkpoint_id: str
    timestamp: str

    # 对话状态快照
    conversation_state: ConversationState

    # 元数据
    model: str
    turn_count: int
    total_tokens: int

    # 可选的用户标记
    label: str | None
    description: str | None


class CompressionState(TypedDict):
    """
    历史压缩状态 - 用于压缩子流程
    """

    # 原始历史
    original_history: list[Content]
    original_token_count: int

    # 压缩结果
    compressed_summary: str | None
    compressed_history: list[Content] | None
    new_token_count: int | None

    # 压缩元数据
    compression_ratio: float | None
    compression_method: Literal["xml_summary", "selective_history"]

    # 错误处理
    compression_error: str | None


class NextSpeakerCheckState(TypedDict):
    """
    下一个发言者检查状态
    """

    # 输入
    last_message: Content
    full_history: list[Content]

    # 分析结果
    next_speaker: Literal["user", "model"] | None
    reasoning: str | None

    # 特殊情况标记
    is_function_response: bool
    is_empty_model_response: bool
    has_direct_question: bool
    indicates_next_action: bool
