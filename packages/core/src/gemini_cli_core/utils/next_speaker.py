"""
下一个发言者检查器 - 从 nextSpeakerChecker.ts 迁移
"""

import asyncio
from typing import Any

from gemini_cli_core.core.types import Content, NextSpeakerResponse


async def check_next_speaker(
    history: list[Content],
    client: Any,  # GeminiClient
    signal: asyncio.Event | None = None,
) -> NextSpeakerResponse | None:
    """
    检查下一个应该发言的是用户还是模型

    Args:
        history: 对话历史
        client: GeminiClient 实例
        signal: 中止信号

    Returns:
        NextSpeakerResponse 或 None

    """
    # 如果历史记录太短，不检查
    if len(history) < 3:
        return None

    # 构建检查提示
    check_prompt = """
Based on the conversation so far, determine who should speak next.

If the model's last response appears incomplete, or if the model explicitly indicated it will continue, or if the task is not yet complete, respond with "model".

If the model's last response appears complete and it's the user's turn to provide input, respond with "user".

Consider:
- Did the model finish its thought?
- Did the model complete the requested task?
- Is the model waiting for user input?
- Did the model indicate it will continue?
"""

    schema = {
        "type": "object",
        "properties": {
            "reasoning": {
                "type": "string",
                "description": "Brief explanation of the decision",
            },
            "next_speaker": {
                "type": "string",
                "enum": ["user", "model"],
                "description": "Who should speak next",
            },
        },
        "required": ["reasoning", "next_speaker"],
    }

    try:
        # 获取最近的几条消息用于判断
        recent_history = history[-6:] if len(history) > 6 else history

        contents = [
            *recent_history,
            {
                "role": "user",
                "parts": [{"text": check_prompt}],
            },
        ]

        result = await client.generate_json(
            contents=contents,
            schema=schema,
            abort_signal=signal,
        )

        return NextSpeakerResponse(
            reasoning=result.get("reasoning", ""),
            next_speaker=result.get("next_speaker", "user"),
        )

    except Exception:
        # 如果检查失败，默认让用户发言
        return None
