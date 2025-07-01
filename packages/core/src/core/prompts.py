"""
Prompt templates for Gemini CLI
"""

from ..core.types import Content


def get_core_system_prompt(
    user_memory: str | None = None,
    additional_context: str | None = None,
) -> str:
    """
    获取核心系统提示词

    Args:
        user_memory: 用户记忆/偏好
        additional_context: 额外上下文（如GEMINI.md内容）

    Returns:
        系统提示词

    """
    prompt_parts = []

    # 基础系统提示
    prompt_parts.append("""You are an AI assistant powered by Google's Gemini model.
You have access to various tools to help complete tasks, including:
- File operations (read, write, edit files)
- Shell commands execution
- Web searching and browsing
- Code analysis and generation
- Git operations
- And more specialized tools

When using tools:
1. Always explain what you're about to do before using a tool
2. Show relevant results after tool execution
3. Handle errors gracefully and suggest alternatives
4. Ask for clarification when needed

Be helpful, accurate, and concise in your responses.""")

    # 添加用户记忆
    if user_memory:
        prompt_parts.append(f"\nUser preferences and context:\n{user_memory}")

    # 添加额外上下文
    if additional_context:
        prompt_parts.append(f"\nAdditional context:\n{additional_context}")

    return "\n\n".join(prompt_parts)


def get_compression_prompt(
    history: list[Content],
    max_summary_length: int = 2000,
) -> str:
    """
    获取历史压缩提示词

    Args:
        history: 对话历史
        max_summary_length: 最大摘要长度

    Returns:
        压缩提示词

    """
    # 将历史转换为文本
    history_text = _format_history_for_compression(history)

    return f"""Please create a concise summary of the following conversation history.
The summary should:
1. Capture the main topics discussed
2. Include key decisions and outcomes
3. Preserve important context for future interactions
4. Be structured in clear sections

Maximum length: {max_summary_length} characters

Format the summary as XML:
<summary>
  <topics>
    <topic>...</topic>
    ...
  </topics>
  <key_points>
    <point>...</point>
    ...
  </key_points>
  <context>
    <item>...</item>
    ...
  </context>
</summary>

Conversation history:
{history_text}"""


def get_next_speaker_prompt(
    last_message: Content,
    conversation_context: str | None = None,
) -> str:
    """
    获取下一个发言者检查提示词

    Args:
        last_message: 最后一条消息
        conversation_context: 对话上下文摘要

    Returns:
        检查提示词

    """
    # 格式化最后的消息
    last_message_text = _format_content(last_message)

    return f"""Analyze the last message in this conversation and determine who should speak next.

Consider:
1. Does the message end with a question that needs a user response?
2. Does the message indicate completion of the current task?
3. Does the message suggest follow-up actions that can be taken autonomously?
4. Is the message a tool/function response that needs processing?

Last message:
Role: {last_message.get("role")}
Content: {last_message_text}

{f"Conversation context: {conversation_context}" if conversation_context else ""}

Respond in JSON format:
{{
  "reasoning": "Your analysis of the situation",
  "next_speaker": "user" or "model"
}}"""


def get_error_handling_prompt(error: Exception, context: str) -> str:
    """
    获取错误处理提示词

    Args:
        error: 错误对象
        context: 错误上下文

    Returns:
        错误处理提示词

    """
    return f"""An error occurred during execution:

Error Type: {type(error).__name__}
Error Message: {error!s}
Context: {context}

Please:
1. Explain what went wrong in simple terms
2. Suggest potential solutions or workarounds
3. Indicate if you can continue with an alternative approach
4. Ask for user guidance if needed"""


def get_tool_selection_prompt(
    user_request: str,
    available_tools: list[str],
    recent_context: str | None = None,
) -> str:
    """
    获取工具选择提示词

    Args:
        user_request: 用户请求
        available_tools: 可用工具列表
        recent_context: 最近的上下文

    Returns:
        工具选择提示词

    """
    tools_list = "\n".join(f"- {tool}" for tool in available_tools)

    return f"""Based on the user's request, select the appropriate tools to use.

User request: {user_request}

Available tools:
{tools_list}

{f"Recent context: {recent_context}" if recent_context else ""}

Consider:
1. Which tools are most relevant to the request?
2. What sequence of tools might be needed?
3. Are there any prerequisites or dependencies?

Explain your tool selection reasoning before making the calls."""


# Helper functions
def _format_history_for_compression(history: list[Content]) -> str:
    """格式化历史记录用于压缩"""
    formatted_parts = []

    for content in history:
        role = content.get("role", "unknown")
        parts = content.get("parts", [])

        message_text = _format_parts(parts)
        if message_text:
            formatted_parts.append(f"[{role}]: {message_text}")

    return "\n\n".join(formatted_parts)


def _format_content(content: Content) -> str:
    """格式化单个内容项"""
    parts = content.get("parts", [])
    return _format_parts(parts)


def _format_parts(parts: list[dict]) -> str:
    """格式化消息部分"""
    text_parts = []

    for part in parts:
        if "text" in part:
            text_parts.append(part["text"])
        elif "function_call" in part:
            func_call = part["function_call"]
            text_parts.append(
                f"[Function Call: {func_call.get('name', 'unknown')}("
                f"{func_call.get('args', {})})]",
            )
        elif "function_response" in part:
            func_resp = part["function_response"]
            text_parts.append(
                f"[Function Response: {func_resp.get('name', 'unknown')} - "
                f"{func_resp.get('response', 'no response')}]",
            )

    return " ".join(text_parts)
