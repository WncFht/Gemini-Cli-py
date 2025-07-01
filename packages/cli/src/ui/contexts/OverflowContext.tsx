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

/**
 * 定义了溢出状态的数据结构。
 */
interface OverflowState {
  // 一个只读的 Set，用于存储当前内容已溢出的组件的 ID。
  overflowingIds: ReadonlySet<string>;
}

/**
 * 定义了可以对溢出状态执行的操作。
 */
interface OverflowActions {
  // 添加一个组件 ID 到溢出集合中。
  addOverflowingId: (id: string) => void;
  // 从溢出集合中移除一个组件 ID。
  removeOverflowingId: (id:string) => void;
}

// 创建一个专门用于传递"状态"的 Context。
const OverflowStateContext = createContext<OverflowState | undefined>(
  undefined,
);

// 创建一个专门用于传递"操作"的 Context。
// 将状态和操作分离是一种常见的 Context 模式，可以避免不必要的重渲染。
const OverflowActionsContext = createContext<OverflowActions | undefined>(
  undefined,
);

/**
 * 一个自定义 Hook，用于方便地消费 `OverflowStateContext`，获取溢出状态。
 */
export const useOverflowState = (): OverflowState | undefined =>
  useContext(OverflowStateContext);

/**
 * 一个自定义 Hook，用于方便地消费 `OverflowActionsContext`，获取操作函数。
 */
export const useOverflowActions = (): OverflowActions | undefined =>
  useContext(OverflowActionsContext);

/**
 * OverflowProvider 是一个 React 组件，它作为 Context 的提供者。
 * 它包裹了需要共享"溢出"状态的子组件树。
 * 任何被它包裹的子组件都可以通过 `useOverflowState` 和 `useOverflowActions` hooks
 * 来访问和操作溢出状态。
 */
export const OverflowProvider: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  // 使用 useState 来存储溢出的 ID 集合。
  const [overflowingIds, setOverflowingIds] = useState(new Set<string>());

  // 使用 useCallback 来记忆化 addOverflowingId 函数，
  // 仅在依赖项改变时才重新创建函数，以优化性能。
  const addOverflowingId = useCallback((id: string) => {
    setOverflowingIds((prevIds) => {
      // 如果 ID 已存在，直接返回旧的 Set，避免不必要的渲染。
      if (prevIds.has(id)) {
        return prevIds;
      }
      // 否则，创建一个新的 Set 并添加 ID。
      const newIds = new Set(prevIds);
      newIds.add(id);
      return newIds;
    });
  }, []);

  // 同理，记忆化 removeOverflowingId 函数。
  const removeOverflowingId = useCallback((id: string) => {
    setOverflowingIds((prevIds) => {
      // 如果 ID 不存在，直接返回旧的 Set。
      if (!prevIds.has(id)) {
        return prevIds;
      }
      const newIds = new Set(prevIds);
      newIds.delete(id);
      return newIds;
    });
  }, []);

  // 使用 useMemo 来记忆化 state 对象。
  // 仅当 `overflowingIds` 发生变化时，才创建一个新的 state 对象。
  // 这可以防止消费此 Context 的子组件在不必要时进行重渲染。
  const stateValue = useMemo(
    () => ({
      overflowingIds,
    }),
    [overflowingIds],
  );

  // 同理，记忆化 actions 对象。
  const actionsValue = useMemo(
    () => ({
      addOverflowingId,
      removeOverflowingId,
    }),
    [addOverflowingId, removeOverflowingId],
  );

  return (
    // 将 state 对象通过 State Context 提供给下层组件。
    <OverflowStateContext.Provider value={stateValue}>
      {/* 将 actions 对象通过 Actions Context 提供给下层组件。 */}
      <OverflowActionsContext.Provider value={actionsValue}>
        {children}
      </OverflowActionsContext.Provider>
    </OverflowStateContext.Provider>
  );
};
