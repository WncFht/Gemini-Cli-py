"""
文件夹结构工具 - 从 getFolderStructure.ts 迁移
"""

from pathlib import Path

import aiofiles
from pydantic import BaseModel

from gemini_cli_core.services.file_discovery import FileDiscoveryService

MAX_ITEMS = 200
TRUNCATION_INDICATOR = "..."
DEFAULT_IGNORED_FOLDERS = {"node_modules", ".git", "dist"}


class FolderInfo(BaseModel):
    name: str
    path: Path
    files: list[str] = []
    sub_folders: list["FolderInfo"] = []
    has_more_files: bool = False
    has_more_subfolders: bool = False


async def _read_full_structure(
    root_path: Path,
    max_items: int,
    ignored_folders: set[str],
    file_service: FileDiscoveryService,
) -> FolderInfo | None:
    root_node = FolderInfo(name=root_path.name, path=root_path)
    queue = [(root_node, root_path)]
    item_count = 0

    while queue:
        folder_info, current_path = queue.pop(0)
        if item_count >= max_items:
            # Mark parent as having more, but don't process this one
            continue

        try:
            entries = await aiofiles.os.scandir(current_path)
            sorted_entries = sorted(entries, key=lambda e: e.name)

            # Process files first
            for entry in sorted_entries:
                if item_count >= max_items:
                    folder_info.has_more_files = True
                    break
                if entry.is_file() and not file_service.should_git_ignore_file(
                    entry.path
                ):
                    folder_info.files.append(entry.name)
                    item_count += 1

            # Process directories
            for entry in sorted_entries:
                if item_count >= max_items:
                    folder_info.has_more_subfolders = True
                    break
                if (
                    entry.is_dir()
                    and entry.name not in ignored_folders
                    and not file_service.should_git_ignore_file(entry.path)
                ):
                    sub_folder_info = FolderInfo(
                        name=entry.name, path=Path(entry.path)
                    )
                    folder_info.sub_folders.append(sub_folder_info)
                    queue.append((sub_folder_info, Path(entry.path)))
                    item_count += 1

        except (OSError, PermissionError):
            continue

    return root_node


def _format_structure(
    node: FolderInfo, indent: str = "", is_last: bool = True
) -> str:
    lines = []
    connector = "└───" if is_last else "├───"
    lines.append(f"{indent}{connector}{node.name}/")

    child_indent = indent + ("    " if is_last else "│   ")

    all_children = node.files + node.sub_folders
    total_children = len(all_children)

    for i, file_name in enumerate(node.files):
        is_last_item = i == total_children - 1 and not node.has_more_subfolders
        file_connector = "└───" if is_last_item else "├───"
        lines.append(f"{child_indent}{file_connector}{file_name}")

    if node.has_more_files:
        is_last_item = not node.sub_folders and not node.has_more_subfolders
        file_connector = "└───" if is_last_item else "├───"
        lines.append(f"{child_indent}{file_connector}{TRUNCATION_INDICATOR}")

    for i, sub_folder in enumerate(node.sub_folders):
        is_last_item = (
            i == len(node.sub_folders) - 1 and not node.has_more_subfolders
        )
        lines.append(_format_structure(sub_folder, child_indent, is_last_item))

    if node.has_more_subfolders:
        lines.append(f"{child_indent}└───{TRUNCATION_INDICATOR}")

    return "\n".join(lines)


async def get_folder_structure(
    directory: str, file_service: FileDiscoveryService
) -> str:
    """Generates a string representation of a directory's structure."""
    resolved_path = Path(directory).resolve()

    try:
        structure_root = await _read_full_structure(
            resolved_path, MAX_ITEMS, DEFAULT_IGNORED_FOLDERS, file_service
        )
        if not structure_root:
            return f"Error: Could not read directory '{resolved_path}'."

        # Recreate the formatting logic from the TS version
        formatted_lines = []
        for i, f in enumerate(structure_root.files):
            is_last = (
                i == len(structure_root.files) - 1
            ) and not structure_root.sub_folders
            formatted_lines.append(f"{'└───' if is_last else '├───'}{f}")

        for i, d in enumerate(structure_root.sub_folders):
            is_last = i == len(structure_root.sub_folders) - 1
            formatted_lines.append(_format_structure(d, "", is_last))

        summary = f"Showing up to {MAX_ITEMS} items. "
        return f"{summary}\n\n{resolved_path}/\n" + "\n".join(formatted_lines)

    except Exception as e:
        return f"Error processing directory '{resolved_path}': {e}"
