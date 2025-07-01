/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import React, {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from 'react';

import { type GenerateContentResponseUsageMetadata } from '@google/genai';

// --- 类型定义 ---

/**
 * 定义了用于累积统计的数据结构。
 * 这可以用于整个会话（cumulative）、当前回合（currentTurn）或单个响应（currentResponse）。
 */
export interface CumulativeStats {
  turnCount: number; // 回合数
  promptTokenCount: number; // 输入 token 数
  candidatesTokenCount: number; // 模型生成 token 数
  totalTokenCount: number; // 总 token 数
  cachedContentTokenCount: number; // 缓存内容 token 数
  toolUsePromptTokenCount: number; // 工具调用 token 数
  thoughtsTokenCount: number; // 思考过程 token 数
  apiTimeMs: number; // API 调用耗时（毫秒）
}

/**
 * 整个会话统计的状态结构。
 */
interface SessionStatsState {
  sessionStartTime: Date; // 会话开始时间
  cumulative: CumulativeStats; // 整个会话的累积统计
  currentTurn: CumulativeStats; // 当前交互回合的累积统计
  currentResponse: CumulativeStats; // 单次模型响应的统计
}

/**
 * 定义了 Context 最终暴露给消费者的值，包括状态和操作函数。
 */
interface SessionStatsContextValue {
  stats: SessionStatsState;
}

// --- Context 定义 ---

const SessionStatsContext = createContext<SessionStatsContextValue | undefined>(
  undefined,
);

// --- 辅助函数 ---

/**
 * 一个可复用的辅助函数，用于累加 token 数量。
 * 它将源对象中的所有 token 值加到目标对象上。
 * @param target - 目标统计对象（例如 cumulative, currentTurn）。
 * @param source - 来自 API 响应的元数据源。
 */
const addTokens = (
  target: CumulativeStats,
  source: GenerateContentResponseUsageMetadata & { apiTimeMs?: number },
) => {
  target.candidatesTokenCount += source.candidatesTokenCount ?? 0;
  target.thoughtsTokenCount += source.thoughtsTokenCount ?? 0;
  target.totalTokenCount += source.totalTokenCount ?? 0;
  target.apiTimeMs += source.apiTimeMs ?? 0;
  target.promptTokenCount += source.promptTokenCount ?? 0;
  target.cachedContentTokenCount += source.cachedContentTokenCount ?? 0;
  target.toolUsePromptTokenCount += source.toolUsePromptTokenCount ?? 0;
};

// --- Provider 组件 ---

/**
 * SessionStatsProvider 是一个 React 组件，作为 Context 的提供者。
 * 它封装了所有与会话统计相关的状态和逻辑，并通过 Context API 将它们提供给其子组件。
 */
export const SessionStatsProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  // 使用 useState 来存储整个会话的统计状态。
  const [stats, setStats] = useState<SessionStatsState>({
    sessionStartTime: new Date(),
    cumulative: {
      turnCount: 0,
      promptTokenCount: 0,
      candidatesTokenCount: 0,
      totalTokenCount: 0,
      cachedContentTokenCount: 0,
      toolUsePromptTokenCount: 0,
      thoughtsTokenCount: 0,
      apiTimeMs: 0,
    },
    currentTurn: {
      turnCount: 0,
      promptTokenCount: 0,
      candidatesTokenCount: 0,
      totalTokenCount: 0,
      cachedContentTokenCount: 0,
      toolUsePromptTokenCount: 0,
      thoughtsTokenCount: 0,
      apiTimeMs: 0,
    },
    currentResponse: {
      turnCount: 0,
      promptTokenCount: 0,
      candidatesTokenCount: 0,
      totalTokenCount: 0,
      cachedContentTokenCount: 0,
      toolUsePromptTokenCount: 0,
      thoughtsTokenCount: 0,
      apiTimeMs: 0,
    },
  });

  /**
   * 一个内部工作函数，用于处理从 API 返回的用量元数据。
   * 使用 useCallback 进行记忆化以优化性能。
   */
  const aggregateTokens = useCallback(
    (
      metadata: GenerateContentResponseUsageMetadata & { apiTimeMs?: number },
    ) => {
      setStats((prevState) => {
        const newCumulative = { ...prevState.cumulative };
        const newCurrentTurn = { ...prevState.currentTurn };
        const newCurrentResponse = {
          turnCount: 0,
          promptTokenCount: 0,
          candidatesTokenCount: 0,
          totalTokenCount: 0,
          cachedContentTokenCount: 0,
          toolUsePromptTokenCount: 0,
          thoughtsTokenCount: 0,
          apiTimeMs: 0,
        };

        // 将新的 token 用量同时累加到"当前回合"、"累积总量"和"当前响应"中。
        addTokens(newCurrentTurn, metadata);
        addTokens(newCumulative, metadata);
        addTokens(newCurrentResponse, metadata);

        return {
          ...prevState,
          cumulative: newCumulative,
          currentTurn: newCurrentTurn,
          currentResponse: newCurrentResponse,
        };
      });
    },
    [],
  );

  /**
   * 开始一个新的人机交互回合。
   * 这会增加总回合数，并重置"当前回合"的统计数据。
   */
  const startNewTurn = useCallback(() => {
    setStats((prevState) => ({
      ...prevState,
      cumulative: {
        ...prevState.cumulative,
        turnCount: prevState.cumulative.turnCount + 1,
      },
      currentTurn: {
        turnCount: 0, // 重置当前回合的统计
        promptTokenCount: 0,
        candidatesTokenCount: 0,
        totalTokenCount: 0,
        cachedContentTokenCount: 0,
        toolUsePromptTokenCount: 0,
        thoughtsTokenCount: 0,
        apiTimeMs: 0,
      },
      currentResponse: {
        turnCount: 0,
        promptTokenCount: 0,
        candidatesTokenCount: 0,
        totalTokenCount: 0,
        cachedContentTokenCount: 0,
        toolUsePromptTokenCount: 0,
        thoughtsTokenCount: 0,
        apiTimeMs: 0,
      },
    }));
  }, []);

  // 使用 useMemo 来记忆化 context 的值，
  // 仅当 stats, startNewTurn, aggregateTokens 之一发生变化时才重新创建。
  // 这可以防止不必要的重渲染。
  const value = useMemo(
    () => ({
      stats,
    }),
    [stats],
  );

  return (
    <SessionStatsContext.Provider value={value}>
      {children}
    </SessionStatsContext.Provider>
  );
};

// --- Consumer Hook ---

/**
 * 一个自定义 Hook，用于方便地消费 `SessionStatsContext`。
 * 它封装了 `useContext` 并添加了错误检查。
 */
export const useSessionStats = () => {
  const context = useContext(SessionStatsContext);
  if (context === undefined) {
    throw new Error(
      'useSessionStats must be used within a SessionStatsProvider',
    );
  }
  return context;
};
