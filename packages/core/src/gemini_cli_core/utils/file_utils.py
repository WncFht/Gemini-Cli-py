import mimetypes
from collections import deque
from pathlib import Path
from typing import Any, Literal

import aiofiles
from pydantic import BaseModel

from gemini_cli_core.services.file_discovery import FileDiscoveryService

DEFAULT_ENCODING = "utf-8"
MAX_LINE_LENGTH_TEXT_FILE = 2000
DEFAULT_MAX_LINES_TEXT_FILE = 2000

FileType = Literal["text", "image", "pdf", "binary"]


def is_binary_file(file_path: Path) -> bool:
    """Checks if a file is likely binary by inspecting its first few bytes."""
    try:
        with file_path.open("rb") as f:
            chunk = f.read(4096)
            if b"\0" in chunk:
                return True
            # Simple heuristic: check for a high percentage of non-printable ASCII
            non_printable = sum(
                1 for byte in chunk if byte < 32 and byte not in {9, 10, 13}
            )
            return non_printable / len(chunk) > 0.3 if chunk else False
    except Exception:
        return False


def detect_file_type(file_path: Path) -> FileType:
    """Detects the type of a file based on its extension and content."""
    mime_type, _ = mimetypes.guess_type(file_path)
    if mime_type:
        if mime_type.startswith("image/"):
            return "image"
        if mime_type == "application/pdf":
            return "pdf"

    # Known binary extensions
    binary_extensions = {
        ".zip",
        ".tar",
        ".gz",
        ".exe",
        ".dll",
        ".so",
        ".class",
        ".jar",
        ".war",
        ".7z",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".odt",
        ".ods",
        ".odp",
        ".bin",
        ".dat",
        ".obj",
        ".o",
        ".a",
        ".lib",
        ".wasm",
        ".pyc",
        ".pyo",
    }
    if file_path.suffix.lower() in binary_extensions:
        return "binary"

    if is_binary_file(file_path):
        return "binary"

    return "text"


class ProcessedFileReadResult(BaseModel):
    llm_content: Any
    return_display: str
    error: str | None = None
    is_truncated: bool = False
    original_line_count: int | None = None
    lines_shown: tuple[int, int] | None = None


async def process_single_file_content(
    file_path: Path,
    root_directory: Path,
    offset: int = 0,
    limit: int | None = None,
) -> ProcessedFileReadResult:
    """Reads and processes a single file, handling text, images, and PDFs."""
    try:
        if not await aiofiles.os.path.exists(file_path):
            return ProcessedFileReadResult(
                llm_content="",
                return_display="File not found.",
                error=f"File not found: {file_path}",
            )
        if await aiofiles.os.path.isdir(file_path):
            return ProcessedFileReadResult(
                llm_content="",
                return_display="Path is a directory.",
                error=f"Path is a directory: {file_path}",
            )

        file_type = detect_file_type(file_path)

        if file_type == "binary":
            return ProcessedFileReadResult(
                llm_content="",
                return_display=f"Skipped binary file: {file_path.name}",
            )

        if file_type in ("image", "pdf"):
            async with aiofiles.open(file_path, "rb") as f:
                import base64

                encoded_content = base64.b64encode(await f.read()).decode(
                    "utf-8"
                )
            mime_type, _ = mimetypes.guess_type(file_path)
            return ProcessedFileReadResult(
                llm_content={
                    "inlineData": {
                        "data": encoded_content,
                        "mimeType": mime_type or "application/octet-stream",
                    }
                },
                return_display=f"Read {file_type} file: {file_path.name}",
            )

        # It's a text file
        async with aiofiles.open(
            file_path, encoding="utf-8", errors="ignore"
        ) as f:
            lines = await f.readlines()

        original_line_count = len(lines)
        limit = limit or DEFAULT_MAX_LINES_TEXT_FILE
        # Ensure selected_lines doesn't try to slice beyond array bounds
        actual_start_line = min(offset, original_line_count)
        end_line = min(actual_start_line + limit, original_line_count)
        selected_lines = lines[actual_start_line:end_line]

        lines_were_truncated_in_length = False
        formatted_lines = []
        for line in selected_lines:
            if len(line) > MAX_LINE_LENGTH_TEXT_FILE:
                lines_were_truncated_in_length = True
                formatted_lines.append(
                    line[:MAX_LINE_LENGTH_TEXT_FILE] + "... [truncated]\n"
                )
            else:
                formatted_lines.append(line)

        content_range_truncated = end_line < original_line_count
        is_truncated = content_range_truncated or lines_were_truncated_in_length
        llm_text_content = ""
        if content_range_truncated:
            llm_text_content += f"[File content truncated: showing lines {actual_start_line + 1}-{end_line} of {original_line_count} total lines. Use offset/limit parameters to view more.]\n"
        elif lines_were_truncated_in_length:
            llm_text_content += f"[File content partially truncated: some lines exceeded maximum length of {MAX_LINE_LENGTH_TEXT_FILE} characters.]\n"

        llm_text_content += "".join(formatted_lines)
        display_message = f"Read lines {actual_start_line + 1}-{end_line} of {original_line_count} from {file_path.name}"
        if is_truncated:
            display_message += " (truncated)"

        return ProcessedFileReadResult(
            llm_content=llm_text_content,
            return_display=display_message,
            is_truncated=is_truncated,
            original_line_count=original_line_count,
            lines_shown=(actual_start_line + 1, end_line),
        )

    except Exception as e:
        return ProcessedFileReadResult(
            llm_content="",
            return_display=f"Error reading file: {e}",
            error=str(e),
        )


async def bfs_file_search(
    root_dir: Path,
    file_name: str,
    file_service: FileDiscoveryService,
    ignore_dirs: list[str] | None = None,
    max_dirs: int = 1000,
) -> list[Path]:
    """Performs a breadth-first search for a specific file."""
    found_files: list[Path] = []
    queue: deque[Path] = deque([root_dir])
    visited: set[Path] = set()
    scanned_dir_count = 0
    ignore_dirs = ignore_dirs or []

    while queue and scanned_dir_count < max_dirs:
        current_dir = queue.popleft()
        if current_dir in visited:
            continue
        visited.add(current_dir)
        scanned_dir_count += 1

        try:
            entries = await aiofiles.os.scandir(current_dir)
            for entry in entries:
                full_path = Path(entry.path)
                if file_service.should_git_ignore_file(
                    str(full_path.relative_to(root_dir))
                ):
                    continue

                if entry.is_dir() and entry.name not in ignore_dirs:
                    queue.append(full_path)
                elif entry.is_file() and entry.name == file_name:
                    found_files.append(full_path)
        except OSError:
            continue

    return found_files
