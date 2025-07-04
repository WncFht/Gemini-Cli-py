"""
This file is refactored from packages/core_ts/src/telemetry/metrics.ts.
It provides functions to record various metrics using OpenTelemetry.
"""

from enum import Enum
from typing import Any

# Check for OpenTelemetry packages, but don't fail if they are not installed.
try:
    from opentelemetry import metrics
    from opentelemetry.metrics import Counter, Histogram, Meter

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

from gemini_cli_core.telemetry.constants import (
    METRIC_API_REQUEST_COUNT,
    METRIC_API_REQUEST_LATENCY,
    METRIC_FILE_OPERATION_COUNT,
    METRIC_SESSION_COUNT,
    METRIC_TOKEN_USAGE,
    METRIC_TOOL_CALL_COUNT,
    METRIC_TOOL_CALL_LATENCY,
    SERVICE_NAME,
)


class FileOperation(str, Enum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"


class MetricsManager:
    """A singleton to manage OpenTelemetry metric instruments."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(MetricsManager, cls).__new__(cls)
            cls._instance.is_initialized = False
            if OTEL_AVAILABLE:
                cls._instance.meter: Meter = metrics.get_meter(SERVICE_NAME)
                cls._instance.tool_call_counter: Counter | None = None
                cls._instance.tool_call_latency_histogram: Histogram | None = (
                    None
                )
                cls._instance.api_request_counter: Counter | None = None
                cls._instance.api_request_latency_histogram: (
                    Histogram | None
                ) = None
                cls._instance.token_usage_counter: Counter | None = None
                cls._instance.file_operation_counter: Counter | None = None
        return cls._instance


def _get_common_attributes(config: Any) -> dict[str, Any]:
    # Placeholder for getting session id from config
    return {"session.id": config.get_session_id()}


def initialize_metrics(config: Any):
    """Initializes all the metric instruments."""
    if not OTEL_AVAILABLE:
        return

    manager = MetricsManager()
    if manager.is_initialized:
        return

    manager.tool_call_counter = manager.meter.create_counter(
        METRIC_TOOL_CALL_COUNT
    )
    manager.tool_call_latency_histogram = manager.meter.create_histogram(
        METRIC_TOOL_CALL_LATENCY, unit="ms"
    )
    manager.api_request_counter = manager.meter.create_counter(
        METRIC_API_REQUEST_COUNT
    )
    manager.api_request_latency_histogram = manager.meter.create_histogram(
        METRIC_API_REQUEST_LATENCY, unit="ms"
    )
    manager.token_usage_counter = manager.meter.create_counter(
        METRIC_TOKEN_USAGE
    )
    manager.file_operation_counter = manager.meter.create_counter(
        METRIC_FILE_OPERATION_COUNT
    )

    session_counter = manager.meter.create_counter(METRIC_SESSION_COUNT)
    session_counter.add(1, _get_common_attributes(config))

    manager.is_initialized = True


def record_tool_call_metrics(
    config: Any,
    function_name: str,
    duration_ms: int,
    success: bool,
    decision: str | None = None,
):
    manager = MetricsManager()
    if (
        not manager.is_initialized
        or not manager.tool_call_counter
        or not manager.tool_call_latency_histogram
    ):
        return

    attributes = {
        **_get_common_attributes(config),
        "function_name": function_name,
        "success": success,
        "decision": decision,
    }
    manager.tool_call_counter.add(1, attributes)
    manager.tool_call_latency_histogram.record(duration_ms, attributes)


def record_token_usage_metrics(
    config: Any, model: str, token_count: int, token_type: str
):
    manager = MetricsManager()
    if not manager.is_initialized or not manager.token_usage_counter:
        return

    attributes = {
        **_get_common_attributes(config),
        "model": model,
        "type": token_type,
    }
    manager.token_usage_counter.add(token_count, attributes)


def record_api_response_metrics(
    config: Any,
    model: str,
    duration_ms: int,
    status_code: int | str | None,
    error: str | None,
):
    manager = MetricsManager()
    if (
        not manager.is_initialized
        or not manager.api_request_counter
        or not manager.api_request_latency_histogram
    ):
        return

    attributes = {
        **_get_common_attributes(config),
        "model": model,
        "status_code": status_code or ("error" if error else "ok"),
    }
    manager.api_request_counter.add(1, attributes)
    manager.api_request_latency_histogram.record(duration_ms, attributes)


def record_api_error_metrics(
    config: Any,
    model: str,
    duration_ms: int,
    status_code: int | str | None,
    error_type: str | None,
):
    manager = MetricsManager()
    if (
        not manager.is_initialized
        or not manager.api_request_counter
        or not manager.api_request_latency_histogram
    ):
        return

    attributes = {
        **_get_common_attributes(config),
        "model": model,
        "status_code": status_code or "error",
        "error_type": error_type or "unknown",
    }
    manager.api_request_counter.add(1, attributes)
    manager.api_request_latency_histogram.record(duration_ms, attributes)


def record_file_operation_metric(
    config: Any,
    operation: FileOperation,
    lines: int | None = None,
    mimetype: str | None = None,
    extension: str | None = None,
):
    manager = MetricsManager()
    if not manager.is_initialized or not manager.file_operation_counter:
        return

    attributes = {**_get_common_attributes(config), "operation": operation}
    if lines is not None:
        attributes["lines"] = lines
    if mimetype is not None:
        attributes["mimetype"] = mimetype
    if extension is not None:
        attributes["extension"] = extension
    manager.file_operation_counter.add(1, attributes)
