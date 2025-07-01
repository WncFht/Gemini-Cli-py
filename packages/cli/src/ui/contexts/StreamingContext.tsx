/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { createContext } from 'react';
import { StreamingState } from '../types.js';

/**
 * 创建一个 React Context，专门用于在组件树中传递当前的"流式响应状态"。
 * 这个 Context 的值是 `StreamingState` 枚举类型，它有三个可能的值：
 * - `StreamingState.Idle`: 空闲状态，没有正在进行的流。
 * - `StreamingState.Responding`: 正在从 API 接收流式数据。
 * - `StreamingState.WaitingForConfirmation`: 正在等待用户对工具调用的确认。
 *
 * 通过这个 Context，应用中的任何组件都可以轻易地"知道"当前的流状态，
 * 并据此做出反应（例如，在 Responding 状态时禁用输入框，在 WaitingForConfirmation 状态时显示确认按钮）。
 */
export const StreamingContext = createContext<StreamingState | undefined>(
  undefined,
);

/**
 * 一个自定义 Hook，用于方便地消费 `StreamingContext`。
 * 它封装了 `React.useContext`，并增加了错误处理：
 * 如果在没有 `StreamingContext.Provider` 的地方使用此 Hook，它会抛出一个明确的错误。
 * @returns {StreamingState} - 当前的流式响应状态。
 */
export const useStreamingContext = (): StreamingState => {
  const context = React.useContext(StreamingContext);
  if (context === undefined) {
    throw new Error(
      'useStreamingContext must be used within a StreamingContextProvider',
    );
  }
  return context;
};
