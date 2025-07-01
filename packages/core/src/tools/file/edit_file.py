"""
This file is refactored from packages/core_ts/src/tools/edit.ts.
"""

import difflib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ...config import ApprovalMode, Config
from ...utils.edit_corrector import ensure_correct_edit
from ...utils.paths import is_within_root, make_relative, shorten_path
from ..base.modifiable_tool import ModifiableTool, ModifyContext
from ..base.tool_base import BaseTool, ToolResult
from ..common import ToolCallConfirmationDetails, ToolEditConfirmationDetails
from .diff_options import DEFAULT_DIFF_CONTEXT_LINES


class EditToolParams(BaseModel):
    file_path: str = Field(
        ..., description="The absolute path to the file to modify."
    )
    old_string: str = Field(..., description="The exact text to be replaced.")
    new_string: str = Field(
        ..., description="The exact new text to replace with."
    )
    expected_replacements: int = Field(
        1, description="The expected number of replacements."
    )
    modified_by_user: bool | None = Field(
        False, description="Whether the edit was modified manually by the user."
    )


class CalculatedEdit(BaseModel):
    current_content: str | None
    new_content: str
    occurrences: int
    error: dict[str, str] | None = None
    is_new_file: bool


class EditTool(
    BaseTool[EditToolParams, ToolResult],
    ModifiableTool[EditToolParams],
):
    """A tool for replacing text in files."""

    NAME = "replace"

    def __init__(self, config: Config):
        super().__init__(
            name=self.NAME,
            display_name="Edit",
            description="Replaces text in a file.",
            parameter_schema=EditToolParams.model_json_schema(),
        )
        self.config = config
        self.client = config.get_gemini_client()
        self.root_directory = Path(config.get_target_dir()).resolve()

    def validate_tool_params(self, params: EditToolParams) -> str | None:
        p = Path(params.file_path)
        if not p.is_absolute():
            return f"File path must be absolute: {params.file_path}"
        if not is_within_root(p, self.root_directory):
            return f"Path must be within the root directory ({self.root_directory}): {params.file_path}"
        return None

    def _apply_replacement(
        self,
        current_content: str | None,
        old_string: str,
        new_string: str,
        is_new_file: bool,
    ) -> str:
        if is_new_file:
            return new_string
        if current_content is None:
            return ""
        if old_string == "":
            return current_content
        return current_content.replace(old_string, new_string)

    async def _calculate_edit(self, params: EditToolParams) -> CalculatedEdit:
        p = Path(params.file_path)
        expected_replacements = params.expected_replacements
        current_content: str | None = None
        error: dict[str, str] | None = None
        final_old_string = params.old_string
        final_new_string = params.new_string
        occurrences = 0

        if p.exists():
            current_content = p.read_text("utf-8").replace("\r\n", "\n")

            corrected_edit = await ensure_correct_edit(
                current_content, params, self.client, None
            )
            final_old_string = corrected_edit.params.old_string
            final_new_string = corrected_edit.params.new_string
            occurrences = corrected_edit.occurrences

            if occurrences == 0:
                error = {
                    "display": "Edit failed, string to replace not found.",
                    "raw": "Could not find the exact string to replace in the file.",
                }
            elif occurrences != expected_replacements:
                error = {
                    "display": f"Found {occurrences} occurrences, but expected {expected_replacements}.",
                    "raw": f"Expected {expected_replacements} replacements, but found {occurrences}.",
                }

        else:
            if params.old_string != "":
                error = {"display": "File not found.", "raw": "File not found"}
            # For new files, old_string is empty, new_string is the content
            occurrences = 0

        is_new_file = not p.exists() and params.old_string == ""
        if is_new_file:
            occurrences = 1  # New file creation is one "occurrence"
            error = None  # Clear error for new file case

        new_content = self._apply_replacement(
            current_content, final_old_string, final_new_string, is_new_file
        )

        return CalculatedEdit(
            current_content=current_content,
            new_content=new_content,
            occurrences=occurrences,
            error=error,
            is_new_file=is_new_file,
        )

    async def should_confirm_execute(
        self, params: EditToolParams, abort_signal: Any | None = None
    ) -> ToolCallConfirmationDetails | bool:
        if self.config.get_approval_mode() == ApprovalMode.AUTO_EDIT:
            return False

        edit_data = await self._calculate_edit(params)
        if edit_data.error:
            # Maybe log this error for debugging
            return False

        diff = "".join(
            difflib.unified_diff(
                (edit_data.current_content or "").splitlines(keepends=True),
                edit_data.new_content.splitlines(keepends=True),
                fromfile=f"Original: {params.file_path}",
                tofile=f"Proposed: {params.file_path}",
                n=DEFAULT_DIFF_CONTEXT_LINES,
            )
        )

        return ToolEditConfirmationDetails(
            title=f"Confirm edit to: {shorten_path(make_relative(Path(params.file_path), self.root_directory))}",
            file_name=Path(params.file_path).name,
            file_diff=diff,
        )

    async def execute(
        self, params: EditToolParams, signal: Any | None = None
    ) -> ToolResult:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return ToolResult(
                llm_content=f"Error: {validation_error}",
                return_display=f"Error: {validation_error}",
            )

        edit_data = await self._calculate_edit(params)
        if edit_data.error:
            return ToolResult(
                llm_content=edit_data.error["raw"],
                return_display=f"Error: {edit_data.error['display']}",
            )

        p = Path(params.file_path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(edit_data.new_content, "utf-8")

            return ToolResult(
                llm_content=f"Successfully edited {params.file_path}",
                return_display={
                    "file_diff": "...",
                    "file_name": p.name,
                },  # Placeholder diff
            )
        except Exception as e:
            return ToolResult(
                llm_content=f"Error writing file: {e}",
                return_display=f"Error: {e}",
            )

    def get_modify_context(
        self, abort_signal: Any | None = None
    ) -> ModifyContext[EditToolParams]:
        async def get_current(params: EditToolParams) -> str:
            edit = await self._calculate_edit(params)
            return edit.current_content or ""

        async def get_proposed(params: EditToolParams) -> str:
            edit = await self._calculate_edit(params)
            return edit.new_content

        return ModifyContext(
            get_file_path=lambda params: params.file_path,
            get_current_content=get_current,
            get_proposed_content=get_proposed,
            create_updated_params=lambda old,
            modified,
            original: EditToolParams(
                **original.model_dump(exclude={"old_string", "new_string"}),
                old_string=old,
                new_string=modified,
                modified_by_user=True,
            ),
        )
