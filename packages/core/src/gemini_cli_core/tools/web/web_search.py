from typing import Any

from pydantic import BaseModel, Field

from gemini_cli_core.core.config import Config
from gemini_cli_core.tools import BaseTool, ToolResult


class WebSearchToolParams(BaseModel):
    query: str = Field(..., description="The search query.")


class GroundingChunkWeb(BaseModel):
    uri: str | None = None
    title: str | None = None


class GroundingChunkItem(BaseModel):
    web: GroundingChunkWeb | None = None


class GroundingSupportSegment(BaseModel):
    startIndex: int
    endIndex: int


class GroundingSupportItem(BaseModel):
    segment: GroundingSupportSegment | None = None
    groundingChunkIndices: list[int] | None = None


class WebSearchTool(BaseTool[WebSearchToolParams, ToolResult]):
    """A tool for performing web searches via Google Search."""

    NAME = "google_web_search"

    def __init__(self, config: Config):
        super().__init__(
            name=self.NAME,
            display_name="GoogleSearch",
            description="Performs a web search using Google Search.",
            parameter_schema=WebSearchToolParams.model_json_schema(),
        )
        self.config = config
        self.client = config.get_gemini_client()

    async def execute(
        self, params: WebSearchToolParams, signal: Any | None = None
    ) -> ToolResult:
        try:
            result = await self.client.generate_content(
                contents=[{"role": "user", "parts": [{"text": params.query}]}],
                generation_config={"tools": [{"google_search": {}}]},
                abort_signal=signal,
            )

            response_text = self.client._get_response_text(result)
            if not response_text or not response_text.strip():
                return ToolResult(
                    llm_content=f"No search results found for: '{params.query}'",
                    return_display="No results found.",
                )

            # Process grounding metadata
            grounding_metadata = result.get("candidates", [{}])[0].get(
                "grounding_metadata", {}
            )
            sources_raw = grounding_metadata.get("grounding_chunks", [])
            supports_raw = grounding_metadata.get("grounding_supports", [])

            sources = [
                GroundingChunkItem.model_validate(s) for s in sources_raw
            ]
            supports = [
                GroundingSupportItem.model_validate(s) for s in supports_raw
            ]

            source_list_formatted: list[str] = []
            if sources:
                for i, source in enumerate(sources):
                    title = source.web.title or "Untitled"
                    uri = source.web.uri or "Unknown URI"
                    source_list_formatted.append(f"[{i + 1}] {title} ({uri})")

            if supports:
                insertions = []
                for support in supports:
                    if support.segment and support.grounding_chunk_indices:
                        marker = "".join(
                            f"[{i + 1}]"
                            for i in support.grounding_chunk_indices
                        )
                        insertions.append(
                            {
                                "index": support.segment.endIndex,
                                "marker": marker,
                            }
                        )

                insertions.sort(key=lambda x: x["index"], reverse=True)
                response_chars = list(response_text)
                for insertion in insertions:
                    response_chars.insert(
                        insertion["index"], insertion["marker"]
                    )
                response_text = "".join(response_chars)

            if source_list_formatted:
                response_text += "\n\nSources:\n" + "\n".join(
                    source_list_formatted
                )

            return ToolResult(
                llm_content=response_text,
                return_display=f"Search results for '{params.query}' returned.",
            )

        except Exception as e:
            return ToolResult(
                llm_content=f"Error during web search: {e}",
                return_display="Error during search.",
            )
