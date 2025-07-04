"""
This file is refactored from packages/core_ts/src/utils/memoryDiscovery.ts
and packages/core_ts/src/utils/memoryImportProcessor.ts.
"""

import logging
import re
from pathlib import Path
from typing import Any

import aiofiles

from gemini_cli_core.tools.memory.memory_tool import (
    DEFAULT_CONTEXT_FILENAME,
    get_global_memory_file_path,
)

from .file_utils import bfs_file_search
from .git_utils import find_git_root

logger = logging.getLogger(__name__)
MAX_DIRECTORIES_TO_SCAN_FOR_MEMORY = 200


class ImportState:
    """State for tracking import processing to prevent circular imports."""

    def __init__(self, max_depth: int = 10):
        self.processed_files: set[Path] = set()
        self.max_depth = max_depth
        self.current_depth = 0


async def process_imports(
    content: str,
    base_path: Path,
    project_root: Path,
    state: ImportState | None = None,
) -> str:
    """Recursively processes @-imports in memory files."""
    state = state or ImportState()
    if state.current_depth >= state.max_depth:
        logger.warning("Maximum import depth reached.")
        return content

    import_regex = re.compile(r"@([./]?[^\s\n]+\.md)")

    async def replace_match(match: re.Match) -> str:
        import_path_str = match.group(1)
        full_path = (base_path / import_path_str).resolve()

        # Security check: Ensure the path is within the project root
        try:
            full_path.relative_to(project_root)
        except ValueError:
            logger.warning(
                f"Import path '{import_path_str}' is outside the project root. Aborting import."
            )
            return f"<!-- Import failed: {import_path_str} - Path is outside of project boundaries -->"

        if full_path in state.processed_files:
            logger.warning(f"Circular import detected and skipped: {full_path}")
            return f"<!-- Circular import detected: {import_path_str} -->"

        try:
            async with aiofiles.open(full_path, encoding="utf-8") as f:
                imported_content = await f.read()

            new_state = ImportState(max_depth=state.max_depth)
            new_state.processed_files = state.processed_files | {full_path}
            new_state.current_depth = state.current_depth + 1

            processed_import = await process_imports(
                imported_content, full_path.parent, project_root, new_state
            )
            return f"<!-- Imported from: {import_path_str} -->\n{processed_import}\n<!-- End import -->"
        except FileNotFoundError:
            return f"<!-- Import failed: {import_path_str} not found -->"
        except Exception as e:
            return f"<!-- Import failed: {e} -->"

    # A simple sequential replacement. For concurrent, would need a more complex approach.
    processed_content = content
    for match in import_regex.finditer(content):
        replacement = await replace_match(match)
        processed_content = processed_content.replace(
            match.group(0), replacement, 1
        )

    return processed_content


async def _get_gemini_md_file_paths(cwd: Path, file_service) -> list[Path]:
    """Finds all GEMINI.md files in the hierarchy."""
    all_paths: set[Path] = set()
    project_root = find_git_root(cwd) or cwd

    # Add global memory file first
    global_memory_path = get_global_memory_file_path()
    if global_memory_path.is_file():
        all_paths.add(global_memory_path)

    # Upward search
    current = cwd
    while True:
        p = current / DEFAULT_CONTEXT_FILENAME
        if p.is_file():
            all_paths.add(p)
        if current == project_root or current.parent == current:
            break
        current = current.parent

    # Downward search
    downward_paths = await bfs_file_search(
        root_dir=cwd,
        file_name=DEFAULT_CONTEXT_FILENAME,
        file_service=file_service,
        max_dirs=MAX_DIRECTORIES_TO_SCAN_FOR_MEMORY,
    )
    for p in downward_paths:
        all_paths.add(p)

    return sorted(list(all_paths))


async def load_server_hierarchical_memory(
    cwd: Path, file_service
) -> dict[str, Any]:
    """Loads and concatenates hierarchical memory files."""
    project_root = find_git_root(cwd) or cwd
    file_paths = await _get_gemini_md_file_paths(cwd, file_service)
    if not file_paths:
        return {"memory_content": "", "file_count": 0}

    contents = []
    for p in file_paths:
        try:
            async with aiofiles.open(p, encoding="utf-8") as f:
                content = await f.read()
            processed_content = await process_imports(
                content, p.parent, project_root
            )

            try:
                relative_path = p.relative_to(cwd)
            except ValueError:
                relative_path = (
                    p.name
                )  # Fallback for global memory files outside cwd

            contents.append(
                f"--- Context from: {relative_path} ---\n{processed_content}\n--- End Context ---"
            )
        except Exception as e:
            logger.warning(f"Could not read memory file {p}: {e}")

    return {
        "memory_content": "\n\n".join(contents),
        "file_count": len(contents),
    }
