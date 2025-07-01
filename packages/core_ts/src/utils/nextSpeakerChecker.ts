/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import { Content, SchemaUnion, Type } from '@google/genai';
import { GeminiClient } from '../core/client.js';
import { GeminiChat } from '../core/geminiChat.js';
import { isFunctionResponse } from './messageInspectors.js';

// 定义一个提示，用于让模型分析对话历史并决定下一个发言者。
const CHECK_PROMPT = `Analyze *only* the content and structure of your immediately preceding response (your last turn in the conversation history). Based *strictly* on that response, determine who should logically speak next: the 'user' or the 'model' (you).
**Decision Rules (apply in order):**
1.  **Model Continues:** If your last response explicitly states an immediate next action *you* intend to take (e.g., "Next, I will...", "Now I'll process...", "Moving on to analyze...", indicates an intended tool call that didn't execute), OR if the response seems clearly incomplete (cut off mid-thought without a natural conclusion), then the **'model'** should speak next.
2.  **Question to User:** If your last response ends with a direct question specifically addressed *to the user*, then the **'user'** should speak next.
3.  **Waiting for User:** If your last response completed a thought, statement, or task *and* does not meet the criteria for Rule 1 (Model Continues) or Rule 2 (Question to User), it implies a pause expecting user input or reaction. In this case, the **'user'** should speak next.
**Output Format:**
Respond *only* in JSON format according to the following schema. Do not include any text outside the JSON structure.
\`\`\`json
{
  "type": "object",
  "properties": {
    "reasoning": {
        "type": "string",
        "description": "Brief explanation justifying the 'next_speaker' choice based *strictly* on the applicable rule and the content/structure of the preceding turn."
    },
    "next_speaker": {
      "type": "string",
      "enum": ["user", "model"],
      "description": "Who should speak next based *only* on the preceding turn and the decision rules."
    }
  },
  "required": ["next_speaker", "reasoning"]
}
\`\`\`
`;

// 定义模型响应的 JSON 结构，用于规范模型输出。
const RESPONSE_SCHEMA: SchemaUnion = {
  type: Type.OBJECT,
  properties: {
    reasoning: {
      type: Type.STRING,
      description:
        "Brief explanation justifying the 'next_speaker' choice based *strictly* on the applicable rule and the content/structure of the preceding turn.",
    },
    next_speaker: {
      type: Type.STRING,
      enum: ['user', 'model'],
      description:
        'Who should speak next based *only* on the preceding turn and the decision rules',
    },
  },
  required: ['reasoning', 'next_speaker'],
};

/**
 * 定义 `checkNextSpeaker` 函数返回的对象结构。
 */
export interface NextSpeakerResponse {
  reasoning: string;
  next_speaker: 'user' | 'model';
}

/**
 * 检查并确定对话中的下一个发言者是用户还是模型。
 *
 * @param chat 当前的 GeminiChat 实例。
 * @param geminiClient 用于与 Gemini API 通信的客户端。
 * @param abortSignal 用于中止异步操作的信号。
 * @returns 一个包含下一个发言者和理由的对象，如果无法确定则返回 null。
 */
export async function checkNextSpeaker(
  chat: GeminiChat,
  geminiClient: GeminiClient,
  abortSignal: AbortSignal,
): Promise<NextSpeakerResponse | null> {
  // 我们需要捕获经过整理的历史记录，因为在很多情况下，模型会返回无效的轮次，
  // 当这些无效轮次被传回端点时，会破坏后续的调用。一个例子是，当模型决定响应一个空的 part 集合时，
  // 如果你将该消息发回服务器，它将返回一个 400 错误，表示模型 part 集合必须有内容。
  const curatedHistory = chat.getHistory(/* curated */ true);

  // 确保有模型响应可供分析
  if (curatedHistory.length === 0) {
    // 如果历史记录为空，则无法确定下一个发言者。
    return null;
  }

  const comprehensiveHistory = chat.getHistory();
  // 如果 `comprehensiveHistory` 为空，则没有最后一条消息可供检查。
  // 这种情况理想情况下应该由前面的 `curatedHistory.length` 检查捕获，
  // 但作为安全措施：
  if (comprehensiveHistory.length === 0) {
    return null;
  }
  const lastComprehensiveMessage =
    comprehensiveHistory[comprehensiveHistory.length - 1];

  // 如果最后一条消息是用户的消息，并且只包含 function_responses，
  // 那么模型应该接下来发言。
  if (
    lastComprehensiveMessage &&
    isFunctionResponse(lastComprehensiveMessage)
  ) {
    return {
      reasoning:
        '最后一条消息是函数响应，所以模型应该接下来发言。',
      next_speaker: 'model',
    };
  }

  // 如果最后一条消息是模型的，并且其 `parts` 为空，
  // 这意味着模型可能仍在思考，应该继续发言。
  if (
    lastComprehensiveMessage &&
    lastComprehensiveMessage.role === 'model' &&
    lastComprehensiveMessage.parts &&
    lastComprehensiveMessage.parts.length === 0
  ) {
    lastComprehensiveMessage.parts.push({ text: '' });
    return {
      reasoning:
        '最后一条消息是一个没有内容的填充模型消息（用户无需操作），模型应该接下来发言。',
      next_speaker: 'model',
    };
  }

  // 检查通过。让我们继续，可能会发出一个 LLM 请求。

  const lastMessage = curatedHistory[curatedHistory.length - 1];
  if (!lastMessage || lastMessage.role !== 'model') {
    // 如果上一轮不是来自模型，或者历史记录为空，则无法确定下一个发言者。
    return null;
  }

  // 构造发送给模型的内容，包含历史记录和检查提示
  const contents: Content[] = [
    ...curatedHistory,
    { role: 'user', parts: [{ text: CHECK_PROMPT }] },
  ];

  try {
    const parsedResponse = (await geminiClient.generateJson(
      contents,
      RESPONSE_SCHEMA,
      abortSignal,
    )) as unknown as NextSpeakerResponse;

    // 验证响应是否符合预期格式
    if (
      parsedResponse &&
      parsedResponse.next_speaker &&
      ['user', 'model'].includes(parsedResponse.next_speaker)
    ) {
      return parsedResponse;
    }
    return null;
  } catch (error) {
    // 捕获并记录与 Gemini 端点通信时发生的错误
    console.warn(
      '在判断对话是否应继续时与 Gemini 端点通信失败。',
      error,
    );
    return null;
  }
}
