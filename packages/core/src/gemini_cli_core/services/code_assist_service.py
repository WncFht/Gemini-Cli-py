"""
This file is refactored from packages/core_ts/src/code_assist/codeAssist.ts.
It provides the core service for interacting with the Code Assist API.
"""

import asyncio
from typing import Any

import httpx

from gemini_cli_core.services.auth_service import (
    get_oauth_credentials,
)
from gemini_cli_core.utils.response_utils import (
    from_count_token_response,
    from_generate_content_response,
    to_count_token_request,
    to_generate_content_request,
)

# The endpoint for the Code Assist API. This might need to be configurable.
CODE_ASSIST_API_ENDPOINT = (
    "https://autopush-generativelanguage.sandbox.googleapis.com"
)


class CodeAssistService:
    """
    A service to interact with the backend for code assistance features.
    It handles authentication and API request/response conversion.
    """

    def __init__(self, project_id: str | None = None):
        self._project_id = project_id
        self._credentials = None
        self._headers = {}

    async def _ensure_authenticated(self):
        """Ensures that the service has valid OAuth2 credentials."""
        if not self._credentials or not self._credentials.valid:
            self._credentials = await get_oauth_credentials()

        token = self._credentials.token
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def generate_content(self, params: Any) -> dict:
        """
        Sends a generateContent request to the Code Assist API.

        Args:
            params: The standard GenerateContentParameters object.

        Returns:
            The standard GenerateContentResponse object.

        """
        await self._ensure_authenticated()

        # Convert the standard request to the Code Assist-specific format
        ca_request = to_generate_content_request(
            params, project=self._project_id
        )

        model_path = f"projects/{self._project_id}/locations/global/models/{params.model}"
        url = f"{CODE_ASSIST_API_ENDPOINT}/v1beta/{model_path}:generateContent"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, json=ca_request.model_dump(), headers=self._headers
            )
            response.raise_for_status()
            ca_response = response.json()

        # Convert the response back to the standard format
        return from_generate_content_response(ca_response)

    async def count_tokens(self, params: Any) -> dict:
        """
        Sends a countTokens request to the Code Assist API.

        Args:
            params: The standard CountTokensParameters object.

        Returns:
            The standard CountTokensResponse object.

        """
        await self._ensure_authenticated()

        ca_request = to_count_token_request(params)

        model_path = f"projects/{self._project_id}/locations/global/models/{params.model}"
        url = f"{CODE_ASSIST_API_ENDPOINT}/v1beta/{model_path}:countTokens"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url, json=ca_request.model_dump(), headers=self._headers
            )
            response.raise_for_status()
            ca_response = response.json()

        return from_count_token_response(ca_response)

    async def load_code_assist(self, request: dict) -> dict:
        """Calls the loadCodeAssist endpoint."""
        await self._ensure_authenticated()
        url = f"{CODE_ASSIST_API_ENDPOINT}/v1internal/cloudcode:loadCodeAssist"
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url=url, json=request, headers=self._headers
            )
            response.raise_for_status()
            return response.json()

    async def onboard_user(self, request: dict) -> dict:
        """
        Calls the onboardUser endpoint and handles the long-running operation.
        """
        await self._ensure_authenticated()
        onboard_url = (
            f"{CODE_ASSIST_API_ENDPOINT}/v1internal/cloudcode:onboardUser"
        )

        lro_res = {}
        async with httpx.AsyncClient(timeout=30.0) as client:
            # This implements the polling logic from setup.ts
            while not lro_res.get("done"):
                onboard_res_raw = await client.post(
                    url=onboard_url, json=request, headers=self._headers
                )
                onboard_res_raw.raise_for_status()
                lro_res = onboard_res_raw.json()
                if not lro_res.get("done"):
                    await asyncio.sleep(5)
        return lro_res

    async def setup_user(self, client_metadata: dict) -> str:
        """
        Performs the user onboarding flow.
        This is a port of the logic from `setup.ts`.
        """
        # This now uses the more granular methods
        load_assist_req = {
            "cloudaicompanionProject": self._project_id,
            "metadata": client_metadata,
        }
        load_res = await self.load_code_assist(load_assist_req)

        if not self._project_id and load_res.get("cloudaicompanionProject"):
            self._project_id = load_res.get("cloudaicompanionProject")

        onboard_tier = self._get_onboard_tier(load_res)
        if (
            onboard_tier.get("userDefinedCloudaicompanionProject")
            and not self._project_id
        ):
            raise ValueError(
                "This account requires setting the GOOGLE_CLOUD_PROJECT env var."
            )

        onboard_req = {
            "tierId": onboard_tier.get("id"),
            "cloudaicompanionProject": self._project_id,
            "metadata": client_metadata,
        }
        lro_res = await self.onboard_user(onboard_req)

        return (
            lro_res.get("response", {})
            .get("cloudaicompanionProject", {})
            .get("id", "")
        )

    def _get_onboard_tier(self, load_res: dict) -> dict:
        """Determines the correct user tier for onboarding."""
        if load_res.get("currentTier"):
            return load_res["currentTier"]

        for tier in load_res.get("allowedTiers", []):
            if tier.get("isDefault"):
                return tier

        # Fallback based on TS logic
        return {
            "id": "legacy-tier",
            "userDefinedCloudaicompanionProject": True,
        }
