"""
内容生成器基类定义 - 从 contentGenerator.ts 迁移
定义了生成内容、流式生成、计算 token 和生成嵌入向量的核心接口
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel


class AuthType(str, Enum):
    """认证类型枚举"""

    LOGIN_WITH_GOOGLE_PERSONAL = (
        "oauth-personal"  # 通过个人的 Google 账号 OAuth 登录
    )
    USE_GEMINI = "gemini-api-key"  # 使用 Gemini API 密钥
    USE_VERTEX_AI = "vertex-ai"  # 使用 Vertex AI


class ContentGeneratorConfig(TypedDict, total=False):
    """内容生成器配置"""

    model: str
    api_key: str | None
    vertexai: bool | None
    auth_type: AuthType | None


class GenerateContentRequest(BaseModel):
    """生成内容请求参数"""

    model: str
    config: dict[str, Any]
    contents: list[dict[str, Any]]


class GenerateContentResponse(BaseModel):
    """生成内容响应"""

    candidates: list[dict[str, Any]]
    usage_metadata: dict[str, Any] | None = None
    prompt_feedback: dict[str, Any] | None = None


class CountTokensRequest(BaseModel):
    """计算 token 请求参数"""

    model: str
    contents: list[dict[str, Any]]


class CountTokensResponse(BaseModel):
    """计算 token 响应"""

    total_tokens: int
    total_billable_characters: int | None = None
    cached_content_token_count: int | None = None


class EmbedContentRequest(BaseModel):
    """生成嵌入向量请求参数"""

    model: str
    contents: list[str]
    task_type: str | None = None
    title: str | None = None


class EmbedContentResponse(BaseModel):
    """生成嵌入向量响应"""

    embeddings: list[list[float]]


class ContentGenerator(ABC):
    """
    内容生成器接口 (ContentGenerator)
    抽象了生成内容、流式生成内容、计算 token 和生成嵌入向量的核心功能
    这是一个适配器接口，允许系统以统一的方式与不同后端的 AI 服务交互
    （例如，标准的 Gemini API、Vertex AI，或通过 Code Assist 的特殊代理）
    """

    @abstractmethod
    async def generate_content(
        self,
        model: str,
        config: dict[str, Any],
        contents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        生成内容

        Args:
            model: 使用的模型名称
            config: 生成配置
            contents: 内容列表

        Returns:
            生成的响应字典

        """

    @abstractmethod
    async def generate_content_stream(
        self,
        model: str,
        config: dict[str, Any],
        contents: list[dict[str, Any]],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        以流式方式生成内容

        Args:
            model: 使用的模型名称
            config: 生成配置
            contents: 内容列表

        Yields:
            生成的响应片段

        """

    @abstractmethod
    async def count_tokens(
        self,
        model: str,
        contents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        计算内容的 token 数量

        Args:
            model: 使用的模型名称
            contents: 内容列表

        Returns:
            token 计数响应

        """

    @abstractmethod
    async def embed_content(
        self,
        model: str,
        contents: list[str],
        task_type: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """
        为内容生成嵌入向量

        Args:
            model: 使用的嵌入模型名称
            contents: 文本内容列表
            task_type: 任务类型（可选）
            title: 标题（可选）

        Returns:
            嵌入向量响应

        """


def part_list_union_to_string(value: Any) -> str:
    """
    Converts a PartListUnion to a string for logging/debugging.
    Refactored from packages/core_ts/src/core/geminiRequest.ts
    """
    if isinstance(value, str):
        return value

    if isinstance(value, list):
        return "".join(part_list_union_to_string(part) for part in value)

    if isinstance(value, dict):
        part = value
        if "videoMetadata" in part:
            return "[Video Metadata]"
        if "thought" in part:
            return f"[Thought: {part['thought']}]"
        if "codeExecutionResult" in part:
            return "[Code Execution Result]"
        if "executableCode" in part:
            return "[Executable Code]"
        if "fileData" in part:
            return "[File Data]"
        if "functionCall" in part:
            return f"[Function Call: {part['functionCall'].get('name', '')}]"
        if "functionResponse" in part:
            return f"[Function Response: {part['functionResponse'].get('name', '')}]"
        if "inlineData" in part:
            return f"<{part['inlineData'].get('mimeType', '')}>"
        if "text" in part:
            return part["text"]

    return ""
