"""
This file is refactored from packages/core_ts/src/code_assist/oauth2.ts.
It handles the OAuth2 authentication flow for the user.
"""

import asyncio
from pathlib import Path

import httpx
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Constants from the TypeScript file
OAUTH_CLIENT_ID = (
    "681255809395-oo8ft2oprdrnp9e3aqf6av3hmdib135j.apps.googleusercontent.com"
)
OAUTH_CLIENT_SECRET = "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"
OAUTH_SCOPE = [
    "https://www.googleapis.com/auth/cloud-platform",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

GEMINI_DIR = Path.home() / ".gemini"
CREDENTIAL_FILENAME = "oauth_creds.json"


def _get_cached_credential_path() -> Path:
    return GEMINI_DIR / CREDENTIAL_FILENAME


def _load_cached_credentials() -> Credentials | None:
    """Loads cached credentials if they exist and are valid."""
    cred_path = _get_cached_credential_path()
    if not cred_path.exists():
        return None
    try:
        creds = Credentials.from_authorized_user_file(
            str(cred_path), OAUTH_SCOPE
        )
        if creds.valid and creds.refresh_token:
            # Refresh the token to ensure it's still active
            creds.refresh(Request())
            return creds
        if not creds.valid and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _cache_credentials(creds)
            return creds
    except Exception:
        # If any error during loading or refreshing, treat as no valid creds
        return None
    return None


def _cache_credentials(credentials: Credentials):
    """Caches the credentials to a local file."""
    GEMINI_DIR.mkdir(exist_ok=True)
    cred_path = _get_cached_credential_path()
    # The `to_json` method of Credentials object gives us the right format
    with open(cred_path, "w") as token:
        token.write(credentials.to_json())


async def get_oauth_credentials() -> Credentials:
    """
    The main function to get OAuth2 credentials.
    It tries to load from cache first, otherwise initiates the web flow.
    """
    creds = _load_cached_credentials()
    if creds:
        return creds

    # Create a flow with the client secrets
    client_config = {
        "installed": {
            "client_id": OAUTH_CLIENT_ID,
            "client_secret": OAUTH_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    # The InstalledAppFlow will handle starting a local server
    flow = InstalledAppFlow.from_client_config(
        client_config,
        scopes=OAUTH_SCOPE,
        redirect_uri="http://localhost",
    )

    # This will automatically open the browser and block until auth is complete.
    # It runs a local server on a random available port.
    # To make this async, we run it in a thread pool executor.
    loop = asyncio.get_running_loop()
    creds = await loop.run_in_executor(
        None, lambda: flow.run_local_server(port=0)
    )

    _cache_credentials(creds)
    return creds


async def get_google_account_id(credentials: Credentials) -> str | None:
    """Retrieves the authenticated user's Google Account ID."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://www.googleapis.com/oauth2/v2/userinfo",
                headers={"Authorization": f"Bearer {credentials.token}"},
            )
            response.raise_for_status()
            user_info = response.json()
            return user_info.get("id")
    except Exception:
        return None


async def clear_cached_credentials():
    """Removes the cached credential file."""
    cred_path = _get_cached_credential_path()
    if cred_path.exists():
        cred_path.unlink()
