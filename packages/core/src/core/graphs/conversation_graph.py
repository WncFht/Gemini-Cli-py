"""
Conversation graph implementation using LangGraph
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from functools import partial
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.graph import CompiledGraph

from ...tools.registry import ToolRegistry
from ..core import Config, EventEmitter
from ..graphs.states import ConversationState
from ..graphs.tool_execution_graph import create_tool_execution_graph
from ..nodes.chat_nodes import (
    ChatNodeContext,
    call_model_node,
    check_continuation_edge,
    check_tool_calls_edge,
    process_user_input_node,
)

logger = logging.getLogger(__name__)


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

    # Create and compile the tool execution graph
    tool_graph = create_tool_execution_graph(
        context.config, context.emitter, tool_registry
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
    """压缩历史节点"""
    logger.info("Compressing history...")

    # TODO: 实际实现
    # 1. 检查token使用量
    # 2. 生成历史摘要
    # 3. 更新历史

    return state


def create_conversation_graph(
    config: Config, emitter: EventEmitter, tool_registry: ToolRegistry
) -> "EventAwareGraph":
    """
    创建对话图

    Args:
        config: 配置对象
        emitter: 事件发送器
        tool_registry: 工具注册表

    Returns:
        一个 EventAwareGraph 实例

    """
    # 创建节点上下文
    context = ChatNodeContext(config, emitter)

    # 创建状态图
    graph = StateGraph(ConversationState)

    # 创建带上下文的节点函数
    process_input = partial(process_user_input_node, context=context)
    call_model = partial(call_model_node, context=context)
    execute_tools = partial(
        execute_tools_node, context=context, tool_registry=tool_registry
    )
    compress_history = partial(compress_history_node, context=context)

    # 添加节点
    graph.add_node("process_input", process_input)
    graph.add_node("call_model", call_model)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("compress_history", compress_history)

    # 添加边
    graph.add_edge("process_input", "call_model")

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
    compiled = graph.compile()

    # 包装以支持事件发送和上下文
    return EventAwareGraph(compiled, emitter, context)


class EventAwareGraph:
    """
    包装LangGraph以支持流式事件发送。
    它使用一个队列来从事件发射器接收事件，并让 astream 方法可以 yield 这些事件。
    """

    def __init__(
        self,
        graph: CompiledGraph,
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
