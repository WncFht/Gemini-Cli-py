from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gemini_cli_core.core.config import Config
from gemini_cli_core.tools import BaseTool, ToolResult
from gemini_cli_core.utils.paths import make_relative, shorten_path


class LSToolParams(BaseModel):
    path: str = Field(
        ..., description="The absolute path to the directory to list."
    )
    respect_git_ignore: bool = Field(
        True,
        description="Optional: Whether to respect .gitignore patterns. Defaults to true.",
    )


class FileEntry(BaseModel):
    name: str
    path: str
    is_directory: bool
    size: int
    modified_time: float


class LSTool(BaseTool[LSToolParams, ToolResult]):
    """A tool for listing files in a directory."""

    NAME = "list_directory"

    def __init__(self, config: Config):
        super().__init__(
            name=self.NAME,
            display_name="ReadFolder",
            description="Lists the names of files and subdirectories directly within a specified directory path.",
            parameter_schema=LSToolParams.model_json_schema(),
        )
        self.config = config
        self.root_directory = Path(config.get_target_dir()).resolve()

    def _is_within_root(self, dirpath: Path) -> bool:
        return (
            self.root_directory in dirpath.parents
            or self.root_directory == dirpath
        )

    def validate_tool_params(self, params: LSToolParams) -> str | None:
        p = Path(params.path)
        if not p.is_absolute():
            return f"Path must be absolute: {params.path}"
        if not self._is_within_root(p):
            return f"Path must be within the root directory ({self.root_directory}): {params.path}"
        return None

    def get_description(self, params: LSToolParams) -> str:
        relative_path = make_relative(Path(params.path), self.root_directory)
        return shorten_path(relative_path)

    async def execute(
        self, params: LSToolParams, signal: Any | None = None
    ) -> ToolResult:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return ToolResult(
                llm_content=f"Error: Invalid parameters. Reason: {validation_error}",
                return_display=f"Error: {validation_error}",
            )

        target_path = Path(params.path)
        if not target_path.exists() or not target_path.is_dir():
            return ToolResult(
                llm_content=f"Error: Directory not found: {params.path}",
                return_display="Error: Directory not found.",
            )

        all_files = list(target_path.iterdir())
        file_discovery = self.config.get_file_service()

        entries: list[FileEntry] = []
        git_ignored_count = 0

        paths_to_filter = [
            str(f.relative_to(self.root_directory)) for f in all_files
        ]

        if params.respect_git_ignore:
            filtered_paths = set(
                file_discovery.filter_files(
                    paths_to_filter, respect_gemini_ignore=False
                )
            )
            git_ignored_count = len(paths_to_filter) - len(filtered_paths)
            files_to_process = [
                self.root_directory.joinpath(p) for p in filtered_paths
            ]
        else:
            files_to_process = all_files

        for p in files_to_process:
            try:
                stat = p.stat()
                entries.append(
                    FileEntry(
                        name=p.name,
                        path=str(p),
                        is_directory=p.is_dir(),
                        size=stat.st_size,
                        modified_time=stat.st_mtime,
                    )
                )
            except OSError:
                continue

        entries.sort(key=lambda e: (not e.is_directory, e.name))

        dir_content = "\n".join(
            [f"{'[DIR] ' if e.is_directory else ''}{e.name}" for e in entries]
        )
        llm_content = f"Directory listing for {params.path}:\n{dir_content}"
        display_message = f"Listed {len(entries)} item(s)."

        if git_ignored_count > 0:
            llm_content += f"\n\n({git_ignored_count} items were git-ignored)"
            display_message += f" ({git_ignored_count} git-ignored)"

        return ToolResult(
            llm_content=llm_content, return_display=display_message
        )
