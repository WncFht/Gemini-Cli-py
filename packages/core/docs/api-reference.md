# API Reference

The `gemini-cli-core` backend is built using FastAPI and exposes several HTTP endpoints for clients to interact with. This document serves as a reference for those endpoints, their purposes, and their request/response schemas.

For a live, interactive API specification, run the server and navigate to `/docs` to see the Swagger UI.

## Base URL

All endpoints are relative to the server's base URL (e.g., `http://127.0.0.1:8000`).

---

## Health Check

### `GET /`
- **Description**: A simple health check endpoint to verify that the server is running.
- **Request Body**: None.
- **Success Response (`200 OK`)**:
  ```json
  {
    "status": "ok"
  }
  ```

---

## Session Management

### `POST /session/start`
- **Description**: Creates a new conversation session and initializes a `GeminiClient` instance for it.
- **Request Body**: `StartSessionRequest`
  ```json
  {
    "config": {
      "key": "value",
      // ... other config parameters for GeminiClient
    }
  }
  ```
- **Success Response (`200 OK`)**: `SessionResponse`
  ```json
  {
    "session_id": "a-unique-session-id"
  }
  ```

### `POST /session/end`
- **Description**: Ends a given session and cleans up its resources.
- **Request Body**: `EndSessionRequest`
  ```json
  {
    "session_id": "the-session-id-to-end"
  }
  ```
- **Success Response (`200 OK`)**:
  ```json
  {
    "status": "ended",
    "session_id": "the-session-id-to-end"
  }
  ```

---

## Core Interaction

### `POST /chat`
- **Description**: The main endpoint for sending chat messages to the agent. This endpoint streams responses back to the client using Server-Sent Events (SSE).
- **Request Body**: `ChatRequest`
  ```json
  {
    "session_id": "a-valid-session-id",
    "messages": [
      {
        "role": "user",
        "parts": [
          { "text": "Hello, world!" }
        ]
      }
    ]
  }
  ```
- **Response (`200 OK`)**: An `EventSourceResponse` stream. The client will receive a series of events, each containing a JSON payload. Events can be of various types (`thought`, `tool_code`, `stream`, `result`, `error`, etc.).

### `POST /tool/confirm`
- **Description**: Used by the client to respond to a tool call that requires user confirmation.
- **Request Body**: `ToolConfirmationRequest`
  ```json
  {
    "session_id": "a-valid-session-id",
    "call_id": "the-tool-call-id-to-confirm",
    "outcome": "approve" // or "cancel"
  }
  ```
- **Success Response (`200 OK`)**:
  ```json
  {
    "status": "resumed",
    "call_id": "the-tool-call-id-to-confirm"
  }
  ```

### `POST /cancel`
- **Description**: Requests the cancellation of the currently running operation for a session.
- **Request Body**: `CancelRequest`
  ```json
  {
    "session_id": "a-valid-session-id"
  }
  ```
- **Success Response (`200 OK`)**:
  ```json
  {
    "status": "cancellation_requested"
  }
  ```
