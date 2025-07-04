import asyncio
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gemini_cli_core.core.config import Config
from gemini_cli_core.tools import BaseTool, ToolResult
from gemini_cli_core.utils.git_utils import is_git_repository


class GrepToolParams(BaseModel):
    pattern: str = Field(..., description="The regex pattern to search for.")
    path: str | None = Field(
        None,
        description="Directory to search in. Defaults to current directory.",
    )
    include: str | None = Field(
        None, description="File pattern to include in the search."
    )


class GrepMatch(BaseModel):
    file_path: str
    line_number: int
    line: str


async def _is_command_available(command: str) -> bool:
    try:
        proc = await asyncio.create_subprocess_shell(
            f"command -v {command}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        return proc.returncode == 0
    except FileNotFoundError:
        return False


async def _run_grep_command(cmd_args: list[str], cwd: Path) -> str:
    proc = await asyncio.create_subprocess_exec(
        *cmd_args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=cwd,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode not in [0, 1]:  # 1 means no matches found
        raise RuntimeError(f"Grep command failed: {stderr.decode()}")
    return stdout.decode()


def _parse_grep_output(output: str, base_path: Path) -> list[GrepMatch]:
    matches = []
    for line in output.strip().split("\n"):
        if not line:
            continue
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        file_path, line_num_str, line_content = parts
        try:
            matches.append(
                GrepMatch(
                    file_path=str(base_path / file_path),
                    line_number=int(line_num_str),
                    line=line_content,
                )
            )
        except ValueError:
            continue
    return matches


class GrepTool(BaseTool[GrepToolParams, ToolResult]):
    """A tool for searching file contents with regex."""

    NAME = "search_file_content"

    def __init__(self, config: Config):
        super().__init__(
            name=self.NAME,
            display_name="SearchText",
            description="Searches for a regular expression pattern within files.",
            parameter_schema=GrepToolParams.model_json_schema(),
        )
        self.root_directory = Path(config.get_target_dir()).resolve()

    async def _grep_with_git(
        self, params: GrepToolParams, search_path: Path
    ) -> list[GrepMatch] | None:
        if not is_git_repository(
            str(search_path)
        ) or not await _is_command_available("git"):
            return None

        cmd = [
            "git",
            "grep",
            "--untracked",
            "-n",
            "-E",
            "--ignore-case",
            params.pattern,
        ]
        if params.include:
            cmd.extend(["--", params.include])

        try:
            output = await _run_grep_command(cmd, search_path)
            return _parse_grep_output(output, search_path)
        except RuntimeError:
            return None

    async def _grep_with_system(
        self, params: GrepToolParams, search_path: Path
    ) -> list[GrepMatch] | None:
        if not await _is_command_available("grep"):
            return None

        cmd = [
            "grep",
            "-r",
            "-n",
            "-H",
            "-E",
            "--exclude-dir=.git",
            params.pattern,
            ".",
        ]
        if params.include:
            cmd.insert(1, f"--include={params.include}")

        try:
            output = await _run_grep_command(cmd, search_path)
            return _parse_grep_output(output, search_path)
        except RuntimeError:
            return None

    async def _grep_with_python(
        self, params: GrepToolParams, search_path: Path
    ) -> list[GrepMatch]:
        matches = []
        regex = re.compile(params.pattern, re.IGNORECASE)

        glob_pattern = f"**/{params.include or '*'}"

        for file_path in search_path.glob(glob_pattern):
            if file_path.is_file() and ".git" not in file_path.parts:
                try:
                    with file_path.open(
                        "r", encoding="utf-8", errors="ignore"
                    ) as f:
                        for i, line in enumerate(f, 1):
                            if regex.search(line):
                                matches.append(
                                    GrepMatch(
                                        file_path=str(file_path),
                                        line_number=i,
                                        line=line.strip(),
                                    )
                                )
                except Exception:
                    continue  # Ignore read errors
        return matches

    async def execute(
        self, params: GrepToolParams, signal: Any | None = None
    ) -> ToolResult:
        search_path = self.root_directory / (params.path or "")
        matches = await self._grep_with_git(params, search_path)
        if matches is None:
            matches = await self._grep_with_system(params, search_path)
        if matches is None:
            matches = await self._grep_with_python(params, search_path)

        if not matches:
            return ToolResult(
                llm_content="No matches found.",
                return_display="No matches found.",
            )

        llm_content = f"Found {len(matches)} matches:\n"
        for match in matches:
            llm_content += (
                f"{match.file_path}:{match.line_number}:{match.line}\n"
            )

        return ToolResult(
            llm_content=llm_content,
            return_display=f"Found {len(matches)} matches.",
        )
