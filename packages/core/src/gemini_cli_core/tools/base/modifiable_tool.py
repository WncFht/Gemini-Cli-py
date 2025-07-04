from __future__ import annotations

import difflib
from typing import TYPE_CHECKING, Generic

from pydantic import BaseModel

if TYPE_CHECKING:
    from .tool_base import Tool, TParams, TResult

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, TypeVar

from gemini_cli_core.tools.file.diff_options import DEFAULT_DIFF_CONTEXT_LINES
from gemini_cli_core.utils.editor import EditorType, open_diff

from .tool_base import Tool

TParams = TypeVar("TParams", bound=BaseModel)
TResult = TypeVar("TResult", bound=BaseModel)


class ModifyContext(BaseModel, Generic[TParams]):
    """
    Context required to allow a tool's parameters to be modified in an editor.
    """

    get_file_path: Callable[[TParams], str]
    get_current_content: Callable[[TParams], str]
    get_proposed_content: Callable[[TParams], str]
    create_updated_params: Callable[[str, str, TParams], TParams]

    class Config:
        arbitrary_types_allowed = True


class ModifiableTool(
    Generic[TParams, TResult], Tool[TParams, TResult], Protocol
):
    """
    A tool that supports a user-driven modification operation.
    """

    def get_modify_context(
        self, abort_signal: Any | None
    ) -> ModifyContext[TParams]: ...


class ModifyResult(BaseModel, Generic[TParams]):
    """The result of a modification operation."""

    updated_params: TParams
    updated_diff: str


def is_modifiable_tool(tool: Tool) -> bool:
    """Type guard to check if a tool is modifiable."""
    return hasattr(tool, "get_modify_context") and Callable(
        tool.get_modify_context
    )


def _create_temp_files_for_modify(
    current_content: str, proposed_content: str, file_path: str
) -> tuple[Path, Path]:
    """Creates temporary files for the diff editor."""
    # TODO: Use a more robust temp file creation method
    temp_dir = Path("/tmp/gemini_mods")
    temp_dir.mkdir(exist_ok=True, parents=True)

    p = Path(file_path)
    old_path = temp_dir / f"{p.stem}-old{p.suffix}"
    new_path = temp_dir / f"{p.stem}-new{p.suffix}"

    old_path.write_text(current_content, encoding="utf-8")
    new_path.write_text(proposed_content, encoding="utf-8")

    return old_path, new_path


def _get_updated_params(
    tmp_old_path: Path,
    tmp_new_path: Path,
    original_params: TParams,
    modify_context: ModifyContext[TParams],
) -> ModifyResult[TParams]:
    """Reads the modified files and creates updated parameters and a new diff."""
    old_content = tmp_old_path.read_text(encoding="utf-8")
    new_content = tmp_new_path.read_text(encoding="utf-8")

    updated_params = modify_context.create_updated_params(
        old_content, new_content, original_params
    )

    diff = difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"Current: {Path(modify_context.get_file_path(original_params)).name}",
        tofile=f"Proposed: {Path(modify_context.get_file_path(original_params)).name}",
        n=DEFAULT_DIFF_CONTEXT_LINES,
    )

    return ModifyResult(
        updated_params=updated_params, updated_diff="".join(diff)
    )


def _delete_temp_files(old_path: Path, new_path: Path):
    """Deletes the temporary files."""
    try:
        old_path.unlink()
        new_path.unlink()
    except OSError as e:
        print(f"Error deleting temp diff files: {e}")


async def modify_with_editor(
    original_params: TParams,
    modify_context: ModifyContext[TParams],
    editor_type: EditorType,
    abort_signal: Any | None = None,
) -> ModifyResult[TParams]:
    """
    Triggers an external editor for the user to modify the proposed content.
    """
    current_content = await modify_context.get_current_content(original_params)
    proposed_content = await modify_context.get_proposed_content(
        original_params
    )

    old_path, new_path = _create_temp_files_for_modify(
        current_content,
        proposed_content,
        modify_context.get_file_path(original_params),
    )

    try:
        await open_diff(str(old_path), str(new_path), editor_type)
        return _get_updated_params(
            old_path, new_path, original_params, modify_context
        )
    finally:
        _delete_temp_files(old_path, new_path)
