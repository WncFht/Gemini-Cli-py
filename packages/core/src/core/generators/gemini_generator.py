"""
Gemini 内容生成器实现 - 从 contentGenerator.ts 迁移
提供与 Gemini API 交互的具体实现
"""

import os
import platform
from collections.abc import AsyncGenerator
from typing import Any

from google import generativeai as genai

from ..config import DEFAULT_GEMINI_MODEL
from ..types import GeminiError
from ..utils.model_check import get_effective_model
from .base import AuthType, ContentGenerator, ContentGeneratorConfig


class GeminiContentGenerator(ContentGenerator):
    """
    Gemini API 内容生成器实现
    使用 Google Generative AI SDK 与 Gemini API 交互
    """

    def __init__(
        self, client: genai.GenerativeModel, config: ContentGeneratorConfig
    ):
        self.client = client
        self.config = config

    async def generate_content(
        self,
        model: str,
        config: dict[str, Any],
        contents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """生成内容"""
        try:
            # 创建模型实例
            model_instance = genai.GenerativeModel(
                model_name=model,
                generation_config=config.get("generation_config", {}),
                system_instruction=config.get("system_instruction"),
                tools=config.get("tools"),
            )

            # 调用 API
            response = await model_instance.generate_content_async(
                contents,
                request_options={
                    "timeout": config.get("timeout", 600),
                },
            )

            # 转换响应格式
            return self._convert_response(response)

        except Exception as e:
            raise GeminiError(f"生成内容失败: {e!s}", "generation_error")

    async def generate_content_stream(
        self,
        model: str,
        config: dict[str, Any],
        contents: list[dict[str, Any]],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """以流式方式生成内容"""
        try:
            # 创建模型实例
            model_instance = genai.GenerativeModel(
                model_name=model,
                generation_config=config.get("generation_config", {}),
                system_instruction=config.get("system_instruction"),
                tools=config.get("tools"),
            )

            # 调用流式 API
            response_stream = await model_instance.generate_content_async(
                contents,
                stream=True,
                request_options={
                    "timeout": config.get("timeout", 600),
                },
            )

            # 流式返回响应
            async for chunk in response_stream:
                yield self._convert_response(chunk)

        except Exception as e:
            raise GeminiError(f"流式生成内容失败: {e!s}", "generation_error")

    async def count_tokens(
        self,
        model: str,
        contents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """计算内容的 token 数量"""
        try:
            model_instance = genai.GenerativeModel(model_name=model)
            response = await model_instance.count_tokens_async(contents)

            return {
                "total_tokens": response.total_tokens,
                "total_billable_characters": getattr(
                    response, "total_billable_characters", None
                ),
                "cached_content_token_count": getattr(
                    response, "cached_content_token_count", None
                ),
            }

        except Exception as e:
            raise GeminiError(f"计算 token 失败: {e!s}", "token_count_error")

    async def embed_content(
        self,
        model: str,
        contents: list[str],
        task_type: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """为内容生成嵌入向量"""
        try:
            requests = [
                genai.types.EmbedContentRequest(
                    content=text, model=model, task_type=task_type, title=title
                )
                for text in contents
            ]
            batch_response = await genai.batch_embed_contents_async(requests)
            return {"embeddings": [e.values for e in batch_response.embeddings]}

        except Exception as e:
            raise GeminiError(f"生成嵌入向量失败: {e!s}", "embedding_error")

    def _convert_response(self, response: Any) -> dict[str, Any]:
        """将 SDK 响应转换为统一格式"""
        # 提取候选内容
        candidates = []
        for candidate in response.candidates:
            parts = []
            for part in candidate.content.parts:
                part_dict = {}

                if hasattr(part, "text"):
                    part_dict["text"] = part.text
                if hasattr(part, "function_call"):
                    part_dict["function_call"] = {
                        "name": part.function_call.name,
                        "args": dict(part.function_call.args),
                    }
                if hasattr(part, "function_response"):
                    part_dict["function_response"] = {
                        "name": part.function_response.name,
                        "response": part.function_response.response,
                    }
                if hasattr(part, "thought") and part.thought:
                    part_dict["thought"] = True

                parts.append(part_dict)

            candidates.append(
                {
                    "content": {
                        "role": candidate.content.role,
                        "parts": parts,
                    },
                    "finish_reason": getattr(candidate, "finish_reason", None),
                    "safety_ratings": getattr(candidate, "safety_ratings", []),
                }
            )

        # 构建响应
        result = {
            "candidates": candidates,
        }

        # 添加使用元数据
        if hasattr(response, "usage_metadata"):
            result["usage_metadata"] = {
                "prompt_token_count": response.usage_metadata.prompt_token_count,
                "candidates_token_count": response.usage_metadata.candidates_token_count,
                "total_token_count": response.usage_metadata.total_token_count,
            }

        # 添加提示反馈
        if hasattr(response, "prompt_feedback"):
            result["prompt_feedback"] = response.prompt_feedback

        return result


class CodeAssistContentGenerator(ContentGenerator):
    """
    Code Assist 内容生成器实现
    通过 OAuth 认证使用个人 Google 账号
    """

    def __init__(self, http_options: dict[str, Any], auth_type: AuthType):
        self.http_options = http_options
        self.auth_type = auth_type
        # TODO: 实现 Code Assist 集成

    async def generate_content(
        self,
        model: str,
        config: dict[str, Any],
        contents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """生成内容 - Code Assist 实现"""
        raise NotImplementedError("Code Assist 内容生成器尚未实现")

    async def generate_content_stream(
        self,
        model: str,
        config: dict[str, Any],
        contents: list[dict[str, Any]],
    ) -> AsyncGenerator[dict[str, Any], None]:
        """流式生成内容 - Code Assist 实现"""
        raise NotImplementedError("Code Assist 流式生成尚未实现")

    async def count_tokens(
        self,
        model: str,
        contents: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """计算 token - Code Assist 实现"""
        raise NotImplementedError("Code Assist token 计算尚未实现")

    async def embed_content(
        self,
        model: str,
        contents: list[str],
        task_type: str | None = None,
        title: str | None = None,
    ) -> dict[str, Any]:
        """生成嵌入 - Code Assist 实现"""
        raise NotImplementedError("Code Assist 嵌入生成尚未实现")


async def create_content_generator_config(
    model: str | None = None,
    auth_type: AuthType | None = None,
    config: dict[str, Any] | None = None,
) -> ContentGeneratorConfig:
    """
    创建内容生成器的配置对象
    这个函数会从环境变量中读取必要的认证信息（如 API keys, Google Cloud 项目）
    并根据指定的认证类型构建一个完整的配置对象

    Args:
        model: 使用的模型名称
        auth_type: 认证类型
        config: 可选的附加配置，例如用于获取运行时模型的函数

    Returns:
        内容生成器配置对象

    """
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    google_api_key = os.getenv("GOOGLE_API_KEY")
    google_cloud_project = os.getenv("GOOGLE_CLOUD_PROJECT")
    google_cloud_location = os.getenv("GOOGLE_CLOUD_LOCATION")

    # 如果在配置中提供了 get_model 函数，则使用它获取运行时模型
    effective_model = (
        config.get("get_model")()
        if config and "get_model" in config
        else model or DEFAULT_GEMINI_MODEL
    )

    content_generator_config: ContentGeneratorConfig = {
        "model": effective_model,
        "auth_type": auth_type,
    }

    # 如果我们使用 Google auth，目前不需要其他验证
    if auth_type == AuthType.LOGIN_WITH_GOOGLE_PERSONAL:
        return content_generator_config

    # 如果使用 Gemini API Key
    if auth_type == AuthType.USE_GEMINI and gemini_api_key:
        content_generator_config["api_key"] = gemini_api_key
        content_generator_config["model"] = await get_effective_model(
            content_generator_config["api_key"],
            content_generator_config["model"],
        )
        return content_generator_config

    # 如果使用 Vertex AI，需要 API Key 和 GCP 项目信息
    if (
        auth_type == AuthType.USE_VERTEX_AI
        and google_api_key
        and google_cloud_project
        and google_cloud_location
    ):
        content_generator_config["api_key"] = google_api_key
        content_generator_config["vertexai"] = True
        content_generator_config["model"] = await get_effective_model(
            content_generator_config["api_key"],
            content_generator_config["model"],
        )
        return content_generator_config

    return content_generator_config


async def create_content_generator(
    config: ContentGeneratorConfig,
) -> ContentGenerator:
    """
    工厂函数，根据提供的配置创建并返回一个 ContentGenerator 实例

    Args:
        config: 内容生成器的配置

    Returns:
        ContentGenerator 实例

    """
    version = os.getenv("CLI_VERSION", platform.python_version())

    # 设置 HTTP 头部，以便后端服务识别请求来源
    http_options = {
        "headers": {
            "User-Agent": f"GeminiCLI/{version} ({platform.system()}; {platform.machine()})",
        },
    }

    # 对于个人 OAuth 登录，使用特殊的 CodeAssistContentGenerator
    if config.get("auth_type") == AuthType.LOGIN_WITH_GOOGLE_PERSONAL:
        return CodeAssistContentGenerator(http_options, config["auth_type"])

    # 对于 API Key 或 Vertex AI，使用标准的 Gemini SDK
    if config.get("auth_type") in [AuthType.USE_GEMINI, AuthType.USE_VERTEX_AI]:
        # 配置 SDK
        api_key = config.get("api_key")
        if api_key:
            genai.configure(
                api_key=api_key,
                transport="rest",  # or "grpc"
                client_options={"api_endpoint": os.getenv("API_ENDPOINT")},
            )

        # 如果是 Vertex AI，需要额外配置
        if config.get("vertexai"):
            # TODO: 配置 Vertex AI
            pass

        # 创建一个占位符或默认模型实例
        # 具体的模型将在每次调用时在方法内部指定
        model_instance = genai.GenerativeModel(config["model"])

        return GeminiContentGenerator(model_instance, config)

    raise GeminiError(
        f"创建 contentGenerator 时出错：不支持的 authType: {config.get('auth_type')}",
        "unsupported_auth_type",
    )
