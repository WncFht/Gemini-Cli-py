"""
This file is refactored from packages/core_ts/src/tools/read-many-files.ts.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ....config import Config
from ...utils.file_utils import process_single_file_content
from ...utils.paths import make_relative
from ..base.tool_base import BaseTool, ToolResult
from .glob import GlobTool


class ReadManyFilesParams(BaseModel):
    paths: list[str] = Field(
        ...,
        description="An array of glob patterns or paths relative to the tool's target directory.",
    )
    use_default_excludes: bool = Field(True)
    respect_git_ignore: bool = Field(True)


class ReadManyFilesTool(BaseTool[ReadManyFilesParams, ToolResult]):
    """A tool for reading content from multiple files."""

    NAME = "read_many_files"

    def __init__(self, config: Config):
        super().__init__(
            name=self.NAME,
            display_name="ReadManyFiles",
            description="Reads content from multiple files specified by glob patterns.",
            parameter_schema=ReadManyFilesParams.model_json_schema(),
        )
        self.config = config
        self.root_directory = Path(config.get_target_dir()).resolve()
        self.glob_tool = GlobTool(config)

    async def execute(
        self, params: ReadManyFilesParams, signal: Any | None = None
    ) -> ToolResult:
        # Use the GlobTool to find the files
        glob_params = self.glob_tool.params(
            pattern=",".join(params.paths),  # A bit of a hack for the pattern
            respect_git_ignore=params.respect_git_ignore,
        )
        glob_result = await self.glob_tool.execute(glob_params, signal)

        if (
            "Error" in glob_result.return_display
            or "not found" in glob_result.return_display
        ):
            return glob_result

        file_paths_str = glob_result.llm_content.splitlines()
        # The first line is the count message, so skip it
        file_paths = [
            path_str for path_str in file_paths_str[1:] if path_str.strip()
        ]

        if not file_paths:
            return ToolResult(
                llm_content="No files found matching the criteria.",
                return_display="No files found.",
            )

        content_parts = []
        processed_files = []
        skipped_files = []

        for file_path_str in file_paths:
            file_path = Path(file_path_str)
            read_result = await process_single_file_content(
                file_path, self.root_directory
            )

            if read_result.error:
                skipped_files.append(
                    {"path": file_path_str, "reason": read_result.error}
                )
            else:
                separator = f"--- {make_relative(file_path, self.root_directory)} ---\n\n"
                if isinstance(read_result.llm_content, str):
                    content_parts.append(
                        separator + read_result.llm_content + "\n\n"
                    )
                else:  # It's a dict for binary content
                    content_parts.append(separator)
                    content_parts.append(read_result.llm_content)
                processed_files.append(file_path_str)

        if not content_parts:
            return ToolResult(
                llm_content="All found files were skipped due to read errors.",
                return_display="All found files were skipped.",
            )

        return ToolResult(
            llm_content="".join(content_parts),
            return_display=f"Read content from {len(processed_files)} file(s).",
        )
