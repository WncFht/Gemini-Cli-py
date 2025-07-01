/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { FunctionDeclaration, PartListUnion, Schema } from '@google/genai';

/**
 * Tool 接口定义了所有工具必须实现的基础功能和属性。
 * 这是一个契约，确保了工具调度器可以统一地处理任何工具。
 */
export interface Tool<
  TParams = unknown,
  TResult extends ToolResult = ToolResult,
> {
  /**
   * 工具的内部名称（用于 API 调用和在注册表中查找）。
   */
  name: string;

  /**
   * 工具的用户友好显示名称。
   */
  displayName: string;

  /**
   * 工具功能的详细描述，会提供给模型以帮助其理解如何使用该工具。
   */
  description: string;

  /**
   * 工具的函数声明 schema，遵循 @google/genai 的 `FunctionDeclaration` 格式。
   * 这定义了工具的参数、类型和必需属性，模型将依据此 schema 来生成调用参数。
   */
  schema: FunctionDeclaration;

  /**
   * 指示工具的输出是否应被渲染为 Markdown。
   */
  isOutputMarkdown: boolean;

  /**
   * 指示工具是否支持实时（流式）输出。
   * 如果为 true，`execute` 方法可以接收一个 `updateOutput` 回调。
   */
  canUpdateOutput: boolean;

  /**
   * 验证工具的参数。
   * 应该在 `shouldConfirmExecute` 和 `execute` 方法中被调用。
   * 如果参数无效，`shouldConfirmExecute` 应立即返回 false。
   * @param params - 需要验证的参数。
   * @returns 如果参数无效，则返回一个错误消息字符串；否则返回 null。
   */
  validateToolParams(params: TParams): string | null;

  /**
   * 获取工具操作的预执行描述。
   * 这段描述会在请求用户确认时显示。
   * @param params - 工具执行的参数。
   * @returns 一个描述工具将做什么的 Markdown 字符串。
   * （为了向后兼容，此方法是可选的）
   */
  getDescription(params: TParams): string;

  /**
   * 判断在执行前是否应该提示用户进行确认。
   * @param params - 工具执行的参数。
   * @param abortSignal - 用于中止操作的 AbortSignal。
   * @returns 如果需要确认，则返回一个包含确认详情的 `ToolCallConfirmationDetails` 对象；
   *          如果不需要确认，则返回 `false`。
   */
  shouldConfirmExecute(
    params: TParams,
    abortSignal: AbortSignal,
  ): Promise<ToolCallConfirmationDetails | false>;

  /**
   * 执行工具的核心逻辑。
   * @param params - 工具执行的参数。
   * @param signal - 用于中止操作的 AbortSignal。
   * @param updateOutput - （可选）一个回调函数，用于在工具执行期间发送流式输出。
   * @returns 一个解析为 `ToolResult` 的 Promise。
   */
  execute(
    params: TParams,
    signal: AbortSignal,
    updateOutput?: (output: string) => void,
  ): Promise<TResult>;
}

/**
 * BaseTool 是一个抽象基类，为实现 `Tool` 接口提供了通用的基础功能。
 * 继承此类可以减少创建新工具时的样板代码。
 */
export abstract class BaseTool<
  TParams = unknown,
  TResult extends ToolResult = ToolResult,
> implements Tool<TParams, TResult>
{
  /**
   * 创建 BaseTool 的一个新实例。
   * @param name - 工具的内部名称（用于 API 调用）。
   * @param displayName - 工具的用户友好显示名称。
   * @param description - 工具功能的描述。
   * @param parameterSchema - 定义参数的 JSON Schema。
   * @param isOutputMarkdown - 工具的输出是否应被渲染为 Markdown。
   * @param canUpdateOutput - 工具是否支持实时（流式）输出。
   */
  constructor(
    readonly name: string,
    readonly displayName: string,
    readonly description: string,
    readonly parameterSchema: Record<string, unknown>,
    readonly isOutputMarkdown: boolean = true,
    readonly canUpdateOutput: boolean = false,
  ) {}

  /**
   * 根据名称、描述和参数 schema 计算得出的函数声明 schema。
   */
  get schema(): FunctionDeclaration {
    return {
      name: this.name,
      description: this.description,
      parameters: this.parameterSchema as Schema,
    };
  }

  /**
   * 验证工具的参数。
   * 这是一个占位符实现，应由子类重写。
   * 典型的实现会使用 JSON Schema 验证器。
   * @param params - 需要验证的参数。
   * @returns 如果参数无效，则返回一个错误消息字符串；否则返回 null。
   */
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  validateToolParams(params: TParams): string | null {
    // 实际实现通常会使用 JSON Schema 验证器。
    // 这是一个应由派生类实现的占位符。
    return null;
  }

  /**
   * 获取工具操作的预执行描述。
   * 这是一个应由派生类重写的默认实现。
   * @param params - 工具执行的参数。
   * @returns 一个描述工具将做什么的 Markdown 字符串。
   */
  getDescription(params: TParams): string {
    return JSON.stringify(params);
  }

  /**
   * 判断在执行前是否应该提示用户进行确认。
   * 默认实现是不需要确认。
   * @param params - 工具执行的参数。
   * @returns 一个解析为 `false` 的 Promise。
   */
  shouldConfirmExecute(
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    params: TParams,
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    abortSignal: AbortSignal,
  ): Promise<ToolCallConfirmationDetails | false> {
    return Promise.resolve(false);
  }

  /**
   * 执行工具的抽象方法。
   * 必须由派生类实现。
   * @param params - 工具执行的参数。
   * @param signal - 用于中止操作的 AbortSignal。
   * @param updateOutput - （可选）用于流式输出的回调。
   * @returns 一个解析为工具执行结果的 Promise。
   */
  abstract execute(
    params: TParams,
    signal: AbortSignal,
    updateOutput?: (output: string) => void,
  ): Promise<TResult>;
}

/**
 * ToolResult 定义了工具执行后的返回结果结构。
 */
export interface ToolResult {
  /**
   * 旨在包含在 LLM 历史记录中的内容。
   * 这应该代表工具执行的客观事实结果，供模型进行后续处理。
   */
  llmContent: PartListUnion;

  /**
   * 用于向用户显示的 Markdown 字符串。
   * 这提供了对结果的用户友好摘要或可视化。
   * 注意：这部分可能被认为是 UI 特有的，如果服务器变为纯 API 驱动，
   * 将来可能会在重构中被移除或修改。
   */
  returnDisplay: ToolResultDisplay;
}

/**
 * 工具结果的显示类型，可以是字符串或文件差异。
 */
export type ToolResultDisplay = string | FileDiff;

/**
 * 文件差异的结构。
 */
export interface FileDiff {
  fileDiff: string;
  fileName: string;
}

// --- 工具调用确认详情类型 ---
// 这些接口定义了在请求用户确认时需要显示的不同类型的信息。

/**
 * 用于"编辑"类工具的确认详情。
 */
export interface ToolEditConfirmationDetails {
  type: 'edit';
  title: string;
  onConfirm: (outcome: ToolConfirmationOutcome) => Promise<void>;
  fileName: string;
  fileDiff: string;
  isModifying?: boolean;
}

/**
 * 用于"执行命令"类工具的确认详情。
 */
export interface ToolExecuteConfirmationDetails {
  type: 'exec';
  title: string;
  onConfirm: (outcome: ToolConfirmationOutcome) => Promise<void>;
  command: string;
  rootCommand: string;
}

/**
 * 用于 MCP（Model-side Code Pre-execution）工具的确认详情。
 */
export interface ToolMcpConfirmationDetails {
  type: 'mcp';
  title:string;
  serverName: string;
  toolName: string;
  toolDisplayName: string;
  onConfirm: (outcome: ToolConfirmationOutcome) => Promise<void>;
}

/**
 * 用于显示一般信息的确认详情。
 */
export interface ToolInfoConfirmationDetails {
  type: 'info';
  title: string;
  onConfirm: (outcome: ToolConfirmationOutcome) => Promise<void>;
  prompt: string;
  urls?: string[];
}

/**
 * 所有可能的工具调用确认详情的联合类型。
 */
export type ToolCallConfirmationDetails =
  | ToolEditConfirmationDetails
  | ToolExecuteConfirmationDetails
  | ToolMcpConfirmationDetails
  | ToolInfoConfirmationDetails;

/**
 * 用户对工具调用确认的可能结果。
 */
export enum ToolConfirmationOutcome {
  ProceedOnce = 'proceed_once', // 同意执行一次
  ProceedAlways = 'proceed_always', // 总是同意执行（会话级别）
  ProceedAlwaysServer = 'proceed_always_server', // 总是同意执行此服务器上的工具
  ProceedAlwaysTool = 'proceed_always_tool', // 总是同意执行此工具
  ModifyWithEditor = 'modify_with_editor', // 使用编辑器修改参数后再执行
  Cancel = 'cancel', // 取消执行
}
