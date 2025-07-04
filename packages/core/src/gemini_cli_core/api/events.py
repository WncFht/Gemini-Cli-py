from enum import Enum
from typing import Any, Literal, Union

from pydantic import BaseModel, Field


class GeminiEventType(str, Enum):
    """Defines the event types that can occur during an interaction with Gemini."""

    CONTENT = "content"
    TOOL_CALL_REQUEST = "tool_call_request"
    TOOL_CALL_RESPONSE = "tool_call_response"
    TOOL_CALL_CONFIRMATION = "tool_call_confirmation"
    USER_CANCELLED = "user_cancelled"
    ERROR = "error"
    CHAT_COMPRESSED = "chat_compressed"
    USAGE_METADATA = "usage_metadata"
    THOUGHT = "thought"


class StructuredError(BaseModel):
    """Structured error information."""

    message: str
    status: int | None = None


class GeminiErrorEventValue(BaseModel):
    """Value for a Gemini error event."""

    error: StructuredError


class ToolCallRequestInfo(BaseModel):
    """Information about a tool call request."""

    call_id: str = Field(..., alias="callId")
    name: str
    args: dict[str, Any]
    is_client_initiated: bool = Field(..., alias="isClientInitiated")


class ToolResultDisplay(BaseModel):
    """
    Placeholder for how a tool result should be displayed.
    Originally from tools/tools.ts.
    """

    kind: str
    content: str


PartListUnion = list[dict[str, Any]]


class ToolCallResponseInfo(BaseModel):
    """Information about a tool call response."""

    call_id: str = Field(..., alias="callId")
    response_parts: PartListUnion = Field(..., alias="responseParts")
    result_display: ToolResultDisplay | None = Field(
        None, alias="resultDisplay"
    )
    # The original type was `Error | undefined`. We'll store the message.
    error: str | None = None


class ToolCallConfirmationDetails(BaseModel):
    """
    Placeholder for details needed for tool call confirmation.
    Originally from tools/tools.ts.
    """

    title: str
    description: str
    params: dict[str, Any]


class ServerToolCallConfirmationDetails(BaseModel):
    """Details for a server-side tool call confirmation."""

    request: ToolCallRequestInfo
    details: ToolCallConfirmationDetails


class ThoughtSummary(BaseModel):
    """Summary of the model's "thinking" process."""

    subject: str
    description: str


class ServerGeminiContentEvent(BaseModel):
    """Event for model-generated content."""

    type: Literal[GeminiEventType.CONTENT]
    value: str


class ServerGeminiThoughtEvent(BaseModel):
    """Event for a model "thought"."""

    type: Literal[GeminiEventType.THOUGHT]
    value: ThoughtSummary


class ServerGeminiToolCallRequestEvent(BaseModel):
    """Event for a tool call request from the model."""

    type: Literal[GeminiEventType.TOOL_CALL_REQUEST]
    value: ToolCallRequestInfo


class ServerGeminiToolCallResponseEvent(BaseModel):
    """Event for a tool execution response."""

    type: Literal[GeminiEventType.TOOL_CALL_RESPONSE]
    value: ToolCallResponseInfo


class ServerGeminiToolCallConfirmationEvent(BaseModel):
    """Event for waiting for user confirmation of a tool call."""

    type: Literal[GeminiEventType.TOOL_CALL_CONFIRMATION]
    value: ServerToolCallConfirmationDetails


class ServerGeminiUserCancelledEvent(BaseModel):
    """Event for user cancellation."""

    type: Literal[GeminiEventType.USER_CANCELLED]
    value: None = None


class ServerGeminiErrorEvent(BaseModel):
    """Event for an error."""

    type: Literal[GeminiEventType.ERROR]
    value: GeminiErrorEventValue


class ChatCompressionInfo(BaseModel):
    """Information about chat history compression."""

    original_token_count: int = Field(..., alias="originalTokenCount")
    new_token_count: int = Field(..., alias="newTokenCount")


class ServerGeminiChatCompressedEvent(BaseModel):
    """Event for chat history compression."""

    type: Literal[GeminiEventType.CHAT_COMPRESSED]
    value: ChatCompressionInfo | None


class GenerateContentResponseUsageMetadata(BaseModel):
    """
    API usage metadata from the response.
    From @google/genai/index.d.ts
    """

    prompt_token_count: int = Field(..., alias="promptTokenCount")
    candidates_token_count: int = Field(..., alias="candidatesTokenCount")
    total_token_count: int = Field(..., alias="totalTokenCount")
    api_time_ms: int | None = Field(None, alias="apiTimeMs")


class ServerGeminiUsageMetadataEvent(BaseModel):
    """Event for API usage metadata."""

    type: Literal[GeminiEventType.USAGE_METADATA]
    value: GenerateContentResponseUsageMetadata


# --- Events for Code Assist Service ---
class CodeAssistEventType(str, Enum):
    """Defines event types specific to the Code Assist service."""

    ASSIST = "assist"
    ERROR = "error"
    PROGRESS = "progress"
    STATUS = "status"


class Status(str, Enum):
    """Status enums for Code Assist events."""

    OK = "ok"
    ERROR = "error"


class CodeAssistError(BaseModel):
    """Error structure for Code Assist events."""

    message: str


class CodeAssistStatusEvent(BaseModel):
    """Event for reporting the status of an operation."""

    type: Literal[CodeAssistEventType.STATUS]
    status: Status
    message: str | None = None


class CodeAssistProgressEvent(BaseModel):
    """Event for reporting progress."""

    type: Literal[CodeAssistEventType.PROGRESS]
    message: str


class CodeAssistEvent(BaseModel):
    """A generic Code Assist event for streaming."""

    type: CodeAssistEventType
    payload: dict[str, Any]


class ClientMetadataIdeType(str, Enum):
    IDE_UNSPECIFIED = "IDE_UNSPECIFIED"
    VSCODE = "VSCODE"
    INTELLIJ = "INTELLIJ"
    VSCODE_CLOUD_WORKSTATION = "VSCODE_CLOUD_WORKSTATION"
    INTELLIJ_CLOUD_WORKSTATION = "INTELLIJ_CLOUD_WORKSTATION"
    CLOUD_SHELL = "CLOUD_SHELL"


class ClientMetadataPlatform(str, Enum):
    PLATFORM_UNSPECIFIED = "PLATFORM_UNSPECIFIED"
    DARWIN_AMD64 = "DARWIN_AMD64"
    DARWIN_ARM64 = "DARWIN_ARM64"
    LINUX_AMD64 = "LINUX_AMD64"
    LINUX_ARM64 = "LINUX_ARM64"
    WINDOWS_AMD64 = "WINDOWS_AMD64"


class ClientMetadataPluginType(str, Enum):
    PLUGIN_UNSPECIFIED = "PLUGIN_UNSPECIFIED"
    CLOUD_CODE = "CLOUD_CODE"
    GEMINI = "GEMINI"
    AIPLUGIN_INTELLIJ = "AIPLUGIN_INTELLIJ"
    AIPLUGIN_STUDIO = "AIPLUGIN_STUDIO"


class ClientMetadata(BaseModel):
    ide_type: ClientMetadataIdeType | None = Field(None, alias="ideType")
    ide_version: str | None = Field(None, alias="ideVersion")
    plugin_version: str | None = Field(None, alias="pluginVersion")
    platform: ClientMetadataPlatform | None = None
    update_channel: str | None = Field(None, alias="updateChannel")
    duet_project: str | None = Field(None, alias="duetProject")
    plugin_type: ClientMetadataPluginType | None = Field(
        None, alias="pluginType"
    )
    ide_name: str | None = Field(None, alias="ideName")


class LoadCodeAssistRequest(BaseModel):
    cloudaicompanion_project: str | None = Field(
        None, alias="cloudaicompanionProject"
    )
    metadata: ClientMetadata


class UserTierId(str, Enum):
    FREE = "free-tier"
    LEGACY = "legacy-tier"
    STANDARD = "standard-tier"


class PrivacyNotice(BaseModel):
    show_notice: bool = Field(..., alias="showNotice")
    notice_text: str | None = Field(None, alias="noticeText")


class GeminiUserTier(BaseModel):
    id: UserTierId
    name: str
    description: str
    user_defined_cloudaicompanion_project: bool | None = Field(
        None, alias="userDefinedCloudaicompanionProject"
    )
    is_default: bool | None = Field(None, alias="isDefault")
    privacy_notice: PrivacyNotice | None = Field(None, alias="privacyNotice")
    has_accepted_tos: bool | None = Field(None, alias="hasAcceptedTos")
    has_onboarded_previously: bool | None = Field(
        None, alias="hasOnboardedPreviously"
    )


class IneligibleTierReasonCode(str, Enum):
    DASHER_USER = "DASHER_USER"
    INELIGIBLE_ACCOUNT = "INELIGIBLE_ACCOUNT"
    NON_USER_ACCOUNT = "NON_USER_ACCOUNT"
    RESTRICTED_AGE = "RESTRICTED_AGE"
    RESTRICTED_NETWORK = "RESTRICTED_NETWORK"
    UNKNOWN = "UNKNOWN"
    UNKNOWN_LOCATION = "UNKNOWN_LOCATION"
    UNSUPPORTED_LOCATION = "UNSUPPORTED_LOCATION"


class IneligibleTier(BaseModel):
    reason_code: IneligibleTierReasonCode = Field(..., alias="reasonCode")
    reason_message: str = Field(..., alias="reasonMessage")
    tier_id: UserTierId = Field(..., alias="tierId")
    tier_name: str = Field(..., alias="tierName")


class LoadCodeAssistResponse(BaseModel):
    current_tier: GeminiUserTier | None = Field(None, alias="currentTier")
    allowed_tiers: list[GeminiUserTier] | None = Field(
        None, alias="allowedTiers"
    )
    ineligible_tiers: list[IneligibleTier] | None = Field(
        None, alias="ineligibleTiers"
    )
    cloudaicompanion_project: str | None = Field(
        None, alias="cloudaicompanionProject"
    )


ServerGeminiStreamEvent = Union[
    ServerGeminiContentEvent,
    ServerGeminiToolCallRequestEvent,
    ServerGeminiToolCallResponseEvent,
    ServerGeminiToolCallConfirmationEvent,
    ServerGeminiUserCancelledEvent,
    ServerGeminiErrorEvent,
    ServerGeminiChatCompressedEvent,
    ServerGeminiThoughtEvent,
    ServerGeminiUsageMetadataEvent,
]
