/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import {
  Content,
  GenerateContentConfig,
  SchemaUnion,
  Type,
} from '@google/genai';
import { DEFAULT_GEMINI_FLASH_MODEL } from '../config/models.js';
import { GeminiClient } from '../core/client.js';
import { EditToolParams } from '../tools/edit.js';
import { LruCache } from './LruCache.js';

// 定义用于修正操作的 LLM 模型
const EditModel = DEFAULT_GEMINI_FLASH_MODEL;
// 定义用于修正操作的 LLM 生成配置
const EditConfig: GenerateContentConfig = {
  thinkingConfig: {
    thinkingBudget: 0, // 不需要在修正时进行"思考"
  },
};

// 定义 LRU 缓存的最大尺寸
const MAX_CACHE_SIZE = 50;

// 用于缓存 ensureCorrectEdit 结果的 LRU 缓存
const editCorrectionCache = new LruCache<string, CorrectedEditResult>(
  MAX_CACHE_SIZE,
);

// 用于缓存 ensureCorrectFileContent 结果的 LRU 缓存
const fileContentCorrectionCache = new LruCache<string, string>(MAX_CACHE_SIZE);

/**
 * 定义了 CorrectedEditResult 中参数的结构。
 */
interface CorrectedEditParams {
  file_path: string;
  old_string: string;
  new_string: string;
}

/**
 * 定义了 ensureCorrectEdit 函数的返回结果结构。
 */
export interface CorrectedEditResult {
  params: CorrectedEditParams;
  occurrences: number;
}

/**
 * 确保编辑参数的正确性，并在必要时进行修正。
 *
 * 这是一个核心的修正函数。当原始的 `old_string` 在文件中找不到时，它会尝试一系列策略来修正它：
 * 1.  **反转义**：首先尝试对 `old_string` 和 `new_string` 进行反转义，以处理 LLM 可能添加的多余的转义字符。
 * 2.  **LLM 修正**：如果反转义后仍然找不到匹配，它会调用 LLM（Gemini）来"猜测" `old_string`
 *     在文件中的正确形式。
 * 3.  **对齐 `new_string`**：如果 `old_string` 被修正了，它还会调用 LLM 来相应地调整 `new_string`，
 *     以保持编辑的意图一致。
 * 4.  **智能裁剪**：尝试裁剪掉 `old_string` 和 `new_string` 两端相同的空白字符，以提高匹配成功率。
 * 5.  **缓存**：所有修正结果都会被缓存，以避免对相同的输入进行重复的、昂贵的 LLM 调用。
 *
 * @param currentContent - 文件的当前内容。
 * @param originalParams - 来自 `edit` 工具的原始参数。
 * @param client - 用于调用 LLM 的 `GeminiClient` 实例。
 * @param abortSignal - 用于中止操作的 AbortSignal。
 * @returns 一个 Promise，解析为一个包含（可能被修正的）编辑参数和最终匹配次数的对象。
 */
export async function ensureCorrectEdit(
  currentContent: string,
  originalParams: EditToolParams, // 这是来自 edit.ts 的 EditToolParams，没有 'corrected' 字段
  client: GeminiClient,
  abortSignal: AbortSignal,
): Promise<CorrectedEditResult> {
  const cacheKey = `${currentContent}---${originalParams.old_string}---${originalParams.new_string}`;
  const cachedResult = editCorrectionCache.get(cacheKey);
  if (cachedResult) {
    return cachedResult;
  }

  let finalNewString = originalParams.new_string;
  const newStringPotentiallyEscaped =
    unescapeStringForGeminiBug(originalParams.new_string) !==
    originalParams.new_string;

  const expectedReplacements = originalParams.expected_replacements ?? 1;

  let finalOldString = originalParams.old_string;
  let occurrences = countOccurrences(currentContent, finalOldString);

  // --- 修正逻辑开始 ---

  // 场景 1: 完美匹配
  if (occurrences === expectedReplacements) {
    // 即使 old_string 匹配了，new_string 可能仍然有转义问题，需要修正。
    if (newStringPotentiallyEscaped) {
      finalNewString = await correctNewStringEscaping(
        client,
        finalOldString,
        originalParams.new_string,
        abortSignal,
      );
    }
  } else if (occurrences > expectedReplacements) {
    // 场景 2: 匹配次数多于预期
    // TODO(b/433126048): 此处的逻辑可以进一步优化，例如尝试寻找更精确的匹配。
    // 目前，如果用户期望替换多个，我们直接返回。
    if (occurrences === expectedReplacements) {
      const result: CorrectedEditResult = {
        params: { ...originalParams },
        occurrences,
      };
      editCorrectionCache.set(cacheKey, result);
      return result;
    }

    // 如果用户期望1个但找到多个，也尝试修正（现有行为）。
    if (expectedReplacements === 1) {
      const result: CorrectedEditResult = {
        params: { ...originalParams },
        occurrences,
      };
      editCorrectionCache.set(cacheKey, result);
      return result;
    }

    // 如果匹配次数与预期不符，直接返回，后续验证会失败。
    const result: CorrectedEditResult = {
      params: { ...originalParams },
      occurrences,
    };
    editCorrectionCache.set(cacheKey, result);
    return result;
  } else {
    // 场景 3: 零匹配或意外状态，这是最需要修正的地方。
    // 步骤 3.1: 尝试对 old_string 进行反转义
    const unescapedOldStringAttempt = unescapeStringForGeminiBug(
      originalParams.old_string,
    );
    occurrences = countOccurrences(currentContent, unescapedOldStringAttempt);

    if (occurrences === expectedReplacements) {
      // 成功！反转义后的 old_string 匹配了。
      finalOldString = unescapedOldStringAttempt;
      // 现在需要确保 new_string 也被正确地修正，以匹配新的 old_string。
      if (newStringPotentiallyEscaped) {
        finalNewString = await correctNewString(
          client,
          originalParams.old_string, // 原始的 old
          unescapedOldStringAttempt, // 修正后的 old
          originalParams.new_string, // 原始的 new (可能被转义)
          abortSignal,
        );
      }
    } else if (occurrences === 0) {
      // 步骤 3.2: 反转义失败，求助于 LLM 来修正 old_string
      const llmCorrectedOldString = await correctOldStringMismatch(
        client,
        currentContent,
        unescapedOldStringAttempt,
        abortSignal,
      );
      const llmOldOccurrences = countOccurrences(
        currentContent,
        llmCorrectedOldString,
      );

      if (llmOldOccurrences === expectedReplacements) {
        // 成功！LLM 找到了正确的 old_string。
        finalOldString = llmCorrectedOldString;
        occurrences = llmOldOccurrences;

        // 同样，需要用 LLM 来修正 new_string 以保持同步。
        if (newStringPotentiallyEscaped) {
          const baseNewStringForLLMCorrection = unescapeStringForGeminiBug(
            originalParams.new_string,
          );
          finalNewString = await correctNewString(
            client,
            originalParams.old_string, // 原始的 old
            llmCorrectedOldString, // 修正后的 old
            baseNewStringForLLMCorrection, // 用于修正的 new 的基础版本
            abortSignal,
          );
        }
      } else {
        // LLM 也失败了，放弃修正。
        const result: CorrectedEditResult = {
          params: { ...originalParams },
          occurrences: 0, // 明确为 0，因为 LLM 失败了
        };
        editCorrectionCache.set(cacheKey, result);
        return result;
      }
    } else {
      // 反转义 old_string 导致匹配次数 > 1
      const result: CorrectedEditResult = {
        params: { ...originalParams },
        occurrences, // 这将 > 1
      };
      editCorrectionCache.set(cacheKey, result);
      return result;
    }
  }

  // 步骤 4: 尝试智能裁剪两端的空白
  const { targetString, pair } = trimPairIfPossible(
    finalOldString,
    finalNewString,
    currentContent,
    expectedReplacements,
  );
  finalOldString = targetString;
  finalNewString = pair;

  // 最终结果构造
  const result: CorrectedEditResult = {
    params: {
      file_path: originalParams.file_path,
      old_string: finalOldString,
      new_string: finalNewString,
    },
    // 用最终的 old_string 重新计算匹配次数
    occurrences: countOccurrences(currentContent, finalOldString),
  };
  editCorrectionCache.set(cacheKey, result);
  return result;
}

/**
 * 确保文件内容没有不当的转义。
 * 如果内容可能被转义，则调用 LLM 进行修正。
 * @param content - 文件内容字符串。
 * @param client - GeminiClient 实例。
 * @param abortSignal - AbortSignal。
 * @returns 一个解析为（可能被修正的）内容字符串的 Promise。
 */
export async function ensureCorrectFileContent(
  content: string,
  client: GeminiClient,
  abortSignal: AbortSignal,
): Promise<string> {
  const cachedResult = fileContentCorrectionCache.get(content);
  if (cachedResult) {
    return cachedResult;
  }

  const contentPotentiallyEscaped =
    unescapeStringForGeminiBug(content) !== content;
  if (!contentPotentiallyEscaped) {
    fileContentCorrectionCache.set(content, content);
    return content;
  }

  const correctedContent = await correctStringEscaping(
    content,
    client,
    abortSignal,
  );
  fileContentCorrectionCache.set(content, correctedContent);
  return correctedContent;
}

// 定义用于 old_string 修正的 LLM 响应的预期 JSON schema
const OLD_STRING_CORRECTION_SCHEMA: SchemaUnion = {
  type: Type.OBJECT,
  properties: {
    corrected_target_snippet: {
      type: Type.STRING,
      description:
        '在提供的文件内容中，与目标片段完全且唯一匹配的修正版本。',
    },
  },
  required: ['corrected_target_snippet'],
};

/**
 * 当 `old_string` 在文件中找不到时，调用 LLM 来尝试修正它。
 * @param geminiClient - GeminiClient 实例。
 * @param fileContent - 文件的完整内容。
 * @param problematicSnippet - 有问题的、无法匹配的 `old_string`。
 * @param abortSignal - AbortSignal。
 * @returns 一个解析为修正后的字符串的 Promise。
 */
export async function correctOldStringMismatch(
  geminiClient: GeminiClient,
  fileContent: string,
  problematicSnippet: string,
  abortSignal: AbortSignal,
): Promise<string> {
  const prompt = `
背景：一个进程需要在文件内容中为一个特定的文本片段找到精确的、字面的、唯一的匹配。提供的片段未能完全匹配。这很可能是因为它被过度转义了。

任务：分析提供的文件内容和有问题的目标片段。在文件内容中识别出该片段*最有可能*意图匹配的部分。输出文件内容中该部分*确切的、字面的*文本。*只*专注于移除多余的转义字符、修正格式、空格或微小差异，以实现完美的字面匹配。输出必须是文件中出现的确切字面文本。

有问题的目标片段:
\`\`\`
${problematicSnippet}
\`\`\`

文件内容:
\`\`\`
${fileContent}
\`\`\`

例如，如果有问题的目标片段是 "\\\\\\nconst greeting = \`Hello \\\\\`\${name}\\\\\`\`;"，而文件内容中有像 "\nconst greeting = \`Hello \`\${name}\`\`;" 这样的内容，那么 corrected_target_snippet 应该就是 "\nconst greeting = \`Hello \`\${name}\`\`;" 来修正不正确的转义以匹配原始文件内容。
如果差异仅在于空格或格式，请对 corrected_target_snippet 应用相似的空格/格式更改。

返回一个 JSON，只包含一个键 'corrected_target_snippet'，其值为修正后的目标片段。如果找不到清晰、唯一的匹配，则返回一个空的 'corrected_target_snippet'。
`.trim();

  const contents: Content[] = [{ role: 'user', parts: [{ text: prompt }] }];

  try {
    const result = await geminiClient.generateJson(
      contents,
      OLD_STRING_CORRECTION_SCHEMA,
      abortSignal,
      EditModel,
      EditConfig,
    );

    if (
      result &&
      typeof result.corrected_target_snippet === 'string' &&
      result.corrected_target_snippet.length > 0
    ) {
      return result.corrected_target_snippet;
    } else {
      return problematicSnippet;
    }
  } catch (error) {
    if (abortSignal.aborted) {
      throw error;
    }

    console.error(
      '用于 old string 片段修正的 LLM 调用期间出错：',
      error,
    );

    return problematicSnippet;
  }
}

// 定义用于 new_string 修正的 LLM 响应的预期 JSON schema
const NEW_STRING_CORRECTION_SCHEMA: SchemaUnion = {
  type: Type.OBJECT,
  properties: {
    corrected_new_string: {
      type: Type.STRING,
      description:
        '将 original_new_string 调整为 corrected_old_string 的合适替代品，同时保持原始更改的意图。',
    },
  },
  required: ['corrected_new_string'],
};

/**
 * 调整 `new_string` 以使其与修正后的 `old_string` 对齐，同时保持原始的修改意图。
 */
export async function correctNewString(
  geminiClient: GeminiClient,
  originalOldString: string,
  correctedOldString: string,
  originalNewString: string,
  abortSignal: AbortSignal,
): Promise<string> {
  if (originalOldString === correctedOldString) {
    return originalNewString;
  }

  const prompt = `
背景：计划进行一次文本替换操作。要被替换的原始文本（original_old_string）与文件中的实际文本（corrected_old_string）略有不同。现在，original_old_string 已被修正以匹配文件内容。
我们现在需要调整替换文本（original_new_string），使其作为 corrected_old_string 的替换文本是合理的，同时保留原始更改的意图。

original_old_string (最初打算查找的内容):
\`\`\`
${originalOldString}
\`\`\`

corrected_old_string (在文件中实际找到并将被替换的内容):
\`\`\`
${correctedOldString}
\`\`\`

original_new_string (打算用来替换 original_old_string 的内容):
\`\`\`
${originalNewString}
\`\`\`

任务：根据 original_old_string 和 corrected_old_string 之间的差异，以及 original_new_string 的内容，生成一个 corrected_new_string。这个 corrected_new_string 应该是 original_new_string 在设计为直接替换 corrected_old_string 时应有的样子，同时保持原始转换的精神。

例如，如果 original_old_string 是 "\\\\\\nconst greeting = \`Hello \\\\\`\${name}\\\\\`\`;" 而 corrected_old_string 是 "\nconst greeting = \`Hello \`\${name}\`\`;"，并且 original_new_string 是 "\\\\\\nconst greeting = \`Hello \\\\\`\${name} \${lastName}\\\\\`\`;"，那么 corrected_new_string 很可能应该是 "\nconst greeting = \`Hello \`\${name} \${lastName}\`\`;" 来修正不正确的转义。
如果差异仅在于空格或格式，请对 corrected_new_string 应用相似的空格/格式更改。

返回一个 JSON，只包含一个键 'corrected_new_string'，其值为修正后的字符串。如果认为不需要或不可能进行调整，则返回原始的 original_new_string。
  `.trim();

  const contents: Content[] = [{ role: 'user', parts: [{ text: prompt }] }];

  try {
    const result = await geminiClient.generateJson(
      contents,
      NEW_STRING_CORRECTION_SCHEMA,
      abortSignal,
      EditModel,
      EditConfig,
    );

    if (
      result &&
      typeof result.corrected_new_string === 'string' &&
      result.corrected_new_string.length > 0
    ) {
      return result.corrected_new_string;
    } else {
      return originalNewString;
    }
  } catch (error) {
    if (abortSignal.aborted) {
      throw error;
    }

    console.error('用于 new_string 修正的 LLM 调用期间出错：', error);
    return originalNewString;
  }
}

// 定义用于 new_string 转义修正的 schema
const CORRECT_NEW_STRING_ESCAPING_SCHEMA: SchemaUnion = {
  type: Type.OBJECT,
  properties: {
    corrected_new_string_escaping: {
      type: Type.STRING,
      description:
        '对 new_string 进行转义修正，确保它是 old_string 的一个合适的替代品，特别是考虑到先前 LLM 生成内容可能存在的过度转义问题。',
    },
  },
  required: ['corrected_new_string_escaping'],
};

/**
 * 修正 `new_string` 中不正确的转义。
 * @param geminiClient - GeminiClient 实例。
 * @param oldString - 将被替换的、已确认正确的旧字符串。
 * @param potentiallyProblematicNewString - 可能有转义问题的 `new_string`。
 * @param abortSignal - AbortSignal。
 * @returns 一个解析为修正后 `new_string` 的 Promise。
 */
export async function correctNewStringEscaping(
  geminiClient: GeminiClient,
  oldString: string,
  potentiallyProblematicNewString: string,
  abortSignal: AbortSignal,
): Promise<string> {
  const prompt = `
背景：计划进行一次文本替换操作。要被替换的文本（old_string）已在文件中正确识别。然而，替换文本（new_string）可能被前一个 LLM 生成时错误地转义了（例如，对于换行符使用了 \\n 而不是 \n，或者不必要的引号如 \\"Hello\\" 而不是 "Hello"）。

old_string (这是将要被替换的确切文本):
\`\`\`
${oldString}
\`\`\`

potentially_problematic_new_string (这是应该替换 old_string 的文本，但可能存在错误的转义，也可能完全正确):
\`\`\`
${potentiallyProblematicNewString}
\`\`\`

任务：分析 potentially_problematic_new_string。如果它因为不正确的转义（例如，"\\n", "\\t", "\\\\", "\\'", "\\"）而语法无效，请修正无效的语法。目标是确保 new_string 在插入代码后是有效的并能被正确解释。

例如，如果 old_string 是 "foo" 且 potentially_problematic_new_string 是 "bar\\nbaz"，那么 corrected_new_string_escaping 应该是 "bar\nbaz"。
如果 potentially_problematic_new_string 是 console.log(\\"Hello World\\")，它应该是 console.log("Hello World")。

返回一个 JSON，只包含一个键 'corrected_new_string_escaping'，其值为修正后的字符串。如果不需要转义修正，则返回原始的 potentially_problematic_new_string。
  `.trim();

  const contents: Content[] = [{ role: 'user', parts: [{ text: prompt }] }];

  try {
    const result = await geminiClient.generateJson(
      contents,
      CORRECT_NEW_STRING_ESCAPING_SCHEMA,
      abortSignal,
      EditModel,
      EditConfig,
    );

    if (
      result &&
      typeof result.corrected_new_string_escaping === 'string' &&
      result.corrected_new_string_escaping.length > 0
    ) {
      return result.corrected_new_string_escaping;
    } else {
      return potentiallyProblematicNewString;
    }
  } catch (error) {
    if (abortSignal.aborted) {
      throw error;
    }

    console.error(
      '用于 new_string 转义修正的 LLM 调用期间出错：',
      error,
    );
    return potentiallyProblematicNewString;
  }
}

// 定义用于通用字符串转义修正的 schema
const CORRECT_STRING_ESCAPING_SCHEMA: SchemaUnion = {
  type: Type.OBJECT,
  properties: {
    corrected_string_escaping: {
      type: Type.STRING,
      description:
        '对字符串进行转义修正，确保其有效，特别是考虑到先前 LLM 生成内容可能存在的过度转义问题。',
    },
  },
  required: ['corrected_string_escaping'],
};

/**
 * 对一个可能被不当转义的通用字符串进行修正。
 * @param potentiallyProblematicString - 可能有转义问题的字符串。
 * @param client - GeminiClient 实例。
 * @param abortSignal - AbortSignal。
 * @returns 一个解析为修正后字符串的 Promise。
 */
export async function correctStringEscaping(
  potentiallyProblematicString: string,
  client: GeminiClient,
  abortSignal: AbortSignal,
): Promise<string> {
  const prompt = `
背景：一个 LLM 刚刚生成了 potentially_problematic_string，该文本可能被不当地转义了（例如，对于换行符使用了 \\n 而不是 \n，或者不必要的引号如 \\"Hello\\" 而不是 "Hello"）。

potentially_problematic_string (这段文本可能存在错误的转义，也可能完全正确):
\`\`\`
${potentiallyProblematicString}
\`\`\`

任务：分析 potentially_problematic_string。如果它因为不正确的转义（例如，"\\n", "\\t", "\\\\", "\\'", "\\"）而语法无效，请修正无效的语法。目标是确保文本有效并能被正确解释。

例如，如果 potentially_problematic_string 是 "bar\\nbaz"，那么 corrected_string_escaping 应该是 "bar\nbaz"。
如果 potentially_problematic_string 是 console.log(\\"Hello World\\")，它应该是 console.log("Hello World")。

返回一个 JSON，只包含一个键 'corrected_string_escaping'，其值为修正后的字符串。如果不需要转义修正，则返回原始的 potentially_problematic_string。
  `.trim();

  const contents: Content[] = [{ role: 'user', parts: [{ text: prompt }] }];

  try {
    const result = await client.generateJson(
      contents,
      CORRECT_STRING_ESCAPING_SCHEMA,
      abortSignal,
      EditModel,
      EditConfig,
    );

    if (
      result &&
      typeof result.corrected_string_escaping === 'string' &&
      result.corrected_string_escaping.length > 0
    ) {
      return result.corrected_string_escaping;
    } else {
      return potentiallyProblematicString;
    }
  } catch (error) {
    if (abortSignal.aborted) {
      throw error;
    }

    console.error(
      '用于字符串转义修正的 LLM 调用期间出错：',
      error,
    );
    return potentiallyProblematicString;
  }
}

/**
 * 如果可能的话，尝试裁剪掉一对字符串（目标和其替换）两端的空白。
 * 只有当裁剪后的目标字符串在原文中的匹配次数仍然符合预期时，才会进行裁剪。
 * @param target - 目标字符串 (old_string)。
 * @param trimIfTargetTrims - 如果目标被裁剪，这个字符串也会被裁剪 (new_string)。
 * @param currentContent - 文件的完整内容。
 * @param expectedReplacements - 预期的替换次数。
 * @returns 一个包含最终 `targetString` 和 `pair` 的对象。
 */
function trimPairIfPossible(
  target: string,
  trimIfTargetTrims: string,
  currentContent: string,
  expectedReplacements: number,
) {
  const trimmedTargetString = target.trim();
  if (target.length !== trimmedTargetString.length) {
    const trimmedTargetOccurrences = countOccurrences(
      currentContent,
      trimmedTargetString,
    );

    if (trimmedTargetOccurrences === expectedReplacements) {
      const trimmedReactiveString = trimIfTargetTrims.trim();
      return {
        targetString: trimmedTargetString,
        pair: trimmedReactiveString,
      };
    }
  }

  return {
    targetString: target,
    pair: trimIfTargetTrims,
  };
}

/**
 * 对一个可能被 LLM 过度转义的字符串进行反转义。
 * 这是一个基于正则表达式的、修复特定转义错误的实用函数。
 * 它可以处理像 `\\n` -> `\n`, `\\\"` -> `"` 等情况。
 * @param inputString - 输入的、可能被过度转义的字符串。
 * @returns 反转义后的字符串。
 */
export function unescapeStringForGeminiBug(inputString: string): string {
  // 正则表达式解释:
  // \\+ : 匹配一个或多个字面反斜杠字符。
  // (n|t|r|'|"|`|\\|\n) : 这是一个捕获组。它匹配以下之一：
  //   n, t, r, ', ", ` : 匹配字面字符 'n', 't', 'r', 单引号, 双引号, 或反引号。
  //                       处理 "\\n", "\\`" 等情况。
  //   \\ : 匹配一个字面反斜杠。处理 "\\\\" (被转义的反斜杠) 等情况。
  //   \n : 匹配一个实际的换行符。处理输入字符串中可能存在的 "\\\n" (一个字面反斜杠后跟一个换行符) 等情况。
  // g : 全局标志，替换所有出现的地方。

  return inputString.replace(
    /\\+(n|t|r|'|"|`|\\|\n)/g,
    (match, capturedChar) => {
      // 'match' 是整个错误的序列，例如，如果输入（在内存中）是 "\\\\`"，match 就是 "\\\\`"。
      // 'capturedChar' 是决定真实含义的字符，例如 '`'。

      switch (capturedChar) {
        case 'n':
          return '\n'; // 正确转义: \n (换行符)
        case 't':
          return '\t'; // 正确转义: \t (制表符)
        case 'r':
          return '\r'; // 正确转义: \r (回车符)
        case "'":
          return "'"; // 正确转义: ' (撇号)
        case '"':
          return '"'; // 正确转义: " (引号)
        case '`':
          return '`'; // 正确转义: ` (反引号)
        case '\\': // 处理 capturedChar 是一个字面反斜杠的情况
          return '\\'; // 用单个反斜杠替换被转义的反斜杠 (例如, "\\\\")
        case '\n': // 处理 capturedChar 是一个实际换行符的情况
          return '\n'; // 用一个干净的换行符替换整个错误的序列 (例如, 内存中的 "\\\n")
        default:
          // 如果正则表达式正确捕获，理想情况下不应到达此回退。
          // 如果捕获了意外的字符，它将返回原始匹配的序列。
          return match;
      }
    },
  );
}

/**
 * 计算子字符串在字符串中出现的次数。
 * @param str - 主字符串。
 * @param substr - 要计数的子字符串。
 * @returns 出现的次数。
 */
export function countOccurrences(str: string, substr: string): number {
  if (substr === '') {
    return 0;
  }
  let count = 0;
  let pos = str.indexOf(substr);
  while (pos !== -1) {
    count++;
    pos = str.indexOf(substr, pos + substr.length); // 从当前匹配之后开始搜索
  }
  return count;
}

/**
 * (仅供测试使用) 重置本模块中的所有缓存。
 */
export function resetEditCorrectorCaches_TEST_ONLY() {
  editCorrectionCache.clear();
  fileContentCorrectionCache.clear();
}
