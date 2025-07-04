import asyncio
import logging
from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph
from langgraph.pregel import Pregel

from gemini_cli_core.core.cancellation import CancelSignal
from gemini_cli_core.core.config import Config
from gemini_cli_core.core.events import EventEmitter
from gemini_cli_core.core.graphs.states import ConversationState
from gemini_cli_core.core.graphs.tool_execution_graph import (
    create_tool_execution_graph,
)
from gemini_cli_core.core.nodes.chat_nodes import (
    ChatNodeContext,
    call_model_node,
    check_continuation_edge,
    check_continuation_node,
    check_tool_calls_edge,
    process_user_input_node,
)
from gemini_cli_core.core.prompts.system_prompts import get_compression_prompt
from gemini_cli_core.core.token_limits import token_limit
from gemini_cli_core.tools.base.registry import ToolRegistry

logger = logging.getLogger(__name__)


class ChatNodeContext:
    """Shared context for chat nodes."""

    def __init__(
        self, config: Config, emitter: EventEmitter, cancel_signal: CancelSignal
    ):
        self.config = config
        self.emitter = emitter
        self.cancel_signal = cancel_signal
        # ...


async def execute_tools_node(
    state: ConversationState,
    context: ChatNodeContext,
    tool_registry: ToolRegistry,
) -> dict[str, Any]:
    """
    Executes the tool execution subgraph to handle pending tool calls.
    """
    pending_calls = state.get("pending_tool_calls", [])
    if not pending_calls:
        return {}

    logger.info(f"Executing {len(pending_calls)} tool calls...")

    # Create and compile the tool execution graph, passing the cancel signal
    tool_graph = create_tool_execution_graph(
        context.config, context.emitter, tool_registry, context.cancel_signal
    )

    # Run the subgraph with the pending calls
    tool_state = {"incoming_requests": pending_calls}
    final_tool_state = await tool_graph.ainvoke(tool_state)

    # Process results and update history
    tool_results = final_tool_state.get("tool_calls", [])
    history = state.get("history", [])

    for call_result in tool_results:
        # We only care about completed calls (success, error, cancelled)
        if hasattr(call_result, "response") and call_result.response:
            response_parts = call_result.response.responseParts
            if response_parts:
                history.append({"role": "function", "parts": response_parts})

    # Clear pending calls and return updated history
    return {
        "history": history,
        "pending_tool_calls": [],
    }


async def compress_history_node(
    state: ConversationState,
    context: ChatNodeContext,
) -> ConversationState:
    """
    Compresses the conversation history if it exceeds a token threshold.
    This logic is migrated from `tryCompressChat` in `client.ts`.
    """
    logger.info("Compressing history...")
    history = state.get("history", [])
    if not history:
        return state

    # This part requires a content_generator instance in the context
    generator = context.get_content_generator()
    model = context.config.get_model()

    try:
        token_count_response = await generator.count_tokens(
            model=model, contents=history
        )
        original_token_count = token_count_response.get("totalTokens", 0)

        limit = token_limit(model)
        if not limit or original_token_count < 0.95 * limit:
            return state

        logger.info(
            f"History ({original_token_count} tokens) exceeds 95% of limit ({limit}). Compressing."
        )

        compression_prompt = get_compression_prompt()
        contents = history + [
            {"role": "user", "parts": [{"text": compression_prompt}]}
        ]

        # Using the main client's generate_content for summarization
        client = context.config.get_gemini_client()
        summary_response = await client.generate_content(
            contents=contents, generation_config={}, abort_signal=None
        )
        summary_text = client._get_response_text(summary_response)

        if not summary_text:
            logger.warning(
                "History compression failed: model did not return a summary."
            )
            return state

        new_history = [
            {"role": "user", "parts": [{"text": summary_text}]},
            {
                "role": "model",
                "parts": [{"text": "Got it. Thanks for the summary!"}],
            },
        ]

        # Optionally, emit a chat_compressed event
        context.emitter.emit(
            "chat_compressed",
            {
                "original_token_count": original_token_count,
                "new_token_count": "unknown",
            },
        )

        state["history"] = new_history
        return state

    except Exception as e:
        logger.error(f"Error during history compression: {e}")
        return state


def should_compress_edge(state: ConversationState) -> str:
    """
    Checks if the history should be compressed before calling the model.
    """
    # For now, we always go to compression node, which will then check the token count.
    # A more optimized way would be to pass token count in state.
    return "compress_history"


def create_conversation_graph(
    config: Config,
    emitter: EventEmitter,
    tool_registry: ToolRegistry,
    cancel_signal: CancelSignal,
) -> "EventAwareGraph":
    """
    创建对话图

    Args:
        config: 配置对象
        emitter: 事件发送器
        tool_registry: 工具注册表
        cancel_signal: 取消信号

    Returns:
        一个 EventAwareGraph 实例

    """
    # Create the context with the cancel signal
    context = ChatNodeContext(config, emitter, cancel_signal)

    # 创建状态图
    graph = StateGraph(ConversationState)
    checkpointer = MemorySaver()

    # 创建带上下文的节点函数
    process_input = partial(process_user_input_node, context=context)
    call_model = partial(call_model_node, context=context)
    execute_tools = partial(
        execute_tools_node, context=context, tool_registry=tool_registry
    )
    compress_history = partial(compress_history_node, context=context)
    check_continuation = partial(check_continuation_node, context=context)

    # 添加节点
    graph.add_node("process_input", process_input)
    graph.add_node("call_model", call_model)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("compress_history", compress_history)
    graph.add_node("check_continuation", check_continuation)

    # 添加边
    graph.add_edge(
        "process_input", "compress_history"
    )  # Check for compression first
    graph.add_edge("compress_history", "call_model")  # Then call model

    # 条件边
    graph.add_conditional_edges(
        "call_model",
        check_tool_calls_edge,
        {
            "execute_tools": "execute_tools",
            "check_continuation": "check_continuation",
        },
    )

    graph.add_conditional_edges(
        "check_continuation",
        check_continuation_edge,
        {"continue": "call_model", "__end__": END},
    )

    graph.add_edge("execute_tools", "call_model")  # 工具执行后回到模型

    # 设置入口点
    graph.set_entry_point("process_input")

    # 编译图
    compiled = graph.compile(checkpointer=checkpointer)

    # 包装以支持事件发送和上下文
    return EventAwareGraph(compiled, emitter, context)


class EventAwareGraph:
    """
    包装LangGraph以支持流式事件发送。
    它使用一个队列来从事件发射器接收事件，并让 astream 方法可以 yield 这些事件。
    """

    def __init__(
        self,
        graph: Pregel,
        emitter: EventEmitter,
        context: ChatNodeContext,
    ):
        self.graph = graph
        self.emitter = emitter
        self.context = context
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self._listener = self.emitter.on("*", self._queue_event)

    def _queue_event(self, event_name: str, event_data: Any) -> None:
        """事件监听器，将事件放入队列"""
        self.event_queue.put_nowait(event_data)

    async def astream(
        self, initial_state: dict[str, Any]
    ) -> AsyncIterator[Any]:
        """
        流式执行图，同时从队列中 yield 事件。
        """

        async def graph_runner():
            try:
                # astream返回的是状态更新，我们在这里仅消费它
                async for _ in self.graph.astream(initial_state):
                    pass
            except Exception as e:
                logger.error(f"Error in graph execution: {e}")
                await self.emitter.emit_error(e)
            finally:
                # 图执行完毕，向队列发送一个特殊信号
                await self.event_queue.put(None)

        # 启动图的执行
        graph_task = asyncio.create_task(graph_runner())

        # 从队列中 yield 事件，直到收到结束信号
        while True:
            event = await self.event_queue.get()
            if event is None:
                break
            yield event

        await graph_task

    def set_content_generator(self, generator):
        """设置内容生成器"""
        self.context.set_content_generator(generator)

    def cleanup(self):
        """清理资源，移除监听器"""
        self.emitter.off("*", self._listener)
