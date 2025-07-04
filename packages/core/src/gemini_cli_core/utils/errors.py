import json
import logging
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger(__name__)


def get_error_message(error: Any) -> str:
    """Safely gets an error message from an exception."""
    if isinstance(error, Exception):
        return str(error)
    try:
        return str(error)
    except Exception:
        return "Failed to get error details"


class ForbiddenError(Exception):
    pass


class UnauthorizedError(Exception):
    pass


class BadRequestError(Exception):
    pass


def to_friendly_error(error: Any) -> Exception:
    """Converts HTTP errors to more specific, friendly exception types."""
    if isinstance(error, httpx.HTTPStatusError):
        response = error.response
        if response.status_code == 400:
            return BadRequestError(response.text)
        if response.status_code == 401:
            return UnauthorizedError(response.text)
        if response.status_code == 403:
            return ForbiddenError(response.text)
    if isinstance(error, Exception):
        return error
    return Exception(get_error_message(error))


async def report_error(
    error: Any,
    base_message: str,
    context: Any | None = None,
    error_type: str = "general",
):
    """Generates an error report and writes it to a temporary file."""
    timestamp = datetime.now().isoformat().replace(":", "-").replace(".", "-")
    report_file_name = f"gemini-client-error-{error_type}-{timestamp}.json"
    report_path = Path(tempfile.gettempdir()) / report_file_name

    error_to_report = {}
    if isinstance(error, Exception):
        error_to_report["message"] = str(error)
        error_to_report["stack"] = "".join(
            __import__("traceback").format_exception(
                type(error), error, error.__traceback__
            )
        )
    else:
        error_to_report["message"] = get_error_message(error)

    report_content = {"error": error_to_report}
    if context:
        report_content["context"] = context

    try:
        report_str = json.dumps(report_content, indent=2, default=str)
        with report_path.open("w", encoding="utf-8") as f:
            f.write(report_str)
        logger.error(f"{base_message} Full report available at: {report_path}")
    except Exception as e:
        logger.error(f"{base_message} Failed to write error report: {e}")
        logger.error(f"Original error: {error_to_report['message']}")
