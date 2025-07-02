"""
This file is a Python port of packages/core_ts/src/utils/editor.ts.

It provides functionality for detecting the user's preferred editor
and opening it in a diff view.
"""

import asyncio
import logging
import os
import shutil
import sys
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)

# A literal type representing all supported editor identifiers.
EditorType = Literal[
    "vscode", "vscodium", "windsurf", "cursor", "vim", "neovim", "zed"
]

VALID_EDITORS: set[EditorType] = {
    "vscode",
    "vscodium",
    "windsurf",
    "cursor",
    "vim",
    "neovim",
    "zed",
}


def is_valid_editor_type(editor: str) -> "EditorType":
    """Type guard to check if a string is a valid EditorType."""
    return editor in VALID_EDITORS


class DiffCommand(TypedDict):
    """Represents a command and its arguments to run a diff."""

    command: str
    args: list[str]


def command_exists(cmd: str) -> bool:
    """Checks if a command exists in the system's PATH."""
    return shutil.which(cmd) is not None


# Maps EditorType to the executable command on different platforms.
EDITOR_COMMANDS: dict[EditorType, dict[str, str]] = {
    "vscode": {"win32": "code.cmd", "default": "code"},
    "vscodium": {"win32": "codium.cmd", "default": "codium"},
    "windsurf": {"win32": "windsurf", "default": "windsurf"},
    "cursor": {"win32": "cursor", "default": "cursor"},
    "vim": {"win32": "vim", "default": "vim"},
    "neovim": {"win32": "nvim", "default": "nvim"},
    "zed": {"win32": "zed", "default": "zed"},
}


def check_has_editor_type(editor: EditorType) -> bool:
    """Checks if the executable for a given editor type is available."""
    command_config = EDITOR_COMMANDS[editor]
    command = (
        command_config["win32"]
        if sys.platform == "win32"
        else command_config["default"]
    )
    return command_exists(command)


def allow_editor_type_in_sandbox(editor: EditorType) -> bool:
    """Checks if the editor is permitted to run in the current sandbox environment."""
    not_using_sandbox = not os.getenv("SANDBOX")
    if editor in ["vscode", "vscodium", "windsurf", "cursor", "zed"]:
        return not_using_sandbox
    return True


def is_editor_available(editor: str | None) -> bool:
    """
    Checks if the preferred editor is set, valid, installed, and allowed.
    """
    if editor and is_valid_editor_type(editor):
        return check_has_editor_type(editor) and allow_editor_type_in_sandbox(
            editor
        )
    return False


def get_diff_command(
    old_path: str, new_path: str, editor: EditorType
) -> DiffCommand | None:
    """Gets the appropriate diff command and arguments for a specific editor."""
    command_config = EDITOR_COMMANDS.get(editor)
    if not command_config:
        return None

    command = (
        command_config["win32"]
        if sys.platform == "win32"
        else command_config["default"]
    )

    if editor in ["vscode", "vscodium", "windsurf", "cursor", "zed"]:
        return {
            "command": command,
            "args": ["--wait", "--diff", old_path, new_path],
        }
    if editor in ["vim", "neovim"]:
        return {
            "command": command,
            "args": [
                "-d",
                "-i",
                "NONE",  # skip viminfo to avoid E138 errors
                "-c",
                "wincmd h | set readonly | wincmd l",  # left readonly, right editable
                "-c",  # set up diff colors
                "highlight DiffAdd cterm=bold ctermbg=22 guibg=#005f00 | "
                "highlight DiffChange cterm=bold ctermbg=24 guibg=#005f87 | "
                "highlight DiffText ctermbg=21 guibg=#0000af | "
                "highlight DiffDelete ctermbg=52 guibg=#5f0000",
                "-c",  # show helpful messages in tabline
                "set showtabline=2 | set tabline=[Instructions]\\ :wqa(save\\ &\\ quit)\\ \\|\\ i/esc(toggle\\ edit\\ mode)",
                "-c",
                "wincmd h | setlocal statusline=OLD\\ FILE",
                "-c",
                "wincmd l | setlocal statusline=%#StatusBold#NEW\\ FILE\\ :wqa(save\\ &\\ quit)\\ \\|\\ i/esc(toggle\\ edit\\ mode)",
                "-c",
                "autocmd WinClosed * wqa",  # auto-close when one window is closed
                old_path,
                new_path,
            ],
        }
    return None


async def open_diff(old_path: str, new_path: str, editor: EditorType) -> None:
    """
    Opens a diff tool to compare two files, blocking until the editor exits.
    """
    diff_command = get_diff_command(old_path, new_path, editor)
    if not diff_command:
        logger.error("No diff tool available. Install a supported editor.")
        return

    try:
        # For both GUI and terminal editors, we want to wait for the process
        # to finish. We can use asyncio.create_subprocess_exec for this.
        # It inherits stdio by default, allowing terminal editors to take over.
        process = await asyncio.create_subprocess_exec(
            diff_command["command"],
            *diff_command["args"],
            # No need to redirect stdio, it will inherit from the parent,
            # which is what we want for terminal editors like vim.
        )
        await process.wait()

        if process.returncode != 0:
            logger.error(f"{editor} exited with code {process.returncode}")

    except Exception as e:
        logger.error(f"Failed to open diff with {editor}: {e}", exc_info=True)
