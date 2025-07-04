import asyncio
from typing import Any, Protocol

from .types import GeminiEventType, ServerGeminiStreamEvent


class WebSocketProtocol(Protocol):
    """WebSocket协议接口"""

    async def send_json(self, data: dict[str, Any]) -> None:
        """发送JSON数据"""
        ...


class EventEmitter:
    """事件发送器 - 保持与TypeScript EventEmitter的兼容性"""

    def __init__(self, websocket: WebSocketProtocol | None = None):
        """
        初始化事件发送器

        Args:
            websocket: WebSocket连接，如果为None则使用内部队列

        """
        self.websocket = websocket
        self._event_queue: asyncio.Queue[ServerGeminiStreamEvent] = (
            asyncio.Queue()
        )
        self._subscribers: list[asyncio.Queue[ServerGeminiStreamEvent]] = []

    async def emit(self, event_type: GeminiEventType, value: Any) -> None:
        """
        发送事件到前端，保持驼峰命名

        Args:
            event_type: 事件类型
            value: 事件值

        """
        # 转换为驼峰命名
        if isinstance(value, dict):
            value = self._to_camel_case(value)

        event = ServerGeminiStreamEvent(type=event_type, value=value)

        # 如果有WebSocket连接，直接发送
        if self.websocket:
            await self.websocket.send_json(event.model_dump(by_alias=True))

        # 同时发送到内部队列和订阅者
        await self._event_queue.put(event)

        # 通知所有订阅者
        for subscriber in self._subscribers:
            await subscriber.put(event)

    async def emit_error(
        self, error: Exception, details: dict[str, Any] | None = None
    ) -> None:
        """
        发送错误事件

        Args:
            error: 错误对象
            details: 额外的错误详情

        """
        error_data = {
            "message": str(error),
            "type": error.__class__.__name__,
        }

        if details:
            error_data["details"] = details

        await self.emit(GeminiEventType.ERROR, error_data)

    async def emit_model_thinking(self, content: str) -> None:
        """发送模型思考事件"""
        await self.emit(GeminiEventType.MODEL_THINKING, {"content": content})

    async def emit_model_response(
        self, content: str, streaming: bool = False
    ) -> None:
        """发送模型响应事件"""
        await self.emit(
            GeminiEventType.MODEL_RESPONSE,
            {"content": content, "streaming": streaming},
        )

    async def emit_tool_calls_update(
        self, tool_calls: list[dict[str, Any]]
    ) -> None:
        """发送工具调用更新事件"""
        await self.emit(
            GeminiEventType.TOOL_CALLS_UPDATE, {"toolCalls": tool_calls}
        )

    async def emit_turn_complete(self, turn_id: str) -> None:
        """发送回合完成事件"""
        await self.emit(GeminiEventType.TURN_COMPLETE, {"turnId": turn_id})

    async def emit_chat_compressed(
        self, compression_info: dict[str, Any]
    ) -> None:
        """发送聊天压缩事件"""
        await self.emit(GeminiEventType.CHAT_COMPRESSED, compression_info)

    def subscribe(self) -> asyncio.Queue[ServerGeminiStreamEvent]:
        """
        订阅事件

        Returns:
            用于接收事件的队列

        """
        queue: asyncio.Queue[ServerGeminiStreamEvent] = asyncio.Queue()
        self._subscribers.append(queue)
        return queue

    def unsubscribe(
        self, queue: asyncio.Queue[ServerGeminiStreamEvent]
    ) -> None:
        """
        取消订阅

        Args:
            queue: 要取消订阅的队列

        """
        if queue in self._subscribers:
            self._subscribers.remove(queue)

    async def get_event(self) -> ServerGeminiStreamEvent:
        """
        获取下一个事件

        Returns:
            下一个事件

        """
        return await self._event_queue.get()

    def _to_camel_case(self, snake_dict: dict[str, Any]) -> dict[str, Any]:
        """
        递归地将snake_case转换为camelCase

        Args:
            snake_dict: 使用snake_case的字典

        Returns:
            使用camelCase的字典

        """

        def convert_key(key: str) -> str:
            """转换单个键"""
            # 特殊情况处理
            special_cases = {
                "call_id": "callId",
                "tool_name": "toolName",
                "display_name": "displayName",
                "file_path": "filePath",
                "error_type": "errorType",
                "auth_type": "authType",
                "function_response": "functionResponse",
                "function_call": "functionCall",
                "tool_calls": "toolCalls",
                "original_token_count": "originalTokenCount",
                "new_token_count": "newTokenCount",
                "next_speaker": "nextSpeaker",
                "turn_id": "turnId",
                "session_id": "sessionId",
                "duration_ms": "durationMs",
                "status_code": "statusCode",
                "result_display": "resultDisplay",
            }

            if key in special_cases:
                return special_cases[key]

            # 通用转换
            components = key.split("_")
            return components[0] + "".join(x.title() for x in components[1:])

        def convert_value(value: Any) -> Any:
            """递归转换值"""
            if isinstance(value, dict):
                return {
                    convert_key(k): convert_value(v) for k, v in value.items()
                }
            if isinstance(value, list):
                return [convert_value(item) for item in value]
            return value

        return {convert_key(k): convert_value(v) for k, v in snake_dict.items()}


class EventCollector:
    """事件收集器 - 用于测试和调试"""

    def __init__(self):
        self.events: list[ServerGeminiStreamEvent] = []
        self.emitter = EventEmitter()
        self._task: asyncio.Task | None = None

    def start(self):
        """开始收集事件"""
        self._task = asyncio.create_task(self._collect())

    async def _collect(self):
        """收集事件的内部方法"""
        queue = self.emitter.subscribe()
        try:
            while True:
                event = await queue.get()
                self.events.append(event)
        except asyncio.CancelledError:
            pass
        finally:
            self.emitter.unsubscribe(queue)

    def stop(self):
        """停止收集事件"""
        if self._task:
            self._task.cancel()

    def clear(self):
        """清空收集的事件"""
        self.events.clear()

    def get_events_by_type(
        self, event_type: GeminiEventType
    ) -> list[ServerGeminiStreamEvent]:
        """获取特定类型的事件"""
        return [e for e in self.events if e.type == event_type]
