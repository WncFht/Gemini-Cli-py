"""
This file is refactored from packages/core_ts/src/tools/read-file.ts.
"""

import mimetypes
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gemini_cli_core.core.config import Config
from gemini_cli_core.tools.base.tool_base import BaseTool, ToolResult
from gemini_cli_core.utils.paths import (
    is_within_root,
    make_relative,
    shorten_path,
)


class ReadFileToolParams(BaseModel):
    absolute_path: str = Field(
        ...,
        description="The absolute path to the file to read.",
        pattern="^/",
    )
    offset: int | None = Field(
        None,
        description="Optional: For text files, the 0-based line number to start reading from.",
    )
    limit: int | None = Field(
        None,
        description="Optional: For text files, maximum number of lines to read.",
    )


def _process_text_content(
    content: str, offset: int | None, limit: int | None
) -> tuple[str, str]:
    """Processes text content, applying offset and limit."""
    lines = content.splitlines()
    total_lines = len(lines)

    if offset is not None and limit is not None:
        start = offset
        end = offset + limit
        content_slice = "\n".join(lines[start:end])
        display = f"Read lines {start + 1}-{min(end, total_lines)} of {total_lines} from"
        return content_slice, display

    # Simple heuristic to truncate very large files for the LLM
    if total_lines > 2000:
        content = "\n".join(lines[:2000]) + "\n... (file truncated)"

    display = f"Read {total_lines} lines from"
    return content, display


def _process_binary_content(file_path: Path) -> tuple[dict, str]:
    """Processes binary content (images, etc.) into a data URI."""
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    with file_path.open("rb") as f:
        import base64

        encoded_content = base64.b64encode(f.read()).decode("utf-8")

    llm_content = {
        "inlineData": {"mimeType": mime_type, "data": encoded_content}
    }
    display = f"Read binary content ({mime_type}) from"
    return llm_content, display


class ReadFileTool(BaseTool[ReadFileToolParams, ToolResult]):
    """A tool for reading files from the filesystem."""

    NAME = "read_file"

    def __init__(self, config: Config):
        super().__init__(
            name=self.NAME,
            display_name="ReadFile",
            description="Reads and returns the content of a specified file. Handles both text and binary files.",
            parameter_schema=ReadFileToolParams.model_json_schema(),
        )
        self.config = config
        self.root_directory = Path(config.get_target_dir()).resolve()

    def validate_tool_params(self, params: ReadFileToolParams) -> str | None:
        p = Path(params.absolute_path)
        if not p.is_absolute():
            return f"File path must be absolute: {params.absolute_path}"
        if not is_within_root(p, self.root_directory):
            return f"File path must be within the root directory ({self.root_directory}): {params.absolute_path}"
        if params.offset is not None and params.offset < 0:
            return "Offset must be a non-negative number"
        if params.limit is not None and params.limit <= 0:
            return "Limit must be a positive number"

        file_discovery = self.config.get_file_service()
        relative_path = make_relative(p, self.root_directory)
        if file_discovery.should_gemini_ignore_file(str(relative_path)):
            return f"File path '{shorten_path(relative_path)}' is ignored by .geminiignore."

        return None

    def get_description(self, params: ReadFileToolParams) -> str:
        relative_path = make_relative(
            Path(params.absolute_path), self.root_directory
        )
        return shorten_path(relative_path)

    async def execute(
        self, params: ReadFileToolParams, signal: Any | None = None
    ) -> ToolResult:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return ToolResult(
                llm_content=f"Error: Invalid parameters. Reason: {validation_error}",
                return_display=f"Error: {validation_error}",
            )

        file_path = Path(params.absolute_path)
        try:
            if not file_path.exists():
                return ToolResult(
                    llm_content="Error: File not found.",
                    return_display="Error: File not found.",
                )
            if file_path.is_dir():
                return ToolResult(
                    llm_content="Error: Path is a directory.",
                    return_display="Error: Path is a directory.",
                )

            llm_content: Any
            display_message: str
            try:
                # Try reading as text first
                with file_path.open("r", encoding="utf-8") as f:
                    content = f.read()
                llm_content, display_message = _process_text_content(
                    content, params.offset, params.limit
                )
            except UnicodeDecodeError:
                # Fallback to binary reading
                llm_content, display_message = _process_binary_content(
                    file_path
                )

            short_path = shorten_path(
                make_relative(file_path, self.root_directory)
            )
            return ToolResult(
                llm_content=llm_content,
                return_display=f"{display_message} '{short_path}'",
            )

        except Exception as e:
            return ToolResult(
                llm_content=f"Error reading file: {e}",
                return_display=f"Error: {e}",
            )
