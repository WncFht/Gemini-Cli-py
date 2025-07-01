/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { Config } from '../config/config.js';
import {
  logToolCall,
  ToolCallRequestInfo,
  ToolCallResponseInfo,
  ToolRegistry,
  ToolResult,
} from '../index.js';
import { convertToFunctionResponse } from './coreToolScheduler.js';

/**
 * 以非交互方式执行单个工具调用。
 *
 * 这个函数是一个简化的工具执行器，它不处理用户确认、并发执行多个调用或实时流式输出。
 * 它的主要职责是：
 * 1. 在工具注册表中查找指定的工具。
 * 2. 直接执行该工具。
 * 3. 记录工具调用的遥测数据（成功或失败）。
 * 4. 将工具的执行结果格式化为模型可理解的 `FunctionResponse`。
 * 这在自动化脚本或不需要用户干预的场景中非常有用。
 *
 * @param config - 应用配置实例。
 * @param toolCallRequest - 单个工具调用的请求信息。
 * @param toolRegistry - 工具注册表实例。
 * @param abortSignal - 可选的，用于中止操作的 AbortSignal。
 * @returns 一个解析为 `ToolCallResponseInfo` 的 Promise，其中包含了执行结果或错误信息。
 */
export async function executeToolCall(
  config: Config,
  toolCallRequest: ToolCallRequestInfo,
  toolRegistry: ToolRegistry,
  abortSignal?: AbortSignal,
): Promise<ToolCallResponseInfo> {
  const tool = toolRegistry.getTool(toolCallRequest.name);

  const startTime = Date.now();
  if (!tool) {
    // 如果在注册表中找不到工具
    const error = new Error(
      `在注册表中找不到工具 "${toolCallRequest.name}"。`,
    );
    const durationMs = Date.now() - startTime;
    // 记录失败的工具调用
    logToolCall(config, {
      'event.name': 'tool_call',
      'event.timestamp': new Date().toISOString(),
      function_name: toolCallRequest.name,
      function_args: toolCallRequest.args,
      duration_ms: durationMs,
      success: false,
      error: error.message,
    });
    // 确保响应结构符合 API 对错误的预期
    return {
      callId: toolCallRequest.callId,
      responseParts: [
        {
          functionResponse: {
            id: toolCallRequest.callId,
            name: toolCallRequest.name,
            response: { error: error.message },
          },
        },
      ],
      resultDisplay: error.message,
      error,
    };
  }

  try {
    // 直接执行，不处理确认或实时输出
    const effectiveAbortSignal = abortSignal ?? new AbortController().signal;
    const toolResult: ToolResult = await tool.execute(
      toolCallRequest.args,
      effectiveAbortSignal,
      // 在非交互模式下没有实时输出回调
    );

    const durationMs = Date.now() - startTime;
    // 记录成功的工具调用
    logToolCall(config, {
      'event.name': 'tool_call',
      'event.timestamp': new Date().toISOString(),
      function_name: toolCallRequest.name,
      function_args: toolCallRequest.args,
      duration_ms: durationMs,
      success: true,
    });

    // 将工具结果转换为 FunctionResponse
    const response = convertToFunctionResponse(
      toolCallRequest.name,
      toolCallRequest.callId,
      toolResult.llmContent,
    );

    return {
      callId: toolCallRequest.callId,
      responseParts: response,
      resultDisplay: toolResult.returnDisplay,
      error: undefined,
    };
  } catch (e) {
    // 处理执行过程中捕获到的错误
    const error = e instanceof Error ? e : new Error(String(e));
    const durationMs = Date.now() - startTime;
    // 记录失败的工具调用
    logToolCall(config, {
      'event.name': 'tool_call',
      'event.timestamp': new Date().toISOString(),
      function_name: toolCallRequest.name,
      function_args: toolCallRequest.args,
      duration_ms: durationMs,
      success: false,
      error: error.message,
    });
    return {
      callId: toolCallRequest.callId,
      responseParts: [
        {
          functionResponse: {
            id: toolCallRequest.callId,
            name: toolCallRequest.name,
            response: { error: error.message },
          },
        },
      ],
      resultDisplay: error.message,
      error,
    };
  }
}
