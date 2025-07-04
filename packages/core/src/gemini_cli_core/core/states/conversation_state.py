from google.generativeai.types import Content, GenerateContentResponse
from pydantic import BaseModel, Field

from gemini_cli_core.api.events import ToolCallRequestInfo


class ConversationState(BaseModel):
    """
    Represents the state of a conversation graph.
    It accumulates data as the graph is processed.
    """

    messages: list[Content] = Field(
        default_factory=list,
        description="The complete history of the conversation, from GeminiChat.comprehensiveHistory.",
    )

    pending_tool_calls: list[ToolCallRequestInfo] = Field(
        default_factory=list,
        description="Tool calls requested by the model in the current turn, from Turn.pendingToolCalls.",
    )

    debug_responses: list[GenerateContentResponse] = Field(
        default_factory=list,
        description="Raw responses from the Gemini API for debugging, from Turn.debugResponses.",
    )

    class Config:
        arbitrary_types_allowed = True
