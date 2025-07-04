# API 参考

`gemini-cli-core` 后端使用 FastAPI 构建，并为客户端交互暴露了多个 HTTP 端点。本文档为这些端点、其用途以及它们的请求/响应模式提供了参考。

要获取实时的、可交互的 API 规范，请运行服务器并访问 `/docs` 以查看 Swagger UI。

## 基础 URL

所有端点都相对于服务器的基础 URL（例如, `http://127.0.0.1:8000`）。

---

## 健康检查

### `GET /`
- **描述**: 一个简单的健康检查端点，用于验证服务器是否正在运行。
- **请求体**: 无。
- **成功响应 (`200 OK`)**:
  ```json
  {
    "status": "ok"
  }
  ```

---

## 会话管理

### `POST /session/start`
- **描述**: 创建一个新的对话会话，并为其初始化一个 `GeminiClient` 实例。
- **请求体**: `StartSessionRequest`
  ```json
  {
    "config": {
      "key": "value",
      // ... 用于 GeminiClient 的其他配置参数
    }
  }
  ```
- **成功响应 (`200 OK`)**: `SessionResponse`
  ```json
  {
    "session_id": "一个唯一的会话ID"
  }
  ```

### `POST /session/end`
- **描述**: 结束给定的会话并清理其资源。
- **请求体**: `EndSessionRequest`
  ```json
  {
    "session_id": "要结束的会话ID"
  }
  ```
- **成功响应 (`200 OK`)**:
  ```json
  {
    "status": "ended",
    "session_id": "要结束的会话ID"
  }
  ```

---

## 核心交互

### `POST /chat`
- **描述**: 用于向代理发送聊天消息的主要端点。此端点使用服务器发送事件（SSE）将响应流式传输回客户端。
- **请求体**: `ChatRequest`
  ```json
  {
    "session_id": "一个有效的会话ID",
    "messages": [
      {
        "role": "user",
        "parts": [
          { "text": "你好，世界！" }
        ]
      }
    ]
  }
  ```
- **响应 (`200 OK`)**: 一个 `EventSourceResponse` 流。客户端将接收一系列事件，每个事件都包含一个 JSON 负载。事件可以是各种类型（`thought`, `tool_code`, `stream`, `result`, `error` 等）。

### `POST /tool/confirm`
- **描述**: 由客户端用于响应需要用户确认的工具调用。
- **请求体**: `ToolConfirmationRequest`
  ```json
  {
    "session_id": "一个有效的会话ID",
    "call_id": "需要确认的工具调用ID",
    "outcome": "approve" // 或 "cancel"
  }
  ```
- **成功响应 (`200 OK`)**:
  ```json
  {
    "status": "resumed",
    "call_id": "需要确认的工具调用ID"
  }
  ```

### `POST /cancel`
- **描述**: 请求取消会话当前正在运行的操作。
- **请求体**: `CancelRequest`
  ```json
  {
    "session_id": "一个有效的会话ID"
  }
  ```
- **成功响应 (`200 OK`)**:
  ```json
  {
    "status": "cancellation_requested"
  }
  ``` 