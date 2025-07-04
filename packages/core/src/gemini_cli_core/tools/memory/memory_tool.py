from pathlib import Path
from typing import Any

import aiofiles
from pydantic import BaseModel, Field

from gemini_cli_core.tools.base.tool_base import BaseTool, ToolResult

GEMINI_CONFIG_DIR = Path.home() / ".gemini"
DEFAULT_CONTEXT_FILENAME = "GEMINI.md"
MEMORY_SECTION_HEADER = "## Gemini Added Memories"


class SaveMemoryParams(BaseModel):
    fact: str = Field(..., description="The specific fact to remember.")


def get_global_memory_file_path() -> Path:
    """Gets the path to the global memory file."""
    return GEMINI_CONFIG_DIR / DEFAULT_CONTEXT_FILENAME


def ensure_newline_separation(content: str) -> str:
    """Ensures there are exactly two newlines before appending new content."""
    if not content:
        return ""
    if content.endswith("\n\n"):
        return ""
    if content.endswith("\n"):
        return "\n"
    return "\n\n"


async def perform_add_memory_entry(text: str, memory_file_path: Path):
    """Adds a new memory entry to the specified memory file."""
    processed_text = text.strip().lstrip("-").strip()
    new_memory_item = f"- {processed_text}"

    await memory_file_path.parent.mkdir(parents=True, exist_ok=True)

    content = ""
    if await aiofiles.os.path.exists(memory_file_path):
        async with aiofiles.open(memory_file_path, encoding="utf-8") as f:
            content = await f.read()

    header_index = content.find(MEMORY_SECTION_HEADER)

    if header_index == -1:
        separator = ensure_newline_separation(content)
        content += f"{separator}{MEMORY_SECTION_HEADER}\n{new_memory_item}\n"
    else:
        start_of_section = header_index + len(MEMORY_SECTION_HEADER)
        end_of_section = content.find("\n## ", start_of_section)
        if end_of_section == -1:
            end_of_section = len(content)

        section_content = content[start_of_section:end_of_section].strip()
        new_section_content = f"{section_content}\n{new_memory_item}".strip()

        before_section = content[:start_of_section].rstrip()
        after_section = content[end_of_section:].lstrip()

        content = (
            f"{before_section}\n{new_section_content}\n{after_section}".strip()
            + "\n"
        )

    async with aiofiles.open(memory_file_path, "w", encoding="utf-8") as f:
        await f.write(content)


class MemoryTool(BaseTool[SaveMemoryParams, ToolResult]):
    """A tool for saving information to long-term memory."""

    NAME = "save_memory"

    def __init__(self):
        super().__init__(
            name=self.NAME,
            display_name="Save Memory",
            description="Saves a specific piece of information to long-term memory.",
            parameter_schema=SaveMemoryParams.model_json_schema(),
        )

    async def execute(
        self, params: SaveMemoryParams, signal: Any | None = None
    ) -> ToolResult:
        if (
            not params.fact
            or not isinstance(params.fact, str)
            or not params.fact.strip()
        ):
            return ToolResult(
                llm_content="Error: 'fact' must be a non-empty string.",
                return_display="Error: Invalid fact.",
            )

        try:
            await perform_add_memory_entry(
                params.fact, get_global_memory_file_path()
            )
            success_message = f'Okay, I\'ve remembered that: "{params.fact}"'
            return ToolResult(
                llm_content={"success": True, "message": success_message},
                return_display=success_message,
            )
        except Exception as e:
            error_message = f"Failed to save memory: {e}"
            return ToolResult(
                llm_content={"success": False, "error": error_message},
                return_display=f"Error: {error_message}",
            )
