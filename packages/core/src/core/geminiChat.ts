/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

// DISCLAIMER: This is a copied version of https://github.com/googleapis/js-genai/blob/main/src/chats.ts with the intention of working around a key bug
// where function responses are not treated as "valid" responses: https://b.corp.google.com/issues/420354090

import {
  Content,
  createUserContent,
  GenerateContentConfig,
  GenerateContentResponse,
  GenerateContentResponseUsageMetadata,
  Part,
  SendMessageParameters,
} from '@google/genai';
import { Config } from '../config/config.js';
import { DEFAULT_GEMINI_FLASH_MODEL } from '../config/models.js';
import {
  logApiError,
  logApiRequest,
  logApiResponse,
} from '../telemetry/loggers.js';
import {
  ApiErrorEvent,
  ApiRequestEvent,
  ApiResponseEvent,
} from '../telemetry/types.js';
import {
  getStructuredResponse,
  getStructuredResponseFromParts,
} from '../utils/generateContentResponseUtilities.js';
import { isFunctionResponse } from '../utils/messageInspectors.js';
import { retryWithBackoff } from '../utils/retry.js';
import { AuthType, ContentGenerator } from './contentGenerator.js';

/**
 * 检查模型响应是否有效。
 * @param response - 从模型收到的 `GenerateContentResponse`。
 * @returns 如果响应有效则返回 `true`，否则返回 `false`。
 */
function isValidResponse(response: GenerateContentResponse): boolean {
  if (response.candidates === undefined || response.candidates.length === 0) {
    return false;
  }
  const content = response.candidates[0]?.content;
  if (content === undefined) {
    return false;
  }
  return isValidContent(content);
}

/**
 * 检查内容对象是否有效。
 * @param content - `Content` 对象。
 * @returns 如果内容有效则返回 `true`，否则返回 `false`。
 */
function isValidContent(content: Content): boolean {
  if (content.parts === undefined || content.parts.length === 0) {
    return false;
  }
  for (const part of content.parts) {
    // part 不应为空对象
    if (part === undefined || Object.keys(part).length === 0) {
      return false;
    }
    // 如果 part 不是思想（thought）且文本为空字符串，则视为无效
    if (!part.thought && part.text !== undefined && part.text === '') {
      return false;
    }
  }
  return true;
}

/**
 * 验证聊天历史记录中是否包含正确的角色。
 *
 * @throws 如果历史记录不是以用户回合（user turn）开始，则抛出错误。
 * @throws 如果历史记录包含无效的角色，则抛出错误。
 */
function validateHistory(history: Content[]) {
  // 空历史记录是有效的。
  if (history.length === 0) {
    return;
  }
  for (const content of history) {
    if (content.role !== 'user' && content.role !== 'model') {
      throw new Error(`角色必须是 'user' 或 'model'，但得到的是 ${content.role}。`);
    }
  }
}

/**
 * 从完整的历史记录中提取经过筛选的（有效的）历史记录。
 *
 * @remarks
 * 模型有时可能会生成无效或空的内容（例如，由于安全过滤器或背诵限制）。
 * 从历史记录中提取有效的回合可以确保后续请求能被模型接受。
 * 如果模型的响应无效，则其对应的用户输入也会被一并移除。
 * @param comprehensiveHistory - 完整的聊天历史记录。
 * @returns 经过筛选的有效聊天历史记录。
 */
function extractCuratedHistory(comprehensiveHistory: Content[]): Content[] {
  if (comprehensiveHistory === undefined || comprehensiveHistory.length === 0) {
    return [];
  }
  const curatedHistory: Content[] = [];
  const length = comprehensiveHistory.length;
  let i = 0;
  while (i < length) {
    if (comprehensiveHistory[i].role === 'user') {
      curatedHistory.push(comprehensiveHistory[i]);
      i++;
    } else {
      const modelOutput: Content[] = [];
      let isValid = true;
      // 收集所有连续的模型输出
      while (i < length && comprehensiveHistory[i].role === 'model') {
        modelOutput.push(comprehensiveHistory[i]);
        // 检查模型输出是否有效
        if (isValid && !isValidContent(comprehensiveHistory[i])) {
          isValid = false;
        }
        i++;
      }
      if (isValid) {
        curatedHistory.push(...modelOutput);
      } else {
        // 如果模型内容无效，则移除最后一个用户输入。
        curatedHistory.pop();
      }
    }
  }
  return curatedHistory;
}

/**
 * GeminiChat 类封装了一个聊天会话，能够在发送消息时携带先前的对话上下文。
 *
 * @remarks
 * 该会话维护了用户与模型之间的所有对话回合。
 */
export class GeminiChat {
  // 一个 Promise，用于表示当前正在发送给模型的消息的状态，以确保消息按顺序发送。
  private sendPromise: Promise<void> = Promise.resolve();

  constructor(
    private readonly config: Config,
    private readonly contentGenerator: ContentGenerator,
    private readonly generationConfig: GenerateContentConfig = {},
    private history: Content[] = [],
  ) {
    validateHistory(history);
  }

  /**
   * 从内容数组中提取所有文本部分并拼接成一个字符串。
   * @param contents - 内容数组。
   * @returns 拼接后的文本字符串。
   */
  private _getRequestTextFromContents(contents: Content[]): string {
    return contents
      .flatMap((content) => content.parts ?? [])
      .map((part) => part.text)
      .filter(Boolean)
      .join('');
  }

  /**
   * 记录 API 请求的遥测数据。
   * @param contents - 发送给 API 的内容。
   * @param model - 使用的模型名称。
   */
  private async _logApiRequest(
    contents: Content[],
    model: string,
  ): Promise<void> {
    const requestText = this._getRequestTextFromContents(contents);
    logApiRequest(this.config, new ApiRequestEvent(model, requestText));
  }

  /**
   * 记录 API 响应的遥测数据。
   * @param durationMs - API 调用的持续时间（毫秒）。
   * @param usageMetadata - API 使用元数据。
   * @param responseText - 响应的文本内容。
   */
  private async _logApiResponse(
    durationMs: number,
    usageMetadata?: GenerateContentResponseUsageMetadata,
    responseText?: string,
  ): Promise<void> {
    logApiResponse(
      this.config,
      new ApiResponseEvent(
        this.config.getModel(),
        durationMs,
        usageMetadata,
        responseText,
      ),
    );
  }

  /**
   * 记录 API 错误的遥测数据。
   * @param durationMs - API 调用的持续时间（毫秒）。
   * @param error - 发生的错误。
   */
  private _logApiError(durationMs: number, error: unknown): void {
    const errorMessage = error instanceof Error ? error.message : String(error);
    const errorType = error instanceof Error ? error.name : 'unknown';

    logApiError(
      this.config,
      new ApiErrorEvent(
        this.config.getModel(),
        errorMessage,
        durationMs,
        errorType,
      ),
    );
  }

  /**
   * 当 OAuth 用户遇到持续的 429 错误时，处理回退到 Flash 模型的逻辑。
   * 如果配置中提供了回退处理器，则使用它；否则返回 null。
   * @param authType - 认证类型。
   * @returns 如果回退成功，则返回新的模型名称；否则返回 null。
   */
  private async handleFlashFallback(authType?: string): Promise<string | null> {
    // 仅为 OAuth 用户处理回退逻辑
    if (authType !== AuthType.LOGIN_WITH_GOOGLE_PERSONAL) {
      return null;
    }

    const currentModel = this.config.getModel();
    const fallbackModel = DEFAULT_GEMINI_FLASH_MODEL;

    // 如果已在使用 Flash 模型，则不进行回退
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
          return fallbackModel;
        }
      } catch (error) {
        console.warn('Flash 回退处理器失败:', error);
      }
    }

    return null;
  }

  /**
   * 向模型发送消息并返回响应。
   *
   * @remarks
   * 此方法将等待前一条消息处理完毕后再发送下一条消息。
   *
   * @see {@link Chat#sendMessageStream} 流式处理方法。
   * @param params - 在聊天会话中发送消息的参数。
   * @returns 模型的响应。
   *
   * @example
   * ```ts
   * const chat = ai.chats.create({model: 'gemini-2.0-flash'});
   * const response = await chat.sendMessage({
   *   message: 'Why is the sky blue?'
   * });
   * console.log(response.text);
   * ```
   */
  async sendMessage(
    params: SendMessageParameters,
  ): Promise<GenerateContentResponse> {
    await this.sendPromise;
    const userContent = createUserContent(params.message);
    // 将新的用户内容追加到经过筛选的历史记录后面
    const requestContents = this.getHistory(true).concat(userContent);

    this._logApiRequest(requestContents, this.config.getModel());

    const startTime = Date.now();
    let response: GenerateContentResponse;

    try {
      const apiCall = () =>
        this.contentGenerator.generateContent({
          model: this.config.getModel() || DEFAULT_GEMINI_FLASH_MODEL,
          contents: requestContents,
          config: { ...this.generationConfig, ...params.config },
        });

      // 使用退避重试策略调用 API
      response = await retryWithBackoff(apiCall, {
        shouldRetry: (error: Error) => {
          // 对 429 (请求过多) 和 5xx (服务器错误) 进行重试
          if (error && error.message) {
            if (error.message.includes('429')) return true;
            if (error.message.match(/5\d{2}/)) return true;
          }
          return false;
        },
        // 如果持续遇到 429 错误，则触发回退到 Flash 模型
        onPersistent429: async (authType?: string) =>
          await this.handleFlashFallback(authType),
        authType: this.config.getContentGeneratorConfig()?.authType,
      });
      const durationMs = Date.now() - startTime;
      await this._logApiResponse(
        durationMs,
        response.usageMetadata,
        getStructuredResponse(response),
      );

      // 异步更新历史记录，但不阻塞返回响应
      this.sendPromise = (async () => {
        const outputContent = response.candidates?.[0]?.content;
        // AFC（自动函数调用）的输入包含了整个筛选过的聊天历史以及新的用户输入，
        // 因此我们需要截断 AFC 历史记录以去除重复的现有聊天历史。
        const fullAutomaticFunctionCallingHistory =
          response.automaticFunctionCallingHistory;
        const index = this.getHistory(true).length;
        let automaticFunctionCallingHistory: Content[] = [];
        if (fullAutomaticFunctionCallingHistory != null) {
          automaticFunctionCallingHistory =
            fullAutomaticFunctionCallingHistory.slice(index) ?? [];
        }
        const modelOutput = outputContent ? [outputContent] : [];
        this.recordHistory(
          userContent,
          modelOutput,
          automaticFunctionCallingHistory,
        );
      })();
      await this.sendPromise.catch(() => {
        // 如果历史记录更新失败，重置 sendPromise 以免后续调用失败
        this.sendPromise = Promise.resolve();
      });
      return response;
    } catch (error) {
      const durationMs = Date.now() - startTime;
      this._logApiError(durationMs, error);
      this.sendPromise = Promise.resolve();
      throw error;
    }
  }

  /**
   * 向模型发送消息并以数据块（chunks）的形式返回流式响应。
   *
   * @remarks
   * 此方法将等待前一条消息处理完毕后再发送下一条消息。
   *
   * @see {@link Chat#sendMessage} 非流式处理方法。
   * @param params - 发送消息的参数。
   * @return 模型的流式响应。
   *
   * @example
   * ```ts
   * const chat = ai.chats.create({model: 'gemini-2.0-flash'});
   * const response = await chat.sendMessageStream({
   *   message: 'Why is the sky blue?'
   * });
   * for await (const chunk of response) {
   *   console.log(chunk.text);
   * }
   * ```
   */
  async sendMessageStream(
    params: SendMessageParameters,
  ): Promise<AsyncGenerator<GenerateContentResponse>> {
    await this.sendPromise;
    const userContent = createUserContent(params.message);
    const requestContents = this.getHistory(true).concat(userContent);
    this._logApiRequest(requestContents, this.config.getModel());

    const startTime = Date.now();

    try {
      const apiCall = () =>
        this.contentGenerator.generateContentStream({
          model: this.config.getModel(),
          contents: requestContents,
          config: { ...this.generationConfig, ...params.config },
        });

      // 注意: 重试流可能很复杂。如果 generateContentStream 本身在产生异步生成器之前
      // 不处理瞬时问题的重试，此处的重试将重新启动流。对于初次调用时的简单 429/500 错误，
      // 这样做是可行的。如果错误发生在流的中途，此设置将不会恢复流，而是会重启它。
      const streamResponse = await retryWithBackoff(apiCall, {
        shouldRetry: (error: Error) => {
          // 检查错误消息中的状态码，或已知的特定错误名称
          if (error && error.message) {
            if (error.message.includes('429')) return true;
            if (error.message.match(/5\d{2}/)) return true;
          }
          return false; // 默认不重试其他错误
        },
        onPersistent429: async (authType?: string) =>
          await this.handleFlashFallback(authType),
        authType: this.config.getContentGeneratorConfig()?.authType,
      });

      // 无论是成功还是失败，都解析内部用于跟踪发送完成的 Promise - `sendPromise`。
      // 实际的失败仍由 `await streamResponse` 传播。
      this.sendPromise = Promise.resolve(streamResponse)
        .then(() => undefined)
        .catch(() => undefined);

      const result = this.processStreamResponse(
        streamResponse,
        userContent,
        startTime,
      );
      return result;
    } catch (error) {
      const durationMs = Date.now() - startTime;
      this._logApiError(durationMs, error);
      this.sendPromise = Promise.resolve();
      throw error;
    }
  }

  /**
   * 返回聊天历史记录。
   *
   * @remarks
   * 历史记录是一个在用户和模型之间交替的内容列表。
   *
   * 有两种类型的历史记录:
   * - `筛选历史记录` (curated history) 只包含用户和模型之间的有效回合，
   *   这些回合将被包含在后续发送给模型的请求中。
   * - `完整历史记录` (comprehensive history) 包含所有回合，包括无效或
   *   空的模型输出，提供了历史的完整记录。
   *
   * 历史记录在收到模型响应后更新，对于流式响应，这意味着收到响应的最后一个数据块。
   *
   * 默认返回 `完整历史记录`。要获取 `筛选历史记录`，请将 `curated` 参数设置为 `true`。
   *
   * @param curated - 是返回筛选历史记录还是完整历史记录。
   * @return 整个聊天会话中在用户和模型之间交替的历史内容。
   */
  getHistory(curated: boolean = false): Content[] {
    const history = curated
      ? extractCuratedHistory(this.history)
      : this.history;
    // 深拷贝历史记录，以避免在聊天会话外部修改历史。
    return structuredClone(history);
  }

  /**
   * 清除聊天历史记录。
   */
  clearHistory(): void {
    this.history = [];
  }

  /**
   * 向聊天历史记录中添加一个新条目。
   * @param content - 要添加到历史记录中的内容。
   */
  addHistory(content: Content): void {
    this.history.push(content);
  }

  /**
   * 设置聊天历史记录。
   * @param history - 新的聊天历史记录。
   */
  setHistory(history: Content[]): void {
    this.history = history;
  }

  /**
   * 从流式响应的所有数据块中获取最终的用量元数据。
   * @param chunks - 响应数据块数组。
   * @returns 最终的用量元数据，如果不存在则为 undefined。
   */
  getFinalUsageMetadata(
    chunks: GenerateContentResponse[],
  ): GenerateContentResponseUsageMetadata | undefined {
    const lastChunkWithMetadata = chunks
      .slice()
      .reverse()
      .find((chunk) => chunk.usageMetadata);

    return lastChunkWithMetadata?.usageMetadata;
  }

  /**
   * 处理流式响应，收集数据块，并在流结束后更新历史记录和日志。
   * @param streamResponse - 来自模型的异步生成器响应。
   * @param inputContent - 用户的输入内容。
   * @param startTime - 请求开始的时间戳。
   */
  private async *processStreamResponse(
    streamResponse: AsyncGenerator<GenerateContentResponse>,
    inputContent: Content,
    startTime: number,
  ) {
    const outputContent: Content[] = [];
    const chunks: GenerateContentResponse[] = [];
    let errorOccurred = false;

    try {
      for await (const chunk of streamResponse) {
        if (isValidResponse(chunk)) {
          chunks.push(chunk);
          const content = chunk.candidates?.[0]?.content;
          if (content !== undefined) {
            // 如果是思想（thought）内容，直接 yield，但不加入最终的 outputContent
            if (this.isThoughtContent(content)) {
              yield chunk;
              continue;
            }
            outputContent.push(content);
          }
        }
        yield chunk;
      }
    } catch (error) {
      errorOccurred = true;
      const durationMs = Date.now() - startTime;
      this._logApiError(durationMs, error);
      throw error;
    }

    // 如果没有发生错误，记录 API 响应日志
    if (!errorOccurred) {
      const durationMs = Date.now() - startTime;
      const allParts: Part[] = [];
      for (const content of outputContent) {
        if (content.parts) {
          allParts.push(...content.parts);
        }
      }
      const fullText = getStructuredResponseFromParts(allParts);
      await this._logApiResponse(
        durationMs,
        this.getFinalUsageMetadata(chunks),
        fullText,
      );
    }
    // 更新历史记录
    this.recordHistory(inputContent, outputContent);
  }

  /**
   * 将用户输入和模型输出记录到历史记录中。
   * @param userInput - 用户的输入内容。
   * @param modelOutput - 模型的输出内容数组。
   * @param automaticFunctionCallingHistory - 自动函数调用的历史记录。
   */
  private recordHistory(
    userInput: Content,
    modelOutput: Content[],
    automaticFunctionCallingHistory?: Content[],
  ) {
    // 过滤掉仅包含思想（thought）的模型输出
    const nonThoughtModelOutput = modelOutput.filter(
      (content) => !this.isThoughtContent(content),
    );

    let outputContents: Content[] = [];
    if (
      nonThoughtModelOutput.length > 0 &&
      nonThoughtModelOutput.every((content) => content.role !== undefined)
    ) {
      outputContents = nonThoughtModelOutput;
    } else if (nonThoughtModelOutput.length === 0 && modelOutput.length > 0) {
      // 这种情况处理模型只返回一个思想（thought）的场景。
      // 此时我们不应添加一个空的模型响应。
    } else {
      // 当不是函数响应时，如果模型返回空响应，则追加一个空内容，
      // 以便历史记录始终在用户和模型之间交替。
      // 这是针对 https://b.corp.google.com/issues/420354090 的变通方法。
      if (!isFunctionResponse(userInput)) {
        outputContents.push({
          role: 'model',
          parts: [],
        } as Content);
      }
    }

    // 如果存在自动函数调用历史，则将其添加到主历史中
    if (
      automaticFunctionCallingHistory &&
      automaticFunctionCallingHistory.length > 0
    ) {
      this.history.push(
        ...extractCuratedHistory(automaticFunctionCallingHistory),
      );
    } else {
      this.history.push(userInput);
    }

    // 合并 outputContents 中相邻的 model 角色
    const consolidatedOutputContents: Content[] = [];
    for (const content of outputContents) {
      if (this.isThoughtContent(content)) {
        continue;
      }
      const lastContent =
        consolidatedOutputContents[consolidatedOutputContents.length - 1];
      // 如果当前和上一个都是文本内容，则将它们的文本合并到上一个内容的第一个 part 中
      if (this.isTextContent(lastContent) && this.isTextContent(content)) {
        lastContent.parts[0].text += content.parts[0].text || '';
        if (content.parts.length > 1) {
          lastContent.parts.push(...content.parts.slice(1));
        }
      } else {
        consolidatedOutputContents.push(content);
      }
    }

    // 将合并后的内容添加到历史记录中
    if (consolidatedOutputContents.length > 0) {
      const lastHistoryEntry = this.history[this.history.length - 1];
      const canMergeWithLastHistory =
        !automaticFunctionCallingHistory ||
        automaticFunctionCallingHistory.length === 0;

      // 如果可以与历史记录中的最后一个条目合并
      if (
        canMergeWithLastHistory &&
        this.isTextContent(lastHistoryEntry) &&
        this.isTextContent(consolidatedOutputContents[0])
      ) {
        // 合并文本内容
        lastHistoryEntry.parts[0].text +=
          consolidatedOutputContents[0].parts[0].text || '';
        if (consolidatedOutputContents[0].parts.length > 1) {
          lastHistoryEntry.parts.push(
            ...consolidatedOutputContents[0].parts.slice(1),
          );
        }
        consolidatedOutputContents.shift(); // 移除已合并的第一个元素
      }
      this.history.push(...consolidatedOutputContents);
    }
  }

  /**
   * 类型守卫，检查内容是否为纯文本内容。
   */
  private isTextContent(
    content: Content | undefined,
  ): content is Content & { parts: [{ text: string }, ...Part[]] } {
    return !!(
      content &&
      content.role === 'model' &&
      content.parts &&
      content.parts.length > 0 &&
      typeof content.parts[0].text === 'string' &&
      content.parts[0].text !== ''
    );
  }

  /**
   * 类型守卫，检查内容是否为思想（thought）内容。
   */
  private isThoughtContent(
    content: Content | undefined,
  ): content is Content & { parts: [{ thought: boolean }, ...Part[]] } {
    return !!(
      content &&
      content.role === 'model' &&
      content.parts &&
      content.parts.length > 0 &&
      typeof content.parts[0].thought === 'boolean' &&
      content.parts[0].thought === true
    );
  }
}
