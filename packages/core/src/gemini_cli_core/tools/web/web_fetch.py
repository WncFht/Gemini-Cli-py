"""
This file is refactored from packages/core_ts/src/tools/web-fetch.ts.
"""

import re
from typing import Any

import html2text
import httpx
from pydantic import BaseModel, Field

from gemini_cli_core.core.config import Config
from gemini_cli_core.tools.base.tool_base import BaseTool, ToolResult
from gemini_cli_core.utils.fetch import is_private_ip


class WebFetchToolParams(BaseModel):
    prompt: str = Field(
        ...,
        description="A prompt containing URL(s) and instructions for processing them.",
    )


def extract_urls(text: str) -> list[str]:
    """Extracts URLs from a string."""
    return re.findall(r"(https?://[^\s]+)", text)


class WebFetchTool(BaseTool[WebFetchToolParams, ToolResult]):
    """A tool for fetching and processing content from URLs."""

    NAME = "web_fetch"

    def __init__(self, config: Config):
        super().__init__(
            name=self.NAME,
            display_name="WebFetch",
            description="Processes content from URL(s) embedded in a prompt.",
            parameter_schema=WebFetchToolParams.model_json_schema(),
        )
        self.config = config
        self.client = config.get_gemini_client()

    async def _fallback_fetch(
        self, params: WebFetchToolParams, signal: Any | None = None
    ) -> ToolResult:
        urls = extract_urls(params.prompt)
        if not urls:
            return ToolResult(
                llm_content="Error: No URL found.",
                return_display="Error: No URL found.",
            )

        url = urls[0]
        if "github.com" in url and "/blob/" in url:
            url = url.replace(
                "github.com", "raw.githubusercontent.com"
            ).replace("/blob/", "/")

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                response.raise_for_status()

            h = html2text.HTML2Text()
            h.ignore_links = True
            h.ignore_images = True
            text_content = h.handle(response.text)[:100000]

            fallback_prompt = f"The user requested: '{params.prompt}'. I fetched the content. Please answer based on this:\n\n{text_content}"

            result = await self.client.generate_content(
                contents=[
                    {"role": "user", "parts": [{"text": fallback_prompt}]}
                ],
                generation_config={},
                abort_signal=signal,
            )
            return ToolResult(
                llm_content=self.client._get_response_text(result),
                return_display=f"Content for {url} processed via fallback.",
            )
        except httpx.HTTPError as e:
            return ToolResult(
                llm_content=f"Error: {e}", return_display=f"Error: {e}"
            )

    async def execute(
        self, params: WebFetchToolParams, signal: Any | None = None
    ) -> ToolResult:
        urls = extract_urls(params.prompt)
        if not urls:
            return ToolResult(
                llm_content="Error: No URL found.",
                return_display="Error: No URL found.",
            )

        # If any URL is private, use the fallback mechanism for all.
        if any(is_private_ip(url) for url in urls):
            return await self._fallback_fetch(params, signal)

        try:
            # Attempt to use the Gemini API's built-in URL context feature
            result = await self.client.generate_content(
                contents=[{"role": "user", "parts": [{"text": params.prompt}]}],
                generation_config={"tools": [{"url_context": {}}]},
                abort_signal=signal,
            )

            response_text = self.client._get_response_text(result)
            if not response_text or not response_text.strip():
                return await self._fallback_fetch(params, signal)

            # TODO: Add grounding metadata processing similar to web-search
            return ToolResult(
                llm_content=response_text,
                return_display="Content processed from prompt.",
            )
        except Exception:
            return await self._fallback_fetch(params, signal)
