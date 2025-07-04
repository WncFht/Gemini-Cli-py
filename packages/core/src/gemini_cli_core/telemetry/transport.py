"""
This file is refactored from packages/core_ts/src/telemetry/clearcut-logger/*.
It provides a transport for sending telemetry events to the Clearcut backend.
"""

import asyncio
import logging
from datetime import datetime
from enum import IntEnum
from typing import Any

import httpx

from gemini_cli_core.telemetry.events import TelemetryEvent
from gemini_cli_core.utils.session import (
    get_installation_id,
    get_obfuscated_google_account_id,
)

logger = logging.getLogger(__name__)


class EventMetadataKey(IntEnum):
    # This enum must be kept in sync with the one in event-metadata-key.ts
    GEMINI_CLI_KEY_UNKNOWN = 0
    GEMINI_CLI_START_SESSION_MODEL = 1
    GEMINI_CLI_START_SESSION_EMBEDDING_MODEL = 2
    GEMINI_CLI_START_SESSION_SANDBOX = 3
    GEMINI_CLI_START_SESSION_CORE_TOOLS = 4
    GEMINI_CLI_START_SESSION_APPROVAL_MODE = 5
    GEMINI_CLI_START_SESSION_API_KEY_ENABLED = 6
    GEMINI_CLI_START_SESSION_VERTEX_API_ENABLED = 7
    GEMINI_CLI_START_SESSION_DEBUG_MODE_ENABLED = 8
    GEMINI_CLI_START_SESSION_MCP_SERVERS = 9
    GEMINI_CLI_START_SESSION_TELEMETRY_ENABLED = 10
    GEMINI_CLI_START_SESSION_TELEMETRY_LOG_USER_PROMPTS_ENABLED = 11
    GEMINI_CLI_START_SESSION_RESPECT_GITIGNORE = 12
    GEMINI_CLI_USER_PROMPT_LENGTH = 13
    GEMINI_CLI_TOOL_CALL_NAME = 14
    GEMINI_CLI_TOOL_CALL_DECISION = 15
    GEMINI_CLI_TOOL_CALL_SUCCESS = 16
    GEMINI_CLI_TOOL_CALL_DURATION_MS = 17
    GEMINI_CLI_TOOL_ERROR_MESSAGE = 18
    GEMINI_CLI_TOOL_CALL_ERROR_TYPE = 19
    GEMINI_CLI_API_REQUEST_MODEL = 20
    GEMINI_CLI_API_RESPONSE_MODEL = 21
    GEMINI_CLI_API_RESPONSE_STATUS_CODE = 22
    GEMINI_CLI_API_RESPONSE_DURATION_MS = 23
    GEMINI_CLI_API_ERROR_MESSAGE = 24
    GEMINI_CLI_API_RESPONSE_INPUT_TOKEN_COUNT = 25
    GEMINI_CLI_API_RESPONSE_OUTPUT_TOKEN_COUNT = 26
    GEMINI_CLI_API_RESPONSE_CACHED_TOKEN_COUNT = 27
    GEMINI_CLI_API_RESPONSE_THINKING_TOKEN_COUNT = 28
    GEMINI_CLI_API_RESPONSE_TOOL_TOKEN_COUNT = 29
    GEMINI_CLI_API_ERROR_MODEL = 30
    GEMINI_CLI_API_ERROR_TYPE = 31
    GEMINI_CLI_API_ERROR_STATUS_CODE = 32
    GEMINI_CLI_API_ERROR_DURATION_MS = 33
    GEMINI_CLI_END_SESSION_ID = 34


class ClearcutTransport:
    """A transport for sending log events to the Clearcut backend."""

    def __init__(self, debug_mode: bool = False):
        self._events_queue = []
        self._last_flush_time = asyncio.get_event_loop().time()
        self._flush_interval_seconds = 60
        self._debug_mode = debug_mode
        self._client = httpx.AsyncClient()

    def _format_metadata(self, event: TelemetryEvent) -> list[dict[str, Any]]:
        metadata = []
        # A simple mapping from event field to metadata key
        # In a real scenario, this would be more robust.
        # This is a simplified version of the logic in the TS file.
        for field, value in event.model_dump(exclude_none=True).items():
            key_name = f"GEMINI_CLI_{event.event_name.upper()}_{field.upper()}"
            if hasattr(EventMetadataKey, key_name):
                metadata.append(
                    {
                        "gemini_cli_key": EventMetadataKey[key_name].value,
                        "value": str(value),
                    }
                )
        return metadata

    def _create_log_event(self, event: TelemetryEvent) -> dict[str, Any]:
        return {
            "console_type": "GEMINI_CLI",
            "application": 102,
            "event_name": event.event_name,
            "obfuscated_google_account_id": get_obfuscated_google_account_id(),
            "client_install_id": get_installation_id(),
            "event_metadata": self._format_metadata(event),
        }

    async def log_event(self, event: TelemetryEvent):
        """Enqueues an event and flushes if needed."""
        formatted_event = {
            "event_time_ms": int(
                datetime.fromisoformat(
                    event.event_timestamp.replace("Z", "+00:00")
                ).timestamp()
                * 1000
            ),
            "source_extension_json": self._create_log_event(event),
        }
        self._events_queue.append(formatted_event)

        if (
            asyncio.get_event_loop().time() - self._last_flush_time
            > self._flush_interval_seconds
        ) or event.event_name in ("start_session", "end_session"):
            await self.flush()

    async def flush(self):
        """Flushes the event queue to Clearcut."""
        if not self._events_queue:
            return

        if self._debug_mode:
            logger.info(
                f"Flushing {len(self._events_queue)} events to Clearcut."
            )

        events_to_send = list(self._events_queue)
        self._events_queue.clear()

        request_payload = [
            {
                "log_source_name": "CONCORD",
                "request_time_ms": int(datetime.utcnow().timestamp() * 1000),
                "log_event": events_to_send,
            }
        ]

        try:
            response = await self._client.post(
                "https://play.googleapis.com/log", json=request_payload
            )
            response.raise_for_status()
            self._last_flush_time = asyncio.get_event_loop().time()
            # Protobuf decoding logic can be added here if needed,
            # for now we assume success on 2xx status.
        except httpx.HTTPError as e:
            logger.error(f"Failed to send telemetry data to Clearcut: {e}")
            # Re-queue failed events
            self._events_queue.extend(events_to_send)

    async def shutdown(self):
        """Flushes any remaining events and closes the HTTP client."""
        await self.flush()
        await self._client.aclose()
