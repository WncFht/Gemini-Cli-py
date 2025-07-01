/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import {
  CallableTool,
  FunctionDeclaration,
  mcpToTool,
  Schema,
} from '@google/genai';
import { Client } from '@modelcontextprotocol/sdk/client/index.js';
import { SSEClientTransport } from '@modelcontextprotocol/sdk/client/sse.js';
import { StdioClientTransport } from '@modelcontextprotocol/sdk/client/stdio.js';
import { StreamableHTTPClientTransport } from '@modelcontextprotocol/sdk/client/streamableHttp.js';
import { parse } from 'shell-quote';
import { MCPServerConfig } from '../config/config.js';
import { DiscoveredMCPTool } from './mcp-tool.js';
import { ToolRegistry } from './tool-registry.js';

// MCP 默认超时时间，10分钟。
export const MCP_DEFAULT_TIMEOUT_MSEC = 10 * 60 * 1000; // default to 10 minutes

/**
 * MCP 服务器的连接状态枚举。
 */
export enum MCPServerStatus {
  /** 服务器已断开或遇到错误 */
  DISCONNECTED = 'disconnected',
  /** 服务器正在连接中 */
  CONNECTING = 'connecting',
  /** 服务器已连接并准备就绪 */
  CONNECTED = 'connected',
}

/**
 * MCP 整体发现过程的状态枚举。
 */
export enum MCPDiscoveryState {
  /** 发现尚未开始 */
  NOT_STARTED = 'not_started',
  /** 发现正在进行中 */
  IN_PROGRESS = 'in_progress',
  /** 发现已完成（无论是否成功） */
  COMPLETED = 'completed',
}

/**
 * 在 core 包内部用于跟踪每个 MCP 服务器状态的 Map。
 */
const mcpServerStatusesInternal: Map<string, MCPServerStatus> = new Map();

/**
 * 跟踪整体的 MCP 发现状态。
 */
let mcpDiscoveryState: MCPDiscoveryState = MCPDiscoveryState.NOT_STARTED;

/**
 * MCP 服务器状态变更事件的监听器类型。
 */
type StatusChangeListener = (
  serverName: string,
  status: MCPServerStatus,
) => void;
const statusChangeListeners: StatusChangeListener[] = [];

/**
 * 添加一个 MCP 服务器状态变更的监听器。
 */
export function addMCPStatusChangeListener(
  listener: StatusChangeListener,
): void {
  statusChangeListeners.push(listener);
}

/**
 * 移除一个 MCP 服务器状态变更的监听器。
 */
export function removeMCPStatusChangeListener(
  listener: StatusChangeListener,
): void {
  const index = statusChangeListeners.indexOf(listener);
  if (index !== -1) {
    statusChangeListeners.splice(index, 1);
  }
}

/**
 * 更新一个 MCP 服务器的状态并通知所有监听器。
 */
function updateMCPServerStatus(
  serverName: string,
  status: MCPServerStatus,
): void {
  mcpServerStatusesInternal.set(serverName, status);
  // 通知所有监听器
  for (const listener of statusChangeListeners) {
    listener(serverName, status);
  }
}

/**
 * 获取一个 MCP 服务器的当前状态。
 */
export function getMCPServerStatus(serverName: string): MCPServerStatus {
  return (
    mcpServerStatusesInternal.get(serverName) || MCPServerStatus.DISCONNECTED
  );
}

/**
 * 获取所有 MCP 服务器的状态。
 */
export function getAllMCPServerStatuses(): Map<string, MCPServerStatus> {
  return new Map(mcpServerStatusesInternal);
}

/**
 * 获取当前的 MCP 发现状态。
 */
export function getMCPDiscoveryState(): MCPDiscoveryState {
  return mcpDiscoveryState;
}

/**
 * 发现所有配置的 MCP 工具。
 * 这是连接和发现过程的入口点。
 * @param mcpServers - 从配置中读取的 MCP 服务器记录。
 * @param mcpServerCommand - （可选）通过命令行启动的 MCP 服务器命令。
 * @param toolRegistry - 要将发现的工具注册到的工具注册表。
 */
export async function discoverMcpTools(
  mcpServers: Record<string, MCPServerConfig>,
  mcpServerCommand: string | undefined,
  toolRegistry: ToolRegistry,
): Promise<void> {
  // 将发现状态设置为进行中
  mcpDiscoveryState = MCPDiscoveryState.IN_PROGRESS;

  try {
    if (mcpServerCommand) {
      const cmd = mcpServerCommand;
      const args = parse(cmd, process.env) as string[];
      if (args.some((arg) => typeof arg !== 'string')) {
        throw new Error('解析 mcpServerCommand 失败: ' + cmd);
      }
      // 使用通用服务器名称 'mcp'
      mcpServers['mcp'] = {
        command: args[0],
        args: args.slice(1),
      };
    }

    const discoveryPromises = Object.entries(mcpServers).map(
      ([mcpServerName, mcpServerConfig]) =>
        connectAndDiscover(mcpServerName, mcpServerConfig, toolRegistry),
    );
    await Promise.all(discoveryPromises);

    // 标记发现过程已完成
    mcpDiscoveryState = MCPDiscoveryState.COMPLETED;
  } catch (error) {
    // 即使出错，也标记为已完成
    mcpDiscoveryState = MCPDiscoveryState.COMPLETED;
    throw error;
  }
}

/**
 * 连接到单个 MCP 服务器并发现其上的工具。
 * @param mcpServerName - MCP 服务器的名称。
 * @param mcpServerConfig - MCP 服务器的配置。
 * @param toolRegistry - 工具注册表。
 */
async function connectAndDiscover(
  mcpServerName: string,
  mcpServerConfig: MCPServerConfig,
  toolRegistry: ToolRegistry,
): Promise<void> {
  // 初始化服务器状态为连接中
  updateMCPServerStatus(mcpServerName, MCPServerStatus.CONNECTING);

  let transport;
  // 根据配置选择不同的传输方式
  if (mcpServerConfig.httpUrl) {
    // 使用 HTTP 流式传输
    transport = new StreamableHTTPClientTransport(
      new URL(mcpServerConfig.httpUrl),
      transportOptions,
    );
  } else if (mcpServerConfig.url) {
    // 使用服务器发送事件 (SSE) 传输
    transport = new SSEClientTransport(new URL(mcpServerConfig.url));
  } else if (mcpServerConfig.command) {
    // 使用标准输入输出 (stdio) 传输，通过子进程启动服务器
    transport = new StdioClientTransport({
      command: mcpServerConfig.command,
      args: mcpServerConfig.args || [],
      env: {
        ...process.env,
        ...(mcpServerConfig.env || {}),
      } as Record<string, string>,
      cwd: mcpServerConfig.cwd,
      stderr: 'pipe',
    });
  } else {
    console.error(
      `MCP 服务器 '${mcpServerName}' 配置无效：缺少 httpUrl (用于 Streamable HTTP)、url (用于 SSE) 或 command (用于 stdio)。正在跳过。`,
    );
    // 更新状态为已断开
    updateMCPServerStatus(mcpServerName, MCPServerStatus.DISCONNECTED);
    return;
  }

  const mcpClient = new Client({
    name: 'gemini-cli-mcp-client',
    version: '0.0.1',
  });

  // 修补 Client.callTool 以使用请求超时，因为 genai McpCallTool.callTool 没有这样做
  // TODO: 在 GenAI SDK 支持带请求选项的 callTool 后移除此 hack
  if ('callTool' in mcpClient) {
    const origCallTool = mcpClient.callTool.bind(mcpClient);
    mcpClient.callTool = function (params, resultSchema, options) {
      return origCallTool(params, resultSchema, {
        ...options,
        timeout: mcpServerConfig.timeout ?? MCP_DEFAULT_TIMEOUT_MSEC,
      });
    };
  }

  try {
    await mcpClient.connect(transport, {
      timeout: mcpServerConfig.timeout ?? MCP_DEFAULT_TIMEOUT_MSEC,
    });
    // 连接成功
    updateMCPServerStatus(mcpServerName, MCPServerStatus.CONNECTED);
  } catch (error) {
    // 创建一个不包含敏感信息的安全配置对象
    const safeConfig = {
      command: mcpServerConfig.command,
      url: mcpServerConfig.url,
      httpUrl: mcpServerConfig.httpUrl,
      cwd: mcpServerConfig.cwd,
      timeout: mcpServerConfig.timeout,
      trust: mcpServerConfig.trust,
      // 排除可能包含敏感数据的 args 和 env
    };

    let errorString =
      `启动或连接到 MCP 服务器 '${mcpServerName}' 失败 ` +
      `${JSON.stringify(safeConfig)}; \n${error}`;
    if (process.env.SANDBOX) {
      errorString += `\n请确保它在沙箱中可用`;
    }
    console.error(errorString);
    // 更新状态为已断开
    updateMCPServerStatus(mcpServerName, MCPServerStatus.DISCONNECTED);
    return;
  }

  mcpClient.onerror = (error) => {
    console.error(`MCP 错误 (${mcpServerName}):`, error.toString());
    // 发生错误时更新状态为已断开
    updateMCPServerStatus(mcpServerName, MCPServerStatus.DISCONNECTED);
  };

  if (transport instanceof StdioClientTransport && transport.stderr) {
    transport.stderr.on('data', (data) => {
      const stderrStr = data.toString();
      // 过滤掉一些 MCP 服务器的冗长 INFO 日志
      if (!stderrStr.includes('] INFO')) {
        console.debug(`MCP STDERR (${mcpServerName}):`, stderrStr);
      }
    });
  }

  try {
    // 将 MCP 客户端转换为 GenAI SDK 可识别的 CallableTool
    const mcpCallableTool: CallableTool = mcpToTool(mcpClient);
    // 从 MCP 服务器获取工具列表
    const discoveredToolFunctions = await mcpCallableTool.tool();

    if (
      !discoveredToolFunctions ||
      !Array.isArray(discoveredToolFunctions.functionDeclarations)
    ) {
      console.error(
        `MCP 服务器 '${mcpServerName}' 未返回有效的工具函数声明。正在跳过。`,
      );
      if (
        transport instanceof StdioClientTransport ||
        transport instanceof SSEClientTransport ||
        transport instanceof StreamableHTTPClientTransport
      ) {
        await transport.close();
      }
      // 更新状态为已断开
      updateMCPServerStatus(mcpServerName, MCPServerStatus.DISCONNECTED);
      return;
    }

    // 遍历发现的每个函数声明
    for (const funcDecl of discoveredToolFunctions.functionDeclarations) {
      if (!funcDecl.name) {
        console.warn(
          `从 MCP 服务器 '${mcpServerName}' 发现一个没有名称的函数声明。正在跳过。`,
        );
        continue;
      }

      let toolNameForModel = funcDecl.name;

      // 将无效字符（基于 Gemini API 的 400 错误信息）替换为下划线
      toolNameForModel = toolNameForModel.replace(/[^a-zA-Z0-9_.-]/g, '_');

      // 如果工具名已存在，则添加服务器名前缀以避免冲突
      const existingTool = toolRegistry.getTool(toolNameForModel);
      if (existingTool) {
        toolNameForModel = mcpServerName + '__' + toolNameForModel;
      }

      // 如果长度超过 63 个字符，用 '___' 替换中间部分
      // (Gemini API 声称最大长度为 64，但实际限制似乎是 63)
      if (toolNameForModel.length > 63) {
        toolNameForModel =
          toolNameForModel.slice(0, 28) + '___' + toolNameForModel.slice(-32);
      }

      // 清理参数 schema
      sanatizeParameters(funcDecl.parameters);

      // 确保 parameters 是一个有效的 JSON schema 对象，如果不是则默认为空。
      const parameterSchema: Record<string, unknown> =
        funcDecl.parameters && typeof funcDecl.parameters === 'object'
          ? { ...(funcDecl.parameters as FunctionDeclaration) }
          : { type: 'object', properties: {} };

      // 将发现的 MCP 工具注册到工具注册表
      toolRegistry.registerTool(
        new DiscoveredMCPTool(
          mcpCallableTool,
          mcpServerName,
          toolNameForModel, // 这是给模型看的、经过处理的名称
          funcDecl.description ?? '',
          parameterSchema,
          funcDecl.name, // 这是在 MCP 服务器上的原始名称
          mcpServerConfig.timeout ?? MCP_DEFAULT_TIMEOUT_MSEC,
          mcpServerConfig.trust,
        ),
      );
    }
  } catch (error) {
    console.error(
      `为 MCP 服务器 '${mcpServerName}' 列出或注册工具失败: ${error}`,
    );
    // 同样在出错时确保清理传输层
    if (
      transport instanceof StdioClientTransport ||
      transport instanceof SSEClientTransport ||
      transport instanceof StreamableHTTPClientTransport
    ) {
      await transport.close();
    }
    // 更新状态为已断开
    updateMCPServerStatus(mcpServerName, MCPServerStatus.DISCONNECTED);
  }

  // 如果没有从此 MCP 服务器注册任何工具，以下 'if' 块将关闭连接。
  // 这样做是为了节省资源，并防止与不提供任何可用功能的服务器保持孤立连接。
  // 与提供了工具的服务器的连接将保持打开，因为这些工具需要连接才能工作。
  if (toolRegistry.getToolsByServer(mcpServerName).length === 0) {
    console.log(
      `没有从 MCP 服务器 '${mcpServerName}' 注册任何工具。正在关闭连接。`,
    );
    if (
      transport instanceof StdioClientTransport ||
      transport instanceof SSEClientTransport ||
      transport instanceof StreamableHTTPClientTransport
    ) {
      await transport.close();
      // 更新状态为已断开
      updateMCPServerStatus(mcpServerName, MCPServerStatus.DISCONNECTED);
    }
  }
}

/**
 * 清理参数 schema 以兼容 Vertex AI。
 * @param schema - 要清理的 schema。
 */
export function sanatizeParameters(schema?: Schema) {
  if (!schema) {
    return;
  }
  if (schema.anyOf) {
    // 如果同时设置了 anyOf 和 default，Vertex AI 会感到困惑。
    schema.default = undefined;
    for (const item of schema.anyOf) {
      sanitizeParameters(item);
    }
  }
  if (schema.items) {
    sanitizeParameters(schema.items);
  }
  if (schema.properties) {
    for (const item of Object.values(schema.properties)) {
      sanitizeParameters(item);
    }
  }
}
