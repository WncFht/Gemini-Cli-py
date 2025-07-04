from typing import Any

from gemini_cli_core.core.generators.base import ContentGenerator
from gemini_cli_core.services.code_assist_service import CodeAssistService


class CodeAssistContentGenerator(ContentGenerator):
    """
    A ContentGenerator that proxies requests to the CodeAssistService.
    """

    def __init__(self, project_id: str | None = None):
        self._service = CodeAssistService(project_id=project_id)

    async def count_tokens(
        self, model: str, contents: list[dict], **kwargs
    ) -> dict[str, Any]:
        """Counts tokens using the CodeAssist service."""
        params = {"model": model, "contents": contents}
        return await self._service.count_tokens(params)

    async def generate_content(
        self, model: str, contents: list[dict], config: dict | None, **kwargs
    ) -> dict[str, Any]:
        """Generates content using the CodeAssist service."""
        params = {
            "model": model,
            "contents": contents,
            "config": config,
        }
        return await self._service.generate_content(params)

    async def embed_content(
        self, model: str, contents: list[dict], **kwargs
    ) -> dict[str, Any]:
        """Embedding is not supported by CodeAssistService."""
        raise NotImplementedError(
            "embed_content is not supported by CodeAssist."
        )
