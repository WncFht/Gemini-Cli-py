/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import {
  FunctionCall,
  FunctionDeclaration,
  GenerateContentResponse,
  GenerateContentResponseUsageMetadata,
  PartListUnion,
} from '@google/genai';
import {
  ToolCallConfirmationDetails,
  ToolResult,
  ToolResultDisplay,
} from '../tools/tools.js';
import { reportError } from '../utils/errorReporting.js';
import { UnauthorizedError, getErrorMessage, toFriendlyError } from '../utils/errors.js';
import { getResponseText } from '../utils/generateContentResponseUtilities.js';
import { GeminiChat } from './geminiChat.js';

/**
 * 定义了传递给服务器的工具的结构。
 */
export interface ServerTool {
  name: string; // 工具名称
  schema: FunctionDeclaration; // 工具的 JSON Schema 定义
  // execute 方法的签名可能会略有不同或被包装
  execute(
    params: Record<string, unknown>,
    signal?: AbortSignal,
  ): Promise<ToolResult>;
  // 检查是否需要用户确认才能执行
  shouldConfirmExecute(
    params: Record<string, unknown>,
    abortSignal: AbortSignal,
  ): Promise<ToolCallConfirmationDetails | false>;
}

/**
 * 定义了在与 Gemini 的交互过程中可能发生的事件类型。
 */
export enum GeminiEventType {
  Content = 'content', // 模型生成了文本内容
  ToolCallRequest = 'tool_call_request', // 模型请求调用一个工具
  ToolCallResponse = 'tool_call_response', // 工具执行完毕并返回结果
  ToolCallConfirmation = 'tool_call_confirmation', // 等待用户确认工具调用
  UserCancelled = 'user_cancelled', // 用户取消了操作
  Error = 'error', // 发生了错误
  ChatCompressed = 'chat_compressed', // 聊天历史被压缩
  UsageMetadata = 'usage_metadata', // API 使用元数据
  Thought = 'thought', // 模型正在"思考"
}

/**
 * 结构化的错误信息。
 */
export interface StructuredError {
  message: string;
  status?: number;
}

/**
 * Gemini 错误事件的值。
 */
export interface GeminiErrorEventValue {
  error: StructuredError;
}

/**
 * 工具调用请求的信息。
 */
export interface ToolCallRequestInfo {
  callId: string; // 唯一的调用 ID
  name: string; // 工具名称
  args: Record<string, unknown>; // 工具参数
  isClientInitiated: boolean; // 是否由客户端发起
}

/**
 * 工具调用响应的信息。
 */
export interface ToolCallResponseInfo {
  callId: string; // 对应的调用 ID
  responseParts: PartListUnion; // 响应内容
  resultDisplay: ToolResultDisplay | undefined; // 用于显示的结果
  error: Error | undefined; // 发生的错误
}

/**
 * 服务器端工具调用确认的详细信息。
 */
export interface ServerToolCallConfirmationDetails {
  request: ToolCallRequestInfo;
  details: ToolCallConfirmationDetails;
}

/**
 * 模型的"思考"过程摘要。
 */
export type ThoughtSummary = {
  subject: string; // 思考的主题
  description: string; // 思考的描述
};

// --- 以下是各种服务端 Gemini 事件的类型定义 ---

/**
 * 模型生成内容的事件。
 */
export type ServerGeminiContentEvent = {
  type: GeminiEventType.Content;
  value: string;
};

/**
 * 模型产生"思考"的事件。
 */
export type ServerGeminiThoughtEvent = {
  type: GeminiEventType.Thought;
  value: ThoughtSummary;
};

/**
 * 模型请求调用工具的事件。
 */
export type ServerGeminiToolCallRequestEvent = {
  type: GeminiEventType.ToolCallRequest;
  value: ToolCallRequestInfo;
};

/**
 * 工具执行完成并返回响应的事件。
 */
export type ServerGeminiToolCallResponseEvent = {
  type: GeminiEventType.ToolCallResponse;
  value: ToolCallResponseInfo;
};

/**
 * 等待用户确认工具调用的事件。
 */
export type ServerGeminiToolCallConfirmationEvent = {
  type: GeminiEventType.ToolCallConfirmation;
  value: ServerToolCallConfirmationDetails;
};

/**
 * 用户取消操作的事件。
 */
export type ServerGeminiUserCancelledEvent = {
  type: GeminiEventType.UserCancelled;
};

/**
 * 发生错误的事件。
 */
export type ServerGeminiErrorEvent = {
  type: GeminiEventType.Error;
  value: GeminiErrorEventValue;
};

/**
 * 聊天历史被压缩的信息。
 */
export interface ChatCompressionInfo {
  originalTokenCount: number;
  newTokenCount: number;
}

/**
 * 聊天历史被压缩的事件。
 */
export type ServerGeminiChatCompressedEvent = {
  type: GeminiEventType.ChatCompressed;
  value: ChatCompressionInfo | null;
};

/**
 * API 使用元数据事件。
 */
export type ServerGeminiUsageMetadataEvent = {
  type: GeminiEventType.UsageMetadata;
  value: GenerateContentResponseUsageMetadata & { apiTimeMs?: number };
};

/**
 * 服务端 Gemini 流式事件的联合类型。
 */
export type ServerGeminiStreamEvent =
  | ServerGeminiContentEvent
  | ServerGeminiToolCallRequestEvent
  | ServerGeminiToolCallResponseEvent
  | ServerGeminiToolCallConfirmationEvent
  | ServerGeminiUserCancelledEvent
  | ServerGeminiErrorEvent
  | ServerGeminiChatCompressedEvent
  | ServerGeminiUsageMetadataEvent
  | ServerGeminiThoughtEvent;

/**
 * Turn 类管理在服务器上下文中的一次"回合"（turn），即一次完整的用户-模型交互循环。
 * 它将来自 GeminiChat 的原始流式响应转换为更简单、结构化的 `ServerGeminiStreamEvent` 事件流。
 */
export class Turn {
  readonly pendingToolCalls: ToolCallRequestInfo[];
  private debugResponses: GenerateContentResponse[];
  private lastUsageMetadata: GenerateContentResponseUsageMetadata | null = null;

  constructor(private readonly chat: GeminiChat) {
    this.pendingToolCalls = [];
    this.debugResponses = [];
  }

  /**
   * 运行一个交互回合。它接收用户请求，通过 `GeminiChat` 发送给模型，
   * 并将模型的流式响应转换为一系列供服务器逻辑使用的事件。
   * @param req - 用户的请求内容。
   * @param signal - 用于中止操作的 AbortSignal。
   * @yields {ServerGeminiStreamEvent} - 交互过程中的各种事件。
   */
  async *run(
    req: PartListUnion,
    signal: AbortSignal,
  ): AsyncGenerator<ServerGeminiStreamEvent> {
    const startTime = Date.now();
    try {
      // 从 GeminiChat 获取流式响应
      const responseStream = await this.chat.sendMessageStream({
        message: req,
        config: {
          abortSignal: signal,
        },
      });

      for await (const resp of responseStream) {
        if (signal?.aborted) {
          yield { type: GeminiEventType.UserCancelled };
          // 如果在处理前被中止，则不将响应添加到 debugResponses
          return;
        }
        this.debugResponses.push(resp);

        // 处理"思考"过程
        const thoughtPart = resp.candidates?.[0]?.content?.parts?.[0];
        if (thoughtPart?.thought) {
          // "思考"过程的文本通常包含一个用双星号包裹的主题（例如 **Subject**）。
          // 字符串的其余部分被认为是描述。
          const rawText = thoughtPart.text ?? '';
          const subjectStringMatches = rawText.match(/\*\*(.*?)\*\*/s);
          const subject = subjectStringMatches
            ? subjectStringMatches[1].trim()
            : '';
          const description = rawText.replace(/\*\*(.*?)\*\*/s, '').trim();
          const thought: ThoughtSummary = {
            subject,
            description,
          };

          yield {
            type: GeminiEventType.Thought,
            value: thought,
          };
          continue;
        }

        // 处理纯文本内容
        const text = getResponseText(resp);
        if (text) {
          yield { type: GeminiEventType.Content, value: text };
        }

        // 处理函数调用（请求执行工具）
        const functionCalls = resp.functionCalls ?? [];
        for (const fnCall of functionCalls) {
          const event = this.handlePendingFunctionCall(fnCall);
          if (event) {
            yield event;
          }
        }

        // 记录用量元数据
        if (resp.usageMetadata) {
          this.lastUsageMetadata =
            resp.usageMetadata as GenerateContentResponseUsageMetadata;
        }
      }

      // 在流结束后，发送最终的用量元数据事件
      if (this.lastUsageMetadata) {
        const durationMs = Date.now() - startTime;
        yield {
          type: GeminiEventType.UsageMetadata,
          value: { ...this.lastUsageMetadata, apiTimeMs: durationMs },
        };
      }
    } catch (e) {
      const error = toFriendlyError(e);
      if (error instanceof UnauthorizedError) {
        throw error;
      }
      if (signal.aborted) {
        yield { type: GeminiEventType.UserCancelled };
        // 常规的取消错误，优雅地失败。
        return;
      }

      // 上报错误
      const contextForReport = [...this.chat.getHistory(/*curated*/ true), req];
      await reportError(
        error,
        'Error when talking to Gemini API',
        contextForReport,
        'Turn.run-sendMessageStream',
      );
      // 构造并产生一个错误事件
      const status =
        typeof error === 'object' &&
        error !== null &&
        'status' in error &&
        typeof (error as { status: unknown }).status === 'number'
          ? (error as { status: number }).status
          : undefined;
      const structuredError: StructuredError = {
        message: getErrorMessage(error),
        status,
      };
      yield { type: GeminiEventType.Error, value: { error: structuredError } };
      return;
    }
  }

  /**
   * 处理模型返回的待处理函数调用。
   * @param fnCall - 模型返回的 `FunctionCall` 对象。
   * @returns 一个 `ServerGeminiToolCallRequestEvent` 事件，或在无效时返回 null。
   */
  private handlePendingFunctionCall(
    fnCall: FunctionCall,
  ): ServerGeminiStreamEvent | null {
    const callId =
      fnCall.id ??
      `${fnCall.name}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    const name = fnCall.name || 'undefined_tool_name';
    const args = (fnCall.args || {}) as Record<string, unknown>;

    const toolCallRequest: ToolCallRequestInfo = {
      callId,
      name,
      args,
      isClientInitiated: false,
    };

    this.pendingToolCalls.push(toolCallRequest);

    // 产生一个工具调用请求事件，而不是挂起/确认状态的事件
    return { type: GeminiEventType.ToolCallRequest, value: toolCallRequest };
  }

  /**
   * 获取用于调试的原始响应列表。
   * @returns `GenerateContentResponse` 数组。
   */
  getDebugResponses(): GenerateContentResponse[] {
    return this.debugResponses;
  }

  /**
   * 获取最后一次记录的用量元数据。
   * @returns `GenerateContentResponseUsageMetadata` 或 null。
   */
  getUsageMetadata(): GenerateContentResponseUsageMetadata | null {
    return this.lastUsageMetadata;
  }
}
