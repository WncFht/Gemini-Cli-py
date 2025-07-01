/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import {
  ApprovalMode,
  AuthType,
  Config,
  EditTool,
  logUserPrompt,
  sessionId,
  ShellTool,
  WriteFileTool,
} from '@google/gemini-cli-core';
import { render } from 'ink';
import { spawn } from 'node:child_process';
import os from 'node:os';
import { basename } from 'node:path';
import v8 from 'node:v8';
import React from 'react';
import { validateAuthMethod } from './config/auth.js';
import { loadCliConfig } from './config/config.js';
import { Extension, loadExtensions } from './config/extension.js';
import {
  LoadedSettings,
  loadSettings,
  SettingScope,
} from './config/settings.js';
import { runNonInteractive } from './nonInteractiveCli.js';
import { AppWrapper } from './ui/App.js';
import { setMaxSizedBoxDebugging } from './ui/components/shared/MaxSizedBox.js';
import { themeManager } from './ui/themes/theme-manager.js';
import { cleanupCheckpoints } from './utils/cleanup.js';
import { readStdin } from './utils/readStdin.js';
import { start_sandbox } from './utils/sandbox.js';
import { getStartupWarnings } from './utils/startupWarnings.js';

/**
 * 根据系统总内存计算并返回 Node.js 的内存限制参数。
 * 目的是在内存充足的情况下，自动增加 Node.js 的堆大小，以提升性能。
 * @param config - 应用配置实例。
 * @returns {string[]} - 一个包含 `--max-old-space-size` 参数的数组，如果需要的话。
 */
function getNodeMemoryArgs(config: Config): string[] {
  const totalMemoryMB = os.totalmem() / (1024 * 1024);
  const heapStats = v8.getHeapStatistics();
  const currentMaxOldSpaceSizeMb = Math.floor(
    heapStats.heap_size_limit / 1024 / 1024,
  );

  // 将目标堆大小设置为总内存的50%
  const targetMaxOldSpaceSizeInMB = Math.floor(totalMemoryMB * 0.5);
  if (config.getDebugMode()) {
    console.debug(
      `Current heap size ${currentMaxOldSpaceSizeMb.toFixed(2)} MB`,
    );
  }

  // 如果设置了环境变量，则不进行重启动
  if (process.env.GEMINI_CLI_NO_RELAUNCH) {
    return [];
  }

  // 如果目标大小大于当前大小，则返回需要添加的启动参数
  if (targetMaxOldSpaceSizeInMB > currentMaxOldSpaceSizeMb) {
    if (config.getDebugMode()) {
      console.debug(
        `Need to relaunch with more memory: ${targetMaxOldSpaceSizeInMB.toFixed(2)} MB`,
      );
    }
    return [`--max-old-space-size=${targetMaxOldSpaceSizeInMB}`];
  }

  return [];
}

/**
 * 使用额外的参数重新启动当前应用进程。
 * @param additionalArgs - 需要附加到启动命令的参数数组。
 */
async function relaunchWithAdditionalArgs(additionalArgs: string[]) {
  const nodeArgs = [...additionalArgs, ...process.argv.slice(1)];
  // 设置环境变量，防止无限循环重启动
  const newEnv = { ...process.env, GEMINI_CLI_NO_RELAUNCH: 'true' };

  const child = spawn(process.execPath, nodeArgs, {
    stdio: 'inherit',
    env: newEnv,
  });

  await new Promise((resolve) => child.on('close', resolve));
  process.exit(0);
}

/**
 * 【核心】CLI 应用的主入口函数。
 * 负责应用的引导、配置加载、环境检查、模式判断和最终的渲染。
 */
export async function main() {
  const workspaceRoot = process.cwd();
  // 1. 加载所有配置和设置
  const settings = loadSettings(workspaceRoot);

  await cleanupCheckpoints();
  // 如果配置文件有误，则打印错误并退出
  if (settings.errors.length > 0) {
    for (const error of settings.errors) {
      let errorMessage = `Error in ${error.path}: ${error.message}`;
      if (!process.env.NO_COLOR) {
        errorMessage = `\x1b[31m${errorMessage}\x1b[0m`;
      }
      console.error(errorMessage);
      console.error(`Please fix ${error.path} and try again.`);
    }
    process.exit(1);
  }

  const extensions = loadExtensions(workspaceRoot);
  const config = await loadCliConfig(settings.merged, extensions, sessionId);

  // 如果用户未选择认证方式但设置了 GEMINI_API_KEY，则自动设为默认值
  if (!settings.merged.selectedAuthType && process.env.GEMINI_API_KEY) {
    settings.setValue(
      SettingScope.User,
      'selectedAuthType',
      AuthType.USE_GEMINI,
    );
  }

  setMaxSizedBoxDebugging(config.getDebugMode());

  // 初始化核心服务
  config.getFileService();
  if (config.getCheckpointingEnabled()) {
    try {
      await config.getGitService();
    } catch {
      // 暂时忽略错误，后续可能会记录日志
    }
  }
  
  // 设置主题
  if (settings.merged.theme) {
    if (!themeManager.setActiveTheme(settings.merged.theme)) {
      // 如果主题未找到，打印警告，UI层会处理后续对话框
      console.warn(`Warning: Theme "${settings.merged.theme}" not found.`);
    }
  }

  // 2. 检查并配置内存
  const memoryArgs = settings.merged.autoConfigureMaxOldSpaceSize
    ? getNodeMemoryArgs(config)
    : [];

  // 3. 检查并进入沙箱环境（如果配置了）
  if (!process.env.SANDBOX) {
    const sandboxConfig = config.getSandbox();
    if (sandboxConfig) {
      if (settings.merged.selectedAuthType) {
        // 在进入沙箱前验证认证，因为沙箱会影响OAuth重定向
        try {
          const err = validateAuthMethod(settings.merged.selectedAuthType);
          if (err) {
            throw new Error(err);
          }
          await config.refreshAuth(settings.merged.selectedAuthType);
        } catch (err) {
          console.error('Error authenticating:', err);
          process.exit(1);
        }
      }
      await start_sandbox(sandboxConfig, memoryArgs);
      process.exit(0);
    } else {
      // 如果不需要进入沙箱，但需要增加内存，则重启动应用
      if (memoryArgs.length > 0) {
        await relaunchWithAdditionalArgs(memoryArgs);
        process.exit(0);
      }
    }
  }
  let input = config.getQuestion();
  const startupWarnings = await getStartupWarnings();

  // 4. 【核心路由】判断应用运行模式
  // 如果是TTY（交互式终端）并且没有通过命令行直接提供问题，则进入交互式UI模式
  if (process.stdin.isTTY && input?.length === 0) {
    setWindowTitle(basename(workspaceRoot), settings);
    // 使用 ink 渲染 React 组件，启动交互式应用
    render(
      <React.StrictMode>
        <AppWrapper
          config={config}
          settings={settings}
          startupWarnings={startupWarnings}
        />
      </React.StrictMode>,
      { exitOnCtrlC: false },
    );
    return;
  }
  // 如果不是 TTY，说明有内容通过管道 (pipe) 传入
  if (!process.stdin.isTTY) {
    input += await readStdin();
  }
  if (!input) {
    console.error('No input provided via stdin.');
    process.exit(1);
  }

  logUserPrompt(config, {
    'event.name': 'user_prompt',
    'event.timestamp': new Date().toISOString(),
    prompt: input,
    prompt_length: input.length,
  });

  // 5. 如果是以上条件之外的情况（例如，通过命令行提供了问题），则进入非交互模式
  const nonInteractiveConfig = await loadNonInteractiveConfig(
    config,
    extensions,
    settings,
  );
  
  // 执行非交互式逻辑并退出
  await runNonInteractive(nonInteractiveConfig, input);
  process.exit(0);
}

/**
 * 设置终端窗口的标题。
 * @param title - 标题内容。
 * @param settings - 加载的设置，用于检查是否隐藏标题。
 */
function setWindowTitle(title: string, settings: LoadedSettings) {
  if (!settings.merged.hideWindowTitle) {
    process.stdout.write(`\x1b]2; Gemini - ${title} \x07`);

    process.on('exit', () => {
      process.stdout.write(`\x1b]2;\x07`);
    });
  }
}

// --- 全局未处理的 Promise Rejection 处理器 ---
process.on('unhandledRejection', (reason, _promise) => {
  // 记录严重的、未预料到的错误
  console.error('=========================================');
  console.error('CRITICAL: Unhandled Promise Rejection!');
  console.error('=========================================');
  console.error('Reason:', reason);
  console.error('Stack trace may follow:');
  if (!(reason instanceof Error)) {
    console.error(reason);
  }
  // 对于真正的未处理错误，直接退出进程
  process.exit(1);
});

/**
 * 加载非交互模式所需的配置。
 * 主要工作是排除掉所有需要用户交互的工具（如shell, edit_file）。
 */
async function loadNonInteractiveConfig(
  config: Config,
  extensions: Extension[],
  settings: LoadedSettings,
) {
  let finalConfig = config;
  if (config.getApprovalMode() !== ApprovalMode.YOLO) {
    // 如果不是 YOLO 模式，确保只使用只读工具
    const existingExcludeTools = settings.merged.excludeTools || [];
    const interactiveTools = [
      ShellTool.Name,
      EditTool.Name,
      WriteFileTool.Name,
    ];

    const newExcludeTools = [
      ...new Set([...existingExcludeTools, ...interactiveTools]),
    ];

    const nonInteractiveSettings = {
      ...settings.merged,
      excludeTools: newExcludeTools,
    };
    finalConfig = await loadCliConfig(
      nonInteractiveSettings,
      extensions,
      config.getSessionId(),
    );
  }

  return await validateNonInterActiveAuth(
    settings.merged.selectedAuthType,
    finalConfig,
  );
}

/**
 * 验证非交互模式下的认证方法。
 */
async function validateNonInterActiveAuth(
  selectedAuthType: AuthType | undefined,
  nonInteractiveConfig: Config,
) {
  // 特殊处理：如果未设置认证方式，但存在 GEMINI_API_KEY 环境变量，则自动使用它。
  if (!selectedAuthType && !process.env.GEMINI_API_KEY) {
    console.error(
      'Please set an Auth method in your .gemini/settings.json OR specify GEMINI_API_KEY env variable file before running',
    );
    process.exit(1);
  }

  selectedAuthType = selectedAuthType || AuthType.USE_GEMINI;
  const err = validateAuthMethod(selectedAuthType);
  if (err != null) {
    console.error(err);
    process.exit(1);
  }

  await nonInteractiveConfig.refreshAuth(selectedAuthType);
  return nonInteractiveConfig;
}
