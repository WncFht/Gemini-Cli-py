/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * 斜杠命令处理器 - React 自定义 Hook
 * 
 * 这个文件实现了一个自定义 React Hook，用于处理 CLI 应用中的斜杠命令（如 /help, /clear 等）
 * 
 * React Hook 工作原理简介：
 * ==================
 * 
 * 1. **什么是 Hook？**
 *    - Hook 是 React 16.8 引入的新特性，让你可以在函数组件中使用状态和其他 React 特性
 *    - Hook 的名称必须以 "use" 开头，这是 React 的约定
 *    - Hook 只能在 React 函数组件或其他自定义 Hook 的顶层调用
 * 
 * 2. **自定义 Hook 的作用：**
 *    - 提取组件逻辑，让多个组件可以共享相同的状态逻辑
 *    - 将复杂的逻辑从组件中分离出来，提高代码的可读性和可维护性
 *    - 遵循 React 的组合模式，而不是继承模式
 * 
 * 3. **这个 Hook 的调用流程：**
 *    组件调用 → Hook 初始化 → 返回处理函数和数据 → 组件使用返回值
 * 
 * 4. **核心功能：**
 *    - 定义所有可用的斜杠命令（/help, /clear, /stats 等）
 *    - 解析用户输入的命令字符串
 *    - 执行对应的命令动作
 *    - 管理命令执行的状态和历史记录
 * 
 * 5. **性能优化：**
 *    - 使用 useMemo 缓存命令列表，避免每次渲染都重新创建
 *    - 使用 useCallback 缓存处理函数，避免子组件不必要的重渲染
 */

// React Hooks 导入 - 用于状态管理和性能优化
import { useCallback, useMemo } from 'react';
// Gemini AI 相关类型
import { type PartListUnion } from '@google/genai';
// 用于打开外部链接的工具
import open from 'open';
// Node.js 进程信息
import process from 'node:process';
// 历史记录管理相关 Hook 的类型定义
import { UseHistoryManagerReturn } from './useHistoryManager.js';
// 状态和引用管理的自定义 Hook
import { useStateAndRef } from './useStateAndRef.js';
// 核心功能模块：配置、Git服务、日志记录、MCP服务器状态等
import {
  Config,
  GitService,
  Logger,
  MCPDiscoveryState,
  MCPServerStatus,
  getMCPDiscoveryState,
  getMCPServerStatus,
} from '@google/gemini-cli-core';
// 会话统计信息的 Hook
import { useSessionStats } from '../contexts/SessionContext.js';
// 消息和历史记录相关的类型定义
import {
  HistoryItem,
  HistoryItemWithoutId,
  Message,
  MessageType,
} from '../types.js';
// Node.js 文件系统操作（Promise 版本）
import { promises as fs } from 'fs';
// Node.js 路径操作工具
import path from 'path';
// 内存显示功能
import { createShowMemoryAction } from './useShowMemoryCommand.js';
// Git 提交信息
import { GIT_COMMIT_INFO } from '../../generated/git-commit.js';
// 格式化工具：时间和内存使用量
import { formatDuration, formatMemoryUsage } from '../utils/formatters.js';
// 获取 CLI 版本信息
import { getCliVersion } from '../../utils/version.js';
// 设置配置相关类型
import { LoadedSettings } from '../../config/settings.js';

/**
 * 斜杠命令执行结果的接口定义
 * 
 * 当斜杠命令执行完成后，可能需要触发额外的工具调用（比如调用 AI 模型或外部服务）
 * 这个接口定义了命令执行的结果和后续需要执行的操作
 */
export interface SlashCommandActionReturn {
  shouldScheduleTool?: boolean;        // 是否应该调度工具调用（可选）
  toolName?: string;                   // 要调用的工具名称（可选）
  toolArgs?: Record<string, unknown>;  // 工具调用的参数，键值对格式（可选）
  message?: string;                    // 简单消息或错误信息（可选）
}

/**
 * 斜杠命令的接口定义
 * 
 * 每个斜杠命令都是一个对象，包含以下属性：
 * - 基本信息：名称、描述、别名
 * - 功能：自动补全、执行动作
 * 
 * 命令执行流程：
 * 1. 用户输入斜杠命令（如 "/help" 或 "/clear"）
 * 2. 系统解析命令，匹配对应的 SlashCommand 对象
 * 3. 调用该对象的 action 函数执行具体操作
 * 4. 可选：返回结果指示是否需要进一步的工具调用
 */
export interface SlashCommand {
  name: string;                        // 命令名称（如 "help", "clear" 等）
  altName?: string;                    // 可选的别名（如 "?" 是 "help" 的别名）
  description?: string;                // 命令描述，用于帮助文档
  completion?: () => Promise<string[]>; // 自动补全函数，返回可能的补全选项
  action: (                           // 命令执行函数
    mainCommand: string,               // 主命令名（如 "help"）
    subCommand?: string,               // 子命令（可选，如 "memory show" 中的 "show"）
    args?: string,                     // 参数字符串（可选，命令后面的所有参数）
  ) =>
    | void                             // 无返回值（命令执行完成，无需后续操作）
    | SlashCommandActionReturn         // 返回工具调度信息
    | Promise<void | SlashCommandActionReturn>; // 异步版本
}

/**
 * 斜杠命令处理器的自定义 React Hook
 * 
 * 这是一个 React Hook，用于定义和处理斜杠命令（如 /help, /clear 等）
 * 
 * React Hook 调用逻辑说明：
 * =====================
 * 
 * 1. **组件调用阶段**：
 *    - 某个 React 组件（比如聊天界面组件）调用这个 Hook
 *    - 传入必要的依赖项（配置、设置、历史记录管理函数等）
 * 
 * 2. **Hook 初始化阶段**：
 *    - 使用 useMemo 创建 GitService 实例（只在 config 变化时重新创建）
 *    - 使用 useCallback 创建优化的消息添加函数
 *    - 使用 useMemo 定义所有可用的斜杠命令列表
 *    - 使用 useCallback 创建命令处理函数
 * 
 * 3. **返回值阶段**：
 *    - 返回一个对象，包含处理函数和命令列表
 *    - 组件可以使用这些返回值来处理用户输入
 * 
 * 4. **命令执行阶段**：
 *    - 当用户输入斜杠命令时，组件调用 handleSlashCommand
 *    - Hook 解析命令并执行对应的操作
 *    - 可能返回需要进一步处理的工具调用信息
 * 
 * React Hook 性能优化说明：
 * =====================
 * 
 * - **useMemo**：缓存计算结果，只在依赖项变化时重新计算
 * - **useCallback**：缓存函数引用，避免子组件不必要的重渲染
 * - **依赖项数组**：告诉 React 什么时候需要重新计算或重新创建
 * 
 * 参数说明：
 * ========
 * 
 * @param config - 应用配置对象，包含模型、项目根目录等信息
 * @param settings - 用户设置，包含主题、编辑器偏好等
 * @param history - 聊天历史记录数组，存储用户和 AI 的对话
 * @param addItem - 添加历史记录项的函数，用于记录新的消息
 * @param clearItems - 清空历史记录的函数，用于清理对话历史
 * @param loadHistory - 加载历史记录的函数，用于恢复之前的对话
 * @param refreshStatic - 刷新静态内容的函数，用于更新 UI 显示
 * @param setShowHelp - 控制帮助对话框显示状态的函数（React 状态设置器）
 * @param onDebugMessage - 调试消息回调函数，用于输出调试信息
 * @param openThemeDialog - 打开主题设置对话框的函数
 * @param openAuthDialog - 打开认证设置对话框的函数
 * @param openEditorDialog - 打开编辑器设置对话框的函数
 * @param performMemoryRefresh - 执行内存刷新的函数，用于刷新 AI 的记忆
 * @param toggleCorgiMode - 切换 Corgi 模式的函数（可能是某种特殊模式）
 * @param showToolDescriptions - 是否显示工具描述的布尔值，控制详细信息显示
 * @param setQuittingMessages - 设置退出消息的函数，用于显示退出时的信息
 * 
 * 返回值：
 * ======
 * 
 * @returns 一个对象，包含：
 *   - handleSlashCommand: 处理斜杠命令的函数
 *   - slashCommands: 所有可用的斜杠命令列表
 *   - pendingHistoryItems: 待处理的历史记录项数组
 */
export const useSlashCommandProcessor = (
  config: Config | null,
  settings: LoadedSettings,
  history: HistoryItem[],
  addItem: UseHistoryManagerReturn['addItem'],
  clearItems: UseHistoryManagerReturn['clearItems'],
  loadHistory: UseHistoryManagerReturn['loadHistory'],
  refreshStatic: () => void,
  setShowHelp: (value: boolean | ((prev: boolean) => boolean)) => void,
  onDebugMessage: (message: string) => void,
  openThemeDialog: () => void,
  openAuthDialog: () => void,
  openEditorDialog: () => void,
  performMemoryRefresh: () => Promise<void>,
  toggleCorgiMode: () => void,
  showToolDescriptions: boolean = false,
  setQuittingMessages: (message: HistoryItem[]) => void,
  openPrivacyNotice: () => void,
) => {
  // 获取会话统计信息（使用 React Context）
  // useSessionStats 是另一个自定义 Hook，从 React Context 中获取会话数据
  // React Context 是一种跨组件传递数据的方式，避免层层传递 props
  const session = useSessionStats();
  
  // 使用 useMemo 优化 GitService 实例的创建
  // ==========================================
  // 
  // React useMemo Hook 的作用：
  // - 缓存计算结果，避免每次组件重渲染时都重新计算
  // - 只有当依赖项数组中的值发生变化时，才会重新计算
  // - 这里的依赖项是 [config]，意味着只有 config 变化时才重新创建 GitService
  // 
  // 为什么需要 useMemo？
  // - GitService 的创建可能涉及文件系统操作，比较耗时
  // - 如果每次渲染都创建新实例，会影响性能
  // - 通过缓存，确保相同的 config 总是返回相同的 GitService 实例
  const gitService = useMemo(() => {
    // 检查配置是否存在且有项目根目录
    if (!config?.getProjectRoot()) {
      return; // 返回 undefined，表示无法创建 GitService
    }
    // 创建并返回新的 GitService 实例
    return new GitService(config.getProjectRoot());
  }, [config]); // 依赖项数组：只有 config 变化时才重新计算

  // 待处理的历史记录项数组
  // 这是一个普通的 JavaScript 数组，用于临时存储待添加到历史记录的项目
  const pendingHistoryItems: HistoryItemWithoutId[] = [];
  
  // 使用自定义 Hook 管理压缩状态
  // ============================
  // 
  // useStateAndRef 是一个自定义 Hook，同时返回状态值和引用
  // 这种模式的好处：
  // - 状态值用于触发 React 重渲染
  // - 引用用于在回调函数中访问最新值（避免闭包陷阱）
  // 
  // 闭包陷阱说明：
  // - 在异步操作或事件处理中，可能会捕获旧的状态值
  // - 使用 ref 可以确保总是获取到最新的状态值
  const [pendingCompressionItemRef, setPendingCompressionItem] =
    useStateAndRef<HistoryItemWithoutId | null>(null);
    
  // 如果有待处理的压缩项，添加到待处理列表中
  // 这是一个条件性的副作用，确保待处理的项目被包含在返回值中
  if (pendingCompressionItemRef.current != null) {
    pendingHistoryItems.push(pendingCompressionItemRef.current);
  }

  // 使用 useCallback 优化消息添加函数
  // =================================
  // 
  // React useCallback Hook 的作用：
  // - 返回一个记忆化的回调函数
  // - 只有当依赖项数组中的值发生变化时，才会返回新的函数引用
  // - 这里的依赖项是 [addItem]，意味着只有 addItem 变化时才创建新函数
  // 
  // 为什么需要 useCallback？
  // - 防止每次渲染都创建新的函数引用
  // - 如果这个函数被传递给子组件，避免子组件不必要的重渲染
  // - 在这个例子中，addMessage 会被传递给各种命令的 action 函数
  const addMessage = useCallback(
    (message: Message) => {
      // 将 Message 对象转换为 HistoryItemWithoutId 格式
      // 这是一个类型转换过程，适配不同的消息类型
      let historyItemContent: HistoryItemWithoutId;
      
      // 根据消息类型进行不同的处理
      if (message.type === MessageType.ABOUT) {
        // 关于信息类型：包含版本、系统信息等
        historyItemContent = {
          type: 'about',
          cliVersion: message.cliVersion,
          osVersion: message.osVersion,
          sandboxEnv: message.sandboxEnv,
          modelVersion: message.modelVersion,
          selectedAuthType: message.selectedAuthType,
          gcpProject: message.gcpProject,
        };
      } else if (message.type === MessageType.STATS) {
        // 统计信息类型：包含会话统计和持续时间
        historyItemContent = {
          type: 'stats',
          duration: message.duration,
        };
      } else if (message.type === MessageType.MODEL_STATS) {
        historyItemContent = {
          type: 'model_stats',
        };
      } else if (message.type === MessageType.TOOL_STATS) {
        historyItemContent = {
          type: 'tool_stats',
        };
      } else if (message.type === MessageType.QUIT) {
        // 退出消息类型：包含最终统计信息
        historyItemContent = {
          type: 'quit',
          duration: message.duration,
        };
      } else if (message.type === MessageType.COMPRESSION) {
        // 压缩消息类型：包含压缩相关信息
        historyItemContent = {
          type: 'compression',
          compression: message.compression,
        };
      } else {
        // 其他消息类型：普通文本消息（信息、错误、用户输入）
        historyItemContent = {
          type: message.type,
          text: message.content,
        };
      }
      // 调用传入的 addItem 函数，将转换后的消息添加到历史记录
      addItem(historyItemContent, message.timestamp.getTime());
    },
    [addItem], // 依赖项数组：只有 addItem 变化时才重新创建函数
  );

  const showMemoryAction = useCallback(async () => {
    const actionFn = createShowMemoryAction(config, settings, addMessage);
    await actionFn();
  }, [config, settings, addMessage]);

  const addMemoryAction = useCallback(
    (
      _mainCommand: string,
      _subCommand?: string,
      args?: string,
    ): SlashCommandActionReturn | void => {
      if (!args || args.trim() === '') {
        addMessage({
          type: MessageType.ERROR,
          content: 'Usage: /memory add <text to remember>',
          timestamp: new Date(),
        });
        return;
      }
      // UI feedback for attempting to schedule
      addMessage({
        type: MessageType.INFO,
        content: `Attempting to save to memory: "${args.trim()}"`,
        timestamp: new Date(),
      });
      // Return info for scheduling the tool call
      return {
        shouldScheduleTool: true,
        toolName: 'save_memory',
        toolArgs: { fact: args.trim() },
      };
    },
    [addMessage],
  );

  const savedChatTags = useCallback(async () => {
    const geminiDir = config?.getProjectTempDir();
    if (!geminiDir) {
      return [];
    }
    try {
      const files = await fs.readdir(geminiDir);
      return files
        .filter(
          (file) => file.startsWith('checkpoint-') && file.endsWith('.json'),
        )
        .map((file) => file.replace('checkpoint-', '').replace('.json', ''));
    } catch (_err) {
      return [];
    }
  }, [config]);

  // 使用 useMemo 定义所有可用的斜杠命令
  // ===================================
  // 
  // 这是 Hook 的核心部分，定义了所有可用的斜杠命令
  // 
  // 为什么使用 useMemo？
  // - 命令列表是一个复杂的数据结构，包含多个对象和函数
  // - 每次重新创建这个数组会导致性能问题
  // - 使用 useMemo 确保只有当依赖项变化时才重新创建命令列表
  // 
  // 依赖项数组说明：
  // - 包含了所有在命令定义中使用的外部函数和变量
  // - 当这些依赖项中的任何一个发生变化时，命令列表会重新生成
  // - 这确保了命令总是使用最新的函数引用
  const slashCommands: SlashCommand[] = useMemo(() => {
    // 创建命令数组，每个命令都是一个 SlashCommand 对象
    const commands: SlashCommand[] = [
      // /help 命令 - 显示帮助信息
      // ========================
      {
        name: 'help',           // 主命令名
        altName: '?',           // 别名，用户可以输入 /? 或 /help
        description: 'for help on gemini-cli',  // 命令描述
        action: (_mainCommand, _subCommand, _args) => {
          // 命令执行函数
          // 参数前缀 _ 表示这些参数在此命令中未使用
          onDebugMessage('Opening help.');  // 发送调试消息
          setShowHelp(true);                // 显示帮助对话框
          // 无返回值，表示命令执行完成，无需后续操作
        },
      },
      
      // /docs 命令 - 打开文档
      // ====================
      {
        name: 'docs',
        description: 'open full Gemini CLI documentation in your browser',
        action: async (_mainCommand, _subCommand, _args) => {
          // 异步命令执行函数
          const docsUrl = 'https://goo.gle/gemini-cli-docs';
          
          // 检查是否在沙箱环境中运行
          // 沙箱环境可能无法直接打开浏览器
          if (process.env.SANDBOX && process.env.SANDBOX !== 'sandbox-exec') {
            // 在沙箱中，只显示 URL 让用户手动打开
            addMessage({
              type: MessageType.INFO,
              content: `Please open the following URL in your browser to view the documentation:\n${docsUrl}`,
              timestamp: new Date(),
            });
          } else {
            // 正常环境，尝试自动打开浏览器
            addMessage({
              type: MessageType.INFO,
              content: `Opening documentation in your browser: ${docsUrl}`,
              timestamp: new Date(),
            });
            await open(docsUrl);  // 使用 open 库打开 URL
          }
        },
      },
      
      // /clear 命令 - 清空屏幕和对话历史
      // ===============================
      {
        name: 'clear',
        description: 'clear the screen and conversation history',
        action: async (_mainCommand, _subCommand, _args) => {
          onDebugMessage('Clearing terminal and resetting chat.');
          clearItems();                                    // 清空 UI 中的历史记录
          await config?.getGeminiClient()?.resetChat();    // 重置 AI 聊天状态
          console.clear();                                 // 清空控制台
          refreshStatic();                                 // 刷新静态 UI 元素
        },
      },
      
      // /theme 命令 - 更改主题
      // =====================
      {
        name: 'theme',
        description: 'change the theme',
        action: (_mainCommand, _subCommand, _args) => {
          openThemeDialog();  // 打开主题选择对话框
        },
      },
      
      // /auth 命令 - 更改认证方式
      // ========================
      {
        name: 'auth',
        description: 'change the auth method',
        action: (_mainCommand, _subCommand, _args) => {
          openAuthDialog();  // 打开认证设置对话框
        },
      },
      
      // /editor 命令 - 设置外部编辑器
      // ============================
      {
        name: 'editor',
        description: 'set external editor preference',
        action: (_mainCommand, _subCommand, _args) => {
          openEditorDialog();  // 打开编辑器设置对话框
        },
      },
      {
        name: 'privacy',
        description: 'display the privacy notice',
        action: (_mainCommand, _subCommand, _args) => {
          openPrivacyNotice();
        },
      },
      {
        name: 'stats',
        altName: 'usage',
        description: 'check session stats. Usage: /stats [model|tools]',
        action: (_mainCommand, subCommand, _args) => {
          if (subCommand === 'model') {
            addMessage({
              type: MessageType.MODEL_STATS,
              timestamp: new Date(),
            });
            return;
          } else if (subCommand === 'tools') {
            addMessage({
              type: MessageType.TOOL_STATS,
              timestamp: new Date(),
            });
            return;
          }

          const now = new Date();
          const { sessionStartTime } = session.stats;
          const wallDuration = now.getTime() - sessionStartTime.getTime();

          addMessage({
            type: MessageType.STATS,
            duration: formatDuration(wallDuration),
            timestamp: new Date(),
          });
        },
      },
      {
        name: 'mcp',
        description: 'list configured MCP servers and tools',
        action: async (_mainCommand, _subCommand, _args) => {
          // Check if the _subCommand includes a specific flag to control description visibility
          let useShowDescriptions = showToolDescriptions;
          if (_subCommand === 'desc' || _subCommand === 'descriptions') {
            useShowDescriptions = true;
          } else if (
            _subCommand === 'nodesc' ||
            _subCommand === 'nodescriptions'
          ) {
            useShowDescriptions = false;
          } else if (_args === 'desc' || _args === 'descriptions') {
            useShowDescriptions = true;
          } else if (_args === 'nodesc' || _args === 'nodescriptions') {
            useShowDescriptions = false;
          }
          // Check if the _subCommand includes a specific flag to show detailed tool schema
          let useShowSchema = false;
          if (_subCommand === 'schema' || _args === 'schema') {
            useShowSchema = true;
          }

          const toolRegistry = await config?.getToolRegistry();
          if (!toolRegistry) {
            addMessage({
              type: MessageType.ERROR,
              content: 'Could not retrieve tool registry.',
              timestamp: new Date(),
            });
            return;
          }

          const mcpServers = config?.getMcpServers() || {};
          const serverNames = Object.keys(mcpServers);

          if (serverNames.length === 0) {
            const docsUrl = 'https://goo.gle/gemini-cli-docs-mcp';
            if (process.env.SANDBOX && process.env.SANDBOX !== 'sandbox-exec') {
              addMessage({
                type: MessageType.INFO,
                content: `No MCP servers configured. Please open the following URL in your browser to view documentation:\n${docsUrl}`,
                timestamp: new Date(),
              });
            } else {
              addMessage({
                type: MessageType.INFO,
                content: `No MCP servers configured. Opening documentation in your browser: ${docsUrl}`,
                timestamp: new Date(),
              });
              await open(docsUrl);
            }
            return;
          }

          // Check if any servers are still connecting
          const connectingServers = serverNames.filter(
            (name) => getMCPServerStatus(name) === MCPServerStatus.CONNECTING,
          );
          const discoveryState = getMCPDiscoveryState();

          let message = '';

          // Add overall discovery status message if needed
          if (
            discoveryState === MCPDiscoveryState.IN_PROGRESS ||
            connectingServers.length > 0
          ) {
            message += `\u001b[33m⏳ MCP servers are starting up (${connectingServers.length} initializing)...\u001b[0m\n`;
            message += `\u001b[90mNote: First startup may take longer. Tool availability will update automatically.\u001b[0m\n\n`;
          }

          message += 'Configured MCP servers:\n\n';

          for (const serverName of serverNames) {
            const serverTools = toolRegistry.getToolsByServer(serverName);
            const status = getMCPServerStatus(serverName);

            // Add status indicator with descriptive text
            let statusIndicator = '';
            let statusText = '';
            switch (status) {
              case MCPServerStatus.CONNECTED:
                statusIndicator = '🟢';
                statusText = 'Ready';
                break;
              case MCPServerStatus.CONNECTING:
                statusIndicator = '🔄';
                statusText = 'Starting... (first startup may take longer)';
                break;
              case MCPServerStatus.DISCONNECTED:
              default:
                statusIndicator = '🔴';
                statusText = 'Disconnected';
                break;
            }

            // Get server description if available
            const server = mcpServers[serverName];

            // Format server header with bold formatting and status
            message += `${statusIndicator} \u001b[1m${serverName}\u001b[0m - ${statusText}`;

            // Add tool count with conditional messaging
            if (status === MCPServerStatus.CONNECTED) {
              message += ` (${serverTools.length} tools)`;
            } else if (status === MCPServerStatus.CONNECTING) {
              message += ` (tools will appear when ready)`;
            } else {
              message += ` (${serverTools.length} tools cached)`;
            }

            // Add server description with proper handling of multi-line descriptions
            if ((useShowDescriptions || useShowSchema) && server?.description) {
              const greenColor = '\u001b[32m';
              const resetColor = '\u001b[0m';

              const descLines = server.description.trim().split('\n');
              if (descLines) {
                message += ':\n';
                for (const descLine of descLines) {
                  message += `    ${greenColor}${descLine}${resetColor}\n`;
                }
              } else {
                message += '\n';
              }
            } else {
              message += '\n';
            }

            // Reset formatting after server entry
            message += '\u001b[0m';

            if (serverTools.length > 0) {
              serverTools.forEach((tool) => {
                if (
                  (useShowDescriptions || useShowSchema) &&
                  tool.description
                ) {
                  // Format tool name in cyan using simple ANSI cyan color
                  message += `  - \u001b[36m${tool.name}\u001b[0m`;

                  // Apply green color to the description text
                  const greenColor = '\u001b[32m';
                  const resetColor = '\u001b[0m';

                  // Handle multi-line descriptions by properly indenting and preserving formatting
                  const descLines = tool.description.trim().split('\n');
                  if (descLines) {
                    message += ':\n';
                    for (const descLine of descLines) {
                      message += `      ${greenColor}${descLine}${resetColor}\n`;
                    }
                  } else {
                    message += '\n';
                  }
                  // Reset is handled inline with each line now
                } else {
                  // Use cyan color for the tool name even when not showing descriptions
                  message += `  - \u001b[36m${tool.name}\u001b[0m\n`;
                }
                if (useShowSchema) {
                  // Prefix the parameters in cyan
                  message += `    \u001b[36mParameters:\u001b[0m\n`;
                  // Apply green color to the parameter text
                  const greenColor = '\u001b[32m';
                  const resetColor = '\u001b[0m';

                  const paramsLines = JSON.stringify(
                    tool.schema.parameters,
                    null,
                    2,
                  )
                    .trim()
                    .split('\n');
                  if (paramsLines) {
                    for (const paramsLine of paramsLines) {
                      message += `      ${greenColor}${paramsLine}${resetColor}\n`;
                    }
                  }
                }
              });
            } else {
              message += '  No tools available\n';
            }
            message += '\n';
          }

          // Make sure to reset any ANSI formatting at the end to prevent it from affecting the terminal
          message += '\u001b[0m';

          addMessage({
            type: MessageType.INFO,
            content: message,
            timestamp: new Date(),
          });
        },
      },
      {
        name: 'memory',
        description:
          'manage memory. Usage: /memory <show|refresh|add> [text for add]',
        action: (mainCommand, subCommand, args) => {
          switch (subCommand) {
            case 'show':
              showMemoryAction();
              return;
            case 'refresh':
              performMemoryRefresh();
              return;
            case 'add':
              return addMemoryAction(mainCommand, subCommand, args); // Return the object
            case undefined:
              addMessage({
                type: MessageType.ERROR,
                content:
                  'Missing command\nUsage: /memory <show|refresh|add> [text for add]',
                timestamp: new Date(),
              });
              return;
            default:
              addMessage({
                type: MessageType.ERROR,
                content: `Unknown /memory command: ${subCommand}. Available: show, refresh, add`,
                timestamp: new Date(),
              });
              return;
          }
        },
      },
      {
        name: 'tools',
        description: 'list available Gemini CLI tools',
        action: async (_mainCommand, _subCommand, _args) => {
          // Check if the _subCommand includes a specific flag to control description visibility
          let useShowDescriptions = showToolDescriptions;
          if (_subCommand === 'desc' || _subCommand === 'descriptions') {
            useShowDescriptions = true;
          } else if (
            _subCommand === 'nodesc' ||
            _subCommand === 'nodescriptions'
          ) {
            useShowDescriptions = false;
          } else if (_args === 'desc' || _args === 'descriptions') {
            useShowDescriptions = true;
          } else if (_args === 'nodesc' || _args === 'nodescriptions') {
            useShowDescriptions = false;
          }

          const toolRegistry = await config?.getToolRegistry();
          const tools = toolRegistry?.getAllTools();
          if (!tools) {
            addMessage({
              type: MessageType.ERROR,
              content: 'Could not retrieve tools.',
              timestamp: new Date(),
            });
            return;
          }

          // Filter out MCP tools by checking if they have a serverName property
          const geminiTools = tools.filter((tool) => !('serverName' in tool));

          let message = 'Available Gemini CLI tools:\n\n';

          if (geminiTools.length > 0) {
            geminiTools.forEach((tool) => {
              if (useShowDescriptions && tool.description) {
                // Format tool name in cyan using simple ANSI cyan color
                message += `  - \u001b[36m${tool.displayName} (${tool.name})\u001b[0m:\n`;

                // Apply green color to the description text
                const greenColor = '\u001b[32m';
                const resetColor = '\u001b[0m';

                // Handle multi-line descriptions by properly indenting and preserving formatting
                const descLines = tool.description.trim().split('\n');

                // If there are multiple lines, add proper indentation for each line
                if (descLines) {
                  for (const descLine of descLines) {
                    message += `      ${greenColor}${descLine}${resetColor}\n`;
                  }
                }
              } else {
                // Use cyan color for the tool name even when not showing descriptions
                message += `  - \u001b[36m${tool.displayName}\u001b[0m\n`;
              }
            });
          } else {
            message += '  No tools available\n';
          }
          message += '\n';

          // Make sure to reset any ANSI formatting at the end to prevent it from affecting the terminal
          message += '\u001b[0m';

          addMessage({
            type: MessageType.INFO,
            content: message,
            timestamp: new Date(),
          });
        },
      },
      {
        name: 'corgi',
        action: (_mainCommand, _subCommand, _args) => {
          toggleCorgiMode();
        },
      },
      {
        name: 'about',
        description: 'show version info',
        action: async (_mainCommand, _subCommand, _args) => {
          const osVersion = process.platform;
          let sandboxEnv = 'no sandbox';
          if (process.env.SANDBOX && process.env.SANDBOX !== 'sandbox-exec') {
            sandboxEnv = process.env.SANDBOX;
          } else if (process.env.SANDBOX === 'sandbox-exec') {
            sandboxEnv = `sandbox-exec (${
              process.env.SEATBELT_PROFILE || 'unknown'
            })`;
          }
          const modelVersion = config?.getModel() || 'Unknown';
          const cliVersion = await getCliVersion();
          const selectedAuthType = settings.merged.selectedAuthType || '';
          const gcpProject = process.env.GOOGLE_CLOUD_PROJECT || '';
          addMessage({
            type: MessageType.ABOUT,
            timestamp: new Date(),
            cliVersion,
            osVersion,
            sandboxEnv,
            modelVersion,
            selectedAuthType,
            gcpProject,
          });
        },
      },
      {
        name: 'bug',
        description: 'submit a bug report',
        action: async (_mainCommand, _subCommand, args) => {
          let bugDescription = _subCommand || '';
          if (args) {
            bugDescription += ` ${args}`;
          }
          bugDescription = bugDescription.trim();

          const osVersion = `${process.platform} ${process.version}`;
          let sandboxEnv = 'no sandbox';
          if (process.env.SANDBOX && process.env.SANDBOX !== 'sandbox-exec') {
            sandboxEnv = process.env.SANDBOX.replace(/^gemini-(?:code-)?/, '');
          } else if (process.env.SANDBOX === 'sandbox-exec') {
            sandboxEnv = `sandbox-exec (${
              process.env.SEATBELT_PROFILE || 'unknown'
            })`;
          }
          const modelVersion = config?.getModel() || 'Unknown';
          const cliVersion = await getCliVersion();
          const memoryUsage = formatMemoryUsage(process.memoryUsage().rss);

          const info = `
*   **CLI Version:** ${cliVersion}
*   **Git Commit:** ${GIT_COMMIT_INFO}
*   **Operating System:** ${osVersion}
*   **Sandbox Environment:** ${sandboxEnv}
*   **Model Version:** ${modelVersion}
*   **Memory Usage:** ${memoryUsage}
`;

          let bugReportUrl =
            'https://github.com/google-gemini/gemini-cli/issues/new?template=bug_report.yml&title={title}&info={info}';
          const bugCommand = config?.getBugCommand();
          if (bugCommand?.urlTemplate) {
            bugReportUrl = bugCommand.urlTemplate;
          }
          bugReportUrl = bugReportUrl
            .replace('{title}', encodeURIComponent(bugDescription))
            .replace('{info}', encodeURIComponent(info));

          addMessage({
            type: MessageType.INFO,
            content: `To submit your bug report, please open the following URL in your browser:\n${bugReportUrl}`,
            timestamp: new Date(),
          });
          (async () => {
            try {
              await open(bugReportUrl);
            } catch (error) {
              const errorMessage =
                error instanceof Error ? error.message : String(error);
              addMessage({
                type: MessageType.ERROR,
                content: `Could not open URL in browser: ${errorMessage}`,
                timestamp: new Date(),
              });
            }
          })();
        },
      },
      {
        name: 'chat',
        description:
          'Manage conversation history. Usage: /chat <list|save|resume> [tag]',
        action: async (_mainCommand, subCommand, args) => {
          const tag = (args || '').trim();
          const logger = new Logger(config?.getSessionId() || '');
          await logger.initialize();
          const chat = await config?.getGeminiClient()?.getChat();
          if (!chat) {
            addMessage({
              type: MessageType.ERROR,
              content: 'No chat client available for conversation status.',
              timestamp: new Date(),
            });
            return;
          }
          if (!subCommand) {
            addMessage({
              type: MessageType.ERROR,
              content: 'Missing command\nUsage: /chat <list|save|resume> [tag]',
              timestamp: new Date(),
            });
            return;
          }
          switch (subCommand) {
            case 'save': {
              const history = chat.getHistory();
              if (history.length > 0) {
                await logger.saveCheckpoint(chat?.getHistory() || [], tag);
                addMessage({
                  type: MessageType.INFO,
                  content: `Conversation checkpoint saved${tag ? ' with tag: ' + tag : ''}.`,
                  timestamp: new Date(),
                });
              } else {
                addMessage({
                  type: MessageType.INFO,
                  content: 'No conversation found to save.',
                  timestamp: new Date(),
                });
              }
              return;
            }
            case 'resume':
            case 'restore':
            case 'load': {
              const conversation = await logger.loadCheckpoint(tag);
              if (conversation.length === 0) {
                addMessage({
                  type: MessageType.INFO,
                  content: `No saved checkpoint found${tag ? ' with tag: ' + tag : ''}.`,
                  timestamp: new Date(),
                });
                return;
              }

              clearItems();
              chat.clearHistory();
              const rolemap: { [key: string]: MessageType } = {
                user: MessageType.USER,
                model: MessageType.GEMINI,
              };
              let hasSystemPrompt = false;
              let i = 0;
              for (const item of conversation) {
                i += 1;

                // Add each item to history regardless of whether we display
                // it.
                chat.addHistory(item);

                const text =
                  item.parts
                    ?.filter((m) => !!m.text)
                    .map((m) => m.text)
                    .join('') || '';
                if (!text) {
                  // Parsing Part[] back to various non-text output not yet implemented.
                  continue;
                }
                if (i === 1 && text.match(/context for our chat/)) {
                  hasSystemPrompt = true;
                }
                if (i > 2 || !hasSystemPrompt) {
                  addItem(
                    {
                      type:
                        (item.role && rolemap[item.role]) || MessageType.GEMINI,
                      text,
                    } as HistoryItemWithoutId,
                    i,
                  );
                }
              }
              console.clear();
              refreshStatic();
              return;
            }
            case 'list':
              addMessage({
                type: MessageType.INFO,
                content:
                  'list of saved conversations: ' +
                  (await savedChatTags()).join(', '),
                timestamp: new Date(),
              });
              return;
            default:
              addMessage({
                type: MessageType.ERROR,
                content: `Unknown /chat command: ${subCommand}. Available: list, save, resume`,
                timestamp: new Date(),
              });
              return;
          }
        },
        completion: async () =>
          (await savedChatTags()).map((tag) => 'resume ' + tag),
      },
      {
        name: 'quit',
        altName: 'exit',
        description: 'exit the cli',
        action: async (mainCommand, _subCommand, _args) => {
          const now = new Date();
          const { sessionStartTime } = session.stats;
          const wallDuration = now.getTime() - sessionStartTime.getTime();

          setQuittingMessages([
            {
              type: 'user',
              text: `/${mainCommand}`,
              id: now.getTime() - 1,
            },
            {
              type: 'quit',
              duration: formatDuration(wallDuration),
              id: now.getTime(),
            },
          ]);

          setTimeout(() => {
            process.exit(0);
          }, 100);
        },
      },
      {
        name: 'compress',
        altName: 'summarize',
        description: 'Compresses the context by replacing it with a summary.',
        action: async (_mainCommand, _subCommand, _args) => {
          if (pendingCompressionItemRef.current !== null) {
            addMessage({
              type: MessageType.ERROR,
              content:
                'Already compressing, wait for previous request to complete',
              timestamp: new Date(),
            });
            return;
          }
          setPendingCompressionItem({
            type: MessageType.COMPRESSION,
            compression: {
              isPending: true,
              originalTokenCount: null,
              newTokenCount: null,
            },
          });
          try {
            const compressed = await config!
              .getGeminiClient()!
              .tryCompressChat(true);
            if (compressed) {
              addMessage({
                type: MessageType.COMPRESSION,
                compression: {
                  isPending: false,
                  originalTokenCount: compressed.originalTokenCount,
                  newTokenCount: compressed.newTokenCount,
                },
                timestamp: new Date(),
              });
            } else {
              addMessage({
                type: MessageType.ERROR,
                content: 'Failed to compress chat history.',
                timestamp: new Date(),
              });
            }
          } catch (e) {
            addMessage({
              type: MessageType.ERROR,
              content: `Failed to compress chat history: ${e instanceof Error ? e.message : String(e)}`,
              timestamp: new Date(),
            });
          }
          setPendingCompressionItem(null);
        },
      },
    ];

    if (config?.getCheckpointingEnabled()) {
      commands.push({
        name: 'restore',
        description:
          'restore a tool call. This will reset the conversation and file history to the state it was in when the tool call was suggested',
        completion: async () => {
          const checkpointDir = config?.getProjectTempDir()
            ? path.join(config.getProjectTempDir(), 'checkpoints')
            : undefined;
          if (!checkpointDir) {
            return [];
          }
          try {
            const files = await fs.readdir(checkpointDir);
            return files
              .filter((file) => file.endsWith('.json'))
              .map((file) => file.replace('.json', ''));
          } catch (_err) {
            return [];
          }
        },
        action: async (_mainCommand, subCommand, _args) => {
          const checkpointDir = config?.getProjectTempDir()
            ? path.join(config.getProjectTempDir(), 'checkpoints')
            : undefined;

          if (!checkpointDir) {
            addMessage({
              type: MessageType.ERROR,
              content: 'Could not determine the .gemini directory path.',
              timestamp: new Date(),
            });
            return;
          }

          try {
            // Ensure the directory exists before trying to read it.
            await fs.mkdir(checkpointDir, { recursive: true });
            const files = await fs.readdir(checkpointDir);
            const jsonFiles = files.filter((file) => file.endsWith('.json'));

            if (!subCommand) {
              if (jsonFiles.length === 0) {
                addMessage({
                  type: MessageType.INFO,
                  content: 'No restorable tool calls found.',
                  timestamp: new Date(),
                });
                return;
              }
              const truncatedFiles = jsonFiles.map((file) => {
                const components = file.split('.');
                if (components.length <= 1) {
                  return file;
                }
                components.pop();
                return components.join('.');
              });
              const fileList = truncatedFiles.join('\n');
              addMessage({
                type: MessageType.INFO,
                content: `Available tool calls to restore:\n\n${fileList}`,
                timestamp: new Date(),
              });
              return;
            }

            const selectedFile = subCommand.endsWith('.json')
              ? subCommand
              : `${subCommand}.json`;

            if (!jsonFiles.includes(selectedFile)) {
              addMessage({
                type: MessageType.ERROR,
                content: `File not found: ${selectedFile}`,
                timestamp: new Date(),
              });
              return;
            }

            const filePath = path.join(checkpointDir, selectedFile);
            const data = await fs.readFile(filePath, 'utf-8');
            const toolCallData = JSON.parse(data);

            if (toolCallData.history) {
              loadHistory(toolCallData.history);
            }

            if (toolCallData.clientHistory) {
              await config
                ?.getGeminiClient()
                ?.setHistory(toolCallData.clientHistory);
            }

            if (toolCallData.commitHash) {
              await gitService?.restoreProjectFromSnapshot(
                toolCallData.commitHash,
              );
              addMessage({
                type: MessageType.INFO,
                content: `Restored project to the state before the tool call.`,
                timestamp: new Date(),
              });
            }

            return {
              shouldScheduleTool: true,
              toolName: toolCallData.toolCall.name,
              toolArgs: toolCallData.toolCall.args,
            };
          } catch (error) {
            addMessage({
              type: MessageType.ERROR,
              content: `Could not read restorable tool calls. This is the error: ${error}`,
              timestamp: new Date(),
            });
          }
        },
      });
    }
    return commands;
  }, [
    onDebugMessage,
    setShowHelp,
    refreshStatic,
    openThemeDialog,
    openAuthDialog,
    openEditorDialog,
    clearItems,
    performMemoryRefresh,
    showMemoryAction,
    addMemoryAction,
    addMessage,
    toggleCorgiMode,
    savedChatTags,
    config,
    settings,
    showToolDescriptions,
    session,
    gitService,
    loadHistory,
    addItem,
    setQuittingMessages,
    pendingCompressionItemRef,
    setPendingCompressionItem,
    openPrivacyNotice,
  ]);

  // 斜杠命令处理函数 - 这是 Hook 返回的核心函数
  // ============================================
  // 
  // 这是整个 Hook 最重要的返回值之一，负责处理用户输入的斜杠命令
  // 
  // React useCallback 的使用原因：
  // - 确保函数引用稳定，避免依赖此函数的组件重渲染
  // - 只有当依赖项数组中的值变化时才创建新的函数引用
  // - 依赖项包括 addItem, slashCommands, addMessage
  // 
  // 函数职责：
  // 1. 解析用户输入，判断是否为斜杠命令
  // 2. 提取主命令、子命令和参数
  // 3. 查找匹配的命令并执行
  // 4. 处理命令执行结果，包括可能的工具调用
  const handleSlashCommand = useCallback(
    async (
      rawQuery: PartListUnion, // 原始查询输入，可能是字符串或其他格式
    ): Promise<SlashCommandActionReturn | boolean> => {
      // 第一步：类型检查
      // ===============
      // 由于 rawQuery 可能是不同类型的输入，首先检查是否为字符串
      if (typeof rawQuery !== 'string') {
        return false; // 不是字符串，不处理，返回 false 表示未处理
      }
      
      // 第二步：命令格式检查
      // ==================
      const trimmed = rawQuery.trim();
      // 检查是否是斜杠命令（以 / 或 ? 开头）
      // ? 是 help 命令的特殊别名
      if (!trimmed.startsWith('/') && !trimmed.startsWith('?')) {
        return false; // 不是斜杠命令，不处理
      }
      
      // 第三步：记录用户输入
      // ==================
      // 记录用户消息的时间戳，用于历史记录排序
      const userMessageTimestamp = Date.now();
      
      // 将用户输入添加到历史记录（除了 quit/exit 命令）
      // quit/exit 命令有特殊的处理逻辑，会在命令执行时自己添加到历史记录
      if (trimmed !== '/quit' && trimmed !== '/exit') {
        addItem(
          { type: MessageType.USER, text: trimmed },
          userMessageTimestamp,
        );
      }

      // 第四步：解析命令结构
      // ==================
      // 命令格式：/主命令 子命令 参数
      // 例如：/memory add some text to remember
      //       主命令=memory, 子命令=add, 参数=some text to remember
      let subCommand: string | undefined;
      let args: string | undefined;

      // 命令解析逻辑
      const commandToMatch = (() => {
        // 特殊处理：? 是 help 命令的别名
        if (trimmed.startsWith('?')) {
          return 'help';
        }
        
        // 分割命令字符串：
        // 1. 去掉开头的 / 符号
        // 2. 按空格分割成多个部分
        // 3. 第一部分是主命令，第二部分是子命令，其余是参数
        const parts = trimmed.substring(1).trim().split(/\s+/);
        
        // 解析子命令（第二部分）
        if (parts.length > 1) {
          subCommand = parts[1];
        }
        
        // 解析参数（第三部分及之后，重新合并为字符串）
        if (parts.length > 2) {
          args = parts.slice(2).join(' ');
        }
        
        return parts[0]; // 返回主命令
      })();

      const mainCommand = commandToMatch;

      // 第五步：查找并执行匹配的命令
      // ===========================
      // 遍历所有注册的斜杠命令，寻找匹配的命令
      for (const cmd of slashCommands) {
        // 检查主命令名或别名是否匹配
        if (mainCommand === cmd.name || mainCommand === cmd.altName) {
          // 找到匹配的命令，执行其 action 函数
          const actionResult = await cmd.action(mainCommand, subCommand, args);
          
          // 第六步：处理命令执行结果
          // ======================
          // 检查是否需要调度工具调用
          // 某些命令（如 /memory add）可能需要调用外部工具或 AI 服务
          if (
            typeof actionResult === 'object' &&
            actionResult?.shouldScheduleTool
          ) {
            // 返回工具调度信息给调用者（通常是 useGeminiStream）
            // 调用者会根据这些信息决定如何处理后续的工具调用
            return actionResult;
          }
          return true; // 命令已处理，但不需要调度工具
        }
      }

      // 第七步：处理未知命令
      // ==================
      // 如果没有找到匹配的命令，显示错误消息
      addMessage({
        type: MessageType.ERROR,
        content: `Unknown command: ${trimmed}`,
        timestamp: new Date(),
      });
      return true; // 表示命令已处理（即使是未知命令）
    },
    [addItem, slashCommands, addMessage], // 依赖项：这些变化时重新创建函数
  );

  // Hook 的返回值：提供给使用此 Hook 的组件
  // ========================================
  // 
  // React Hook 的返回值通常是一个对象或数组，包含：
  // 1. 状态值 - 组件可以使用的数据
  // 2. 操作函数 - 组件可以调用的方法
  // 3. 衍生数据 - 基于状态计算出的其他数据
  // 
  // 在这个 Hook 中，返回值包含：
  // - handleSlashCommand: 处理斜杠命令的函数
  // - slashCommands: 所有可用的斜杠命令列表
  // - pendingHistoryItems: 待处理的历史记录项
  // 
  // 组件使用方式示例：
  // const { handleSlashCommand, slashCommands, pendingHistoryItems } = useSlashCommandProcessor(...);
  // 
  // 然后组件可以：
  // - 调用 handleSlashCommand(userInput) 来处理用户输入
  // - 使用 slashCommands 来显示可用命令列表或实现自动补全
  // - 监听 pendingHistoryItems 来显示正在处理的项目
  return { 
    handleSlashCommand,    // 处理斜杠命令的函数
    slashCommands,         // 所有可用的斜杠命令列表
    pendingHistoryItems    // 待处理的历史记录项
  };
};
