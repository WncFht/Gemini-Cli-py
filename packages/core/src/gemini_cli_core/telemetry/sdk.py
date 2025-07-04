"""
This file is refactored from packages/core_ts/src/telemetry/sdk.ts.
It provides the main entry point for initializing the telemetry system.
"""

import atexit
import json
import logging
import sys
from typing import Any

from gemini_cli_core.telemetry import logger as telemetry_logger
from gemini_cli_core.telemetry import metrics as telemetry_metrics
from gemini_cli_core.telemetry.transport import ClearcutTransport

_is_initialized = False
_transport_instance: ClearcutTransport | None = None

# OpenTelemetry is optional
try:
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
    )
    from opentelemetry.semconv.resource import ResourceAttributes

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False


class JsonFormatter(logging.Formatter):
    """Formats log records as JSON."""

    def format(self, record):
        log_object = {
            "timestamp": self.formatTime(record, self.datefmt),
            "name": record.name,
            "level": record.levelname,
            "message": record.getMessage(),
        }
        if hasattr(record, "data"):
            log_object["data"] = record.data
        return json.dumps(log_object)


def _setup_observable_logger():
    """Configures the observable logger to output JSON to stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter())
    telemetry_logger.observable_logger.addHandler(handler)
    telemetry_logger.observable_logger.setLevel(logging.INFO)


def initialize_telemetry_sdk(config: Any):
    """
    Initializes the entire telemetry SDK, including logging and metrics.
    """
    global _is_initialized, _transport_instance
    if _is_initialized or not config.get_telemetry_enabled():
        return

    # 1. Initialize our custom Clearcut transport
    _transport_instance = ClearcutTransport(debug_mode=config.get_debug_mode())

    # 2. Initialize our logging system with the transport and config
    telemetry_logger.init_telemetry(config, _transport_instance)

    # 3. Configure the observable logger
    _setup_observable_logger()

    # 4. Initialize OpenTelemetry if available
    if OTEL_AVAILABLE:
        resource = Resource(
            attributes={
                ResourceAttributes.SERVICE_NAME: "gemini-cli",
                "session.id": config.get_session_id(),
            }
        )
        provider = TracerProvider(resource=resource)
        # For now, we only export to console, mirroring the default TS behavior
        processor = BatchSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)

    # 5. Initialize our metrics system
    telemetry_metrics.initialize_metrics(config)

    # 6. Register shutdown hook
    atexit.register(shutdown_telemetry_sdk)

    _is_initialized = True
    logging.info("Telemetry SDK initialized.")


def shutdown_telemetry_sdk():
    """Shuts down the telemetry SDK gracefully."""
    global _is_initialized, _transport_instance
    if not _is_initialized or not _transport_instance:
        return

    # Create a new event loop to run async shutdown in atexit context
    import asyncio

    async def do_shutdown():
        if _transport_instance:
            await _transport_instance.shutdown()
        # OTel shutdown can be added here if more components are used.

    try:
        asyncio.run(do_shutdown())
        logging.info("Telemetry SDK shut down gracefully.")
    except Exception as e:
        logging.exception(f"Error shutting down telemetry SDK: {e}")
    finally:
        _is_initialized = False


def is_telemetry_sdk_initialized() -> bool:
    """Returns true if the telemetry SDK has been initialized."""
    return _is_initialized
