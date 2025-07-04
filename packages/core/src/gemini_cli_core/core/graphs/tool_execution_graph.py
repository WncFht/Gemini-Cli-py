"""
This file is refactored from packages/core_ts/src/core/coreToolScheduler.ts.

It defines the graph for executing tool calls, managing validation,
approval, and execution of tools.
"""

import asyncio
import time
from functools import partial
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, CompiledGraph, StateGraph

from gemini_cli_core.api.events import (
    ServerGeminiToolCallConfirmationEvent,
    ServerToolCallConfirmationDetails,
    ToolCallResponseInfo,
)
from gemini_cli_core.core.cancellation import CancelSignal
from gemini_cli_core.core.config import Config
from gemini_cli_core.core.events import EventEmitter
from gemini_cli_core.core.nodes.tool_nodes import (
    CompletedToolCall,
    ErroredToolCall,
    ScheduledToolCall,
    SuccessfulToolCall,
    ToolCall,
    ToolExecutionState,
    ValidatingToolCall,
    WaitingToolCall,
)
from gemini_cli_core.core.types import ApprovalMode
from gemini_cli_core.tools.base import ToolRegistry, ToolResult


class ToolNodeContext:
    """Shared context for tool execution nodes."""

    def __init__(
        self,
        config: Config,
        emitter: EventEmitter,
        tool_registry: ToolRegistry,
        cancel_signal: CancelSignal,
    ):
        self.config = config
        self.emitter = emitter
        self.tool_registry = tool_registry
        self.cancel_signal = cancel_signal


def create_error_response(request, error: Exception) -> ToolCallResponseInfo:
    """Creates a ToolCallResponseInfo for an error."""
    return ToolCallResponseInfo(
        callId=request.call_id,
        error=str(error),
        responseParts={
            "functionResponse": {
                "id": request.call_id,
                "name": request.name,
                "response": {"error": str(error)},
            }
        },
        resultDisplay=str(error),
    )


def convert_to_function_response(
    tool_name: str, call_id: str, llm_content: Any
) -> list[dict[str, Any]]:
    """
    Converts tool result content to a format consumable by the Gemini API.
    A simplified version of the logic in coreToolScheduler.ts.
    """

    def create_part(output: str) -> dict[str, Any]:
        return {
            "functionResponse": {
                "id": call_id,
                "name": tool_name,
                "response": {"output": output},
            }
        }

    if isinstance(llm_content, str):
        return [create_part(llm_content)]
    if isinstance(llm_content, list):
        # Assuming it's a list of parts, pass it through.
        return llm_content
    if isinstance(llm_content, dict):
        # Assuming it's a single part, wrap in a list.
        return [llm_content]

    # Default fallback
    return [create_part("Tool execution succeeded.")]


async def execute_single_tool(
    call: ScheduledToolCall, context: ToolNodeContext
) -> CompletedToolCall:
    """Executes a single scheduled tool call."""
    start_time = time.time()

    def live_output_callback(output_chunk: str):
        """Callback to emit live tool output."""
        event_data = {
            "type": "tool_log",
            "payload": {
                "callId": call.request.request.call_id,
                "output": output_chunk,
            },
        }
        context.emitter.emit("tool_log", event_data)

    try:
        # Pass the cancel signal to the tool execution method
        tool_result: ToolResult = await call.tool.execute(
            call.request.args,
            context.cancel_signal,
            live_output_callback,
        )

        response_parts = convert_to_function_response(
            call.request.name,
            call.request.request.call_id,
            tool_result.llm_content,
        )

        response_info = ToolCallResponseInfo(
            callId=call.request.request.call_id,
            responseParts=response_parts,
            resultDisplay=tool_result.return_display,
        )

        return SuccessfulToolCall(
            request=call.request,
            tool=call.tool,
            response=response_info,
            duration_ms=(time.time() - start_time) * 1000,
            outcome=call.outcome,
        )
    except Exception as e:
        response_info = create_error_response(call.request, e)
        return ErroredToolCall(
            request=call.request,
            response=response_info,
            duration_ms=(time.time() - start_time) * 1000,
            outcome=call.outcome,
        )


async def schedule_tools_node(
    state: ToolExecutionState, context: ToolNodeContext
) -> dict[str, Any]:
    """
    Node to validate and schedule tool calls.
    Corresponds to the `schedule` method in CoreToolScheduler.
    """
    new_tool_calls: list[ToolCall] = []
    for req_info in state.incoming_requests:
        tool_instance = context.tool_registry.get_tool(req_info.name)

        if not tool_instance:
            error = ValueError(f"Tool '{req_info.name}' not found in registry.")
            new_tool_calls.append(
                ErroredToolCall(
                    request=req_info,
                    response=create_error_response(req_info, error),
                    duration_ms=0,
                )
            )
            continue

        validating_call = ValidatingToolCall(
            request=req_info, tool=tool_instance, start_time=time.time()
        )

        try:
            if context.config.get_approval_mode() == ApprovalMode.YOLO:
                new_tool_calls.append(
                    ScheduledToolCall(**validating_call.model_dump())
                )
            else:
                # TODO: Pass a real AbortSignal equivalent
                confirmation_details = (
                    await tool_instance.should_confirm_execute(
                        req_info.args, None
                    )
                )
                if confirmation_details:
                    # TODO: Wrap onConfirm callback
                    new_tool_calls.append(
                        WaitingToolCall(
                            **validating_call.model_dump(),
                            confirmation_details=confirmation_details,
                        )
                    )
                else:
                    new_tool_calls.append(
                        ScheduledToolCall(**validating_call.model_dump())
                    )
        except Exception as e:
            new_tool_calls.append(
                ErroredToolCall(
                    request=req_info,
                    response=create_error_response(req_info, e),
                )
            )

    return {"tool_calls": state.tool_calls + new_tool_calls}


async def wait_for_approval_node(
    state: ToolExecutionState, context: ToolNodeContext
) -> dict[str, Any]:
    """
    Node to wait for user approval for tool calls.
    Emits an event for each waiting call and causes the graph to interrupt.
    """
    waiting_calls = [
        call for call in state.tool_calls if isinstance(call, WaitingToolCall)
    ]

    for call in waiting_calls:
        event = ServerGeminiToolCallConfirmationEvent(
            value=ServerToolCallConfirmationDetails(
                request=call.request, details=call.confirmation_details
            )
        )
        context.emitter.emit(event.type.value, event)

    # The graph will be interrupted after this node if there are waiting calls.
    # No state change is needed here; the client will update the state upon resumption.
    return {}


async def execute_tools_node(
    state: ToolExecutionState, context: ToolNodeContext
) -> dict[str, Any]:
    """
    Node to execute all scheduled tool calls.
    Corresponds to `attemptExecutionOfScheduledCalls` in CoreToolScheduler.
    """
    scheduled_calls = [
        call for call in state.tool_calls if isinstance(call, ScheduledToolCall)
    ]

    if not scheduled_calls:
        # If there's nothing to execute, just pass through.
        return {}

    tasks = [execute_single_tool(call, context) for call in scheduled_calls]
    completed_calls = await asyncio.gather(*tasks)
    completed_map = {
        call.request.request.call_id: call for call in completed_calls
    }

    # Replace scheduled calls with their completed counterparts
    updated_tool_calls = [
        completed_map.get(call.request.request.call_id, call)
        for call in state.tool_calls
    ]

    return {"tool_calls": updated_tool_calls}


def should_wait_for_approval(state: ToolExecutionState) -> str:
    """
    Conditional edge to determine if we need to wait for user approval.
    """
    has_waiting_calls = any(
        isinstance(call, WaitingToolCall) for call in state.tool_calls
    )
    if has_waiting_calls:
        return "wait_for_approval"
    return "execute_tools"


def create_tool_execution_graph(
    config: Config, emitter: EventEmitter, tool_registry: ToolRegistry
) -> CompiledGraph:
    """
    Creates the tool execution graph.
    """
    context = ToolNodeContext(config, emitter, tool_registry, CancelSignal())
    graph = StateGraph(ToolExecutionState)
    checkpointer = MemorySaver()

    # Create nodes with context
    schedule_tools = partial(schedule_tools_node, context=context)
    wait_for_approval = partial(wait_for_approval_node, context=context)
    execute_tools = partial(execute_tools_node, context=context)

    # Add nodes
    graph.add_node("schedule_tools", schedule_tools)
    graph.add_node("wait_for_approval", wait_for_approval)
    graph.add_node("execute_tools", execute_tools)

    # Add edges
    graph.set_entry_point("schedule_tools")
    graph.add_conditional_edges(
        "schedule_tools",
        should_wait_for_approval,
        {
            "wait_for_approval": "wait_for_approval",
            "execute_tools": "execute_tools",
        },
    )
    # This node will interrupt, and resume to execute_tools
    graph.add_edge("wait_for_approval", "execute_tools")
    graph.add_edge("execute_tools", END)

    interrupt_nodes = ["wait_for_approval"]
    return graph.compile(
        checkpointer=checkpointer, interrupt_before=interrupt_nodes
    )
