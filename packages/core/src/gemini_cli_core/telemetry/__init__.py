# Export the main SDK functions
# Export all event types
from .events import (
    ApiErrorEvent,
    ApiRequestEvent,
    ApiResponseEvent,
    EndSessionEvent,
    StartSessionEvent,
    TelemetryEvent,
    ToolCallDecision,
    ToolCallEvent,
    UserPromptEvent,
)

# Export all logger functions
from .logger import (
    log_api_error,
    log_api_request,
    log_api_response,
    log_cli_configuration,
    log_tool_call,
    log_user_prompt,
)
from .sdk import (
    initialize_telemetry_sdk,
    is_telemetry_sdk_initialized,
    shutdown_telemetry_sdk,
)

__all__ = [
    # SDK
    "initialize_telemetry_sdk",
    "is_telemetry_sdk_initialized",
    "shutdown_telemetry_sdk",
    # Loggers
    "log_api_error",
    "log_api_request",
    "log_api_response",
    "log_cli_configuration",
    "log_tool_call",
    "log_user_prompt",
    # Events
    "ApiErrorEvent",
    "ApiRequestEvent",
    "ApiResponseEvent",
    "EndSessionEvent",
    "StartSessionEvent",
    "TelemetryEvent",
    "ToolCallDecision",
    "ToolCallEvent",
    "UserPromptEvent",
]
