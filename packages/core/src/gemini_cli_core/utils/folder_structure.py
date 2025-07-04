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
    is_ignored: bool = False


async def _read_full_structure(
    root_path: Path,
    max_items: int,
    ignored_folders: set[str],
    file_service: FileDiscoveryService,
) -> FolderInfo | None:
    root_node = FolderInfo(name=root_path.name, path=root_path)
    queue = [(root_node, root_path)]
    item_count = 1  # Start with 1 for the root directory itself
    processed_paths = set()

    while queue:
        folder_info, current_path = queue.pop(0)

        if current_path in processed_paths:
            continue
        processed_paths.add(current_path)

        if item_count >= max_items and folder_info != root_node:
            continue

        try:
            entries = await aiofiles.os.scandir(current_path)
            sorted_entries = sorted(entries, key=lambda e: e.name)
        except (OSError, PermissionError) as e:
            if current_path == root_path:
                return None  # Cannot read root
            print(f"Warning: Could not read directory {current_path}: {e}")
            continue

        files_in_dir = []
        subfolders_in_dir = []

        # Process files
        for entry in sorted_entries:
            if entry.is_file():
                if item_count >= max_items:
                    folder_info.has_more_files = True
                    break
                if not file_service.should_git_ignore_file(entry.path):
                    files_in_dir.append(entry.name)
                    item_count += 1
        folder_info.files = files_in_dir

        # Process directories
        for entry in sorted_entries:
            if entry.is_dir():
                if item_count >= max_items:
                    folder_info.has_more_subfolders = True
                    break

                is_git_ignored = file_service.should_git_ignore_file(entry.path)
                is_explicitly_ignored = entry.name in ignored_folders

                sub_folder_info = FolderInfo(
                    name=entry.name,
                    path=Path(entry.path),
                    is_ignored=(is_git_ignored or is_explicitly_ignored),
                )
                subfolders_in_dir.append(sub_folder_info)
                item_count += 1

                if not sub_folder_info.is_ignored:
                    queue.append((sub_folder_info, Path(entry.path)))
        folder_info.sub_folders = subfolders_in_dir

    return root_node


def _format_structure_recursive(
    node: FolderInfo,
    builder: list[str],
    indent: str,
    is_last: bool,
    is_root: bool = False,
):
    connector = "└───" if is_last else "├───"
    if not is_root:
        line = f"{indent}{connector}{node.name}/"
        if node.is_ignored:
            line += TRUNCATION_INDICATOR
        builder.append(line)

    child_indent = indent + ("    " if is_last else "│   ")
    if is_root:
        child_indent = ""

    children = node.files + node.sub_folders
    total_children = len(children)

    # Format files
    for i, file_name in enumerate(node.files):
        is_last_item = (i == len(node.files) - 1) and not (
            node.sub_folders or node.has_more_subfolders
        )
        file_connector = "└───" if is_last_item else "├───"
        builder.append(f"{child_indent}{file_connector}{file_name}")

    if node.has_more_files:
        is_last_item = not (node.sub_folders or node.has_more_subfolders)
        file_connector = "└───" if is_last_item else "├───"
        builder.append(f"{child_indent}{file_connector}{TRUNCATION_INDICATOR}")

    # Format subfolders
    for i, sub_folder in enumerate(node.sub_folders):
        is_last_item = (
            i == len(node.sub_folders) - 1
        ) and not node.has_more_subfolders
        _format_structure_recursive(
            sub_folder, builder, child_indent, is_last_item
        )

    if node.has_more_subfolders:
        builder.append(f"{child_indent}└───{TRUNCATION_INDICATOR}")


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

        structure_lines = []
        _format_structure_recursive(
            structure_root, structure_lines, "", True, is_root=True
        )

        truncation_occurred = False

        def check_truncation(node: FolderInfo):
            nonlocal truncation_occurred
            if (
                node.has_more_files
                or node.has_more_subfolders
                or node.is_ignored
            ):
                truncation_occurred = True
                return
            for sub in node.sub_folders:
                check_truncation(sub)

        check_truncation(structure_root)
        disclaimer = ""
        if truncation_occurred:
            disclaimer = f"Folders or files indicated with {TRUNCATION_INDICATOR} contain more items not shown, were ignored, or the display limit ({MAX_ITEMS} items) was reached."

        summary = (
            f"Showing up to {MAX_ITEMS} items (files + folders). {disclaimer}"
        ).strip()

        output = f"{summary}\n\n{resolved_path.as_posix()}/\n" + "\n".join(
            structure_lines
        )
        return output

    except Exception as e:
        return f"Error processing directory '{resolved_path}': {e}"
