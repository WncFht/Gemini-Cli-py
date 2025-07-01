/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { Part, PartListUnion } from '@google/genai';
import {
  ApprovalMode,
  Config,
  EditorType,
  logToolCall,
  Tool,
  ToolCallConfirmationDetails,
  ToolCallEvent,
  ToolCallRequestInfo,
  ToolCallResponseInfo,
  ToolConfirmationOutcome,
  ToolRegistry,
  ToolResult,
} from '../index.js';
import {
  isModifiableTool,
  ModifyContext,
  modifyWithEditor,
} from '../tools/modifiable-tool.js';
import { getResponseTextFromParts } from '../utils/generateContentResponseUtilities.js';

// --- 工具调用状态定义 ---
// 以下类型定义了一个工具调用（ToolCall）从被请求到最终完成的完整生命周期状态机。

/**
 * 状态：正在验证。
 * 工具调用已被接收，正在验证工具是否存在以及参数是否初步有效。
 */
export type ValidatingToolCall = {
  status: 'validating';
  request: ToolCallRequestInfo;
  tool: Tool;
  startTime?: number;
  outcome?: ToolConfirmationOutcome;
};

/**
 * 状态：已调度。
 * 工具调用已通过验证和用户确认（如果需要），准备执行。
 */
export type ScheduledToolCall = {
  status: 'scheduled';
  request: ToolCallRequestInfo;
  tool: Tool;
  startTime?: number;
  outcome?: ToolConfirmationOutcome;
};

/**
 * 状态：错误。
 * 工具调用在执行过程中发生错误。这是一个终端状态。
 */
export type ErroredToolCall = {
  status: 'error';
  request: ToolCallRequestInfo;
  response: ToolCallResponseInfo;
  durationMs?: number;
  outcome?: ToolConfirmationOutcome;
};

/**
 * 状态：成功。
 * 工具调用已成功执行。这是一个终端状态。
 */
export type SuccessfulToolCall = {
  status: 'success';
  request: ToolCallRequestInfo;
  tool: Tool;
  response: ToolCallResponseInfo;
  durationMs?: number;
  outcome?: ToolConfirmationOutcome;
};

/**
 * 状态：正在执行。
 * 工具正在运行中。
 */
export type ExecutingToolCall = {
  status: 'executing';
  request: ToolCallRequestInfo;
  tool: Tool;
  liveOutput?: string;
  startTime?: number;
  outcome?: ToolConfirmationOutcome;
};

/**
 * 状态：已取消。
 * 工具调用被用户或系统取消。这是一个终端状态。
 */
export type CancelledToolCall = {
  status: 'cancelled';
  request: ToolCallRequestInfo;
  response: ToolCallResponseInfo;
  tool: Tool;
  durationMs?: number;
  outcome?: ToolConfirmationOutcome;
};

/**
 * 状态：等待批准。
 * 工具调用需要用户确认才能继续执行。
 */
export type WaitingToolCall = {
  status: 'awaiting_approval';
  request: ToolCallRequestInfo;
  tool: Tool;
  confirmationDetails: ToolCallConfirmationDetails;
  startTime?: number;
  outcome?: ToolConfirmationOutcome;
};

/**
 * 工具调用所有可能状态的联合类型。
 */
export type Status = ToolCall['status'];

/**
 * 表示一个工具调用的联合类型，包含了其所有可能的状态。
 */
export type ToolCall =
  | ValidatingToolCall
  | ScheduledToolCall
  | ErroredToolCall
  | SuccessfulToolCall
  | ExecutingToolCall
  | CancelledToolCall
  | WaitingToolCall;

/**
 * 表示已完成的工具调用的联合类型（所有终端状态）。
 */
export type CompletedToolCall =
  | SuccessfulToolCall
  | CancelledToolCall
  | ErroredToolCall;

// --- 处理器回调函数类型定义 ---

/**
 * 用户确认处理器的类型定义。
 * @param toolCall - 等待确认的工具调用对象。
 * @returns 一个解析为用户确认结果的 Promise。
 */
export type ConfirmHandler = (
  toolCall: WaitingToolCall,
) => Promise<ToolConfirmationOutcome>;

/**
 * 工具实时输出更新处理器的类型定义。
 * @param toolCallId - 工具调用的 ID。
 * @param outputChunk - 新的输出数据块。
 */
export type OutputUpdateHandler = (
  toolCallId: string,
  outputChunk: string,
) => void;

/**
 * 所有工具调用完成处理器的类型定义。
 * @param completedToolCalls - 已完成的工具调用数组。
 */
export type AllToolCallsCompleteHandler = (
  completedToolCalls: CompletedToolCall[],
) => void;

/**
 * 工具调用列表更新处理器的类型定义。
 * @param toolCalls - 当前所有工具调用的数组。
 */
export type ToolCallsUpdateHandler = (toolCalls: ToolCall[]) => void;

/**
 * 将工具输出格式化为 Gemini 的 FunctionResponse Part。
 * @param callId - 工具调用的 ID。
 * @param toolName - 工具的名称。
 * @param output - 工具的输出字符串。
 * @returns 一个 `Part` 对象。
 */
function createFunctionResponsePart(
  callId: string,
  toolName: string,
  output: string,
): Part {
  return {
    functionResponse: {
      id: callId,
      name: toolName,
      response: { output },
    },
  };
}

/**
 * 将工具执行结果（`ToolResult`）转换为模型可以理解的 `FunctionResponse` 格式。
 * 这会处理各种不同的 `llmContent` 格式，如字符串、二进制数据、其他 Part 等。
 * @param toolName - 工具名称。
 * @param callId - 工具调用 ID。
 * @param llmContent - 来自工具执行结果的内容。
 * @returns 格式化后的 `PartListUnion`。
 */
export function convertToFunctionResponse(
  toolName: string,
  callId: string,
  llmContent: PartListUnion,
): PartListUnion {
  const contentToProcess =
    Array.isArray(llmContent) && llmContent.length === 1
      ? llmContent[0]
      : llmContent;

  if (typeof contentToProcess === 'string') {
    return createFunctionResponsePart(callId, toolName, contentToProcess);
  }

  if (Array.isArray(contentToProcess)) {
    const functionResponse = createFunctionResponsePart(
      callId,
      toolName,
      'Tool execution succeeded.',
    );
    return [functionResponse, ...contentToProcess];
  }

  // 此时，contentToProcess 是一个单独的 Part 对象。
  if (contentToProcess.functionResponse) {
    if (contentToProcess.functionResponse.response?.content) {
      const stringifiedOutput =
        getResponseTextFromParts(
          contentToProcess.functionResponse.response.content as Part[],
        ) || '';
      return createFunctionResponsePart(callId, toolName, stringifiedOutput);
    }
    // 这是一个我们应该直接透传的 functionResponse。
    return contentToProcess;
  }

  if (contentToProcess.inlineData || contentToProcess.fileData) {
    const mimeType =
      contentToProcess.inlineData?.mimeType ||
      contentToProcess.fileData?.mimeType ||
      'unknown';
    const functionResponse = createFunctionResponsePart(
      callId,
      toolName,
      `Binary content of type ${mimeType} was processed.`,
    );
    return [functionResponse, contentToProcess];
  }

  if (contentToProcess.text !== undefined) {
    return createFunctionResponsePart(callId, toolName, contentToProcess.text);
  }

  // 其他类型 part 的默认情况。
  return createFunctionResponsePart(
    callId,
    toolName,
    'Tool execution succeeded.',
  );
}

/**
 * 创建一个表示错误的工具调用响应。
 * @param request - 原始的工具调用请求。
 * @param error - 发生的错误。
 * @returns 一个 `ToolCallResponseInfo` 对象。
 */
const createErrorResponse = (
  request: ToolCallRequestInfo,
  error: Error,
): ToolCallResponseInfo => ({
  callId: request.callId,
  error,
  responseParts: {
    functionResponse: {
      id: request.callId,
      name: request.name,
      response: { error: error.message },
    },
  },
  resultDisplay: error.message,
});

/**
 * 核心工具调度器的构造函数选项。
 */
interface CoreToolSchedulerOptions {
  toolRegistry: Promise<ToolRegistry>;
  outputUpdateHandler?: OutputUpdateHandler;
  onAllToolCallsComplete?: AllToolCallsCompleteHandler;
  onToolCallsUpdate?: ToolCallsUpdateHandler;
  approvalMode?: ApprovalMode;
  getPreferredEditor: () => EditorType | undefined;
  config: Config;
}

/**
 * 核心工具调度器 (CoreToolScheduler)
 *
 * 负责管理模型请求的工具调用的整个生命周期。
 * 它的职责包括：
 * - 从工具注册表 (ToolRegistry) 查找工具。
 * - 根据配置的批准模式 (ApprovalMode) 管理用户确认流程。
 * - 调度和执行工具。
 * - 跟踪每个工具调用的状态（验证、等待批准、执行、成功、失败、取消）。
 * - 将工具执行结果格式化成模型可识别的响应。
 * - 通过回调通知外部调用者状态更新和最终完成。
 */
export class CoreToolScheduler {
  private toolRegistry: Promise<ToolRegistry>;
  private toolCalls: ToolCall[] = [];
  private outputUpdateHandler?: OutputUpdateHandler;
  private onAllToolCallsComplete?: AllToolCallsCompleteHandler;
  private onToolCallsUpdate?: ToolCallsUpdateHandler;
  private approvalMode: ApprovalMode;
  private getPreferredEditor: () => EditorType | undefined;
  private config: Config;

  constructor(options: CoreToolSchedulerOptions) {
    this.config = options.config;
    this.toolRegistry = options.toolRegistry;
    this.outputUpdateHandler = options.outputUpdateHandler;
    this.onAllToolCallsComplete = options.onAllToolCallsComplete;
    this.onToolCallsUpdate = options.onToolCallsUpdate;
    this.approvalMode = options.approvalMode ?? ApprovalMode.DEFAULT;
    this.getPreferredEditor = options.getPreferredEditor;
  }

  /**
   * 内部方法，用于更新指定工具调用的状态。
   * 这是状态转换的唯一入口点，确保状态更新的一致性。
   * @param targetCallId - 目标工具调用的 ID。
   * @param newStatus - 新的状态。
   * @param auxiliaryData - 附加数据，根据新状态的不同而不同（例如，响应信息、错误信息等）。
   */
  private setStatusInternal(
    targetCallId: string,
    status: 'success',
    response: ToolCallResponseInfo,
  ): void;
  private setStatusInternal(
    targetCallId: string,
    status: 'awaiting_approval',
    confirmationDetails: ToolCallConfirmationDetails,
  ): void;
  private setStatusInternal(
    targetCallId: string,
    status: 'error',
    response: ToolCallResponseInfo,
  ): void;
  private setStatusInternal(
    targetCallId: string,
    status: 'cancelled',
    reason: string,
  ): void;
  private setStatusInternal(
    targetCallId: string,
    status: 'executing' | 'scheduled' | 'validating',
  ): void;
  private setStatusInternal(
    targetCallId: string,
    newStatus: Status,
    auxiliaryData?: unknown,
  ): void {
    this.toolCalls = this.toolCalls.map((currentCall) => {
      // 如果不是目标调用，或者调用已处于终端状态，则直接返回
      if (
        currentCall.request.callId !== targetCallId ||
        currentCall.status === 'success' ||
        currentCall.status === 'error' ||
        currentCall.status === 'cancelled'
      ) {
        return currentCall;
      }

      // 此时，currentCall 处于一个非终端状态，应该有 startTime 和 tool 属性。
      const existingStartTime = currentCall.startTime;
      const toolInstance = (
        currentCall as
          | ValidatingToolCall
          | ScheduledToolCall
          | ExecutingToolCall
          | WaitingToolCall
      ).tool;

      const outcome = (
        currentCall as
          | ValidatingToolCall
          | ScheduledToolCall
          | ExecutingToolCall
          | WaitingToolCall
      ).outcome;

      // 根据新的状态创建新的工具调用对象
      switch (newStatus) {
        case 'success': {
          const durationMs = existingStartTime
            ? Date.now() - existingStartTime
            : undefined;
          return {
            request: currentCall.request,
            tool: toolInstance,
            status: 'success',
            response: auxiliaryData as ToolCallResponseInfo,
            durationMs,
            outcome,
          } as SuccessfulToolCall;
        }
        case 'error': {
          const durationMs = existingStartTime
            ? Date.now() - existingStartTime
            : undefined;
          return {
            request: currentCall.request,
            status: 'error',
            response: auxiliaryData as ToolCallResponseInfo,
            durationMs,
            outcome,
          } as ErroredToolCall;
        }
        case 'awaiting_approval':
          return {
            request: currentCall.request,
            tool: toolInstance,
            status: 'awaiting_approval',
            confirmationDetails: auxiliaryData as ToolCallConfirmationDetails,
            startTime: existingStartTime,
            outcome,
          } as WaitingToolCall;
        case 'scheduled':
          return {
            request: currentCall.request,
            tool: toolInstance,
            status: 'scheduled',
            startTime: existingStartTime,
            outcome,
          } as ScheduledToolCall;
        case 'cancelled': {
          const durationMs = existingStartTime
            ? Date.now() - existingStartTime
            : undefined;
          return {
            request: currentCall.request,
            tool: toolInstance,
            status: 'cancelled',
            response: {
              callId: currentCall.request.callId,
              responseParts: {
                functionResponse: {
                  id: currentCall.request.callId,
                  name: currentCall.request.name,
                  response: {
                    error: `[Operation Cancelled] Reason: ${auxiliaryData}`,
                  },
                },
              },
              resultDisplay: undefined,
              error: undefined,
            },
            durationMs,
            outcome,
          } as CancelledToolCall;
        }
        case 'validating':
          return {
            request: currentCall.request,
            tool: toolInstance,
            status: 'validating',
            startTime: existingStartTime,
            outcome,
          } as ValidatingToolCall;
        case 'executing':
          return {
            request: currentCall.request,
            tool: toolInstance,
            status: 'executing',
            startTime: existingStartTime,
            outcome,
          } as ExecutingToolCall;
        default: {
          const exhaustiveCheck: never = newStatus;
          return exhaustiveCheck;
        }
      }
    });
    this.notifyToolCallsUpdate();
    this.checkAndNotifyCompletion();
  }

  /**
   * 内部方法，用于设置（更新）工具调用的参数。
   * 主要用于"通过编辑器修改"的场景。
   * @param targetCallId - 目标工具调用的 ID。
   * @param args - 新的参数对象。
   */
  private setArgsInternal(targetCallId: string, args: unknown): void {
    this.toolCalls = this.toolCalls.map((call) => {
      if (call.request.callId !== targetCallId) return call;
      return {
        ...call,
        request: { ...call.request, args: args as Record<string, unknown> },
      };
    });
  }

  /**
   * 检查是否有任何工具调用正在运行（执行中或等待批准）。
   * @returns 如果有工具正在运行，则为 true。
   */
  private isRunning(): boolean {
    return this.toolCalls.some(
      (call) =>
        call.status === 'executing' || call.status === 'awaiting_approval',
    );
  }

  /**
   * 调度一个新的或一批新的工具调用请求。
   * @param request - 单个或多个工具调用请求信息。
   * @param signal - 用于中止操作的 AbortSignal。
   */
  async schedule(
    request: ToolCallRequestInfo | ToolCallRequestInfo[],
    signal: AbortSignal,
  ): Promise<void> {
    if (this.isRunning()) {
      throw new Error(
        '当有其他工具调用正在积极运行时（执行中或等待批准），无法调度新的工具调用。',
      );
    }
    const requestsToProcess = Array.isArray(request) ? request : [request];
    const toolRegistry = await this.toolRegistry;

    // 为每个请求创建初始的 ToolCall 对象
    const newToolCalls: ToolCall[] = requestsToProcess.map(
      (reqInfo): ToolCall => {
        const toolInstance = toolRegistry.getTool(reqInfo.name);
        if (!toolInstance) {
          // 如果找不到工具，直接标记为错误
          return {
            status: 'error',
            request: reqInfo,
            response: createErrorResponse(
              reqInfo,
              new Error(`在注册表中找不到工具 "${reqInfo.name}"。`),
            ),
            durationMs: 0,
          };
        }
        // 初始状态为 'validating'
        return {
          status: 'validating',
          request: reqInfo,
          tool: toolInstance,
          startTime: Date.now(),
        };
      },
    );

    this.toolCalls = this.toolCalls.concat(newToolCalls);
    this.notifyToolCallsUpdate();

    // 遍历新的工具调用，决定是直接调度还是需要用户确认
    for (const toolCall of newToolCalls) {
      if (toolCall.status !== 'validating') {
        continue;
      }

      const { request: reqInfo, tool: toolInstance } = toolCall;
      try {
        // 在 YOLO（You Only Live Once）模式下，跳过确认，直接调度
        if (this.approvalMode === ApprovalMode.YOLO) {
          this.setStatusInternal(reqInfo.callId, 'scheduled');
        } else {
          // 检查工具是否需要确认
          const confirmationDetails = await toolInstance.shouldConfirmExecute(
            reqInfo.args,
            signal,
          );

          if (confirmationDetails) {
            // 如果需要确认，包装 onConfirm 回调函数并进入 'awaiting_approval' 状态
            const originalOnConfirm = confirmationDetails.onConfirm;
            const wrappedConfirmationDetails: ToolCallConfirmationDetails = {
              ...confirmationDetails,
              onConfirm: (outcome: ToolConfirmationOutcome) =>
                this.handleConfirmationResponse(
                  reqInfo.callId,
                  originalOnConfirm,
                  outcome,
                  signal,
                ),
            };
            this.setStatusInternal(
              reqInfo.callId,
              'awaiting_approval',
              wrappedConfirmationDetails,
            );
          } else {
            // 如果不需要确认，直接进入 'scheduled' 状态
            this.setStatusInternal(reqInfo.callId, 'scheduled');
          }
        }
      } catch (error) {
        this.setStatusInternal(
          reqInfo.callId,
          'error',
          createErrorResponse(
            reqInfo,
            error instanceof Error ? error : new Error(String(error)),
          ),
        );
      }
    }
    // 尝试执行所有已调度的调用
    this.attemptExecutionOfScheduledCalls(signal);
    this.checkAndNotifyCompletion();
  }

  /**
   * 处理用户的确认响应（同意、取消、修改）。
   * @param callId - 对应的工具调用 ID。
   * @param originalOnConfirm - 工具自身提供的原始 onConfirm 回调。
   * @param outcome - 用户的确认结果。
   * @param signal - 用于中止操作的 AbortSignal。
   */
  async handleConfirmationResponse(
    callId: string,
    originalOnConfirm: (outcome: ToolConfirmationOutcome) => Promise<void>,
    outcome: ToolConfirmationOutcome,
    signal: AbortSignal,
  ): Promise<void> {
    const toolCall = this.toolCalls.find(
      (c) => c.request.callId === callId && c.status === 'awaiting_approval',
    );

    if (toolCall && toolCall.status === 'awaiting_approval') {
      await originalOnConfirm(outcome);
    }

    // 更新工具调用的 outcome
    this.toolCalls = this.toolCalls.map((call) => {
      if (call.request.callId !== callId) return call;
      return {
        ...call,
        outcome,
      };
    });

    if (outcome === ToolConfirmationOutcome.Cancel || signal.aborted) {
      // 如果用户取消，将状态设置为 'cancelled'
      this.setStatusInternal(
        callId,
        'cancelled',
        'User did not allow tool call',
      );
    } else if (outcome === ToolConfirmationOutcome.ModifyWithEditor) {
      // 如果用户选择用编辑器修改
      const waitingToolCall = toolCall as WaitingToolCall;
      if (isModifiableTool(waitingToolCall.tool)) {
        const modifyContext = waitingToolCall.tool.getModifyContext(signal);
        const editorType = this.getPreferredEditor();
        if (!editorType) {
          return;
        }

        this.setStatusInternal(callId, 'awaiting_approval', {
          ...waitingToolCall.confirmationDetails,
          isModifying: true,
        } as ToolCallConfirmationDetails);

        const { updatedParams, updatedDiff } = await modifyWithEditor<
          typeof waitingToolCall.request.args
        >(
          waitingToolCall.request.args,
          modifyContext as ModifyContext<typeof waitingToolCall.request.args>,
          editorType,
          signal,
        );
        // 更新参数并再次等待确认
        this.setArgsInternal(callId, updatedParams);
        this.setStatusInternal(callId, 'awaiting_approval', {
          ...waitingToolCall.confirmationDetails,
          fileDiff: updatedDiff,
          isModifying: false,
        } as ToolCallConfirmationDetails);
      }
    } else {
      // 如果用户同意，将状态设置为 'scheduled'
      this.setStatusInternal(callId, 'scheduled');
    }
    this.attemptExecutionOfScheduledCalls(signal);
  }

  /**
   * 尝试执行所有处于 'scheduled' 状态的工具调用。
   * 只有当所有工具调用都处于 'scheduled' 或终端状态时，才会执行。
   * @param signal - 用于中止操作的 AbortSignal。
   */
  private attemptExecutionOfScheduledCalls(signal: AbortSignal): void {
    const allCallsFinalOrScheduled = this.toolCalls.every(
      (call) =>
        call.status === 'scheduled' ||
        call.status === 'cancelled' ||
        call.status === 'success' ||
        call.status === 'error',
    );

    if (allCallsFinalOrScheduled) {
      const callsToExecute = this.toolCalls.filter(
        (call) => call.status === 'scheduled',
      );

      callsToExecute.forEach((toolCall) => {
        if (toolCall.status !== 'scheduled') return;

        const scheduledCall = toolCall as ScheduledToolCall;
        const { callId, name: toolName } = scheduledCall.request;
        this.setStatusInternal(callId, 'executing');

        // 如果工具支持并且提供了回调，则设置实时输出回调
        const liveOutputCallback =
          scheduledCall.tool.canUpdateOutput && this.outputUpdateHandler
            ? (outputChunk: string) => {
                if (this.outputUpdateHandler) {
                  this.outputUpdateHandler(callId, outputChunk);
                }
                this.toolCalls = this.toolCalls.map((tc) =>
                  tc.request.callId === callId && tc.status === 'executing'
                    ? { ...(tc as ExecutingToolCall), liveOutput: outputChunk }
                    : tc,
                );
                this.notifyToolCallsUpdate();
              }
            : undefined;

        // 执行工具
        scheduledCall.tool
          .execute(scheduledCall.request.args, signal, liveOutputCallback)
          .then((toolResult: ToolResult) => {
            if (signal.aborted) {
              this.setStatusInternal(
                callId,
                'cancelled',
                'User cancelled tool execution.',
              );
              return;
            }

            const response = convertToFunctionResponse(
              toolName,
              callId,
              toolResult.llmContent,
            );

            const successResponse: ToolCallResponseInfo = {
              callId,
              responseParts: response,
              resultDisplay: toolResult.returnDisplay,
              error: undefined,
            };
            this.setStatusInternal(callId, 'success', successResponse);
          })
          .catch((executionError: Error) => {
            this.setStatusInternal(
              callId,
              'error',
              createErrorResponse(
                scheduledCall.request,
                executionError instanceof Error
                  ? executionError
                  : new Error(String(executionError)),
              ),
            );
          });
      });
    }
  }

  /**
   * 检查是否所有工具调用都已完成（处于终端状态），如果是，则通知监听器。
   */
  private checkAndNotifyCompletion(): void {
    const allCallsAreTerminal = this.toolCalls.every(
      (call) =>
        call.status === 'success' ||
        call.status === 'error' ||
        call.status === 'cancelled',
    );

    if (this.toolCalls.length > 0 && allCallsAreTerminal) {
      const completedCalls = [...this.toolCalls] as CompletedToolCall[];
      this.toolCalls = [];

      for (const call of completedCalls) {
        logToolCall(this.config, new ToolCallEvent(call));
      }

      if (this.onAllToolCallsComplete) {
        this.onAllToolCallsComplete(completedCalls);
      }
      this.notifyToolCallsUpdate();
    }
  }

  /**
   * 通知监听器工具调用列表发生了更新。
   */
  private notifyToolCallsUpdate(): void {
    if (this.onToolCallsUpdate) {
      this.onToolCallsUpdate([...this.toolCalls]);
    }
  }
}
