/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import {
    CompletedToolCall,
    Config,
    ServerGeminiContentEvent as ContentEvent,
    EditorType,
    ServerGeminiErrorEvent as ErrorEvent,
    GeminiClient,
    ServerGeminiStreamEvent as GeminiEvent,
    getErrorMessage,
    GitService,
    isNodeError,
    logUserPrompt,
    MessageSenderType,
    ServerGeminiChatCompressedEvent,
    GeminiEventType as ServerGeminiEventType,
    ThoughtSummary,
    ToolCallRequestInfo,
    UnauthorizedError,
    UserPromptEvent,
} from '@google/gemini-cli-core';
import { type Part, type PartListUnion } from '@google/genai';
import { promises as fs } from 'fs';
import { useInput } from 'ink';
import path from 'path';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSession } from '../contexts/SessionContext.js';
import {
    HistoryItem,
    HistoryItemToolGroup,
    HistoryItemWithoutId,
    MessageType,
    StreamingState,
    ToolCallStatus,
} from '../types.js';
import { isAtCommand } from '../utils/commandUtils.js';
import { parseAndFormatApiError } from '../utils/errorParsing.js';
import { findLastSafeSplitPoint } from '../utils/markdownUtilities.js';
import { handleAtCommand } from './atCommandProcessor.js';
import { useShellCommandProcessor } from './shellCommandProcessor.js';
import { UseHistoryManagerReturn } from './useHistoryManager.js';
import { useLogger } from './useLogger.js';
import {
    TrackedToolCall,
    useReactToolScheduler,
} from './useReactToolScheduler.js';
import { useStateAndRef } from './useStateAndRef.js';

/**
 * 合并多个 PartListUnion 数组为一个。
 * @param list - 要合并的 PartListUnion 数组。
 * @returns {PartListUnion} - 合并后的单个 PartListUnion。
 */
export function mergePartListUnions(list: PartListUnion[]): PartListUnion {
  const resultParts: PartListUnion = [];
  for (const item of list) {
    if (Array.isArray(item)) {
      resultParts.push(...item);
    } else {
      resultParts.push(item);
    }
  }
  return resultParts;
}

enum StreamProcessingStatus {
  Completed,
  UserCancelled,
  Error,
}

/**
 * 【核心 Hook】`useGeminiStream` 是驱动整个交互式聊天体验的核心 React Hook。
 * 它封装了与 Gemini API 交互的所有复杂逻辑，包括：
 * - 管理流式响应的状态 (空闲, 响应中, 等待确认)。
 * - 处理用户输入，并将其分发给命令处理器（斜杠命令、@命令、shell命令）。
 * - 调用 `GeminiClient` 发起聊天请求。
 * - 监听并处理从服务端返回的结构化事件流（文本、工具调用、思考过程等）。
 * - 与 `useReactToolScheduler` 协作，调度并管理工具调用的整个生命周期。
 * - 处理请求取消、错误和鉴权失败等边界情况。
 */
export const useGeminiStream = (
  geminiClient: GeminiClient,
  history: HistoryItem[],
  addItem: UseHistoryManagerReturn['addItem'],
  setShowHelp: React.Dispatch<React.SetStateAction<boolean>>,
  config: Config,
  onDebugMessage: (message: string) => void,
  handleSlashCommand: (
    cmd: PartListUnion,
  ) => Promise<
    import('./slashCommandProcessor.js').SlashCommandActionReturn | boolean
  >,
  shellModeActive: boolean,
  getPreferredEditor: () => EditorType | undefined,
  onAuthError: () => void,
  performMemoryRefresh: () => Promise<void>,
) => {
  const { client } = useSession();
  const [initError, setInitError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const turnCancelledRef = useRef(false);
  const [isResponding, setIsResponding] = useState<boolean>(false);
  const [thought, setThought] = useState<ThoughtSummary | null>(null);
  const [pendingHistoryItemRef, setPendingHistoryItem] =
    useStateAndRef<HistoryItemWithoutId | null>(null);
  const processedMemoryToolsRef = useRef<Set<string>>(new Set());
  const logger = useLogger();
  const gitService = useMemo(() => {
    if (!config.getProjectRoot()) {
      return;
    }
    return new GitService(config.getProjectRoot());
  }, [config]);

  const [isStreaming, setIsStreaming] = useState(false);
  const [completedTools, setCompletedTools] = useState<TrackedToolCall[]>([]);

  const onToolsComplete: (tools: TrackedToolCall[]) => void = useCallback(
    (tools) => {
      setCompletedTools((prev) => [...prev, ...tools]);
    },
    [],
  );

  const [toolCalls, scheduleToolCalls] = useReactToolScheduler(
    (completedToolCalls: CompletedToolCall[]) => {
      const toolResponseParts = completedToolCalls
        .map((c) => c.response.responseParts)
        .flat();
      
      if (toolResponseParts.length > 0) {
        submitQuery(toolResponseParts, { isContinuation: true });
      }
    },
    config,
    setPendingHistoryItem,
    getPreferredEditor,
  );

  const onExec = useCallback(async (done: Promise<void>) => {
    setIsResponding(true);
    await done;
    setIsResponding(false);
  }, []);
  const { handleShellCommand } = useShellCommandProcessor(
    addItem,
    setPendingHistoryItem,
    onExec,
    onDebugMessage,
    config,
    geminiClient,
  );
  
  // 2. 【状态管理】通过 `useMemo` 计算并派生出当前的流状态
  //    这是UI判断应该显示输入框、加载动画还是确认按钮的核心依据。
  const streamingState = useMemo(() => {
    // 如果有任何一个工具在等待用户批准，则状态为 `WaitingForConfirmation`
    if (completedTools.some((tc) => tc.status === 'awaiting_approval')) {
      return StreamingState.WaitingForConfirmation;
    }
    // 如果正在从API接收响应，或者有任何一个工具正在执行/调度/验证/等待提交，则状态为 `Responding`
    if (
      isResponding ||
      completedTools.some(
        (tc) =>
          tc.status === 'executing' ||
          tc.status === 'scheduled' ||
          tc.status === 'validating' ||
          ((tc.status === 'success' ||
            tc.status === 'error' ||
            tc.status === 'cancelled') &&
            !(tc as TrackedToolCall)
              .responseSubmittedToGemini),
      )
    ) {
      return StreamingState.Responding;
    }
    // 否则，状态为空闲 `Idle`
    return StreamingState.Idle;
  }, [isResponding, completedTools]);
  
  // 3. 【用户交互】使用 `ink` 的 `useInput` hook 来监听用户键盘输入，处理取消操作
  useInput((_input, key) => {
    if (streamingState === StreamingState.Responding && key.escape) {
      if (turnCancelledRef.current) {
        return;
      }
      turnCancelledRef.current = true;
      abortControllerRef.current?.abort();
      if (pendingHistoryItemRef.current) {
        addItem(pendingHistoryItemRef.current, Date.now());
      }
      addItem(
        {
          type: MessageType.INFO,
          text: 'Request cancelled.',
        },
        Date.now(),
      );
      setPendingHistoryItem(null);
      setIsResponding(false);
    }
  });
  
  /**
   * 在将查询发送给 Gemini 之前对其进行预处理。
   * 这包括记录日志、分发给不同的命令处理器（斜杠、@、shell）等。
   * @param query - 用户的原始输入。
   * @param userMessageTimestamp - 消息时间戳。
   * @param abortSignal - 中止信号。
   * @returns 一个对象，包含处理后的查询和是否应继续发送给Gemini的标志。
   */
  const prepareQueryForGemini = useCallback(
    async (
      query: PartListUnion,
      userMessageTimestamp: number,
      abortSignal: AbortSignal,
    ): Promise<{
      queryToSend: PartListUnion | null;
      shouldProceed: boolean;
    }> => {
      if (turnCancelledRef.current) {
        return { queryToSend: null, shouldProceed: false };
      }
      if (typeof query === 'string' && query.trim().length === 0) {
        return { queryToSend: null, shouldProceed: false };
      }

      let localQueryToSendToGemini: PartListUnion | null = null;

      if (typeof query === 'string') {
        const trimmedQuery = query.trim();
        logUserPrompt(
          config,
          new UserPromptEvent(trimmedQuery.length, trimmedQuery),
        );
        onDebugMessage(`User query: '${trimmedQuery}'`);
        await logger?.logMessage(MessageSenderType.USER, trimmedQuery);

        // 分发给斜杠命令处理器
        const slashCommandResult = await handleSlashCommand(trimmedQuery);
        if (typeof slashCommandResult === 'boolean' && slashCommandResult) {
          // 如果命令已处理且不需后续操作，则直接返回
          return { queryToSend: null, shouldProceed: false };
        } else if (
          typeof slashCommandResult === 'object' &&
          slashCommandResult.shouldScheduleTool
        ) {
          // 如果斜杠命令希望直接调度一个工具（例如 /memory add）
          const { toolName, toolArgs } = slashCommandResult;
          if (toolName && toolArgs) {
            const toolCallRequest: ToolCallRequestInfo = {
              callId: `${toolName}-${Date.now()}-${Math.random().toString(16).slice(2)}`,
              name: toolName,
              args: toolArgs,
              isClientInitiated: true,
            };
            // 直接调用工具调度器，然后结束本次流程
            scheduleToolCalls([toolCallRequest], abortSignal);
          }
          return { queryToSend: null, shouldProceed: false }; // Handled by scheduling the tool
        }
        
        // 分发给 Shell 命令处理器
        if (shellModeActive && handleShellCommand(trimmedQuery, abortSignal)) {
          return { queryToSend: null, shouldProceed: false };
        }

        // 分发给 @ 命令处理器
        if (isAtCommand(trimmedQuery)) {
          const atCommandResult = await handleAtCommand({
            query: trimmedQuery,
            config,
            addItem,
            onDebugMessage,
            messageId: userMessageTimestamp,
            signal: abortSignal,
          });
          if (!atCommandResult.shouldProceed) {
            return { queryToSend: null, shouldProceed: false };
          }
          localQueryToSendToGemini = atCommandResult.processedQuery;
        } else {
          // 如果是普通查询，添加到历史记录并准备发送
          addItem(
            { type: MessageType.USER, text: trimmedQuery },
            userMessageTimestamp,
          );
          localQueryToSendToGemini = trimmedQuery;
        }
      } else {
        // 如果查询不是字符串，说明它是一个工具调用的响应，直接准备发送
        localQueryToSendToGemini = query;
      }

      if (localQueryToSendToGemini === null) {
        onDebugMessage(
          'Query processing resulted in null, not sending to Gemini.',
        );
        return { queryToSend: null, shouldProceed: false };
      }
      return { queryToSend: localQueryToSendToGemini, shouldProceed: true };
    },
    [
      config,
      addItem,
      onDebugMessage,
      handleShellCommand,
      handleSlashCommand,
      logger,
      shellModeActive,
      scheduleToolCalls,
    ],
  );

  // --- 流事件处理器 ---

  /**
   * 处理从后端发来的 'Content' 类型事件。
   * 负责将流式文本块拼接起来，并以合适的时机更新UI上的"待定"消息项。
   */
  const handleContentEvent = useCallback(
    (
      eventValue: ContentEvent['value'],
      currentGeminiMessageBuffer: string,
      userMessageTimestamp: number,
    ): string => {
      if (turnCancelledRef.current) {
        // 如果用户已取消，则阻止任何后续的UI更新
        return '';
      }
      let newGeminiMessageBuffer = currentGeminiMessageBuffer + eventValue;
      // 如果当前的待定消息不是 gemini 类型，说明一个新的AI响应开始了
      if (
        pendingHistoryItemRef.current?.type !== 'gemini' &&
        pendingHistoryItemRef.current?.type !== 'gemini_content'
      ) {
        if (pendingHistoryItemRef.current) {
          // 将上一个待定项（可能是工具调用组）固化到历史记录中
          addItem(pendingHistoryItemRef.current, userMessageTimestamp);
        }
        // 创建一个新的 'gemini' 类型的待定项来接收文本
        setPendingHistoryItem({ type: 'gemini', text: '' });
        newGeminiMessageBuffer = eventValue;
      }
      // 为了优化渲染性能，当消息变得很长时，将其分割成多个历史项
      const splitPoint = findLastSafeSplitPoint(newGeminiMessageBuffer);
      if (splitPoint === newGeminiMessageBuffer.length) {
        // 如果不需要分割，则直接更新当前待定消息的内容
        setPendingHistoryItem((item) => ({
          type: item?.type as 'gemini' | 'gemini_content',
          text: newGeminiMessageBuffer,
        }));
      } else {
        // 如果需要分割，则将已完整的部分固化到历史记录中...
        const beforeText = newGeminiMessageBuffer.substring(0, splitPoint);
        const afterText = newGeminiMessageBuffer.substring(splitPoint);
        addItem(
          {
            type: pendingHistoryItemRef.current?.type as
              | 'gemini'
              | 'gemini_content',
            text: beforeText,
          },
          userMessageTimestamp,
        );
        // ...然后创建一个新的待定项来接收剩余的文本。
        setPendingHistoryItem({ type: 'gemini_content', text: afterText });
        newGeminiMessageBuffer = afterText;
      }
      return newGeminiMessageBuffer;
    },
    [addItem, pendingHistoryItemRef, setPendingHistoryItem],
  );
  
  /** 处理用户取消事件 */
  const handleUserCancelledEvent = useCallback(
    (userMessageTimestamp: number) => {
      if (turnCancelledRef.current) {
        return;
      }
      if (pendingHistoryItemRef.current) {
        if (pendingHistoryItemRef.current.type === 'tool_group') {
          const updatedTools = pendingHistoryItemRef.current.tools.map(
            (tool) =>
              tool.status === ToolCallStatus.Pending ||
              tool.status === ToolCallStatus.Confirming ||
              tool.status === ToolCallStatus.Executing
                ? { ...tool, status: ToolCallStatus.Canceled }
                : tool,
          );
          const pendingItem: HistoryItemToolGroup = {
            ...pendingHistoryItemRef.current,
            tools: updatedTools,
          };
          addItem(pendingItem, userMessageTimestamp);
        } else {
          addItem(pendingHistoryItemRef.current, userMessageTimestamp);
        }
        setPendingHistoryItem(null);
      }
      addItem(
        { type: MessageType.INFO, text: 'User cancelled the request.' },
        userMessageTimestamp,
      );
      setIsResponding(false);
    },
    [addItem, pendingHistoryItemRef, setPendingHistoryItem],
  );
  
  /** 处理错误事件 */
  const handleErrorEvent = useCallback(
    (eventValue: ErrorEvent['value'], userMessageTimestamp: number) => {
      if (pendingHistoryItemRef.current) {
        addItem(pendingHistoryItemRef.current, userMessageTimestamp);
        setPendingHistoryItem(null);
      }
      addItem(
        {
          type: MessageType.ERROR,
          text: parseAndFormatApiError(
            eventValue.error,
            config.getContentGeneratorConfig().authType,
          ),
        },
        userMessageTimestamp,
      );
    },
    [addItem, pendingHistoryItemRef, setPendingHistoryItem, config],
  );
  
  /** 处理聊天历史压缩事件 */
  const handleChatCompressionEvent = useCallback(
    (eventValue: ServerGeminiChatCompressedEvent['value']) =>
      addItem(
        {
          type: 'info',
          text:
            `IMPORTANT: This conversation approached the input token limit for ${config.getModel()}. ` +
            `A compressed context will be sent for future messages (compressed from: ` +
            `${eventValue?.originalTokenCount ?? 'unknown'} to ` +
            `${eventValue?.newTokenCount ?? 'unknown'} tokens).`,
        },
        Date.now(),
      ),
    [addItem, config],
  );
  
  /**
   * 【核心】处理从后端 GeminiClient 返回的所有流事件。
   * 这是一个事件循环，根据事件类型分发到不同的处理器。
   * @param stream - 从 `GeminiClient` 返回的异步事件流。
   * @param userMessageTimestamp - 用户消息的时间戳。
   * @param signal - 中止信号。
   * @returns 处理状态。
   */
  const processGeminiStreamEvents = useCallback(
    async (
      stream: AsyncIterable<GeminiEvent>,
      userMessageTimestamp: number,
      signal: AbortSignal,
    ): Promise<StreamProcessingStatus> => {
      let geminiMessageBuffer = '';
      const toolCallRequests: ToolCallRequestInfo[] = [];
      for await (const event of stream) {
        switch (event.type) {
          case ServerGeminiEventType.Thought:
            setThought(event.value);
            break;
          case ServerGeminiEventType.Content:
            geminiMessageBuffer = handleContentEvent(
              event.value,
              geminiMessageBuffer,
              userMessageTimestamp,
            );
            break;
          case ServerGeminiEventType.ToolCallRequest:
            // 收集所有工具调用请求
            toolCallRequests.push(event.value);
            break;
          case ServerGeminiEventType.UserCancelled:
            handleUserCancelledEvent(userMessageTimestamp);
            break;
          case ServerGeminiEventType.Error:
            handleErrorEvent(event.value, userMessageTimestamp);
            break;
          case ServerGeminiEventType.ChatCompressed:
            handleChatCompressionEvent(event.value);
            break;
          case ServerGeminiEventType.ToolCallConfirmation:
          case ServerGeminiEventType.ToolCallResponse:
            // 在这一层不做任何处理
            break;
          default: {
            // 强制 exhaustive switch-case 检查
            const unreachable: never = event;
            return unreachable;
          }
        }
      }
      // 当流结束后，如果收集到了工具调用请求，则批量调度它们
      if (toolCallRequests.length > 0) {
        scheduleToolCalls(toolCallRequests, signal);
      }
      return StreamProcessingStatus.Completed;
    },
    [
      handleContentEvent,
      handleUserCancelledEvent,
      handleErrorEvent,
      scheduleToolCalls,
      handleChatCompressionEvent,
    ],
  );
  
  /**
   * 提交查询的入口函数。
   * 这是用户按下回车或工具调用结果返回后，驱动新一轮对话的核心。
   * @param query - 要提交的查询或工具响应。
   * @param options - 包含是否为连续对话的选项。
   */
  const submitQuery = useCallback(
    async (
      queryToSend: PartListUnion,
      options?: { isContinuation?: boolean },
    ) => {
      // 防止在响应中时重复提交
      if (
        (streamingState === StreamingState.Responding ||
          streamingState === StreamingState.WaitingForConfirmation) &&
        !options?.isContinuation
      )
        return;

      const userMessageTimestamp = Date.now();
      setShowHelp(false);
      
      // 创建新的 AbortController
      abortControllerRef.current = new AbortController();
      const abortSignal = abortControllerRef.current.signal;
      turnCancelledRef.current = false;
      
      // 1. 【预处理】调用 prepareQueryForGemini 对输入进行预处理和命令分发
      const { queryToSend: preparedQueryToSend, shouldProceed } = await prepareQueryForGemini(
        queryToSend,
        userMessageTimestamp,
        abortSignal,
      );

      if (!shouldProceed || preparedQueryToSend === null) {
        return;
      }
      
      // 如果不是连续对话（即用户发起的新一轮），则重置会话统计
      if (!options?.isContinuation) {
        startNewTurn();
      }

      setIsResponding(true);
      setInitError(null);

      try {
        const stream = client.sendMessageStream(
          preparedQueryToSend as any[], // The API client expects a plain array
        );

        for await (const event of stream) {
          switch (event.type) {
            case 'content':
              onContent(event.payload.text);
              break;
            case 'tool_call_request':
              // When the model wants to call a tool, schedule it.
              scheduleToolCalls(event.payload, abortSignal);
              break;
            // Other cases like error, thought, etc. would be handled here.
            case 'error':
              onStreamError(new Error(event.payload.message));
              break;
          }
        }
      } catch (err) {
        // ... (error handling)
        if (err instanceof UnauthorizedError) {
          onAuthError();
        } else if (!isNodeError(err) || err.name !== 'AbortError') {
          addItem(
            {
              type: MessageType.ERROR,
              text: parseAndFormatApiError(
                getErrorMessage(err) || 'Unknown error',
                config.getContentGeneratorConfig().authType,
              ),
            },
            userMessageTimestamp,
          );
        }
      } finally {
        setIsResponding(false);
      }
    },
    [
      streamingState,
      setShowHelp,
      prepareQueryForGemini,
      processGeminiStreamEvents,
      pendingHistoryItemRef,
      addItem,
      setPendingHistoryItem,
      setInitError,
      client,
      onAuthError,
      config,
      scheduleToolCalls,
    ],
  );

  /**
   * 【核心】这是一个非常重要的 `useEffect`，它负责**自动将会话延续下去**。
   * 它监听 `completedTools` 和 `isResponding` 状态的变化。
   * 主要职责是：当所有工具都执行完毕后，收集它们的结果，并自动调用 `submitQuery` 将结果发回给 Gemini。
   */
  useEffect(() => {
    const run = async () => {
      // 如果正在响应中，则不执行任何操作，等待当前响应完成
      if (isResponding) {
        return;
      }
      
      // 1. 筛选出所有已经执行完毕（成功、失败、取消）但其结果尚未提交给 Gemini 的工具调用
      const completedAndReadyToSubmitTools = completedTools.filter(
        (
          tc: TrackedToolCall,
        ): tc is TrackedToolCall => {
          const isTerminalState =
            tc.status === 'success' ||
            tc.status === 'error' ||
            tc.status === 'cancelled';

            if (isTerminalState) {
              return (
                tc.response?.responseParts !== undefined
              );
            }
            return false;
          },
        );

      // 对于客户端主动发起的工具调用（如/memory add），完成后直接标记为已提交，无需发回给Gemini
      const clientTools = completedAndReadyToSubmitTools.filter(
        (t) => t.request.isClientInitiated,
      );
      if (clientTools.length > 0) {
        scheduleToolCalls(clientTools.map((t) => t.request), abortControllerRef.current?.signal);
      }

      // 检查是否有新的 save_memory 工具成功执行，如果有，则刷新内存
      const newSuccessfulMemorySaves = completedAndReadyToSubmitTools.filter(
        (t) =>
          t.request.name === 'save_memory' &&
          t.status === 'success' &&
          !processedMemoryToolsRef.current.has(t.request.callId),
      );

      if (newSuccessfulMemorySaves.length > 0) {
        // 异步执行内存刷新
        void performMemoryRefresh();
        // 标记为已处理，防止重复刷新
        newSuccessfulMemorySaves.forEach((t) =>
          processedMemoryToolsRef.current.add(t.request.callId),
        );
      }

      // 2. 【关键检查】只有当所有正在处理的工具都执行完毕时，才继续
      const allToolsAreComplete =
        completedTools.length > 0 &&
        completedTools.length === completedAndReadyToSubmitTools.length;

      if (!allToolsAreComplete) {
        return;
      }
      
      // 筛选出由 Gemini 模型发起的工具调用
      const geminiTools = completedAndReadyToSubmitTools.filter(
        (t) => !t.request.isClientInitiated,
      );

      if (geminiTools.length === 0) {
        return;
      }

      // 如果所有工具都被用户取消了，则特殊处理：将取消结果添加到历史，但不发回给 Gemini
      const allToolsCancelled = geminiTools.every(
        (tc) => tc.status === 'cancelled',
      );

      if (allToolsCancelled) {
        if (geminiClient) {
          // 手动将 function response 添加到核心历史记录中
          const responsesToAdd = geminiTools.flatMap(
            (toolCall) => toolCall.response.responseParts,
          );
          for (const response of responsesToAdd) {
            let parts: Part[];
            if (Array.isArray(response)) {
              parts = response;
            } else if (typeof response === 'string') {
              parts = [{ text: response }];
            } else {
              parts = [response];
            }
            geminiClient.addHistory({
              role: 'user',
              parts,
            });
          }
        }

        const callIdsToMarkAsSubmitted = geminiTools.map(
          (toolCall) => toolCall.request.callId,
        );
        scheduleToolCalls(callIdsToMarkAsSubmitted, abortControllerRef.current?.signal);
        return;
      }
      
      // 3. 【核心操作】收集所有工具的响应，合并它们，并再次调用 `submitQuery`
      const responsesToSend: PartListUnion[] = geminiTools.map(
        (toolCall) => toolCall.response.responseParts,
      );
      const callIdsToMarkAsSubmitted = geminiTools.map(
        (toolCall) => toolCall.request.callId,
      );

      scheduleToolCalls(callIdsToMarkAsSubmitted, abortControllerRef.current?.signal);
      // 以"连续对话"模式提交，这会跳过一些用户输入处理步骤，直接将工具结果发送给模型
      submitQuery(mergePartListUnions(responsesToSend), {
        isContinuation: true,
      });
    };
    void run();
  }, [
    completedTools,
    isResponding,
    submitQuery,
    scheduleToolCalls,
    addItem,
    geminiClient,
    performMemoryRefresh,
    abortControllerRef,
  ]);
  
  // 组合所有待定项（文本、工具组），用于UI渲染
  const pendingHistoryItems = [
    pendingHistoryItemRef.current,
    pendingToolCallGroupDisplay,
  ].filter((i) => i !== undefined && i !== null);

  // 另一个 useEffect，用于在需要时自动保存可恢复的工具调用快照
  useEffect(() => {
    const saveRestorableToolCalls = async () => {
      if (!config.getCheckpointingEnabled()) {
        return;
      }
      const restorableToolCalls = completedTools.filter(
        (toolCall) =>
          (toolCall.request.name === 'replace' ||
            toolCall.request.name === 'write_file') &&
          toolCall.status === 'awaiting_approval',
      );

      if (restorableToolCalls.length > 0) {
        const checkpointDir = config.getProjectTempDir()
          ? path.join(config.getProjectTempDir(), 'checkpoints')
          : undefined;

        if (!checkpointDir) {
          return;
        }

        try {
          await fs.mkdir(checkpointDir, { recursive: true });
        } catch (error) {
          if (!isNodeError(error) || error.code !== 'EEXIST') {
            onDebugMessage(
              `Failed to create checkpoint directory: ${getErrorMessage(error)}`,
            );
            return;
          }
        }

        for (const toolCall of restorableToolCalls) {
          const filePath = toolCall.request.args['file_path'] as string;
          if (!filePath) {
            onDebugMessage(
              `Skipping restorable tool call due to missing file_path: ${toolCall.request.name}`,
            );
            continue;
          }

          try {
            let commitHash = await gitService?.createFileSnapshot(
              `Snapshot for ${toolCall.request.name}`,
            );

            if (!commitHash) {
              commitHash = await gitService?.getCurrentCommitHash();
            }

            if (!commitHash) {
              onDebugMessage(
                `Failed to create snapshot for ${filePath}. Skipping restorable tool call.`,
              );
              continue;
            }

            const timestamp = new Date()
              .toISOString()
              .replace(/:/g, '-')
              .replace(/\./g, '_');
            const toolName = toolCall.request.name;
            const fileName = path.basename(filePath);
            const toolCallWithSnapshotFileName = `${timestamp}-${fileName}-${toolName}.json`;
            const clientHistory = await geminiClient?.getHistory();
            const toolCallWithSnapshotFilePath = path.join(
              checkpointDir,
              toolCallWithSnapshotFileName,
            );

            await fs.writeFile(
              toolCallWithSnapshotFilePath,
              JSON.stringify(
                {
                  history,
                  clientHistory,
                  toolCall: {
                    name: toolCall.request.name,
                    args: toolCall.request.args,
                  },
                  commitHash,
                  filePath,
                },
                null,
                2,
              ),
            );
          } catch (error) {
            onDebugMessage(
              `Failed to write restorable tool call file: ${getErrorMessage(
                error,
              )}`,
            );
          }
        }
      }
    };
    saveRestorableToolCalls();
  }, [completedTools, config, onDebugMessage, gitService, history, geminiClient]);

  return {
    streamingState,
    submitQuery,
    initError,
    pendingHistoryItems,
    thought,
  };
};
