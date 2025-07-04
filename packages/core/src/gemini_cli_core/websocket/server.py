import asyncio
import json
import logging
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from gemini_cli_core.core import (
    CancelStreamMessage,
    Config,
    EventEmitter,
    GeminiEventType,
    ToolConfirmationMessage,
    UserInputMessage,
    WebSocketMessage,
)

logger = logging.getLogger(__name__)


class GeminiWebSocketServer:
    """WebSocket服务器 - 处理前后端通信"""

    def __init__(self, config: Config):
        """
        初始化WebSocket服务器

        Args:
            config: 配置对象

        """
        self.config = config
        self.app = FastAPI(title="Gemini CLI Core")
        self.active_connections: dict[str, WebSocket] = {}
        self.event_emitters: dict[str, EventEmitter] = {}
        self.conversation_tasks: dict[str, asyncio.Task] = {}

        # 配置CORS
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],  # 在生产环境中应该限制
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

        # 注册路由
        self._register_routes()

    def _register_routes(self) -> None:
        """注册WebSocket路由"""

        @self.app.websocket("/ws/{session_id}")
        async def websocket_endpoint(websocket: WebSocket, session_id: str):
            await self.handle_connection(websocket, session_id)

        @self.app.get("/health")
        async def health_check():
            return {"status": "ok", "version": "0.1.0"}

    async def handle_connection(
        self, websocket: WebSocket, session_id: str
    ) -> None:
        """
        处理WebSocket连接

        Args:
            websocket: WebSocket连接
            session_id: 会话ID

        """
        await websocket.accept()

        # 存储连接
        self.active_connections[session_id] = websocket

        # 创建事件发送器
        emitter = EventEmitter(websocket)
        self.event_emitters[session_id] = emitter

        logger.info(f"WebSocket connection established: {session_id}")

        try:
            # 发送初始化成功事件
            await emitter.emit(
                GeminiEventType.MODEL_RESPONSE,
                {"content": "Connected to Gemini CLI Core", "streaming": False},
            )

            # 处理消息循环
            await self._message_loop(websocket, session_id, emitter)

        except WebSocketDisconnect:
            logger.info(f"WebSocket disconnected: {session_id}")
        except Exception as e:
            logger.exception(f"WebSocket error for session {session_id}: {e}")
            await emitter.emit_error(e)
        finally:
            # 清理资源
            await self._cleanup_session(session_id)

    async def _message_loop(
        self,
        websocket: WebSocket,
        session_id: str,
        emitter: EventEmitter,
    ) -> None:
        """
        处理WebSocket消息循环

        Args:
            websocket: WebSocket连接
            session_id: 会话ID
            emitter: 事件发送器

        """
        while True:
            # 接收消息
            raw_message = await websocket.receive_text()

            try:
                message_data = json.loads(raw_message)
                message = self._parse_message(message_data)

                # 处理不同类型的消息
                await self._handle_message(message, session_id, emitter)

            except json.JSONDecodeError as e:
                logger.exception(f"Invalid JSON message: {e}")
                await emitter.emit_error(
                    Exception("Invalid message format"),
                    {"raw_message": raw_message},
                )
            except Exception as e:
                logger.exception(f"Error handling message: {e}")
                await emitter.emit_error(e)

    def _parse_message(self, data: dict[str, Any]) -> WebSocketMessage:
        """
        解析WebSocket消息

        Args:
            data: 原始消息数据

        Returns:
            解析后的消息对象

        """
        message_type = data.get("type")

        if message_type == "user_input":
            return UserInputMessage(**data)
        if message_type == "tool_confirmation_response":
            return ToolConfirmationMessage(**data)
        if message_type == "cancel_stream":
            return CancelStreamMessage(**data)
        raise ValueError(f"Unknown message type: {message_type}")

    async def _handle_message(
        self,
        message: WebSocketMessage,
        session_id: str,
        emitter: EventEmitter,
    ) -> None:
        """
        处理不同类型的消息

        Args:
            message: 消息对象
            session_id: 会话ID
            emitter: 事件发送器

        """
        if isinstance(message, UserInputMessage):
            await self._handle_user_input(message, session_id, emitter)
        elif isinstance(message, ToolConfirmationMessage):
            await self._handle_tool_confirmation(message, session_id, emitter)
        elif isinstance(message, CancelStreamMessage):
            await self._handle_cancel_stream(session_id, emitter)

    async def _handle_user_input(
        self,
        message: UserInputMessage,
        session_id: str,
        emitter: EventEmitter,
    ) -> None:
        """
        处理用户输入

        Args:
            message: 用户输入消息
            session_id: 会话ID
            emitter: 事件发送器

        """
        # 取消之前的任务（如果有）
        if session_id in self.conversation_tasks:
            self.conversation_tasks[session_id].cancel()

        # 创建新的对话任务
        from ..graphs.conversation import create_conversation_graph

        graph = create_conversation_graph(self.config, emitter)

        # 初始状态
        initial_state = {
            "session_id": session_id,
            "user_id": None,  # TODO: 从认证中获取
            "model": self.config.get_model(),
            "curated_history": [],
            "comprehensive_history": [],
            "current_user_input": message.value,
            "current_model_response": None,
            "current_model_thinking": None,
            "pending_tool_calls": [],
            "tool_call_results": [],
            "needs_compression": False,
            "continue_conversation": False,
            "is_streaming": True,
            "is_cancelled": False,
            "approval_mode": self.config.get_approval_mode(),
            "environment_initialized": False,
            "total_tokens": 0,
            "token_limit": 1000000,  # TODO: 从模型配置获取
            "error": None,
            "error_details": None,
            "turn_count": 0,
            "max_turns": 100,
        }

        # 启动对话任务
        task = asyncio.create_task(
            self._run_conversation(graph, initial_state, session_id, emitter),
        )
        self.conversation_tasks[session_id] = task

    async def _handle_tool_confirmation(
        self,
        message: ToolConfirmationMessage,
        session_id: str,
        emitter: EventEmitter,
    ) -> None:
        """
        处理工具确认响应

        Args:
            message: 工具确认消息
            session_id: 会话ID
            emitter: 事件发送器

        """
        # TODO: 实现工具确认处理
        # 需要与正在执行的工具子图通信
        logger.info(f"Tool confirmation received: {message}")

    async def _handle_cancel_stream(
        self,
        session_id: str,
        emitter: EventEmitter,
    ) -> None:
        """
        处理取消流

        Args:
            session_id: 会话ID
            emitter: 事件发送器

        """
        # 取消当前任务
        if session_id in self.conversation_tasks:
            self.conversation_tasks[session_id].cancel()
            await emitter.emit(
                GeminiEventType.MODEL_RESPONSE,
                {"content": "Stream cancelled", "streaming": False},
            )

    async def _run_conversation(
        self,
        graph: Any,  # LangGraph instance
        initial_state: dict[str, Any],
        session_id: str,
        emitter: EventEmitter,
    ) -> None:
        """
        运行对话图

        Args:
            graph: LangGraph实例
            initial_state: 初始状态
            session_id: 会话ID
            emitter: 事件发送器

        """
        try:
            # 执行图
            async for state in graph.astream(initial_state):
                # 检查是否被取消
                if state.get("is_cancelled"):
                    break

                # 处理状态更新
                # TODO: 根据状态变化发送相应事件

            # 发送回合完成事件
            await emitter.emit_turn_complete(
                f"{session_id}_{state.get('turn_count', 0)}",
            )

        except asyncio.CancelledError:
            logger.info(f"Conversation cancelled for session {session_id}")
        except Exception as e:
            logger.exception(
                f"Conversation error for session {session_id}: {e}"
            )
            await emitter.emit_error(e)

    async def _cleanup_session(self, session_id: str) -> None:
        """
        清理会话资源

        Args:
            session_id: 会话ID

        """
        # 移除连接
        self.active_connections.pop(session_id, None)
        self.event_emitters.pop(session_id, None)

        # 取消任务
        if session_id in self.conversation_tasks:
            self.conversation_tasks[session_id].cancel()
            self.conversation_tasks.pop(session_id, None)

        logger.info(f"Session cleaned up: {session_id}")

    def run(self, host: str = "0.0.0.0", port: int = 8000) -> None:
        """
        运行WebSocket服务器

        Args:
            host: 监听地址
            port: 监听端口

        """
        import uvicorn

        logger.info(f"Starting WebSocket server on {host}:{port}")
        uvicorn.run(self.app, host=host, port=port)
