"""
This file is refactored from packages/core_ts/src/core/logger.ts.
It handles file-based logging of session messages and checkpoints.
"""

import json
import logging
import time
from datetime import datetime
from enum import Enum
from pathlib import Path

import aiofiles
from pydantic import BaseModel, ValidationError

from gemini_cli_core.core.types import Content
from gemini_cli_core.utils.paths import get_project_temp_dir

logger = logging.getLogger(__name__)

LOG_FILE_NAME = "logs.json"
CHECKPOINT_FILE_NAME = "checkpoint.json"


class MessageSenderType(str, Enum):
    USER = "user"


class LogEntry(BaseModel):
    session_id: str
    message_id: int
    timestamp: str
    type: MessageSenderType
    message: str


class SessionLogger:
    def __init__(self, session_id: str):
        self.session_id: str = session_id
        self.gemini_dir: Path | None = None
        self.log_file_path: Path | None = None
        self.checkpoint_file_path: Path | None = None
        self.message_id: int = 0
        self.initialized: bool = False
        self.logs: list[LogEntry] = []

    async def _read_log_file(self) -> list[LogEntry]:
        if not self.log_file_path:
            raise OSError("Log file path not set during read attempt.")
        try:
            async with aiofiles.open(self.log_file_path, encoding="utf-8") as f:
                content = await f.read()

            parsed_logs = json.loads(content)
            if not isinstance(parsed_logs, list):
                await self._backup_corrupted_log_file("malformed_array")
                return []

            valid_logs = []
            for entry_data in parsed_logs:
                try:
                    valid_logs.append(LogEntry.model_validate(entry_data))
                except ValidationError:
                    continue  # Skip invalid entries
            return valid_logs

        except FileNotFoundError:
            return []
        except json.JSONDecodeError:
            logger.debug(
                f"Invalid JSON in log file {self.log_file_path}. Backing up."
            )
            await self._backup_corrupted_log_file("invalid_json")
            return []
        except Exception as e:
            logger.debug(
                f"Failed to read/parse log file {self.log_file_path}: {e}"
            )
            raise

    async def _backup_corrupted_log_file(self, reason: str):
        if not self.log_file_path:
            return
        backup_path = self.log_file_path.with_suffix(
            f".{reason}.{int(time.time())}.bak"
        )
        try:
            await aiofiles.os.rename(self.log_file_path, backup_path)
            logger.debug(f"Backed up corrupted log file to {backup_path}")
        except Exception:
            pass  # Ignore if rename fails

    async def initialize(self):
        if self.initialized:
            return

        try:
            self.gemini_dir = get_project_temp_dir(Path.cwd())
            self.log_file_path = self.gemini_dir / LOG_FILE_NAME
            self.checkpoint_file_path = self.gemini_dir / CHECKPOINT_FILE_NAME

            self.gemini_dir.mkdir(parents=True, exist_ok=True)

            if not self.log_file_path.exists():
                async with aiofiles.open(
                    self.log_file_path, "w", encoding="utf-8"
                ) as f:
                    await f.write("[]")

            self.logs = await self._read_log_file()
            session_logs = [
                log for log in self.logs if log.session_id == self.session_id
            ]
            self.message_id = (
                max(log.message_id for log in session_logs) + 1
                if session_logs
                else 0
            )
            self.initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize logger: {e}")
            self.initialized = False

    async def _update_log_file(
        self, entry_to_append: LogEntry
    ) -> LogEntry | None:
        if not self.log_file_path:
            raise OSError("Log file path not set.")

        # This logic should ideally be atomic using file locks
        # For asyncio, a lock per logger instance can prevent race conditions
        # from a single process, but not across processes.

        current_logs = await self._read_log_file()
        session_logs = [
            log
            for log in current_logs
            if log.session_id == entry_to_append.session_id
        ]
        next_id = (
            max(log.message_id for log in session_logs) + 1
            if session_logs
            else 0
        )
        entry_to_append.message_id = next_id

        current_logs.append(entry_to_append)

        async with aiofiles.open(
            self.log_file_path, "w", encoding="utf-8"
        ) as f:
            await f.write(
                json.dumps([log.model_dump() for log in current_logs], indent=2)
            )

        self.logs = current_logs
        return entry_to_append

    async def log_message(self, type: MessageSenderType, message: str):
        if not self.initialized or self.session_id is None:
            return

        new_entry = LogEntry(
            session_id=self.session_id,
            message_id=self.message_id,  # Will be recalculated in _update
            type=type,
            message=message,
            timestamp=datetime.utcnow().isoformat(),
        )

        written_entry = await self._update_log_file(new_entry)
        if written_entry:
            self.message_id = written_entry.message_id + 1

    def _get_checkpoint_path(self, tag: str | None = None) -> Path:
        if not self.checkpoint_file_path or not self.gemini_dir:
            raise OSError("Checkpoint path not set.")
        if not tag:
            return self.checkpoint_file_path
        return self.gemini_dir / f"checkpoint-{tag}.json"

    async def save_checkpoint(
        self, conversation: list[Content], tag: str | None = None
    ):
        if not self.initialized:
            return
        path = self._get_checkpoint_path(tag)
        async with aiofiles.open(path, "w", encoding="utf-8") as f:
            await f.write(json.dumps(conversation, indent=2))

    async def load_checkpoint(self, tag: str | None = None) -> list[Content]:
        if not self.initialized:
            return []
        path = self._get_checkpoint_path(tag)
        if not path.exists():
            return []

        try:
            async with aiofiles.open(path, encoding="utf-8") as f:
                content = await f.read()
            return json.loads(content)
        except Exception:
            return []

    def close(self):
        self.initialized = False
        self.logs = []
        self.message_id = 0
