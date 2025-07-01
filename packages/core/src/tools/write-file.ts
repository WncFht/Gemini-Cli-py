/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

import * as Diff from 'diff';
import fs from 'fs';
import path from 'path';
import { ApprovalMode, Config } from '../config/config.js';
import { GeminiClient } from '../core/client.js';
import {
  FileOperation,
  recordFileOperationMetric,
} from '../telemetry/metrics.js';
import {
  ensureCorrectEdit,
  ensureCorrectFileContent,
} from '../utils/editCorrector.js';
import { getErrorMessage, isNodeError } from '../utils/errors.js';
import { getSpecificMimeType } from '../utils/fileUtils.js';
import { makeRelative, shortenPath } from '../utils/paths.js';
import { SchemaValidator } from '../utils/schemaValidator.js';
import { DEFAULT_DIFF_OPTIONS } from './diffOptions.js';
import { ModifiableTool, ModifyContext } from './modifiable-tool.js';
import {
  BaseTool,
  FileDiff,
  ToolCallConfirmationDetails,
  ToolConfirmationOutcome,
  ToolEditConfirmationDetails,
  ToolResult,
} from './tools.js';

/**
 * WriteFile 工具的参数接口。
 */
export interface WriteFileToolParams {
  /**
   * 要写入的文件的绝对路径。
   */
  file_path: string;

  /**
   * 要写入文件的内容。
   */
  content: string;
}

/**
 * 内部接口，用于存储获取修正后文件内容的结果。
 */
interface GetCorrectedFileContentResult {
  originalContent: string; // 文件的原始内容
  correctedContent: string; // 经过修正后的新内容
  fileExists: boolean; // 文件是否存在
  error?: { message: string; code?: string }; // 如果读取文件时出错，存储错误信息
}

/**
 * WriteFileTool 类实现了将内容写入文件的工具逻辑。
 * 它可以创建新文件或覆盖现有文件，并集成了智能内容修正和用户确认功能。
 */
export class WriteFileTool
  extends BaseTool<WriteFileToolParams, ToolResult>
  implements ModifiableTool<WriteFileToolParams>
{
  static readonly Name: string = 'write_file';
  private readonly client: GeminiClient;

  constructor(private readonly config: Config) {
    super(
      WriteFileTool.Name,
      'WriteFile',
      '将内容写入本地文件系统中的指定文件。',
      {
        properties: {
          file_path: {
            description:
              "要写入的文件的绝对路径 (例如, '/home/user/project/file.txt')。不支持相对路径。",
            type: 'string',
          },
          content: {
            description: '要写入文件的内容。',
            type: 'string',
          },
        },
        required: ['file_path', 'content'],
        type: 'object',
      },
    );

    this.client = this.config.getGeminiClient();
  }

  /**
   * 检查路径是否在根目录内。
   */
  private isWithinRoot(pathToCheck: string): boolean {
    const normalizedPath = path.normalize(pathToCheck);
    const normalizedRoot = path.normalize(this.config.getTargetDir());
    const rootWithSep = normalizedRoot.endsWith(path.sep)
      ? normalizedRoot
      : normalizedRoot + path.sep;
    return (
      normalizedPath === normalizedRoot ||
      normalizedPath.startsWith(rootWithSep)
    );
  }

  /**
   * 验证 WriteFile 工具的参数。
   */
  validateToolParams(params: WriteFileToolParams): string | null {
    if (
      this.schema.parameters &&
      !SchemaValidator.validate(
        this.schema.parameters as Record<string, unknown>,
        params,
      )
    ) {
      return '参数未通过 schema 验证。';
    }
    const filePath = params.file_path;
    if (!path.isAbsolute(filePath)) {
      return `文件路径必须是绝对路径：${filePath}`;
    }
    if (!this.isWithinRoot(filePath)) {
      return `文件路径必须在根目录 (${this.config.getTargetDir()}) 内：${filePath}`;
    }

    try {
      // 仅当路径存在时才应执行此检查。
      // 如果它不存在，则它是一个新文件，这对于写入是有效的。
      if (fs.existsSync(filePath)) {
        const stats = fs.lstatSync(filePath);
        if (stats.isDirectory()) {
          return `路径是一个目录，而不是文件：${filePath}`;
        }
      }
    } catch (statError: unknown) {
      // 如果 fs.existsSync 为 true 但 lstatSync 失败（例如，权限问题，或文件被删除的竞争条件）
      // 这表示访问路径时出现问题，应予以报告。
      return `验证时访问路径属性出错：${filePath}。原因：${statError instanceof Error ? statError.message : String(statError)}`;
    }

    return null;
  }

  /**
   * 获取用于在确认时显示的简短描述。
   */
  getDescription(params: WriteFileToolParams): string {
    if (!params.file_path || !params.content) {
      return `模型未为 write file 工具提供有效参数`;
    }
    const relativePath = makeRelative(
      params.file_path,
      this.config.getTargetDir(),
    );
    return `正在写入 ${shortenPath(relativePath)}`;
  }

  /**
   * 处理 WriteFile 工具的确认提示。
   */
  async shouldConfirmExecute(
    params: WriteFileToolParams,
    abortSignal: AbortSignal,
  ): Promise<ToolCallConfirmationDetails | false> {
    if (this.config.getApprovalMode() === ApprovalMode.AUTO_EDIT) {
      return false;
    }

    const validationError = this.validateToolParams(params);
    if (validationError) {
      return false;
    }

    const correctedContentResult = await this._getCorrectedFileContent(
      params.file_path,
      params.content,
      abortSignal,
    );

    if (correctedContentResult.error) {
      // 如果文件存在但无法读取，我们无法显示差异以供确认。
      return false;
    }

    const { originalContent, correctedContent } = correctedContentResult;
    const relativePath = makeRelative(
      params.file_path,
      this.config.getTargetDir(),
    );
    const fileName = path.basename(params.file_path);

    const fileDiff = Diff.createPatch(
      fileName,
      originalContent, // 原始内容（如果文件是新的或不可读，则为空）
      correctedContent, // 经过潜在修正后的内容
      'Current',
      'Proposed',
      DEFAULT_DIFF_OPTIONS,
    );

    const confirmationDetails: ToolEditConfirmationDetails = {
      type: 'edit',
      title: `确认写入：${shortenPath(relativePath)}`,
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
   * 执行文件写入操作。
   */
  async execute(
    params: WriteFileToolParams,
    abortSignal: AbortSignal,
  ): Promise<ToolResult> {
    const validationError = this.validateToolParams(params);
    if (validationError) {
      return {
        llmContent: `错误：提供的参数无效。原因：${validationError}`,
        returnDisplay: `错误：${validationError}`,
      };
    }

    const correctedContentResult = await this._getCorrectedFileContent(
      params.file_path,
      params.content,
      abortSignal,
    );

    if (correctedContentResult.error) {
      const errDetails = correctedContentResult.error;
      const errorMsg = `检查现有文件时出错：${errDetails.message}`;
      return {
        llmContent: `检查现有文件 ${params.file_path} 时出错：${errDetails.message}`,
        returnDisplay: errorMsg,
      };
    }

    const {
      originalContent,
      correctedContent: fileContent,
      fileExists,
    } = correctedContentResult;
    // fileExists 为 true 表示文件已存在（可读或不可读但在 readError 中被捕获）。
    // fileExists 为 false 表示文件不存在 (ENOENT)。
    const isNewFile =
      !fileExists ||
      (correctedContentResult.error !== undefined &&
        !correctedContentResult.fileExists);

    try {
      const dirName = path.dirname(params.file_path);
      if (!fs.existsSync(dirName)) {
        fs.mkdirSync(dirName, { recursive: true });
      }

      fs.writeFileSync(params.file_path, fileContent, 'utf8');

      // 生成差异以供显示结果
      const fileName = path.basename(params.file_path);
      // 如果存在 readError，correctedContentResult 中的 originalContent 为 ''，
      // 但对于差异，我们希望尽可能显示写入前的原始内容。
      // 然而，如果文件不可读，currentContentForDiff 将为空。
      const currentContentForDiff = correctedContentResult.error
        ? '' // 或其他表示内容不可读的指示符
        : originalContent;

      const fileDiff = Diff.createPatch(
        fileName,
        currentContentForDiff,
        fileContent,
        'Original',
        'Written',
        DEFAULT_DIFF_OPTIONS,
      );

      const llmSuccessMessage = isNewFile
        ? `已成功创建并写入新文件：${params.file_path}`
        : `已成功覆盖文件：${params.file_path}`;

      const displayResult: FileDiff = { fileDiff, fileName };

      const lines = fileContent.split('\n').length;
      const mimetype = getSpecificMimeType(params.file_path);
      const extension = path.extname(params.file_path); // 获取扩展名
      if (isNewFile) {
        recordFileOperationMetric(
          this.config,
          FileOperation.CREATE,
          lines,
          mimetype,
          extension,
        );
      } else {
        recordFileOperationMetric(
          this.config,
          FileOperation.UPDATE,
          lines,
          mimetype,
          extension,
        );
      }

      return {
        llmContent: llmSuccessMessage,
        returnDisplay: displayResult,
      };
    } catch (error) {
      const errorMsg = `写入文件时出错：${error instanceof Error ? error.message : String(error)}`;
      return {
        llmContent: `写入文件 ${params.file_path} 时出错：${errorMsg}`,
        returnDisplay: `错误：${errorMsg}`,
      };
    }
  }

  /**
   * 内部方法，用于获取经过修正的文件内容。
   * 它会读取现有文件（如果存在），然后调用修正逻辑来处理模型提供的新内容。
   * @param filePath - 文件路径。
   * @param proposedContent - 模型建议写入的内容。
   * @param abortSignal - AbortSignal。
   * @returns 一个包含原始内容、修正后内容和文件状态的结果对象。
   */
  private async _getCorrectedFileContent(
    filePath: string,
    proposedContent: string,
    abortSignal: AbortSignal,
  ): Promise<GetCorrectedFileContentResult> {
    let originalContent = '';
    let fileExists = false;
    let correctedContent = proposedContent;

    try {
      originalContent = fs.readFileSync(filePath, 'utf8');
      fileExists = true; // 文件存在且已读取
    } catch (err) {
      if (isNodeError(err) && err.code === 'ENOENT') {
        fileExists = false;
        originalContent = '';
      } else {
        // 文件存在但无法读取（权限等问题）
        fileExists = true; // 标记为存在但有问题
        originalContent = ''; // 无法使用其内容
        const error = {
          message: getErrorMessage(err),
          code: isNodeError(err) ? err.code : undefined,
        };
        // 提前返回，因为无法有意义地进行内容修正
        return { originalContent, correctedContent, fileExists, error };
      }
    }

    // 如果 readError 已设置，我们已经返回了。
    // 所以，文件要么被成功读取（fileExists=true, originalContent 已设置），
    // 要么是 ENOENT（fileExists=false, originalContent=''）。

    if (fileExists) {
      // 这意味着 originalContent 可用。
      // 将整个当前内容视为 old_string，调用修正逻辑。
      const { params: correctedParams } = await ensureCorrectEdit(
        originalContent,
        {
          old_string: originalContent, // 将整个当前内容视为 old_string
          new_string: proposedContent,
          file_path: filePath,
        },
        this.client,
        abortSignal,
      );
      correctedContent = correctedParams.new_string;
    } else {
      // 这意味着是新文件 (ENOENT)。
      // 对建议写入的内容进行转义修正。
      correctedContent = await ensureCorrectFileContent(
        proposedContent,
        this.client,
        abortSignal,
      );
    }
    return { originalContent, correctedContent, fileExists };
  }

  /**
   * 为"通过编辑器修改"功能提供上下文。
   */
  getModifyContext(
    abortSignal: AbortSignal,
  ): ModifyContext<WriteFileToolParams> {
    return {
      getFilePath: (params: WriteFileToolParams) => params.file_path,
      getCurrentContent: async (params: WriteFileToolParams) => {
        const correctedContentResult = await this._getCorrectedFileContent(
          params.file_path,
          params.content,
          abortSignal,
        );
        return correctedContentResult.originalContent;
      },
      getProposedContent: async (params: WriteFileToolParams) => {
        const correctedContentResult = await this._getCorrectedFileContent(
          params.file_path,
          params.content,
          abortSignal,
        );
        return correctedContentResult.correctedContent;
      },
      createUpdatedParams: (
        _oldContent: string,
        modifiedProposedContent: string,
        originalParams: WriteFileToolParams,
      ) => ({
        ...originalParams,
        content: modifiedProposedContent,
      }),
    };
  }
}
