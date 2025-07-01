"""
This file is refactored from packages/core_ts/src/tools/glob.ts.
"""

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ....config import Config
from ...utils.paths import is_within_root, make_relative, shorten_path
from ..base.tool_base import BaseTool, ToolResult


class GlobToolParams(BaseModel):
    pattern: str = Field(
        ..., description="The glob pattern to match files against."
    )
    path: str = Field(
        ".",
        description="Optional: The directory to search in. Defaults to current directory.",
    )
    case_sensitive: bool = Field(
        False, description="Whether the search should be case-sensitive."
    )
    respect_git_ignore: bool = Field(
        True, description="Whether to respect .gitignore patterns."
    )


class GlobTool(BaseTool[GlobToolParams, ToolResult]):
    """A tool for finding files using glob patterns."""

    NAME = "glob"

    def __init__(self, config: Config):
        super().__init__(
            name=self.NAME,
            display_name="FindFiles",
            description="Efficiently finds files matching specific glob patterns.",
            parameter_schema=GlobToolParams.model_json_schema(),
        )
        self.config = config
        self.root_directory = Path(config.get_target_dir()).resolve()

    def validate_tool_params(self, params: GlobToolParams) -> str | None:
        search_dir = self.root_directory.joinpath(params.path).resolve()
        if not is_within_root(search_dir, self.root_directory):
            return "Search path resolves outside the tool's root directory."
        if not search_dir.exists() or not search_dir.is_dir():
            return "Search path does not exist or is not a directory."
        if not params.pattern:
            return "The 'pattern' parameter cannot be empty."
        return None

    def get_description(self, params: GlobToolParams) -> str:
        search_dir = self.root_directory.joinpath(params.path)
        relative_path = make_relative(search_dir, self.root_directory)
        return f"'{params.pattern}' within {shorten_path(str(relative_path))}"

    async def execute(
        self, params: GlobToolParams, signal: Any | None = None
    ) -> ToolResult:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return ToolResult(
                llm_content=f"Error: Invalid parameters. Reason: {validation_error}",
                return_display=validation_error,
            )

        search_dir = self.root_directory.joinpath(params.path)
        # Python's glob is case-sensitive on Linux/macOS by default, case-insensitive on Windows.
        # The `case_sensitive` parameter from JS is complex to replicate cross-platform.
        # We will use the default behavior of `rglob`.
        all_found = list(search_dir.rglob(params.pattern))

        file_discovery = self.config.get_file_service()

        absolute_paths = [str(p) for p in all_found if p.is_file()]

        filtered_paths = absolute_paths
        git_ignored_count = 0
        if params.respect_git_ignore:
            filtered_paths = file_discovery.filter_files(
                absolute_paths, respect_gemini_ignore=False
            )
            git_ignored_count = len(absolute_paths) - len(filtered_paths)

        if not filtered_paths:
            return ToolResult(
                llm_content="No files found.", return_display="No files found."
            )

        # Sort by modification time
        try:
            sorted_paths = sorted(
                filtered_paths,
                key=lambda p: Path(p).stat().st_mtime,
                reverse=True,
            )
        except FileNotFoundError:
            # A file might be deleted between glob and stat, filter it out.
            existing_paths = [p for p in filtered_paths if Path(p).exists()]
            sorted_paths = sorted(
                existing_paths,
                key=lambda p: Path(p).stat().st_mtime,
                reverse=True,
            )

        file_list_str = "\n".join(sorted_paths)
        result_message = f"Found {len(sorted_paths)} file(s):\n{file_list_str}"
        if git_ignored_count > 0:
            result_message += (
                f"\n({git_ignored_count} additional files were git-ignored)"
            )

        return ToolResult(
            llm_content=result_message,
            return_display=f"Found {len(sorted_paths)} matching file(s).",
        )
