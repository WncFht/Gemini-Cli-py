/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import {
  Content,
  EmbedContentParameters,
  GenerateContentConfig,
  GenerateContentResponse,
  Part,
  PartListUnion,
  SchemaUnion,
  Tool,
} from '@google/genai';
import { ProxyAgent, setGlobalDispatcher } from 'undici';
import { Config } from '../config/config.js';
import { DEFAULT_GEMINI_FLASH_MODEL } from '../config/models.js';
import { ReadManyFilesTool } from '../tools/read-many-files.js';
import { reportError } from '../utils/errorReporting.js';
import { getErrorMessage } from '../utils/errors.js';
import { getResponseText } from '../utils/generateContentResponseUtilities.js';
import { getFolderStructure } from '../utils/getFolderStructure.js';
import { checkNextSpeaker } from '../utils/nextSpeakerChecker.js';
import { retryWithBackoff } from '../utils/retry.js';
import {
  AuthType,
  ContentGenerator,
  ContentGeneratorConfig,
  createContentGenerator
} from './contentGenerator.js';
import { GeminiChat } from './geminiChat.js';
import { getCoreSystemPrompt } from './prompts.js';
import { tokenLimit } from './tokenLimits.js';
import {
  ChatCompressionInfo,
  GeminiEventType,
  ServerGeminiStreamEvent,
  Turn,
} from './turn.js';

/**
 * 检查模型是否支持"思考"功能。
 * @param model - 模型名称字符串。
 * @returns 如果支持则返回 true。
 */
function isThinkingSupported(model: string) {
  if (model.startsWith('gemini-2.5')) return true;
  return false;
}

/**
 * GeminiClient 是与 Gemini API 交互的顶层客户端。
 * 它负责管理聊天会话、初始化环境上下文、发送消息、处理流式响应，
 * 以及协调更底层的组件如 GeminiChat 和 ContentGenerator。
 */
export class GeminiClient {
  private chat?: GeminiChat;
  private contentGenerator?: ContentGenerator;
  private model: string;
  private embeddingModel: string;
  // 默认的生成配置
  private generateContentConfig: GenerateContentConfig = {
    temperature: 0,
    topP: 1,
  };
  // 最大对话回合数，用于防止无限递归
  private readonly MAX_TURNS = 100;

  constructor(private config: Config) {
    if (config.getProxy()) {
      setGlobalDispatcher(new ProxyAgent(config.getProxy() as string));
    }

    this.model = config.getModel();
    this.embeddingModel = config.getEmbeddingModel();
  }

  /**
   * 异步初始化客户端，创建 ContentGenerator 和 GeminiChat 实例。
   * 这是客户端可以工作前必须调用的方法。
   * @param contentGeneratorConfig - 内容生成器的配置。
   */
  async initialize(contentGeneratorConfig: ContentGeneratorConfig) {
    this.contentGenerator = await createContentGenerator(
      contentGeneratorConfig,
    );
    this.chat = await this.startChat();
  }

  /**
   * 获取 ContentGenerator 实例，如果未初始化则抛出错误。
   * @returns ContentGenerator 实例。
   */
  private getContentGenerator(): ContentGenerator {
    if (!this.contentGenerator) {
      throw new Error('内容生成器未初始化');
    }
    return this.contentGenerator;
  }

  /**
   * 向当前聊天会话添加一条历史记录。
   * @param content - 要添加的内容。
   */
  async addHistory(content: Content) {
    this.getChat().addHistory(content);
  }

  /**
   * 获取当前的 GeminiChat 实例，如果未初始化则抛出错误。
   * @returns GeminiChat 实例。
   */
  getChat(): GeminiChat {
    if (!this.chat) {
      throw new Error('聊天未初始化');
    }
    return this.chat;
  }

  /**
   * 获取当前聊天会话的历史记录。
   * @returns 聊天历史内容数组。
   */
  async getHistory(): Promise<Content[]> {
    return this.getChat().getHistory();
  }

  /**
   * 设置当前聊天会话的历史记录。
   * @param history - 新的聊天历史内容数组。
   */
  async setHistory(history: Content[]): Promise<void> {
    this.getChat().setHistory(history);
  }

  /**
   * 重置聊天会话，会重新初始化环境上下文和历史记录。
   */
  async resetChat(): Promise<void> {
    this.chat = await this.startChat();
    await this.chat;
  }

  /**
   * 构建并返回初始的环境上下文，作为与模型对话的开场白。
   * 包括日期、操作系统、工作目录、文件结构等信息。
   * 如果配置了 `getFullContext`，则会读取并包含项目下所有文件的内容。
   * @returns 一个包含环境信息的 `Part` 数组。
   */
  private async getEnvironment(): Promise<Part[]> {
    const cwd = this.config.getWorkingDir();
    const today = new Date().toLocaleDateString(undefined, {
      weekday: 'long',
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });
    const platform = process.platform;
    const folderStructure = await getFolderStructure(cwd, {
      fileService: this.config.getFileService(),
    });
    const context = `
  这是 Gemini CLI。我们正在为聊天设置上下文。
  今天的日期是 ${today}。
  我的操作系统是：${platform}
  我当前的工作目录是：${cwd}
  ${folderStructure}
          `.trim();

    const initialParts: Part[] = [{ text: context }];
    const toolRegistry = await this.config.getToolRegistry();

    // 如果设置了 fullContext 标志，则添加完整的文件上下文
    if (this.config.getFullContext()) {
      try {
        const readManyFilesTool = toolRegistry.getTool(
          'read_many_files',
        ) as ReadManyFilesTool;
        if (readManyFilesTool) {
          // 读取目标目录中的所有文件
          const result = await readManyFilesTool.execute(
            {
              paths: ['**/*'], // 递归读取所有文件
              useDefaultExcludes: true, // 使用默认排除项
            },
            AbortSignal.timeout(30000),
          );
          if (result.llmContent) {
            initialParts.push({
              text: `\n--- 完整文件上下文 ---\n${result.llmContent}`,
            });
          } else {
            console.warn(
              '请求了完整上下文，但 read_many_files 没有返回任何内容。',
            );
          }
        } else {
          console.warn(
            '请求了完整上下文，但未找到 read_many_files 工具。',
          );
        }
      } catch (error) {
        // 这里不使用 reportError，因为这是启动/配置阶段的错误，而不是聊天/生成阶段的错误。
        console.error('读取完整文件上下文时出错:', error);
        initialParts.push({
          text: '\n--- 读取完整文件上下文时出错 ---',
        });
      }
    }

    return initialParts;
  }

  /**
   * 启动一个新的聊天会话。
   * @param extraHistory - 可选的额外历史记录，会附加在初始环境上下文之后。
   * @returns 一个新的 `GeminiChat` 实例。
   */
  private async startChat(extraHistory?: Content[]): Promise<GeminiChat> {
    const envParts = await this.getEnvironment();
    const toolRegistry = await this.config.getToolRegistry();
    const toolDeclarations = toolRegistry.getFunctionDeclarations();
    const tools: Tool[] = [{ functionDeclarations: toolDeclarations }];
    // 初始历史记录包含环境上下文，以及一个模型的确认响应
    const initialHistory: Content[] = [
      {
        role: 'user',
        parts: envParts,
      },
      {
        role: 'model',
        parts: [{ text: '好的，感谢提供上下文！' }],
      },
      ...(extraHistory ?? []),
    ];
    try {
      const userMemory = this.config.getUserMemory();
      // 获取核心系统提示
      const systemInstruction = getCoreSystemPrompt(userMemory);
      // 如果模型支持，则启用"思考"功能
      const generateContentConfigWithThinking = isThinkingSupported(this.model)
        ? {
            ...this.generateContentConfig,
            thinkingConfig: {
              includeThoughts: true,
            },
          }
        : this.generateContentConfig;
      // 创建新的 GeminiChat 实例
      return new GeminiChat(
        this.config,
        this.getContentGenerator(),
        {
          systemInstruction,
          ...generateContentConfigWithThinking,
          tools,
        },
        history,
      );
    } catch (error) {
      await reportError(
        error,
        '初始化 Gemini 聊天会话时出错。',
        history,
        'startChat',
      );
      throw new Error(`初始化聊天失败：${getErrorMessage(error)}`);
    }
  }

  /**
   * 发送流式消息。这是与模型进行交互的主要入口点。
   * 它管理着多回合对话的自动进行。
   * @param request - 要发送给模型的请求内容。
   * @param signal - 用于中止操作的 AbortSignal。
   * @param turns - 剩余的回合数，用于防止无限循环。
   * @yields {ServerGeminiStreamEvent} - 交互过程中的各种事件。
   * @returns {Promise<Turn>} - 解析为本次交互的最终 Turn 对象。
   */
  async *sendMessageStream(
    request: PartListUnion,
    signal: AbortSignal,
    turns: number = this.MAX_TURNS,
  ): AsyncGenerator<ServerGeminiStreamEvent, Turn> {
    if (!turns) {
      // 防止无限递归
      return new Turn(this.getChat());
    }

    // 尝试压缩聊天历史
    const compressed = await this.tryCompressChat();
    if (compressed) {
      yield { type: GeminiEventType.ChatCompressed, value: compressed };
    }
    // 为本次交互创建一个新的 Turn
    const turn = new Turn(this.getChat());
    // 运行 Turn 并将事件流向上层传递
    const resultStream = turn.run(request, signal);
    for await (const event of resultStream) {
      yield event;
    }
    // 如果没有待处理的工具调用，并且操作未被取消，则检查模型是否想继续发言
    if (!turn.pendingToolCalls.length && signal && !signal.aborted) {
      const nextSpeakerCheck = await checkNextSpeaker(
        this.getChat(),
        this,
        signal,
      );
      // 如果模型希望继续，则自动发起下一轮对话
      if (nextSpeakerCheck?.next_speaker === 'model') {
        const nextRequest = [{ text: '请继续。' }];
        // 这个递归调用的事件将被直接 yield 出去，
        // 但最终返回的 turn 对象将是顶层的那个。
        yield* this.sendMessageStream(nextRequest, signal, turns - 1);
      }
    }
    return turn;
  }

  /**
   * 请求模型根据提供的 schema 生成一个 JSON 对象。
   * @param contents - 发送给模型的内容。
   * @param schema - 期望的 JSON 对象的 schema。
   * @param abortSignal - 用于中止操作的 AbortSignal。
   * @param model - 使用的模型，默认为 Flash 模型。
   * @param config - 额外的生成配置。
   * @returns 一个解析为 JSON 对象的 Promise。
   */
  async generateJson(
    contents: Content[],
    schema: SchemaUnion,
    abortSignal: AbortSignal,
    model: string = DEFAULT_GEMINI_FLASH_MODEL,
    config: GenerateContentConfig = {},
  ): Promise<Record<string, unknown>> {
    try {
      const userMemory = this.config.getUserMemory();
      const systemInstruction = getCoreSystemPrompt(userMemory);
      const requestConfig = {
        abortSignal,
        ...this.generateContentConfig,
        ...config,
      };

      const apiCall = () =>
        this.getContentGenerator().generateContent({
          model,
          config: {
            ...requestConfig,
            systemInstruction,
            responseSchema: schema,
            responseMimeType: 'application/json',
          },
          contents,
        });

      const result = await retryWithBackoff(apiCall, {
        onPersistent429: async (authType?: string) =>
          await this.handleFlashFallback(authType),
        authType: this.config.getContentGeneratorConfig()?.authType,
      });

      const text = getResponseText(result);
      if (!text) {
        const error = new Error(
          'API 在 generateJson 中返回了空响应。',
        );
        await reportError(
          error,
          'generateJson 中的错误：API 返回了空响应。',
          contents,
          'generateJson-empty-response',
        );
        throw error;
      }
      try {
        return JSON.parse(text);
      } catch (parseError) {
        await reportError(
          parseError,
          '从 generateJson 解析 JSON 响应失败。',
          {
            responseTextFailedToParse: text,
            originalRequestContents: contents,
          },
          'generateJson-parse',
        );
        throw new Error(
          `解析 API 响应为 JSON 失败：${getErrorMessage(parseError)}`,
        );
      }
    } catch (error) {
      if (abortSignal.aborted) {
        throw error;
      }

      // 避免重复报告上面已处理的空响应情况
      if (
        error instanceof Error &&
        error.message === 'API 在 generateJson 中返回了空响应。'
      ) {
        throw error;
      }

      await reportError(
        error,
        '通过 API 生成 JSON 内容时出错。',
        contents,
        'generateJson-api',
      );
      throw new Error(
        `生成 JSON 内容失败：${getErrorMessage(error)}`,
      );
    }
  }

  /**
   * 一个通用的、非聊天模式的内容生成方法。
   * @param contents - 发送给模型的内容。
   * @param generationConfig - 本次调用的生成配置。
   * @param abortSignal - 用于中止操作的 AbortSignal。
   * @returns 模型的响应。
   */
  async generateContent(
    contents: Content[],
    generationConfig: GenerateContentConfig,
    abortSignal: AbortSignal,
  ): Promise<GenerateContentResponse> {
    const modelToUse = this.model;
    const configToUse: GenerateContentConfig = {
      ...this.generateContentConfig,
      ...generationConfig,
    };

    try {
      const userMemory = this.config.getUserMemory();
      const systemInstruction = getCoreSystemPrompt(userMemory);

      const requestConfig = {
        abortSignal,
        ...configToUse,
        systemInstruction,
      };

      const apiCall = () =>
        this.getContentGenerator().generateContent({
          model: modelToUse,
          config: requestConfig,
          contents,
        });

      const result = await retryWithBackoff(apiCall, {
        onPersistent429: async (authType?: string) =>
          await this.handleFlashFallback(authType),
        authType: this.config.getContentGeneratorConfig()?.authType,
      });
      return result;
    } catch (error: unknown) {
      if (abortSignal.aborted) {
        throw error;
      }

      await reportError(
        error,
        `使用模型 ${modelToUse} 通过 API 生成内容时出错。`,
        {
          requestContents: contents,
          requestConfig: configToUse,
        },
        'generateContent-api',
      );
      throw new Error(
        `使用模型 ${modelToUse} 生成内容失败：${getErrorMessage(error)}`,
      );
    }
  }

  /**
   * 为给定的文本数组生成嵌入向量。
   * @param texts - 需要生成嵌入的字符串数组。
   * @returns 一个包含嵌入向量的二维数组。
   */
  async generateEmbedding(texts: string[]): Promise<number[][]> {
    if (!texts || texts.length === 0) {
      return [];
    }
    const embedModelParams: EmbedContentParameters = {
      model: this.embeddingModel,
      contents: texts,
    };

    const embedContentResponse =
      await this.getContentGenerator().embedContent(embedModelParams);
    if (
      !embedContentResponse.embeddings ||
      embedContentResponse.embeddings.length === 0
    ) {
      throw new Error('API 响应中未找到嵌入。');
    }

    if (embedContentResponse.embeddings.length !== texts.length) {
      throw new Error(
        `API 返回的嵌入数量不匹配。预期 ${texts.length}，得到 ${embedContentResponse.embeddings.length}。`,
      );
    }

    return embedContentResponse.embeddings.map((embedding, index) => {
      const values = embedding.values;
      if (!values || values.length === 0) {
        throw new Error(
          `API 为索引 ${index} 的输入文本返回了空的嵌入："${texts[index]}"`,
        );
      }
      return values;
    });
  }

  /**
   * 尝试压缩聊天历史记录。
   * 当历史记录的 token 数量超过模型限制的 95% 时，或者当 `force` 参数为 true 时，
   * 会调用模型来总结当前对话，并用总结替换掉完整的历史记录。
   * @param force - 是否强制执行压缩，忽略 token 数量检查。
   * @returns 如果执行了压缩，则返回包含原始和新 token 数量的对象；否则返回 null。
   */
  async tryCompressChat(
    force: boolean = false,
  ): Promise<ChatCompressionInfo | null> {
    const history = this.getChat().getHistory(true); // 获取筛选过的历史记录

    // 无论是否强制，如果历史记录为空，则不执行任何操作。
    if (history.length === 0) {
      return null;
    }

    let { totalTokens: originalTokenCount } =
      await this.getContentGenerator().countTokens({
        model: this.model,
        contents: curatedHistory,
      });

    // 如果不是强制，则根据上下文大小检查是否应该压缩。
    if (!force) {
      if (originalTokenCount === undefined) {
        // 如果 token 计数未定义，我们无法确定是否需要压缩。
        console.warn(
          `无法确定模型 ${this.model} 的 token 数量。跳过压缩检查。`,
        );
        return null;
      }
      const tokenCount = originalTokenCount; // 现在保证是一个数字

      const limit = tokenLimit(this.model);
      if (!limit) {
        // 如果模型没有定义限制，我们无法压缩。
        console.warn(
          `模型 ${this.model} 没有定义 token 限制。跳过压缩检查。`,
        );
        return null;
      }

      if (tokenCount < 0.95 * limit) {
        return null;
      }
    }

    const summarizationRequestMessage = {
      text: '请总结我们到目前为止的对话。总结应简明扼要但全面地概述所有讨论过的关键主题、问题、答案和重要细节。此总结将取代当前的聊天历史以节省 token，因此它必须捕捉到所有必要的要素，以便我们能像没有信息丢失一样有效地理解上下文并继续对话。',
    };
    const response = await this.getChat().sendMessage({
      message: summarizationRequestMessage,
    });
    this.chat = await this.startChat([
      {
        role: 'user',
        parts: [{ text: summary }],
      },
      {
        role: 'model',
        parts: [{ text: 'Got it. Thanks for the additional context!' }],
      },
    ]);

    const { totalTokens: newTokenCount } =
      await this.getContentGenerator().countTokens({
        model: this.model,
        contents: this.getChat().getHistory(),
      });
    if (newTokenCount === undefined) {
      console.warn('Could not determine compressed history token count.');
      return null;
    }

    return {
      originalTokenCount,
      newTokenCount,
    };
  }

  /**
   * 当 OAuth 用户持续遇到 429 错误时，处理回退到 Flash 模型的逻辑。
   * 如果配置中提供了回退处理器，则使用它；否则返回 null。
   * @param authType - 认证类型。
   * @returns 如果回退成功，则返回新的模型名称；否则返回 null。
   */
  private async handleFlashFallback(authType?: string): Promise<string | null> {
    // 仅为 OAuth 用户处理回退逻辑
    if (authType !== AuthType.LOGIN_WITH_GOOGLE_PERSONAL) {
      return null;
    }

    const currentModel = this.model;
    const fallbackModel = DEFAULT_GEMINI_FLASH_MODEL;

    // 如果已在使用 Flash 模型，则不回退
    if (currentModel === fallbackModel) {
      return null;
    }

    // 检查配置中是否有回退处理器（由 CLI 包设置）
    const fallbackHandler = this.config.flashFallbackHandler;
    if (typeof fallbackHandler === 'function') {
      try {
        const accepted = await fallbackHandler(currentModel, fallbackModel);
        if (accepted) {
          this.config.setModel(fallbackModel);
          this.model = fallbackModel;
          return fallbackModel;
        }
      } catch (error) {
        console.warn('Flash 回退处理器失败:', error);
      }
    }

    return null;
  }
}
