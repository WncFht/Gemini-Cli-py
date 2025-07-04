import json
import logging
import time
from typing import Any

from gemini_cli_core.api.events import ToolCallRequestInfo
from gemini_cli_core.core.config import Config
from gemini_cli_core.core.events import EventEmitter
from gemini_cli_core.core.generators.base import ContentGenerator
from gemini_cli_core.core.graphs.states import ConversationState
from gemini_cli_core.core.types import Content, GeminiError, Part
from gemini_cli_core.telemetry.logger import (
    log_api_error,
    log_api_request,
    log_api_response,
)
from gemini_cli_core.utils.retry import retry_with_backoff

logger = logging.getLogger(__name__)


def is_valid_response(response: dict[str, Any]) -> bool:
    """
    检查模型响应是否有效

    Args:
        response: 从模型收到的响应

    Returns:
        如果响应有效则返回 True

    """
    if not response.get("candidates"):
        return False

    content = response["candidates"][0].get("content")
    if not content:
        return False

    return is_valid_content(content)


def is_valid_content(content: dict[str, Any]) -> bool:
    """
    检查内容对象是否有效

    Args:
        content: Content 对象

    Returns:
        如果内容有效则返回 True

    """
    parts = content.get("parts", [])
    if not parts:
        return False

    for part in parts:
        # part 不应为空对象
        if not part or not isinstance(part, dict):
            return False

        # 如果 part 不是思想（thought）且文本为空字符串，则视为无效
        if not part.get("thought") and part.get("text") == "":
            return False

    return True


def is_function_response(content: dict[str, Any]) -> bool:
    """Checks if the content is a function response."""
    parts = content.get("parts", [])
    return (
        content.get("role") == "user"
        and bool(parts)
        and all("function_response" in part for part in parts)
    )


def validate_history(history: list[Content]) -> None:
    """
    验证聊天历史记录中是否包含正确的角色

    Args:
        history: 聊天历史记录

    Raises:
        ValueError: 如果历史记录无效

    """
    if not history:
        return

    for content in history:
        if content["role"] not in ["user", "model", "function"]:
            raise ValueError(
                f"角色必须是 'user'、'model' 或 'function'，但得到的是 {content['role']}"
            )


def extract_curated_history(
    comprehensive_history: list[Content],
) -> list[Content]:
    """
    从完整的历史记录中提取经过筛选的（有效的）历史记录

    模型有时可能会生成无效或空的内容（例如，由于安全过滤器或背诵限制）
    从历史记录中提取有效的回合可以确保后续请求能被模型接受
    如果模型的响应无效，则其对应的用户输入也会被一并移除

    Args:
        comprehensive_history: 完整的聊天历史记录

    Returns:
        经过筛选的有效聊天历史记录

    """
    if not comprehensive_history:
        return []

    curated_history: list[Content] = []
    length = len(comprehensive_history)
    i = 0

    while i < length:
        if comprehensive_history[i]["role"] == "user":
            curated_history.append(comprehensive_history[i])
            i += 1
        else:
            model_output: list[Content] = []
            is_valid = True

            # 收集所有连续的模型输出
            while i < length and comprehensive_history[i]["role"] == "model":
                model_output.append(comprehensive_history[i])
                # 检查模型输出是否有效
                if is_valid and not is_valid_content(comprehensive_history[i]):
                    is_valid = False
                i += 1

            if is_valid:
                curated_history.extend(model_output)
            # 如果模型内容无效，则移除最后一个用户输入
            elif curated_history:
                curated_history.pop()

    return curated_history


class ChatNodeContext:
    """聊天节点的共享上下文"""

    def __init__(self, config: Config, emitter: EventEmitter):
        self.config = config
        self.emitter = emitter
        self.content_generator: ContentGenerator | None = None

    def set_content_generator(self, generator: ContentGenerator) -> None:
        """设置内容生成器"""
        self.content_generator = generator

    def get_content_generator(self) -> ContentGenerator:
        """获取内容生成器"""
        if not self.content_generator:
            raise GeminiError("内容生成器未初始化", "initialization_error")
        return self.content_generator


async def process_user_input_node(
    state: ConversationState,
    context: ChatNodeContext,
) -> ConversationState:
    """
    处理用户输入节点

    Args:
        state: 当前会话状态
        context: 节点上下文

    Returns:
        更新后的状态

    """
    logger.info("Processing user input")

    user_input = state.get("current_user_input", [])
    if not user_input:
        raise ValueError("没有用户输入")

    # 构建用户内容
    user_content: Content = {
        "role": "user",
        "parts": user_input,
    }

    # 添加到历史记录
    history = state.get("history", [])
    history.append(user_content)

    # 验证历史记录
    validate_history(history)

    state["history"] = history
    state["user_content"] = user_content

    return state


async def call_model_node(
    state: ConversationState,
    context: ChatNodeContext,
) -> ConversationState:
    """
    调用模型节点

    Args:
        state: 当前会话状态
        context: 节点上下文

    Returns:
        更新后的状态

    """
    logger.info("Calling model")

    # 获取筛选后的历史记录
    history = state.get("history", [])
    curated_history = extract_curated_history(history)

    # 准备请求内容
    request_contents = curated_history

    # 记录 API 请求
    await log_api_request(
        context.config,
        context.config.get_model(),
        _get_request_text_from_contents(request_contents),
    )

    start_time = time.time()

    try:
        # 获取工具声明
        tool_registry = await context.config.get_tool_registry()
        tool_declarations = tool_registry.get_function_declarations()
        tools = (
            [{"function_declarations": tool_declarations}]
            if tool_declarations
            else []
        )

        # 生成配置
        generation_config = {
            "temperature": 0,
            "top_p": 1,
        }

        # 如果模型支持思考功能
        if _is_thinking_supported(context.config.get_model()):
            generation_config["thinking_config"] = {
                "include_thoughts": True,
            }

        # 系统指令
        from gemini_cli_core.core.prompts import get_core_system_prompt

        user_memory = context.config.get_user_memory()
        system_instruction = get_core_system_prompt(user_memory)

        # 调用 API
        async def api_call():
            return (
                await context.get_content_generator().generate_content_stream(
                    model=context.config.get_model(),
                    config={
                        "generation_config": generation_config,
                        "system_instruction": system_instruction,
                        "tools": tools,
                    },
                    contents=request_contents,
                )
            )

        # 使用重试机制
        response_stream = await retry_with_backoff(
            api_call,
            auth_type=context.config.get_content_generator_config().get(
                "auth_type"
            ),
        )

        # 处理流式响应
        model_parts: list[Part] = []
        thinking_parts: list[Part] = []
        tool_calls: list[ToolCallRequestInfo] = []
        usage_metadata = None

        async for chunk in response_stream:
            # 提取部分内容
            if chunk.get("candidates"):
                candidate = chunk["candidates"][0]
                content = candidate.get("content", {})
                parts = content.get("parts", [])

                for part in parts:
                    # 处理思考内容
                    if part.get("thought"):
                        thinking_parts.append(part)
                        await context.emitter.emit_model_thinking(
                            part.get("text", ""),
                        )
                    # 处理函数调用
                    elif part.get("function_call"):
                        func_call = part["function_call"]
                        tool_call = ToolCallRequestInfo(
                            call_id=f"call_{len(tool_calls)}",
                            name=func_call["name"],
                            args=func_call.get("args", {}),
                            is_client_initiated=False,
                        )
                        tool_calls.append(tool_call)
                    # 处理普通文本
                    elif part.get("text"):
                        model_parts.append(part)
                        await context.emitter.emit_model_response(
                            part["text"],
                            streaming=True,
                        )
                    # 处理其他类型的部分
                    else:
                        model_parts.append(part)

            # 更新使用元数据
            if chunk.get("usage_metadata"):
                usage_metadata = chunk["usage_metadata"]

        # 记录 API 响应
        duration_ms = int((time.time() - start_time) * 1000)
        response_text = "".join(
            part.get("text", "") for part in model_parts if part.get("text")
        )

        await log_api_response(
            context.config,
            context.config.get_model(),
            duration_ms,
            usage_metadata,
            response_text,
        )

        # 构建模型响应内容并更新历史记录
        # A model turn can contain text parts and/or function call parts.
        model_turn_parts: list[Part] = []

        if model_parts:
            model_turn_parts.extend(model_parts)

        if tool_calls:
            for tc in tool_calls:
                model_turn_parts.append(
                    {"function_call": {"name": tc.name, "args": tc.args}}
                )

        if model_turn_parts:
            model_content: Content = {
                "role": "model",
                "parts": model_turn_parts,
            }
            history.append(model_content)
            state["history"] = history
        else:
            # Handle empty responses workaround from geminiChat.ts
            last_message = curated_history[-1] if curated_history else None
            is_after_tool_response = last_message and last_message.get(
                "role"
            ) in ["function", "tool"]
            if not is_after_tool_response:
                model_content: Content = {"role": "model", "parts": []}
                history.append(model_content)
                state["history"] = history

        # 更新状态
        state["current_model_response"] = response_text
        state["current_model_thinking"] = "".join(
            part.get("text", "") for part in thinking_parts if part.get("text")
        )
        state["pending_tool_calls"] = [tc.model_dump() for tc in tool_calls]
        state["usage_metadata"] = usage_metadata

        # Reset user input for the next turn
        state["current_user_input"] = None

        return state

    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        await log_api_error(
            context.config,
            context.config.get_model(),
            duration_ms,
            e,
        )
        raise


async def check_tool_calls_edge(state: ConversationState) -> str:
    """
    检查是否有工具调用的条件边

    Args:
        state: 当前会话状态

    Returns:
        下一个节点的名称

    """
    if state.get("pending_tool_calls"):
        return "execute_tools"
    return "check_continuation"


async def check_continuation_node(
    state: ConversationState, context: ChatNodeContext
) -> dict[str, Any]:
    """
    Checks if the conversation should continue automatically.
    This logic is migrated from `nextSpeakerChecker.ts`.
    """
    history = state.get("history", [])
    if not history:
        return {"next_step": "end"}

    last_message = history[-1]
    if last_message.get("role") != "model":
        # Check if the last message is a user turn with only function responses
        if is_function_response(last_message):
            return {"next_step": "continue"}
        return {"next_step": "end"}

    # Use LLM to check if it should continue
    check_prompt = """Analyze *only* the content and structure of your immediately preceding response. Based *strictly* on that response, determine who should logically speak next: the 'user' or the 'model' (you).
**Decision Rules (apply in order):**
1.  **Model Continues:** If your last response explicitly states an immediate next action *you* intend to take, OR if the response seems clearly incomplete, then the **'model'** should speak next.
2.  **Question to User:** If your last response ends with a direct question specifically addressed *to the user*, then the **'user'** should speak next.
3.  **Waiting for User:** If your last response completed a thought or task *and* does not meet the criteria for Rule 1 or 2, it implies a pause expecting user input. In this case, the **'user'** should speak next.
Respond *only* in JSON format: {"reasoning": "...", "next_speaker": "user" | "model"}
"""

    contents = history + [{"role": "user", "parts": [{"text": check_prompt}]}]

    try:
        response = await context.get_content_generator().generate_content(
            model=context.config.get_model(),
            config={},  # Simple config for this check
            contents=contents,
        )
        response_text = (
            response.get("candidates", [{}])[0]
            .get("content", {})
            .get("parts", [{}])[0]
            .get("text", "")
        )
        parsed = json.loads(response_text)

        if parsed.get("next_speaker") == "model":
            return {
                "next_step": "continue",
                "current_user_input": [{"text": "Please continue."}],
            }

    except Exception as e:
        logger.warning(f"Could not determine next speaker: {e}")

    return {"next_step": "end"}


def check_continuation_edge(state: ConversationState) -> str:
    """
    Conditional edge to determine if the conversation should continue.
    """
    return state.get("next_step", "end")


def _get_request_text_from_contents(contents: list[Content]) -> str:
    """
    从内容数组中提取所有文本部分并拼接成一个字符串

    Args:
        contents: 内容数组

    Returns:
        拼接后的文本字符串

    """
    text_parts = []
    for content in contents:
        for part in content.get("parts", []):
            if part.get("text"):
                text_parts.append(part["text"])

    return "".join(text_parts)


def _is_thinking_supported(model: str) -> bool:
    """
    检查模型是否支持"思考"功能

    Args:
        model: 模型名称

    Returns:
        如果支持则返回 True

    """
    return model.startswith("gemini-2.5")
