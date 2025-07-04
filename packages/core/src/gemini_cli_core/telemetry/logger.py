import logging
from typing import Any

from gemini_cli_core.telemetry.events import (
    ApiErrorEvent,
    ApiRequestEvent,
    ApiResponseEvent,
    StartSessionEvent,
    TelemetryEvent,
    ToolCallEvent,
    UserPromptEvent,
)
from gemini_cli_core.telemetry.metrics import (
    record_api_error_metrics,
    record_api_response_metrics,
    record_token_usage_metrics,
    record_tool_call_metrics,
)
from gemini_cli_core.telemetry.transport import ClearcutTransport

# This will be configured by the SDK
_transport: ClearcutTransport | None = None
_config: Any | None = None  # Using Any to avoid circular dependency on config
_is_initialized = False

# A standard Python logger for structured, observable logs
observable_logger = logging.getLogger("gemini_cli_observable")


def _log_to_observable(event: TelemetryEvent):
    """Logs events to a standard logger for observability."""
    # We can configure this logger to output JSON for easy parsing.
    observable_logger.info(
        event.event_name, extra={"data": event.model_dump_json()}
    )


def init_telemetry(config: Any, transport: ClearcutTransport):
    """Initializes the telemetry system with config and transport."""
    global _config, _transport, _is_initialized
    _config = config
    _transport = transport
    _is_initialized = True


def log_cli_configuration(event: StartSessionEvent):
    """Logs the initial CLI configuration."""
    if not _is_initialized or not _transport:
        return
    _transport.log_event(event)
    _log_to_observable(event)


def log_user_prompt(event: UserPromptEvent):
    """Logs a user prompt event."""
    if not _is_initialized or not _transport:
        return

    should_log_prompts = _config and _config.get("telemetry", {}).get(
        "log_user_prompts", False
    )
    if not should_log_prompts:
        event.prompt = None  # Clear prompt if not allowed

    _transport.log_event(event)
    _log_to_observable(event)


def log_tool_call(event: ToolCallEvent):
    """Logs a tool call event."""
    if not _is_initialized or not _transport:
        return
    _transport.log_event(event)
    _log_to_observable(event)
    record_tool_call_metrics(
        config=_config,
        function_name=event.function_name,
        duration_ms=event.duration_ms,
        success=event.success,
        decision=event.decision.value if event.decision else None,
    )


def log_api_request(event: ApiRequestEvent):
    """Logs an API request event."""
    if not _is_initialized or not _transport:
        return
    _transport.log_event(event)
    _log_to_observable(event)
    record_api_error_metrics(
        config=_config,
        model=event.model,
        duration_ms=event.duration_ms,
        status_code=event.status_code,
        error_type=event.error_type,
    )


def log_api_error(event: ApiErrorEvent):
    """Logs an API error event."""
    if not _is_initialized or not _transport:
        return
    _transport.log_event(event)
    _log_to_observable(event)
    # TODO: Add call to record_api_error_metrics from metrics.py


def log_api_response(event: ApiResponseEvent):
    """Logs an API response event."""
    if not _is_initialized or not _transport:
        return
    _transport.log_event(event)
    _log_to_observable(event)
    record_api_response_metrics(
        config=_config,
        model=event.model,
        duration_ms=event.duration_ms,
        status_code=event.status_code,
        error=event.error,
    )
    if not event.error:
        record_token_usage_metrics(
            _config, event.model, event.input_token_count, "input"
        )
        record_token_usage_metrics(
            _config, event.model, event.output_token_count, "output"
        )
        record_token_usage_metrics(
            _config, event.model, event.cached_content_token_count, "cache"
        )
        record_token_usage_metrics(
            _config, event.model, event.thoughts_token_count, "thought"
        )
        record_token_usage_metrics(
            _config, event.model, event.tool_token_count, "tool"
        )
