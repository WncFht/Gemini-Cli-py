import logging
from pathlib import Path
from uuid import uuid4

from .paths import GEMINI_DIR

logger = logging.getLogger(__name__)

SESSION_ID = str(uuid4())

_gemini_dir = Path.home() / GEMINI_DIR
_installation_id_file = _gemini_dir / "installation_id"


def _ensure_gemini_dir_exists():
    """Ensures the .gemini directory exists in the user's home directory."""
    _gemini_dir.mkdir(parents=True, exist_ok=True)


def _read_installation_id() -> str | None:
    """Reads the installation ID from the file."""
    if _installation_id_file.exists():
        return _installation_id_file.read_text("utf-8").strip()
    return None


def _write_installation_id(installation_id: str):
    """Writes the installation ID to the file."""
    _installation_id_file.write_text(installation_id, "utf-8")


def get_installation_id() -> str:
    """
    Retrieves the installation ID from a file, creating it if it doesn't exist.
    """
    try:
        _ensure_gemini_dir_exists()
        installation_id = _read_installation_id()
        if not installation_id:
            installation_id = str(uuid4())
            _write_installation_id(installation_id)
        return installation_id
    except Exception as e:
        logger.error(
            f"Error accessing installation ID file, generating ephemeral ID: {e}"
        )
        return "ephemeral-installation-id"


def get_obfuscated_google_account_id() -> str:
    """
    Retrieves the obfuscated Google Account ID for the currently authenticated user.
    Placeholder for when OAuth is available.
    """
    # TODO: Implement when OAuth is available.
    return ""
