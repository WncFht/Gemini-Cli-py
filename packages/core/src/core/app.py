"""
应用管理器 - 从 client.ts 迁移的核心功能
管理聊天会话、初始化环境上下文、处理消息发送等
"""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from ..core.config import Config
from ..core.events import EventEmitter, ServerGeminiStreamEvent
from ..core.types import (
    ChatCompressionInfo,
    Content,
    GeminiError,
    GeminiEventType,
    Part,
)
from ..graphs.conversation import create_conversation_graph
from ..graphs.states import ConversationState
from ..graphs.tool_execution_graph import (
    ToolExecutionState,
    create_tool_execution_graph,
)
from ..tools.common import ToolConfirmationOutcome
from ..utils.errors import get_error_message, report_error
from ..utils.retry import retry_with_backoff
from ..utils.token_limits import token_limit
from .generators.base import ContentGenerator, ContentGeneratorConfig
from .generators.gemini_generator import create_content_generator
from .prompts import get_core_system_prompt

logger = logging.getLogger(__name__)


class GeminiClient:
    """
    与 Gemini API 交互的顶层客户端
    负责管理聊天会话、初始化环境上下文、发送消息、处理流式响应等
    """

    def __init__(self, config: Config) -> None:
        self.config = config
        self.content_generator: ContentGenerator | None = None
        self.conversation_graph = None
        self.emitter = EventEmitter()
        self.model = config.get_model()
        self.embedding_model = config.get_embedding_model()
        self.generate_content_config = {
            "temperature": 0,
            "top_p": 1,
        }
        self.MAX_TURNS = 100
        self._conversation_state = ConversationState()
        self._history: list[Content] = []
        self._current_tool_execution_state: ToolExecutionState | None = None

    async def initialize(
        self, content_generator_config: ContentGeneratorConfig
    ) -> None:
        """
        异步初始化客户端，创建 ContentGenerator 和会话图实例
        这是客户端可以工作前必须调用的方法
        """
        self.content_generator = await create_content_generator(
            content_generator_config
        )
        tool_registry = await self.config.get_tool_registry()
        self.conversation_graph = create_conversation_graph(
            self.config, self.emitter, tool_registry
        )
        self.conversation_graph.set_content_generator(self.content_generator)
        await self._start_chat()

    def get_content_generator(self) -> ContentGenerator:
        """获取 ContentGenerator 实例，如果未初始化则抛出错误"""
        if not self.content_generator:
            raise GeminiError("内容生成器未初始化", "initialization_error")
        return self.content_generator

    async def add_history(self, content: Content) -> None:
        """向当前聊天会话添加一条历史记录"""
        self._history.append(content)
        self._conversation_state.history = self._history

    async def get_history(self) -> list[Content]:
        """获取当前聊天会话的历史记录"""
        return self._history.copy()

    async def set_history(self, history: list[Content]) -> None:
        """设置当前聊天会话的历史记录"""
        self._history = history.copy()
        self._conversation_state.history = self._history

    async def reset_chat(self) -> None:
        """重置聊天会话，会重新初始化环境上下文和历史记录"""
        await self._start_chat()

    async def _get_environment(self) -> list[Part]:
        """
        构建并返回初始的环境上下文，作为与模型对话的开场白
        包括日期、操作系统、工作目录、文件结构等信息
        """
        from ..utils.folder_structure import get_folder_structure

        cwd = self.config.get_working_dir()
        today = datetime.now().strftime("%Y年%m月%d日 %A")
        platform = self.config.get_platform()

        folder_structure = await get_folder_structure(
            cwd, file_service=self.config.get_file_service()
        )

        context = f"""
这是 Gemini CLI。我们正在为聊天设置上下文。
今天的日期是 {today}。
我的操作系统是：{platform}
我当前的工作目录是：{cwd}
{folder_structure}
        """.strip()

        initial_parts: list[Part] = [{"text": context}]

        # 如果设置了 fullContext 标志，则添加完整的文件上下文
        if self.config.get_full_context():
            try:
                tool_registry = await self.config.get_tool_registry()
                read_many_files_tool = tool_registry.get_tool("read_many_files")

                if read_many_files_tool:
                    # 读取目标目录中的所有文件
                    result = await read_many_files_tool.execute(
                        {
                            "paths": ["**/*"],  # 递归读取所有文件
                            "useDefaultExcludes": True,  # 使用默认排除项
                        },
                        timeout=30,
                    )
                    if result.get("llm_content"):
                        initial_parts.append(
                            {
                                "text": f"\n--- 完整文件上下文 ---\n{result['llm_content']}"
                            }
                        )
                    else:
                        logger.warning(
                            "请求了完整上下文，但 read_many_files 没有返回任何内容。"
                        )
                else:
                    logger.warning(
                        "请求了完整上下文，但未找到 read_many_files 工具。"
                    )
            except Exception as e:
                logger.error(f"读取完整文件上下文时出错: {e}")
                initial_parts.append(
                    {"text": "\n--- 读取完整文件上下文时出错 ---"}
                )

        return initial_parts

    async def _start_chat(
        self, extra_history: list[Content] | None = None
    ) -> None:
        """
        启动一个新的聊天会话

        Args:
            extra_history: 可选的额外历史记录，会附加在初始环境上下文之后

        """
        env_parts = await self._get_environment()

        # 初始历史记录包含环境上下文，以及一个模型的确认响应
        initial_history: list[Content] = [
            {
                "role": "user",
                "parts": env_parts,
            },
            {
                "role": "model",
                "parts": [{"text": "好的，感谢提供上下文！"}],
            },
        ]

        if extra_history:
            initial_history.extend(extra_history)

        self._history = initial_history
        self._conversation_state = ConversationState(
            history=initial_history,
        )

    def _is_thinking_supported(self, model: str) -> bool:
        """检查模型是否支持"思考"功能"""
        return model.startswith("gemini-2.5")

    async def send_message_stream(
        self,
        request: list[Part],
        signal: asyncio.Event | None = None,
        turns: int = None,
    ) -> AsyncGenerator[ServerGeminiStreamEvent, None]:
        """
        Sends a streaming message. This is the main entry point for interaction
        with the model. It manages the automatic multi-turn conversation flow.
        """
        if turns is None:
            turns = self.MAX_TURNS

        if not turns:
            # Prevent infinite recursion
            return

        # Try to compress chat history
        try:
            compressed = await self._try_compress_chat()
            if compressed:
                yield ServerGeminiStreamEvent(
                    type=GeminiEventType.CHAT_COMPRESSED,
                    value=compressed.model_dump(),
                )
        except Exception as e:
            logger.error(f"Error during chat compression: {e}")
            # Decide if we should yield an error event and stop
            # For now, we log and continue

        # Update conversation state
        self._conversation_state.current_user_input = request

        # Run the conversation graph
        try:
            # The graph's astream now yields events directly.
            async for event in self.conversation_graph.astream(
                self._conversation_state.model_dump()
            ):
                # The graph now internally handles the continuation logic,
                # so we just yield the events.
                if event.type == GeminiEventType.TOOL_CALL_CONFIRMATION:
                    # Graph is about to interrupt. Store the current tool state.
                    self._current_tool_execution_state = (
                        ToolExecutionState.model_validate(event.value)
                    )

                yield event

        except Exception as e:
            logger.error(f"Error in send_message_stream: {e}")
            await self.emitter.emit_error(e)
            # The graph's astream should handle yielding the error event
            # based on the emitter. Raising here would be redundant if so.

    async def handle_tool_confirmation(
        self, call_id: str, outcome: ToolConfirmationOutcome
    ) -> AsyncGenerator[ServerGeminiStreamEvent, None]:
        """
        Handles the user's confirmation response for a tool call and resumes the graph.
        """
        if not self._current_tool_execution_state:
            raise GeminiError(
                "No tool execution state found to handle confirmation.",
                "invalid_state",
            )

        # Find and update the tool call based on user outcome
        updated_calls = []
        call_found = False
        for call in self._current_tool_execution_state.tool_calls:
            if (
                call.request.request.call_id == call_id
                and call.status == "awaiting_approval"
            ):
                call_found = True
                if outcome == ToolConfirmationOutcome.APPROVE:
                    # Transition to scheduled
                    call.status = "scheduled"
                else:  # CANCEL or MODIFY (for now, treat as cancel)
                    # Transition to cancelled
                    call.status = "cancelled"
                    # TODO: Add response part for cancellation
                call.outcome = outcome
            updated_calls.append(call)

        if not call_found:
            raise GeminiError(
                f"Could not find waiting tool call with id {call_id} to update.",
                "not_found",
            )

        self._current_tool_execution_state.tool_calls = updated_calls

        # Resume the tool execution graph
        tool_graph = create_tool_execution_graph(
            self.config, self.emitter, await self.config.get_tool_registry()
        )
        final_tool_state = await tool_graph.ainvoke(
            self._current_tool_execution_state.model_dump(),
        )
        self._current_tool_execution_state = None  # Clear the state

        # Add tool results back to the main conversation history
        tool_results = final_tool_state.get("tool_calls", [])
        for call_result in tool_results:
            if hasattr(call_result, "response") and call_result.response:
                response_parts = call_result.response.responseParts
                if response_parts:
                    self._history.append(
                        {"role": "function", "parts": response_parts}
                    )

        # Continue the main conversation graph from where it left off
        self._conversation_state.history = self._history
        self._conversation_state.pending_tool_calls = []

        async for event in self.conversation_graph.astream(
            self._conversation_state.model_dump(),
            {"recursion_limit": self.MAX_TURNS},
        ):
            yield event

    @retry_with_backoff()
    async def generate_json(
        self,
        contents: list[Content],
        schema: dict[str, Any],
        abort_signal: asyncio.Event | None = None,
        model: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Requests the model to generate a JSON object based on the provided schema.
        """
        user_memory = self.config.get_user_memory()
        system_instruction = get_core_system_prompt(user_memory)

        request_config = {
            **self.generate_content_config,
            **(config or {}),
            "system_instruction": system_instruction,
            "response_schema": schema,
            "response_mime_type": "application/json",
        }

        result = await self.get_content_generator().generate_content(
            model=model or self.model,
            config=request_config,
            contents=contents,
        )

        response_text = self._get_response_text(result)
        if not response_text:
            error = GeminiError(
                "API in generateJson returned an empty response.",
                "empty_response",
            )
            await report_error(
                error,
                "Error in generateJson: API returned empty response.",
                contents,
                "generateJson-empty-response",
            )
            raise error

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            await report_error(
                e,
                "Failed to parse JSON response from generateJson.",
                {
                    "responseTextFailedToParse": response_text,
                    "originalRequestContents": contents,
                },
                "generateJson-parse",
            )
            raise GeminiError(
                f"Failed to parse API response as JSON: {get_error_message(e)}",
                "json_parse_error",
            ) from e

    @retry_with_backoff()
    async def generate_content(
        self,
        contents: list[Content],
        generation_config: dict[str, Any],
        abort_signal: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        """
        A general-purpose, non-chat content generation method.
        """
        model_to_use = self.model
        config_to_use = {**self.generate_content_config, **generation_config}

        user_memory = self.config.get_user_memory()
        system_instruction = get_core_system_prompt(user_memory)
        request_config = {
            **config_to_use,
            "system_instruction": system_instruction,
        }

        return await self.get_content_generator().generate_content(
            model=model_to_use, config=request_config, contents=contents
        )

    async def generate_embedding(self, texts: list[str]) -> list[list[float]]:
        """
        为给定的文本数组生成嵌入向量

        Args:
            texts: 需要生成嵌入的字符串数组

        Returns:
            包含嵌入向量的二维数组

        """
        if not texts:
            return []

        embed_response = await self.get_content_generator().embed_content(
            model=self.embedding_model,
            contents=[{"role": "user", "parts": [{"text": t} for t in texts]}],
        )

        if not embed_response.get("embedding"):
            raise GeminiError("API 响应中未找到嵌入。", "missing_embeddings")

        return embed_response["embedding"]["values"]

    async def _try_compress_chat(
        self, force: bool = False
    ) -> ChatCompressionInfo | None:
        """
        尝试压缩聊天历史

        Args:
            force: 是否强制压缩

        Returns:
            压缩信息，如果没有压缩则返回 None

        """
        from .nodes.chat_nodes import extract_curated_history

        history = self._conversation_state.history
        curated_history = extract_curated_history(history)

        if not curated_history:
            return None

        token_count_response = await self.get_content_generator().count_tokens(
            model=self.model, contents=curated_history
        )
        original_token_count = token_count_response.get("totalTokens")

        if original_token_count is None:
            logger.warning(
                f"无法确定模型 {self.model} 的 token 数量。跳过压缩检查。"
            )
            return None

        limit = token_limit(self.model)
        if not limit:
            logger.warning(
                f"模型 {self.model} 没有定义 token 限制。跳过压缩检查。"
            )
            return None

        if not force and original_token_count < 0.95 * limit:
            return None

        logger.info("聊天历史记录超出 token 限制，正在尝试压缩。")

        # Create summarization request
        summarization_request = {
            "text": "Please summarize our conversation so far. The summary should be a concise but comprehensive overview of all key topics, questions, answers, and important details discussed. This summary will replace the current chat history to save tokens, so it must capture all the necessary elements for us to understand the context and continue our conversation as if no information was lost."
        }
        summarization_contents = curated_history + [
            {"role": "user", "parts": [summarization_request]}
        ]

        summary_response = await self.generate_content(
            contents=summarization_contents,
            generation_config={},
            abort_signal=None,
        )
        summary_text = self._get_response_text(summary_response)

        if not summary_text:
            logger.warning("聊天历史压缩失败：模型没有返回摘要。")
            return None

        # Reset chat with the summary
        summary_history = [
            {"role": "user", "parts": [{"text": summary_text}]},
            {
                "role": "model",
                "parts": [{"text": "好的，感谢提供上下文！"}],
            },
        ]
        await self._start_chat(extra_history=summary_history)

        # Count new tokens
        new_token_count_response = (
            await self.get_content_generator().count_tokens(
                model=self.model, contents=self._history
            )
        )
        new_token_count = new_token_count_response.get("totalTokens")

        if new_token_count is None:
            logger.warning("无法确定压缩后历史记录的 token 数量。")
            return None

        compression_info = ChatCompressionInfo(
            originalTokenCount=original_token_count,
            newTokenCount=new_token_count,
        )

        logger.info(
            f"聊天历史已压缩。从 {original_token_count} 到 {new_token_count} 个 token。"
        )
        return compression_info

    async def _handle_flash_fallback(
        self, auth_type: str | None = None
    ) -> str | None:
        """Handles fallback to the Flash model for persistent 429 errors."""
        # This logic is based on `handleFlashFallback` in the TypeScript version.
        # It's simplified here to be part of the client, not a separate handler in config.
        if (
            auth_type != "oauth-personal"
        ):  # Assuming AuthType.LOGIN_WITH_GOOGLE_PERSONAL
            return None

        current_model = self.model
        fallback_model = "gemini-2.0-flash"  # Assuming a default fallback

        if current_model == fallback_model:
            return None

        logger.warning(
            f"Persistent 429 errors with {current_model}. "
            f"Consider switching to a fallback like {fallback_model}."
        )
        # In a real CLI, we might prompt the user here. For now, we auto-switch.
        # This is a deviation from the TS code that has a `flashFallbackHandler`.
        self.model = fallback_model
        return fallback_model

    def _get_response_text(self, response: dict[str, Any]) -> str | None:
        """从响应中提取文本"""
        candidates = response.get("candidates", [])
        if not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        if not parts:
            return None

        return parts[0].get("text")
