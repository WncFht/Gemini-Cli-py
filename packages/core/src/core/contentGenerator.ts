/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import {
  CountTokensParameters,
  CountTokensResponse,
  EmbedContentParameters,
  EmbedContentResponse,
  GenerateContentParameters,
  GenerateContentResponse,
  GoogleGenAI,
} from '@google/genai';
import { createCodeAssistContentGenerator } from '../code_assist/codeAssist.js';
import { DEFAULT_GEMINI_MODEL } from '../config/models.js';
import { getEffectiveModel } from './modelCheck.js';

/**
 * 内容生成器接口 (ContentGenerator)
 * 抽象了生成内容、流式生成内容、计算 token 和生成嵌入向量的核心功能。
 * 这是一个适配器接口，允许系统以统一的方式与不同后端的 AI 服务交互
 *（例如，标准的 Gemini API、Vertex AI，或通过 Code Assist 的特殊代理）。
 */
export interface ContentGenerator {
  /**
   * 生成内容。
   * @param request - 生成内容的参数。
   * @returns 一个解析为 `GenerateContentResponse` 的 Promise。
   */
  generateContent(
    request: GenerateContentParameters,
  ): Promise<GenerateContentResponse>;

  /**
   * 以流式方式生成内容。
   * @param request - 生成内容的参数。
   * @returns 一个解析为 `GenerateContentResponse` 异步生成器的 Promise。
   */
  generateContentStream(
    request: GenerateContentParameters,
  ): Promise<AsyncGenerator<GenerateContentResponse>>;

  /**
   * 计算内容的 token 数量。
   * @param request - 计算 token 的参数。
   * @returns 一个解析为 `CountTokensResponse` 的 Promise。
   */
  countTokens(request: CountTokensParameters): Promise<CountTokensResponse>;

  /**
   * 为内容生成嵌入向量。
   * @param request - 生成嵌入向量的参数。
   * @returns 一个解析为 `EmbedContentResponse` 的 Promise。
   */
  embedContent(request: EmbedContentParameters): Promise<EmbedContentResponse>;
}

/**
 * 认证类型枚举。
 * 定义了可以用来与 Google AI 服务进行认证的不同方式。
 */
export enum AuthType {
  LOGIN_WITH_GOOGLE_PERSONAL = 'oauth-personal', // 通过个人的 Google 账号 OAuth 登录
  USE_GEMINI = 'gemini-api-key', // 使用 Gemini API 密钥
  USE_VERTEX_AI = 'vertex-ai', // 使用 Vertex AI
}

/**
 * 内容生成器的配置类型。
 */
export type ContentGeneratorConfig = {
  model: string;
  apiKey?: string;
  vertexai?: boolean;
  authType?: AuthType | undefined;
};

/**
 * 创建内容生成器的配置对象。
 * 这个函数会从环境变量中读取必要的认证信息（如 API keys, Google Cloud 项目），
 * 并根据指定的认证类型构建一个完整的配置对象。
 * @param model - 使用的模型名称。
 * @param authType - 认证类型。
 * @param config - 可选的附加配置，例如用于获取运行时模型的函数。
 * @returns 一个解析为 `ContentGeneratorConfig` 的 Promise。
 */
export async function createContentGeneratorConfig(
  model: string | undefined,
  authType: AuthType | undefined,
  config?: { getModel?: () => string },
): Promise<ContentGeneratorConfig> {
  const geminiApiKey = process.env.GEMINI_API_KEY;
  const googleApiKey = process.env.GOOGLE_API_KEY;
  const googleCloudProject = process.env.GOOGLE_CLOUD_PROJECT;
  const googleCloudLocation = process.env.GOOGLE_CLOUD_LOCATION;

  // 如果在配置中提供了 getModel 函数，则使用它获取运行时模型，否则回退到参数或默认模型。
  const effectiveModel = config?.getModel?.() || model || DEFAULT_GEMINI_MODEL;

  const contentGeneratorConfig: ContentGeneratorConfig = {
    model: effectiveModel,
    authType,
  };

  // 如果我们使用 Google auth，目前不需要其他验证。
  if (authType === AuthType.LOGIN_WITH_GOOGLE_PERSONAL) {
    return contentGeneratorConfig;
  }

  // 如果使用 Gemini API Key
  if (authType === AuthType.USE_GEMINI && geminiApiKey) {
    contentGeneratorConfig.apiKey = geminiApiKey;
    contentGeneratorConfig.model = await getEffectiveModel(
      contentGeneratorConfig.apiKey,
      contentGeneratorConfig.model,
    );

    return contentGeneratorConfig;
  }

  // 如果使用 Vertex AI，需要 API Key 和 GCP 项目信息
  if (
    authType === AuthType.USE_VERTEX_AI &&
    !!googleApiKey &&
    googleCloudProject &&
    googleCloudLocation
  ) {
    contentGeneratorConfig.apiKey = googleApiKey;
    contentGeneratorConfig.vertexai = true;
    contentGeneratorConfig.model = await getEffectiveModel(
      contentGeneratorConfig.apiKey,
      contentGeneratorConfig.model,
    );

    return contentGeneratorConfig;
  }

  return contentGeneratorConfig;
}

/**
 * 工厂函数，根据提供的配置创建并返回一个 `ContentGenerator` 实例。
 * @param config - 内容生成器的配置。
 * @returns 一个解析为 `ContentGenerator` 实例的 Promise。
 */
export async function createContentGenerator(
  config: ContentGeneratorConfig,
): Promise<ContentGenerator> {
  const version = process.env.CLI_VERSION || process.version;
  // 设置 HTTP 头部，以便后端服务识别请求来源
  const httpOptions = {
    headers: {
      'User-Agent': `GeminiCLI/${version} (${process.platform}; ${process.arch})`,
    },
  };

  // 对于个人 OAuth 登录，使用特殊的 CodeAssistContentGenerator
  if (config.authType === AuthType.LOGIN_WITH_GOOGLE_PERSONAL) {
    return createCodeAssistContentGenerator(httpOptions, config.authType);
  }

  // 对于 API Key 或 Vertex AI，使用标准的 GoogleGenAI SDK
  if (
    config.authType === AuthType.USE_GEMINI ||
    config.authType === AuthType.USE_VERTEX_AI
  ) {
    const googleGenAI = new GoogleGenAI({
      apiKey: config.apiKey === '' ? undefined : config.apiKey,
      vertexai: config.vertexai,
      httpOptions,
    });

    // `googleGenAI.models` 实现了 ContentGenerator 接口
    return googleGenAI.models;
  }

  throw new Error(
    `创建 contentGenerator 时出错：不支持的 authType: ${config.authType}`,
  );
}
