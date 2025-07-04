import difflib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gemini_cli_core.core.config import Config
from gemini_cli_core.core.types import ApprovalMode
from gemini_cli_core.tools import BaseTool, ToolResult
from gemini_cli_core.tools.common import ToolEditConfirmationDetails
from gemini_cli_core.tools.file.diff_options import DEFAULT_DIFF_CONTEXT_LINES
from gemini_cli_core.utils.edit_corrector import ensure_correct_file_content
from gemini_cli_core.utils.paths import (
    is_within_root,
    make_relative,
    shorten_path,
)

from ..base.modifiable_tool import (
    ModifiableTool,
    ModifyContext,
)


class WriteFileToolParams(BaseModel):
    file_path: str = Field(
        ..., description="The absolute path to the file to write."
    )
    content: str = Field(..., description="The content to write to the file.")
    modified_by_user: bool = Field(False, description="Internal flag.")


class WriteFileTool(
    BaseTool[WriteFileToolParams, ToolResult],
    ModifiableTool[WriteFileToolParams],
):
    """A tool for writing content to files."""

    NAME = "write_file"

    def __init__(self, config: Config):
        super().__init__(
            name=self.NAME,
            display_name="WriteFile",
            description="Writes content to a specified file in the local filesystem.",
            parameter_schema=WriteFileToolParams.model_json_schema(),
        )
        self.config = config
        self.client = config.get_gemini_client()
        self.root_directory = Path(config.get_target_dir()).resolve()

    def _is_within_root(self, p: Path) -> bool:
        return is_within_root(p, self.root_directory)

    def validate_tool_params(self, params: WriteFileToolParams) -> str | None:
        p = Path(params.file_path)
        if not p.is_absolute():
            return f"File path must be absolute: {params.file_path}"
        if not self._is_within_root(p):
            return f"Path must be within the root directory ({self.root_directory}): {params.file_path}"
        if p.exists() and p.is_dir():
            return f"Path is a directory, not a file: {params.file_path}"
        return None

    def get_description(self, params: WriteFileToolParams) -> str:
        relative_path = make_relative(
            Path(params.file_path), self.root_directory
        )
        return f"Writing to {shorten_path(relative_path)}"

    async def _get_corrected_content(
        self, file_path: Path, proposed_content: str
    ) -> tuple[str, str, bool]:
        original_content = ""
        file_exists = False
        if file_path.exists() and file_path.is_file():
            original_content = file_path.read_text(encoding="utf-8")
            file_exists = True

        # TODO: Implement ensureCorrectEdit logic for existing files if needed
        corrected_content = await ensure_correct_file_content(
            proposed_content, self.client, None
        )
        return original_content, corrected_content, file_exists

    async def should_confirm_execute(
        self, params: WriteFileToolParams, abort_signal: Any | None = None
    ) -> ToolEditConfirmationDetails | bool:
        if self.config.get_approval_mode() == ApprovalMode.AUTO_EDIT:
            return False

        validation_error = self.validate_tool_params(params)
        if validation_error:
            return False

        (
            original_content,
            corrected_content,
            _,
        ) = await self._get_corrected_content(
            Path(params.file_path), params.content
        )

        diff = "".join(
            difflib.unified_diff(
                original_content.splitlines(keepends=True),
                corrected_content.splitlines(keepends=True),
                fromfile=f"Original: {params.file_path}",
                tofile=f"Proposed: {params.file_path}",
                n=DEFAULT_DIFF_CONTEXT_LINES,
            )
        )

        return ToolEditConfirmationDetails(
            title=f"Confirm write to: {shorten_path(make_relative(Path(params.file_path), self.root_directory))}",
            file_name=Path(params.file_path).name,
            file_diff=diff,
        )

    async def execute(
        self, params: WriteFileToolParams, signal: Any | None = None
    ) -> ToolResult:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return ToolResult(
                llm_content=f"Error: {validation_error}",
                return_display=f"Error: {validation_error}",
            )

        file_path = Path(params.file_path)
        try:
            (
                original_content,
                corrected_content,
                is_new_file,
            ) = await self._get_corrected_content(file_path, params.content)

            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(corrected_content, encoding="utf-8")

            diff = "".join(
                difflib.unified_diff(
                    original_content.splitlines(keepends=True),
                    corrected_content.splitlines(keepends=True),
                    fromfile=f"Original: {file_path.name}",
                    tofile=f"Written: {file_path.name}",
                    n=DEFAULT_DIFF_CONTEXT_LINES,
                )
            )

            return ToolResult(
                llm_content=f"Successfully wrote to {params.file_path}",
                return_display={"file_diff": diff, "file_name": file_path.name},
            )
        except Exception as e:
            return ToolResult(
                llm_content=f"Error writing file: {e}",
                return_display=f"Error: {e}",
            )

    def get_modify_context(
        self, abort_signal: Any | None
    ) -> ModifyContext[WriteFileToolParams]:
        async def get_current(params: WriteFileToolParams) -> str:
            content, _, _ = await self._get_corrected_content(
                Path(params.file_path), params.content
            )
            return content

        async def get_proposed(params: WriteFileToolParams) -> str:
            _, content, _ = await self._get_corrected_content(
                Path(params.file_path), params.content
            )
            return content

        return ModifyContext(
            get_file_path=lambda params: params.file_path,
            get_current_content=get_current,
            get_proposed_content=get_proposed,
            create_updated_params=lambda _,
            modified,
            original: WriteFileToolParams(
                **original.model_dump(exclude={"content"}),
                content=modified,
                modified_by_user=True,
            ),
        )
