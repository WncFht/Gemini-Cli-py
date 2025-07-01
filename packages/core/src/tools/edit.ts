/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import * as Diff from 'diff';
import * as fs from 'fs';
import * as path from 'path';
import { ApprovalMode, Config } from '../config/config.js';
import { GeminiClient } from '../core/client.js';
import { ensureCorrectEdit } from '../utils/editCorrector.js';
import { isNodeError } from '../utils/errors.js';
import { makeRelative, shortenPath } from '../utils/paths.js';
import { SchemaValidator } from '../utils/schemaValidator.js';
import { DEFAULT_DIFF_OPTIONS } from './diffOptions.js';
import { ModifiableTool, ModifyContext } from './modifiable-tool.js';
import { ReadFileTool } from './read-file.js';
import {
  BaseTool,
  ToolCallConfirmationDetails,
  ToolConfirmationOutcome,
  ToolEditConfirmationDetails,
  ToolResult,
  ToolResultDisplay,
} from './tools.js';

/**
 * Edit 工具的参数接口。
 */
export interface EditToolParams {
  /**
   * 要修改的文件的绝对路径。
   */
  file_path: string;

  /**
   * 要被替换的文本。
   */
  old_string: string;

  /**
   * 用来替换的新文本。
   */
  new_string: string;

  /**
   * 预期的替换次数。如果未指定，则默认为 1。
   * 当您想要替换多个出现时使用此参数。
   */
  expected_replacements?: number;
}

/**
 * 内部接口，用于存储计算出的编辑操作的结果。
 */
interface CalculatedEdit {
  currentContent: string | null; // 文件的当前内容
  newContent: string; // 编辑后的新内容
  occurrences: number; // old_string 的实际出现次数
  error?: { display: string; raw: string }; // 如果发生错误，存储错误信息
  isNewFile: boolean; // 是否是创建新文件
}

/**
 * EditTool 类实现了文本替换工具的核心逻辑。
 * 它能够替换文件中的文本，并集成了智能修正、用户确认和交互式修改等高级功能。
 */
export class EditTool
  extends BaseTool<EditToolParams, ToolResult>
  implements ModifiableTool<EditToolParams>
{
  static readonly Name = 'replace'; // 工具的静态名称
  private readonly config: Config;
  private readonly rootDirectory: string;
  private readonly client: GeminiClient;

  /**
   * 创建 EditLogic 的一个新实例。
   * @param config - 应用的配置对象。
   */
  constructor(config: Config) {
    super(
      EditTool.Name,
      'Edit',
      `替换文件中的文本。默认情况下，替换单个出现，但当指定 \`expected_replacements\` 时可以替换多个出现。此工具需要提供围绕更改的大量上下文以确保精确定位。在尝试文本替换之前，请始终使用 ${ReadFileTool.Name} 工具检查文件的当前内容。

对必需参数的期望：
1. \`file_path\` 必须是绝对路径；否则将抛出错误。
2. \`old_string\` 必须是要替换的确切字面文本（包括所有空格、缩进、换行符和周围代码等）。
3. \`new_string\` 必须是用来替换 \`old_string\` 的确切字面文本（也包括所有空格、缩进、换行符和周围代码等）。确保生成的代码是正确且符合习惯的。
4. 永远不要对 \`old_string\` 或 \`new_string\`进行转义，这会破坏确切字面文本的要求。
**重要提示：** 如果以上任何一条不满足，工具将失败。对于 \`old_string\` 尤其关键：必须唯一地标识要更改的单个实例。请在目标文本之前和之后至少包含3行上下文，并精确匹配空格和缩进。如果此字符串匹配多个位置，或不完全匹配，工具将失败。
**多次替换：** 将 \`expected_replacements\` 设置为您要替换的出现次数。工具将替换所有与 \`old_string\` 完全匹配的出现。请确保替换次数符合您的期望。`,
      {
        properties: {
          file_path: {
            description:
              "要修改的文件的绝对路径。必须以 '/' 开头。",
            type: 'string',
          },
          old_string: {
            description:
              '要替换的确切字面文本，最好是未转义的。对于单次替换（默认），请在目标文本之前和之后至少包含3行上下文，并精确匹配空格和缩进。对于多次替换，请指定 expected_replacements 参数。如果此字符串不是确切的字面文本（即您对其进行了转义）或不完全匹配，工具将失败。',
            type: 'string',
          },
          new_string: {
            description:
              '用来替换 `old_string` 的确切字面文本，最好是未转义的。请提供确切的文本。确保生成的代码是正确且符合习惯的。',
            type: 'string',
          },
          expected_replacements: {
            type: 'number',
            description:
              '预期的替换次数。如果未指定，则默认为 1。当您想要替换多个出现时使用此参数。',
            minimum: 1,
          },
        },
        required: ['file_path', 'old_string', 'new_string'],
        type: 'object',
      },
    );
    this.config = config;
    this.rootDirectory = path.resolve(this.config.getTargetDir());
    this.client = config.getGeminiClient();
  }

  /**
   * 检查路径是否在根目录内。
   * @param pathToCheck - 要检查的绝对路径。
   * @returns 如果路径在根目录内则为 true，否则为 false。
   */
  private isWithinRoot(pathToCheck: string): boolean {
    const normalizedPath = path.normalize(pathToCheck);
    const normalizedRoot = this.rootDirectory;
    const rootWithSep = normalizedRoot.endsWith(path.sep)
      ? normalizedRoot
      : normalizedRoot + path.sep;
    return (
      normalizedPath === normalizedRoot ||
      normalizedPath.startsWith(rootWithSep)
    );
  }

  /**
   * 验证 Edit 工具的参数。
   * @param params - 要验证的参数。
   * @returns 如果无效则返回错误消息字符串，否则返回 null。
   */
  validateToolParams(params: EditToolParams): string | null {
    if (
      this.schema.parameters &&
      !SchemaValidator.validate(
        this.schema.parameters as Record<string, unknown>,
        params,
      )
    ) {
      return '参数未通过 schema 验证。';
    }

    if (!path.isAbsolute(params.file_path)) {
      return `文件路径必须是绝对路径：${params.file_path}`;
    }

    if (!this.isWithinRoot(params.file_path)) {
      return `文件路径必须在根目录 (${this.rootDirectory}) 内：${params.file_path}`;
    }

    return null;
  }

  /**
   * 内部方法，用于应用文本替换。
   */
  private _applyReplacement(
    currentContent: string | null,
    oldString: string,
    newString: string,
    isNewFile: boolean,
  ): string {
    if (isNewFile) {
      return newString;
    }
    if (currentContent === null) {
      // 如果不是新文件，不应该发生这种情况，但作为防御性措施，如果 oldString 也为空，则返回 newString 或空字符串
      return oldString === '' ? newString : '';
    }
    // 如果 oldString 为空且不是新文件，则不修改内容。
    if (oldString === '' && !isNewFile) {
      return currentContent;
    }
    return currentContent.replaceAll(oldString, newString);
  }

  /**
   * 计算编辑操作的潜在结果。
   * 这是执行前的"预演"，它会读取文件，调用 `ensureCorrectEdit` 进行智能修正，并确定最终的编辑结果和可能出现的错误。
   * @param params - 编辑操作的参数。
   * @param abortSignal - 用于中止操作的 AbortSignal。
   * @returns 一个描述潜在编辑结果的对象。
   * @throws 如果读取文件时发生意外的文件系统错误（如权限问题），则抛出异常。
   */
  private async calculateEdit(
    params: EditToolParams,
    abortSignal: AbortSignal,
  ): Promise<CalculatedEdit> {
    const expectedReplacements = params.expected_replacements ?? 1;
    let currentContent: string | null = null;
    let fileExists = false;
    let isNewFile = false;
    let finalNewString = params.new_string;
    let finalOldString = params.old_string;
    let occurrences = 0;
    let error: { display: string; raw: string } | undefined = undefined;

    try {
      currentContent = fs.readFileSync(params.file_path, 'utf8');
      // 将行尾标准化为 LF 以进行一致处理。
      currentContent = currentContent.replace(/\r\n/g, '\n');
      fileExists = true;
    } catch (err: unknown) {
      if (!isNodeError(err) || err.code !== 'ENOENT') {
        // 重新抛出意外的文件系统错误（权限等）。
        throw err;
      }
      fileExists = false;
    }

    if (params.old_string === '' && !fileExists) {
      // 创建一个新文件
      isNewFile = true;
    } else if (!fileExists) {
      // 尝试编辑一个不存在的文件（且 old_string 不为空）
      error = {
        display: `找不到文件。无法应用编辑。使用空的 old_string 来创建新文件。`,
        raw: `找不到文件：${params.file_path}`,
      };
    } else if (currentContent !== null) {
      // 编辑一个已存在的文件
      const correctedEdit = await ensureCorrectEdit(
        currentContent,
        params,
        this.client,
        abortSignal,
      );
      finalOldString = correctedEdit.params.old_string;
      finalNewString = correctedEdit.params.new_string;
      occurrences = correctedEdit.occurrences;

      if (params.old_string === '') {
        // 错误：尝试创建一个已存在的文件
        error = {
          display: `编辑失败。试图创建一个已存在的文件。`,
          raw: `文件已存在，无法创建：${params.file_path}`,
        };
      } else if (occurrences === 0) {
        error = {
          display: `编辑失败，找不到要替换的字符串。`,
          raw: `编辑失败，在 ${params.file_path} 中找到 0 个 old_string 的出现。未进行任何编辑。未找到 old_string 中的确切文本。请确保您没有错误地转义内容，并检查空格、缩进和上下文。使用 ${ReadFileTool.Name} 工具进行验证。`,
        };
      } else if (occurrences !== expectedReplacements) {
        error = {
          display: `编辑失败，预期 ${expectedReplacements} 次出现，但找到了 ${occurrences} 次。`,
          raw: `编辑失败，在文件 ${params.file_path} 中，预期 ${expectedReplacements} 次出现，但找到了 ${occurrences} 次 old_string`,
        };
      }
    } else {
      // 如果文件存在且没有抛出异常，则不应发生这种情况，但作为防御性措施：
      error = {
        display: `读取文件内容失败。`,
        raw: `读取已存在文件内容失败：${params.file_path}`,
      };
    }

    const newContent = this._applyReplacement(
      currentContent,
      finalOldString,
      finalNewString,
      isNewFile,
    );

    return {
      currentContent,
      newContent,
      occurrences,
      error,
      isNewFile,
    };
  }

  /**
   * 处理 Edit 工具在 CLI 中的确认提示。
   * 它需要计算差异（diff）以展示给用户。
   */
  async shouldConfirmExecute(
    params: EditToolParams,
    abortSignal: AbortSignal,
  ): Promise<ToolCallConfirmationDetails | false> {
    if (this.config.getApprovalMode() === ApprovalMode.AUTO_EDIT) {
      return false;
    }
    const validationError = this.validateToolParams(params);
    if (validationError) {
      console.error(
        `[EditTool 包装器] 尝试使用无效参数进行确认：${validationError}`,
      );
      return false;
    }

    let editData: CalculatedEdit;
    try {
      editData = await this.calculateEdit(params, abortSignal);
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      console.log(`准备编辑时出错：${errorMsg}`);
      return false;
    }

    if (editData.error) {
      console.log(`错误：${editData.error.display}`);
      return false;
    }

    const fileName = path.basename(params.file_path);
    const fileDiff = Diff.createPatch(
      fileName,
      editData.currentContent ?? '',
      editData.newContent,
      'Current',
      'Proposed',
      DEFAULT_DIFF_OPTIONS,
    );
    const confirmationDetails: ToolEditConfirmationDetails = {
      type: 'edit',
      title: `确认编辑：${shortenPath(makeRelative(params.file_path, this.rootDirectory))}`,
      fileName,
      fileDiff,
      onConfirm: async (outcome: ToolConfirmationOutcome) => {
        if (outcome === ToolConfirmationOutcome.ProceedAlways) {
          this.config.setApprovalMode(ApprovalMode.AUTO_EDIT);
        }
      },
    };
    return confirmationDetails;
  }

  /**
   * 获取用于在确认时显示的简短描述。
   */
  getDescription(params: EditToolParams): string {
    if (!params.file_path || !params.old_string || !params.new_string) {
      return `模型未为 edit 工具提供有效参数`;
    }
    const relativePath = makeRelative(params.file_path, this.rootDirectory);
    if (params.old_string === '') {
      return `创建 ${shortenPath(relativePath)}`;
    }

    const oldStringSnippet =
      params.old_string.split('\n')[0].substring(0, 30) +
      (params.old_string.length > 30 ? '...' : '');
    const newStringSnippet =
      params.new_string.split('\n')[0].substring(0, 30) +
      (params.new_string.length > 30 ? '...' : '');

    if (params.old_string === params.new_string) {
      return `文件 ${shortenPath(relativePath)} 无更改`;
    }
    return `${shortenPath(relativePath)}: ${oldStringSnippet} => ${newStringSnippet}`;
  }

  /**
   * 执行编辑操作。
   * @param params - 编辑操作的参数。
   * @param signal - 用于中止操作的 AbortSignal。
   * @returns 编辑操作的结果。
   */
  async execute(
    params: EditToolParams,
    signal: AbortSignal,
  ): Promise<ToolResult> {
    const validationError = this.validateToolParams(params);
    if (validationError) {
      return {
        llmContent: `错误：提供的参数无效。原因：${validationError}`,
        returnDisplay: `错误：${validationError}`,
      };
    }

    let editData: CalculatedEdit;
    try {
      editData = await this.calculateEdit(params, signal);
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      return {
        llmContent: `准备编辑时出错：${errorMsg}`,
        returnDisplay: `准备编辑时出错：${errorMsg}`,
      };
    }

    if (editData.error) {
      return {
        llmContent: editData.error.raw,
        returnDisplay: `错误：${editData.error.display}`,
      };
    }

    try {
      this.ensureParentDirectoriesExist(params.file_path);
      fs.writeFileSync(params.file_path, editData.newContent, 'utf8');

      let displayResult: ToolResultDisplay;
      if (editData.isNewFile) {
        displayResult = `已创建 ${shortenPath(makeRelative(params.file_path, this.rootDirectory))}`;
      } else {
        // 生成差异以供显示，即使核心逻辑技术上不需要它
        // CLI 包装器将使用 ToolResult 的这一部分
        const fileName = path.basename(params.file_path);
        const fileDiff = Diff.createPatch(
          fileName,
          editData.currentContent ?? '', // 如果不是 isNewFile，则此处不应为 null
          editData.newContent,
          'Current',
          'Proposed',
          DEFAULT_DIFF_OPTIONS,
        );
        displayResult = { fileDiff, fileName };
      }

      const llmSuccessMessage = editData.isNewFile
        ? `已创建新文件：${params.file_path} 并写入提供的内容。`
        : `已成功修改文件：${params.file_path}（${editData.occurrences} 次替换）。`;

      return {
        llmContent: llmSuccessMessage,
        returnDisplay: displayResult,
      };
    } catch (error) {
      const errorMsg = error instanceof Error ? error.message : String(error);
      return {
        llmContent: `执行编辑时出错：${errorMsg}`,
        returnDisplay: `写入文件时出错：${errorMsg}`,
      };
    }
  }

  /**
   * 确保父目录存在，如果不存在则创建。
   */
  private ensureParentDirectoriesExist(filePath: string): void {
    const dirName = path.dirname(filePath);
    if (!fs.existsSync(dirName)) {
      fs.mkdirSync(dirName, { recursive: true });
    }
  }

  /**
   * 为"通过编辑器修改"功能提供上下文。
   * 实现了 `ModifiableTool` 接口。
   */
  getModifyContext(_: AbortSignal): ModifyContext<EditToolParams> {
    return {
      getFilePath: (params: EditToolParams) => params.file_path,
      getCurrentContent: async (params: EditToolParams): Promise<string> => {
        try {
          return fs.readFileSync(params.file_path, 'utf8');
        } catch (err) {
          if (!isNodeError(err) || err.code !== 'ENOENT') throw err;
          return '';
        }
      },
      getProposedContent: async (params: EditToolParams): Promise<string> => {
        try {
          const currentContent = fs.readFileSync(params.file_path, 'utf8');
          return this._applyReplacement(
            currentContent,
            params.old_string,
            params.new_string,
            params.old_string === '' && currentContent === '',
          );
        } catch (err) {
          if (!isNodeError(err) || err.code !== 'ENOENT') throw err;
          return '';
        }
      },
      createUpdatedParams: (
        oldContent: string,
        modifiedProposedContent: string,
        originalParams: EditToolParams,
      ): EditToolParams => ({
        ...originalParams,
        old_string: oldContent,
        new_string: modifiedProposedContent,
      }),
    };
  }
}
