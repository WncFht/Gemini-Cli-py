"""
This file is refactored from packages/core_ts/src/utils/paths.ts.
"""

import hashlib
from pathlib import Path

GEMINI_DIR = ".gemini"
TMP_DIR_NAME = "tmp"


def tildeify_path(p: Path) -> str:
    """Replaces the home directory with a tilde."""
    home = Path.home()
    if p.is_relative_to(home):
        return f"~/{p.relative_to(home)}"
    return str(p)


def shorten_path(file_path: str, max_len: int = 35) -> str:
    """Shortens a path string if it exceeds maxLen."""
    if len(file_path) <= max_len:
        return file_path

    p = Path(file_path)
    parts = list(p.parts)

    if len(parts) <= 2:
        return file_path[-max_len:]

    # Keep root, first, ..., last
    # e.g., /a/b/c/d.txt -> /a/.../d.txt
    start = parts[0]
    end = parts[-1]

    # +3 for "..."
    if len(start) + len(end) + len(p.anchor) + 1 + 3 > max_len:
        # Fallback for very long start/end parts
        return f"...{file_path[-(max_len - 3) :]}"

    return f"{p.parts[0]}{p.anchor}...{p.anchor}{p.parts[-1]}"


def make_relative(target_path: Path, root_directory: Path) -> str:
    """Calculates the relative path, returning '.' for the same path."""
    try:
        relative_path = target_path.relative_to(root_directory)
        return str(relative_path) or "."
    except ValueError:
        # This can happen if target_path is not within root_directory
        return str(target_path)


def get_project_hash(project_root: str) -> str:
    """Generates a unique hash for a project based on its root path."""
    return hashlib.sha256(project_root.encode()).hexdigest()


def get_project_temp_dir(project_root: str | Path) -> Path:
    """Generates a unique temporary directory path for a project."""
    hash_val = get_project_hash(str(project_root))
    return Path.home() / GEMINI_DIR / TMP_DIR_NAME / hash_val


def is_within_root(path_to_check: Path, root_directory: Path) -> bool:
    """Checks if a path is within a given root directory."""
    try:
        path_to_check.resolve().relative_to(root_directory.resolve())
        return True
    except ValueError:
        return False
