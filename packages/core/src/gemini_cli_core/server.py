import json
import uuid
from collections.abc import AsyncGenerator
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from gemini_cli_core.core.app import GeminiApp
from gemini_cli_core.core.config import Config

app = FastAPI(
    title="Gemini CLI Core Backend",
    description="The Python backend for Gemini CLI, powered by LangGraph.",
    version="0.1.0",
)


class SessionManager:
    """Manages active GeminiApp sessions."""

    def __init__(self):
        self._sessions: dict[str, GeminiApp] = {}
        self._graphs: dict[str, object] = {}  # To hold and cleanup graphs

    async def create_session(self, raw_config: dict) -> str:
        """
        Creates a new session with a GeminiApp instance and returns its ID.
        """
        session_id = str(uuid.uuid4())
        # TODO: The config object might need more sophisticated creation logic
        # depending on what the CLI sends.
        config = Config(**raw_config)
        app_instance = GeminiApp(config)
        await app_instance.initialize()
        self._sessions[session_id] = app_instance
        return session_id

    def get_session(self, session_id: str) -> GeminiApp | None:
        """Retrieves a session by its ID."""
        return self._sessions.get(session_id)

    def end_session(self, session_id: str):
        """Ends a session and cleans up its resources."""
        # TODO: Implement graph cleanup logic once graph instances are managed
        if session_id in self._sessions:
            del self._sessions[session_id]
        if session_id in self._graphs:
            del self._graphs[session_id]


# Global session manager instance
session_manager = SessionManager()


# --- API Models ---
class StartSessionRequest(BaseModel):
    """Request model for starting a session."""

    config: dict[str, Any]


class SessionResponse(BaseModel):
    """Response model for session operations."""

    session_id: str


class EndSessionRequest(BaseModel):
    """Request model for ending a session."""

    session_id: str


class ChatRequest(BaseModel):
    """Request model for a chat message."""

    session_id: str
    messages: list[dict[str, Any]]


class ToolConfirmationRequest(BaseModel):
    """Request model for responding to a tool confirmation."""

    session_id: str
    call_id: str
    outcome: str  # "approve", "cancel", "modify"
    # TODO: Add modified_args if outcome is "modify"


class CancelRequest(BaseModel):
    """Request model for cancelling an operation."""

    session_id: str


# --- Session Endpoints ---
@app.post("/session/start", response_model=SessionResponse)
async def start_session(request: StartSessionRequest):
    """Starts a new session and returns a session_id."""
    session_id = await session_manager.create_session(request.config)
    return SessionResponse(session_id=session_id)


@app.post("/session/end")
async def end_session(request: EndSessionRequest):
    """Ends a given session."""
    session_manager.end_session(request.session_id)
    return {"status": "ended", "session_id": request.session_id}


@app.get("/")
async def read_root():
    """Root endpoint for health checks."""
    return {"status": "ok"}


# --- Tool Interaction Endpoints ---
@app.post("/tool/confirm")
async def tool_confirm(request: ToolConfirmationRequest):
    """
    Receives user confirmation for a tool call and resumes the graph.
    """
    session = session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # This method will need to be implemented in GeminiApp
    await session.resume_with_tool_confirmation(
        request.call_id, request.outcome
    )

    return {"status": "resumed", "call_id": request.call_id}


@app.post("/cancel")
async def cancel(request: CancelRequest):
    """
    Cancels the currently running operation for a session.
    """
    session = session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    session.cancel()
    print(f"Cancellation requested for session {request.session_id}")

    return {"status": "cancellation_requested"}


# --- Chat Endpoint ---
@app.post("/chat")
async def chat(request: ChatRequest):
    """
    Handles the main chat interaction, streaming events back to the client.
    """
    session = session_manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    async def event_generator() -> AsyncGenerator[dict[str, Any], None]:
        """The generator for SSE events."""
        try:
            # The chat_stream method in GeminiApp yields events.
            # We just need to format them for SSE.
            async for event in session.chat_stream(request.messages):
                # LangGraph events can be complex objects with non-serializable parts.
                # We need to ensure they are JSON-serializable.
                # The event from chat_stream should already be a dict.
                yield {"data": json.dumps(jsonable_encoder(event))}
        except Exception as e:
            # Handle potential errors during the stream
            error_event = {
                "type": "error",
                "payload": {"message": f"An error occurred: {e!s}"},
            }
            yield {"data": json.dumps(error_event)}

    return EventSourceResponse(event_generator())


# The server can be run from the `packages/core` directory with:
# uv run uvicorn gemini_cli_core.server:app --reload
