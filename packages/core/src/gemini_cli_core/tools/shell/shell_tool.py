import asyncio
import os
import shlex
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from gemini_cli_core.core.config import Config
from gemini_cli_core.tools import BaseTool, ToolResult
from gemini_cli_core.tools.common import ToolCallConfirmationDetails
from gemini_cli_core.utils.paths import is_within_root


class ShellToolParams(BaseModel):
    command: str = Field(..., description="Exact bash command to execute.")
    description: str | None = Field(
        None, description="Brief description of the command for the user."
    )
    directory: str | None = Field(
        None, description="Directory to run the command in."
    )


class ShellTool(BaseTool[ShellToolParams, ToolResult]):
    """A tool for executing shell commands."""

    NAME = "run_shell_command"

    def __init__(self, config: Config):
        super().__init__(
            name=self.NAME,
            display_name="Shell",
            description="Executes a shell command.",
            parameter_schema=ShellToolParams.model_json_schema(),
            is_output_markdown=False,
            can_update_output=True,
        )
        self.config = config
        self.whitelist: set[str] = set()

    def get_command_root(self, command: str) -> str | None:
        try:
            return shlex.split(command)[0]
        except ValueError:
            return None

    def is_command_allowed(self, command: str) -> bool:
        # Simplified version of the JS logic.
        # TODO: Implement the full whitelist/blacklist logic.
        if "`" in command or "$(" in command:
            return False
        return True

    def validate_tool_params(self, params: ShellToolParams) -> str | None:
        if not self.is_command_allowed(params.command):
            return f"Command is not allowed: {params.command}"
        if not params.command.strip():
            return "Command cannot be empty."
        if not self.get_command_root(params.command):
            return "Could not identify command root."
        if params.directory:
            if not is_within_root(
                Path(self.config.get_target_dir()) / Path(params.directory),
                Path(self.config.get_target_dir()),
            ):
                return "Directory must be within the project root."
        return None

    async def should_confirm_execute(
        self, params: ShellToolParams, abort_signal: Any | None = None
    ) -> ToolCallConfirmationDetails | bool:
        if self.validate_tool_params(params):
            return False
        root_command = self.get_command_root(params.command)
        if root_command in self.whitelist:
            return False

        return ToolCallConfirmationDetails(
            title="Confirm Shell Command",
            description=f"Allow shell command: {params.command}",
            params=params.model_dump(),
        )

    async def execute(
        self,
        params: ShellToolParams,
        signal: Any | None = None,
        update_output: Callable | None = None,
    ) -> ToolResult:
        validation_error = self.validate_tool_params(params)
        if validation_error:
            return ToolResult(
                llm_content=f"Error: {validation_error}",
                return_display=f"Error: {validation_error}",
            )

        cwd = self.config.get_target_dir()
        if params.directory:
            cwd = cwd / params.directory

        proc = await asyncio.create_subprocess_shell(
            params.command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            preexec_fn=os.setsid,  # To kill the whole process group
        )

        output = ""

        async def read_stream(stream, is_stdout):
            nonlocal output
            while True:
                line = await stream.readline()
                if not line:
                    break
                line_str = line.decode("utf-8", errors="replace")
                output += line_str
                if update_output:
                    update_output(line_str)

        stdout_task = asyncio.create_task(read_stream(proc.stdout, True))
        stderr_task = asyncio.create_task(read_stream(proc.stderr, False))

        try:
            await asyncio.wait_for(proc.wait(), timeout=300)  # 5 min timeout
        except TimeoutError:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            return ToolResult(
                llm_content="Error: Command timed out.",
                return_display="Error: Command timed out.",
            )

        await asyncio.gather(stdout_task, stderr_task)

        return ToolResult(
            llm_content=f"Command executed with exit code {proc.returncode}\nOutput:\n{output}",
            return_display=output
            or f"Command finished with exit code {proc.returncode}",
        )
