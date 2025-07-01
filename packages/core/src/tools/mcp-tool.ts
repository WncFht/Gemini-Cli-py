/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { CallableTool, FunctionCall, Part } from '@google/genai';
import {
  BaseTool,
  ToolCallConfirmationDetails,
  ToolConfirmationOutcome,
  ToolMcpConfirmationDetails,
  ToolResult,
} from './tools.js';

type ToolParams = Record<string, unknown>;

/**
 * DiscoveredMCPTool 是一个适配器类，用于将通过 MCP (Model-Context Protocol)
 * 发现的远程工具包装成符合本地 `Tool` 接口的对象。
 *
 * 它处理了与远程 MCP 工具交互的复杂性，包括：
 * - 为模型提供一个经过清理和唯一化的工具名称。
 * - 管理执行确认流程，包括基于服务器或单个工具的信任设置。
 * - 将本地的 `execute` 调用转换为对远程 MCP 服务器的 `callTool` 请求。
 * - 将远程服务器返回的结果格式化为用户友好的显示字符串。
 */
export class DiscoveredMCPTool extends BaseTool<ToolParams, ToolResult> {
  // 一个静态的白名单，用于存储用户已选择"总是同意"的服务器或工具。
  private static readonly allowlist: Set<string> = new Set();

  constructor(
    // 从 `@google/genai` 来的 `CallableTool` 实例，封装了与 MCP 服务器的通信。
    private readonly mcpTool: CallableTool,
    // 工具所在的 MCP 服务器的名称。
    readonly serverName: string,
    // 工具的名称，这是经过处理后暴露给模型和在注册表中使用的唯一名称。
    readonly name: string,
    // 工具的描述。
    readonly description: string,
    // 工具的参数 schema。
    readonly parameterSchema: Record<string, unknown>,
    // 工具在 MCP 服务器上的原始名称。
    readonly serverToolName: string,
    // 调用超时时间。
    readonly timeout?: number,
    // 服务器是否被信任（如果是，则跳过确认）。
    readonly trust?: boolean,
  ) {
    super(
      name,
      `${serverToolName} (${serverName} MCP Server)`,
      description,
      parameterSchema,
      true, // isOutputMarkdown
      false, // canUpdateOutput
    );
  }

  /**
   * 判断在执行前是否应该提示用户进行确认。
   *
   * @param _params - 工具参数（在此方法中未使用）。
   * @param _abortSignal - AbortSignal（在此方法中未使用）。
   * @returns 如果需要确认，则返回一个包含确认详情的对象；否则返回 `false`。
   */
  async shouldConfirmExecute(
    _params: ToolParams,
    _abortSignal: AbortSignal,
  ): Promise<ToolCallConfirmationDetails | false> {
    const serverAllowListKey = this.serverName;
    const toolAllowListKey = `${this.serverName}.${this.serverToolName}`;

    if (this.trust) {
      return false; // 服务器是受信任的，无需确认
    }

    if (
      DiscoveredMCPTool.allowlist.has(serverAllowListKey) ||
      DiscoveredMCPTool.allowlist.has(toolAllowListKey)
    ) {
      return false; // 服务器和/或工具已在白名单中
    }

    const confirmationDetails: ToolMcpConfirmationDetails = {
      type: 'mcp',
      title: '确认 MCP 工具执行',
      serverName: this.serverName,
      toolName: this.serverToolName, // 在确认时显示原始工具名称
      toolDisplayName: this.name, // 显示暴露给模型和用户的全局注册表名称
      onConfirm: async (outcome: ToolConfirmationOutcome) => {
        // 根据用户的选择，将服务器或特定工具添加到白名单
        if (outcome === ToolConfirmationOutcome.ProceedAlwaysServer) {
          DiscoveredMCPTool.allowlist.add(serverAllowListKey);
        } else if (outcome === ToolConfirmationOutcome.ProceedAlwaysTool) {
          DiscoveredMCPTool.allowlist.add(toolAllowListKey);
        }
      },
    };
    return confirmationDetails;
  }

  /**
   * 执行工具。
   * 此方法会将本地的调用请求转换为对远程 MCP 服务器的实际调用。
   *
   * @param params - 工具的参数。
   * @returns 一个解析为 `ToolResult` 的 Promise。
   */
  async execute(params: ToolParams): Promise<ToolResult> {
    const functionCalls: FunctionCall[] = [
      {
        name: this.serverToolName, // 使用在 MCP 服务器上的原始工具名称
        args: params,
      },
    ];

    // 通过 mcpTool 实例调用远程工具
    const responseParts: Part[] = await this.mcpTool.callTool(functionCalls);

    return {
      llmContent: responseParts,
      returnDisplay: getStringifiedResultForDisplay(responseParts),
    };
  }
}

/**
 * 处理一个 `Part` 对象数组（主要来自工具的执行结果），
 * 以生成一个用户友好的字符串表示，通常用于在 CLI 中显示。
 *
 * 这个函数会智能地处理不同的 `Part` 类型：
 * 1. `FunctionResponse` 部分：
 *    - 如果 `response.content` 是一个仅包含 `TextPart` 的数组，它会将所有文本内容连接成一个单一的字符串。
 *    - 如果 `response.content` 是一个包含其他类型 `Part` 的数组，它会保留 `content` 数组本身。这用于处理工具返回的 JSON 对象等结构化数据。
 *    - 否则，它会保留整个 `functionResponse` 对象。
 * 2. 其他 `Part` 类型：
 *    - 直接保留原样。
 *
 * 所有处理过的部分最终会被格式化为一个带缩进的 JSON 字符串，并包裹在 Markdown 代码块中。
 *
 * @param result - 来自工具执行结果的 `Part` 数组。
 * @returns 格式化后的字符串。
 */
function getStringifiedResultForDisplay(result: Part[]) {
  if (!result || result.length === 0) {
    return '```json\n[]\n```';
  }

  const processFunctionResponse = (part: Part) => {
    if (part.functionResponse) {
      const responseContent = part.functionResponse.response?.content;
      if (responseContent && Array.isArray(responseContent)) {
        // 检查 responseContent 中的所有 part 是否都是简单的 TextPart
        const allTextParts = responseContent.every(
          (p: Part) => p.text !== undefined,
        );
        if (allTextParts) {
          // 如果是，则将它们的文本连接起来
          return responseContent.map((p: Part) => p.text).join('');
        }
        // 如果不全是简单的 TextPart，则返回这些内容部分的数组，以便进行 JSON 字符串化
        return responseContent;
      }

      // 如果没有内容，或不是数组，或不是 functionResponse，则字符串化整个 functionResponse 部分以供检查
      return part.functionResponse;
    }
    return part; // 对于非 FunctionResponsePart 或意外结构的回退
  };

  const processedResults =
    result.length === 1
      ? processFunctionResponse(result[0])
      : result.map(processFunctionResponse);
  if (typeof processedResults === 'string') {
    return processedResults;
  }

  return '```json\n' + JSON.stringify(processedResults, null, 2) + '\n```';
}
