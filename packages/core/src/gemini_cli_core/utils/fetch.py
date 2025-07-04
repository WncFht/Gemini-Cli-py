import re
from typing import Final
from urllib.parse import urlparse

import httpx

# Compiled regexes for private IP ranges.
PRIVATE_IP_RANGES: Final[list[re.Pattern[str]]] = [
    re.compile(r"^10\."),
    re.compile(r"^127\."),
    re.compile(r"^172\.(1[6-9]|2[0-9]|3[0-1])\."),
    re.compile(r"^192\.168\."),
    re.compile(r"^::1$"),
    re.compile(r"^fc00:"),
    re.compile(r"^fe80:"),
]


class FetchError(Exception):
    """Custom exception for fetch-related errors."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message)
        self.code = code


def is_private_ip(url: str) -> bool:
    """
    Checks if a URL resolves to a private or local IP address.
    """
    try:
        hostname = urlparse(url).hostname
        if not hostname:
            return False
        # Handle localhost explicitly, as it may not be covered by IP ranges.
        if hostname == "localhost":
            return True
        return any(r.search(hostname) for r in PRIVATE_IP_RANGES)
    except Exception:
        # If URL parsing fails, treat it as not a private IP.
        return False


async def fetch_with_timeout(url: str, timeout: float) -> httpx.Response:
    """
    Fetches a URL with a specified timeout, raising a custom FetchError on failure.

    Args:
        url: The URL to fetch.
        timeout: The timeout in seconds.

    Returns:
        The httpx.Response object.

    Raises:
        FetchError: If the request times out or another request error occurs.

    """
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=timeout)
            response.raise_for_status()
            return response
    except httpx.TimeoutException:
        raise FetchError(
            f"Request timed out after {timeout}s", "ETIMEDOUT"
        ) from None
    except httpx.RequestError as e:
        # Encapsulate generic httpx errors into our custom FetchError.
        raise FetchError(f"Request failed: {e}") from e
