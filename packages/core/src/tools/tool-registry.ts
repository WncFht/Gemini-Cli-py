/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { FunctionDeclaration } from '@google/genai';
import { execSync, spawn } from 'node:child_process';
import { Config } from '../config/config.js';
import { discoverMcpTools } from './mcp-client.js';
import { DiscoveredMCPTool } from './mcp-tool.js';
import { BaseTool, Tool, ToolResult } from './tools.js';

type ToolParams = Record<string, unknown>;

/**
 * DiscoveredTool 类是一个适配器，用于将通过命令行发现的外部工具包装成
 * 符合内部 `Tool` 接口的对象。
 * 这使得工具调度器可以统一处理内建工具和外部发现的工具。
 */
export class DiscoveredTool extends BaseTool<ToolParams, ToolResult> {
  constructor(
    private readonly config: Config,
    readonly name: string,
    readonly description: string,
    readonly parameterSchema: Record<string, unknown>,
  ) {
    const discoveryCmd = config.getToolDiscoveryCommand()!;
    const callCommand = config.getToolCallCommand()!;
    // 自动向描述中追加关于工具来源和调用方式的信息
    description += `

这个工具是通过在项目根目录执行命令 \`${discoveryCmd}\` 从项目中发现的。
调用时，此工具将在项目根目录执行命令 \`${callCommand} ${name}\`。
工具的发现和调用命令可以在项目或用户设置中配置。

调用时，工具调用命令会作为一个子进程执行。
成功时，工具的输出将作为 JSON 字符串返回。
否则，将返回以下信息：

Stdout: 标准输出流的内容。可能为 \`(empty)\` 或不完整。
Stderr: 标准错误流的内容。可能为 \`(empty)\` 或不完整。
Error: 子进程的错误信息，如果没有错误则为 \`(none)\`。
Exit Code: 退出码，如果被信号终止则为 \`(none)\`。
Signal: 终止信号，如果没有信号则为 \`(none)\`。
`;
    super(
      name,
      name,
      description,
      parameterSchema,
      false, // isOutputMarkdown
      false, // canUpdateOutput
    );
  }

  /**
   * 执行这个发现的工具。
   * 它会通过 `spawn` 创建一个子进程来运行配置的 `toolCallCommand`，
   * 并将参数通过 `stdin` 以 JSON 格式传递给子进程。
   * @param params - 工具的参数。
   * @returns 一个解析为 `ToolResult` 的 Promise。
   */
  async execute(params: ToolParams): Promise<ToolResult> {
    const callCommand = this.config.getToolCallCommand()!;
    const child = spawn(callCommand, [this.name]);
    // 将参数作为 JSON 字符串写入子进程的标准输入
    child.stdin.write(JSON.stringify(params));
    child.stdin.end();

    let stdout = '';
    let stderr = '';
    let error: Error | null = null;
    let code: number | null = null;
    let signal: NodeJS.Signals | null = null;

    // 等待子进程完成
    await new Promise<void>((resolve) => {
      const onStdout = (data: Buffer) => {
        stdout += data?.toString();
      };

      const onStderr = (data: Buffer) => {
        stderr += data?.toString();
      };

      const onError = (err: Error) => {
        error = err;
      };

      const onClose = (
        _code: number | null,
        _signal: NodeJS.Signals | null,
      ) => {
        code = _code;
        signal = _signal;
        cleanup();
        resolve();
      };

      const cleanup = () => {
        child.stdout.removeListener('data', onStdout);
        child.stderr.removeListener('data', onStderr);
        child.removeListener('error', onError);
        child.removeListener('close', onClose);
        if (child.connected) {
          child.disconnect();
        }
      };

      child.stdout.on('data', onStdout);
      child.stderr.on('data', onStderr);
      child.on('error', onError);
      child.on('close', onClose);
    });

    // 如果有任何错误、非零退出码、信号或标准错误输出，则返回详细的错误信息
    if (error || code !== 0 || signal || stderr) {
      const llmContent = [
        `Stdout: ${stdout || '(empty)'}`,
        `Stderr: ${stderr || '(empty)'}`,
        `Error: ${error ?? '(none)'}`,
        `Exit Code: ${code ?? '(none)'}`,
        `Signal: ${signal ?? '(none)'}`,
      ].join('\n');
      return {
        llmContent,
        returnDisplay: llmContent,
      };
    }

    // 成功时，返回标准输出
    return {
      llmContent: stdout,
      returnDisplay: stdout,
    };
  }
}

/**
 * ToolRegistry 是一个中央存储库，用于管理所有可用的工具。
 * 它负责注册内建工具和动态发现外部工具。
 */
export class ToolRegistry {
  private tools: Map<string, Tool> = new Map();
  private discovery: Promise<void> | null = null;
  private config: Config;

  constructor(config: Config) {
    this.config = config;
  }

  /**
   * 注册一个工具定义。
   * @param tool - 包含 schema 和执行逻辑的工具对象。
   */
  registerTool(tool: Tool): void {
    if (this.tools.has(tool.name)) {
      // 决定行为：抛出错误、记录警告或允许覆盖
      console.warn(
        `名为 "${tool.name}" 的工具已被注册。正在覆盖。`,
      );
    }
    this.tools.set(tool.name, tool);
  }

  /**
   * 从项目中发现工具（如果已配置并可用）。
   * 可以多次调用以更新发现的工具。
   * 它会先移除所有之前发现的工具，然后重新执行发现过程。
   */
  async discoverTools(): Promise<void> {
    // 移除任何先前发现的工具
    for (const tool of this.tools.values()) {
      if (tool instanceof DiscoveredTool || tool instanceof DiscoveredMCPTool) {
        this.tools.delete(tool.name);
      } else {
        // 保留手动注册的工具
      }
    }
    // 使用发现命令发现工具（如果已配置）
    const discoveryCmd = this.config.getToolDiscoveryCommand();
    if (discoveryCmd) {
      // 执行发现命令并提取函数声明
      const functions: FunctionDeclaration[] = [];
      for (const tool of JSON.parse(execSync(discoveryCmd).toString().trim())) {
        if (tool['function_declarations']) {
          functions.push(...tool['function_declarations']);
        } else if (tool['functionDeclarations']) {
          functions.push(...tool['functionDeclarations']);
        } else if (tool['name']) {
          functions.push(tool);
        }
      }
      // 将每个函数注册为一个 DiscoveredTool
      for (const func of functions) {
        this.registerTool(
          new DiscoveredTool(
            this.config,
            func.name!,
            func.description!,
            func.parameters! as Record<string, unknown>,
          ),
        );
      }
    }
    // 使用 MCP 服务器发现工具（如果已配置）
    await discoverMcpTools(
      this.config.getMcpServers() ?? {},
      this.config.getMcpServerCommand(),
      this,
    );
  }

  /**
   * 获取所有工具的 schema 列表（`FunctionDeclaration` 数组）。
   * 这是为了将可用工具的信息提供给模型。
   * @returns `FunctionDeclaration` 数组。
   */
  getFunctionDeclarations(): FunctionDeclaration[] {
    const declarations: FunctionDeclaration[] = [];
    this.tools.forEach((tool) => {
      declarations.push(tool.schema);
    });
    return declarations;
  }

  /**
   * 返回一个包含所有已注册和已发现工具实例的数组。
   */
  getAllTools(): Tool[] {
    return Array.from(this.tools.values());
  }

  /**
   * 返回从特定 MCP 服务器注册的工具数组。
   */
  getToolsByServer(serverName: string): Tool[] {
    const serverTools: Tool[] = [];
    for (const tool of this.tools.values()) {
      if ((tool as DiscoveredMCPTool)?.serverName === serverName) {
        serverTools.push(tool);
      }
    }
    return serverTools;
  }

  /**
   * 获取特定工具的定义。
   * @param name - 工具的名称。
   * @returns 找到的 `Tool` 实例，如果不存在则为 `undefined`。
   */
  getTool(name: string): Tool | undefined {
    return this.tools.get(name);
  }
}
