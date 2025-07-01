"""
Conversation graph implementation using LangGraph
"""

import logging
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.graph import CompiledGraph

from ..core import Config, EventEmitter
from ..graphs.states import ConversationState

logger = logging.getLogger(__name__)


async def process_user_input(state: ConversationState) -> ConversationState:
    """处理用户输入节点"""
    logger.info(f"Processing user input: {state.get('current_user_input')}")

    # TODO: 实际实现
    # 1. 将用户输入添加到历史
    # 2. 准备发送给模型

    return state


async def call_model(state: ConversationState) -> ConversationState:
    """调用模型节点"""
    logger.info("Calling model...")

    # TODO: 实际实现
    # 1. 调用Gemini模型
    # 2. 处理流式响应
    # 3. 提取工具调用

    # 临时响应
    state["current_model_response"] = (
        "这是一个临时响应。完整的模型集成将在下一阶段实现。"
    )

    return state


async def check_tool_calls(state: ConversationState) -> str:
    """检查是否有工具调用的条件边"""
    if state.get("pending_tool_calls"):
        return "execute_tools"
    return "check_continuation"


async def execute_tools(state: ConversationState) -> ConversationState:
    """执行工具节点"""
    logger.info(
        f"Executing {len(state.get('pending_tool_calls', []))} tool calls"
    )

    # TODO: 实际实现
    # 1. 创建工具执行子图
    # 2. 处理批准流程
    # 3. 执行工具
    # 4. 收集结果

    return state


async def check_continuation(state: ConversationState) -> str:
    """检查是否继续对话的条件边"""
    # TODO: 实现checkNextSpeaker逻辑

    # 暂时总是结束
    return "end"


async def compress_history(state: ConversationState) -> ConversationState:
    """压缩历史节点"""
    logger.info("Compressing history...")

    # TODO: 实际实现
    # 1. 检查token使用量
    # 2. 生成历史摘要
    # 3. 更新历史

    return state


def create_conversation_graph(
    config: Config, emitter: EventEmitter
) -> CompiledGraph:
    """
    创建对话图

    Args:
        config: 配置对象
        emitter: 事件发送器

    Returns:
        编译后的LangGraph图

    """
    # 创建状态图
    graph = StateGraph(ConversationState)

    # 添加节点
    graph.add_node("process_input", process_user_input)
    graph.add_node("call_model", call_model)
    graph.add_node("execute_tools", execute_tools)
    graph.add_node("compress_history", compress_history)

    # 添加边
    graph.add_edge("process_input", "call_model")

    # 条件边
    graph.add_conditional_edges(
        "call_model",
        check_tool_calls,
        {
            "execute_tools": "execute_tools",
            "check_continuation": END,
        },
    )

    graph.add_conditional_edges(
        "execute_tools",
        check_continuation,
        {
            "continue": "call_model",
            "end": END,
        },
    )

    # 设置入口点
    graph.set_entry_point("process_input")

    # 编译图
    compiled = graph.compile()

    # 包装以支持事件发送
    return EventAwareGraph(compiled, emitter)


class EventAwareGraph:
    """包装LangGraph以支持事件发送"""

    def __init__(self, graph: CompiledGraph, emitter: EventEmitter):
        self.graph = graph
        self.emitter = emitter

    async def astream(self, initial_state: dict[str, Any]):
        """流式执行图并发送事件"""
        try:
            async for state in self.graph.astream(initial_state):
                # 发送状态更新事件
                if state.get("current_model_response"):
                    await self.emitter.emit_model_response(
                        state["current_model_response"],
                        streaming=True,
                    )

                if state.get("current_model_thinking"):
                    await self.emitter.emit_model_thinking(
                        state["current_model_thinking"],
                    )

                if state.get("pending_tool_calls"):
                    # 转换工具调用格式
                    tool_calls = [
                        {
                            "callId": tc.get("call_id"),
                            "name": tc.get("name"),
                            "args": tc.get("args", {}),
                            "status": "scheduled",
                        }
                        for tc in state["pending_tool_calls"]
                    ]
                    await self.emitter.emit_tool_calls_update(tool_calls)

                yield state

        except Exception as e:
            logger.exception(f"Error in graph execution: {e}")
            await self.emitter.emit_error(e)
            raise
