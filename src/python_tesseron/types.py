"""Pydantic models for Tesseron protocol wire types.

Design Contract: DC-015 (TypeDefinitions)
Spec Reference: §2 (Wire Format), various

These models represent the JSON-RPC message envelopes and structured
payloads defined in the Tesseron protocol specification. They are used
both by the test suite (to construct and validate messages) and by the
SDK implementation (to parse and serialise protocol messages).

All models use ``model_config = ConfigDict(extra="ignore")`` so that
unknown fields added by future protocol versions are silently ignored
rather than causing validation errors.

Guarantees:
- All wire types modeled as Pydantic BaseModel with ConfigDict(extra=ignore)
- camelCase wire names aliased to snake_case Python names
- JSON-RPC envelope shapes: Request, Notification, SuccessResponse, ErrorResponse
- id may be string, int, or None per REQ-003
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# JSON-RPC 2.0 envelope shapes
# ---------------------------------------------------------------------------


class JsonRpcRequest(BaseModel):
    """A JSON-RPC 2.0 request (expects a response).

    Attributes:
        jsonrpc: Protocol version string, always "2.0".
        id: Caller-assigned identifier. MAY be string, integer, or null.
        method: Method name.
        params: Method parameters (optional).

    """

    model_config = ConfigDict(extra="ignore")

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    method: str
    params: dict[str, Any] | None = None


class JsonRpcNotification(BaseModel):
    """A JSON-RPC 2.0 notification (fire-and-forget, no id, no response).

    Attributes:
        jsonrpc: Protocol version string, always "2.0".
        method: Method name.
        params: Method parameters (optional).

    """

    model_config = ConfigDict(extra="ignore")

    jsonrpc: Literal["2.0"] = "2.0"
    method: str
    params: dict[str, Any] | None = None


class JsonRpcSuccessResponse(BaseModel):
    """A JSON-RPC 2.0 success response.

    Attributes:
        jsonrpc: Protocol version string, always "2.0".
        id: Echoed from the original request.
        result: The result payload.

    """

    model_config = ConfigDict(extra="ignore")

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    result: Any


class JsonRpcErrorObject(BaseModel):
    """The ``error`` sub-object in a JSON-RPC error response.

    Attributes:
        code: Numeric error code.
        message: Human-readable error description.
        data: Optional structured payload.

    """

    model_config = ConfigDict(extra="ignore")

    code: int
    message: str
    data: Any | None = None


class JsonRpcErrorResponse(BaseModel):
    """A JSON-RPC 2.0 error response.

    Attributes:
        jsonrpc: Protocol version string, always "2.0".
        id: Echoed from the original request.
        error: Structured error object.

    """

    model_config = ConfigDict(extra="ignore")

    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None
    error: JsonRpcErrorObject


# ---------------------------------------------------------------------------
# Tesseron capability types
# ---------------------------------------------------------------------------


class TesseronCapabilities(BaseModel):
    """The four independently-negotiable capabilities.

    Attributes:
        streaming: App can send/receive progress and log notifications.
        subscriptions: App honours resources/subscribe.
        sampling: App can issue sampling/request.
        elicitation: App can issue elicitation/request.

    """

    model_config = ConfigDict(extra="ignore")

    streaming: bool = True
    subscriptions: bool = True
    sampling: bool = True
    elicitation: bool = True


# ---------------------------------------------------------------------------
# App identity types
# ---------------------------------------------------------------------------


class AppMetadata(BaseModel):
    """Identity metadata for the app declared in tesseron/hello.

    Attributes:
        id: Unique app identifier. MUST match ``/^[a-z][a-z0-9_]*$/``.
            Reserved values: tesseron, mcp, system.
        name: Human-readable app name.
        description: Optional short description for the agent.
        origin: Informational origin identifier.
        version: Optional version string.
        icon_url: Optional absolute URL of an icon.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: str
    name: str
    description: str | None = None
    origin: str
    version: str | None = None
    icon_url: str | None = Field(default=None, alias="iconUrl")


class AgentIdentity(BaseModel):
    """Identity of the connected agent.

    Attributes:
        id: Agent identifier (``"pending"`` until claimed).
        name: Human-readable agent name.

    """

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str


# ---------------------------------------------------------------------------
# Action manifest types
# ---------------------------------------------------------------------------


class ActionAnnotations(BaseModel):
    """Advisory metadata attached to an action.

    Attributes:
        read_only: The action does not mutate state.
        destructive: The action mutates persistent state.
        requires_confirmation: The action MUST NOT be called without
            explicit user confirmation.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    read_only: bool | None = Field(default=None, alias="readOnly")
    destructive: bool | None = None
    requires_confirmation: bool | None = Field(default=None, alias="requiresConfirmation")


class ActionManifestEntry(BaseModel):
    """A single action declared in tesseron/hello.

    Attributes:
        name: Action name.
        description: Human-readable description shown to the agent.
        input_schema: JSON Schema for the action's input.
        output_schema: Optional JSON Schema for the action's output.
        annotations: Optional advisory metadata.
        timeout_ms: Override the default 60,000 ms timeout.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "additionalProperties": True},
        alias="inputSchema",
    )
    output_schema: dict[str, Any] | None = Field(default=None, alias="outputSchema")
    annotations: ActionAnnotations | None = None
    timeout_ms: int | None = Field(default=None, alias="timeoutMs")
    strict_output: bool = Field(default=False, alias="strictOutput")


# ---------------------------------------------------------------------------
# Resource manifest types
# ---------------------------------------------------------------------------


class ResourceManifestEntry(BaseModel):
    """A single resource declared in tesseron/hello.

    Attributes:
        name: Resource name.
        description: Human-readable description.
        subscribable: Whether the resource supports subscriptions.
        output_schema: Optional JSON Schema for the resource value.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    description: str = ""
    subscribable: bool = False
    output_schema: dict[str, Any] | None = Field(default=None, alias="outputSchema")


# ---------------------------------------------------------------------------
# Handshake message params
# ---------------------------------------------------------------------------


class HelloParams(BaseModel):
    """Parameters for the tesseron/hello request.

    Attributes:
        protocol_version: MUST be "1.2.0".
        app: App identity.
        actions: List of declared actions.
        resources: List of declared resources.
        capabilities: What the app can do.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    protocol_version: str = Field(default="1.2.0", alias="protocolVersion")
    app: AppMetadata
    actions: list[ActionManifestEntry] = Field(default_factory=list)
    resources: list[ResourceManifestEntry] = Field(default_factory=list)
    capabilities: TesseronCapabilities = Field(default_factory=TesseronCapabilities)


class WelcomeResult(BaseModel):
    """The result payload of the tesseron/hello response.

    Attributes:
        session_id: Opaque session identifier.
        protocol_version: Gateway's protocol version.
        capabilities: Intersection of app and agent capabilities.
        agent: Identity of the connected agent.
        claim_code: 6-character human-friendly claim code (XXXX-XX).
            Present on hello, absent on resume.
        resume_token: Token for session resume.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    session_id: str = Field(alias="sessionId")
    protocol_version: str = Field(alias="protocolVersion")
    capabilities: TesseronCapabilities
    agent: AgentIdentity
    claim_code: str | None = Field(default=None, alias="claimCode")
    resume_token: str | None = Field(default=None, alias="resumeToken")


class ResumeParams(BaseModel):
    """Parameters for the tesseron/resume request.

    Carries the same app/actions/resources/capabilities as HelloParams
    because the app may have changed since the previous connection.

    Attributes:
        protocol_version: MUST be "1.2.0".
        session_id: The session to rejoin.
        resume_token: The token received in the previous welcome.
        app: App identity (may have changed).
        actions: Current action list.
        resources: Current resource list.
        capabilities: Current capabilities.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    protocol_version: str = Field(default="1.2.0", alias="protocolVersion")
    session_id: str = Field(alias="sessionId")
    resume_token: str = Field(alias="resumeToken")
    app: AppMetadata
    actions: list[ActionManifestEntry] = Field(default_factory=list)
    resources: list[ResourceManifestEntry] = Field(default_factory=list)
    capabilities: TesseronCapabilities = Field(default_factory=TesseronCapabilities)


class ClaimedParams(BaseModel):
    """Parameters for the tesseron/claimed notification.

    Sent by the gateway when a session is claimed.

    Attributes:
        agent: Real agent identity.
        claimed_at: Unix epoch milliseconds when claim occurred.
        agent_capabilities: Updated capabilities (authoritative after claim).

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    agent: AgentIdentity
    claimed_at: int = Field(alias="claimedAt")
    agent_capabilities: TesseronCapabilities | None = Field(default=None, alias="agentCapabilities")


# ---------------------------------------------------------------------------
# Action invocation types
# ---------------------------------------------------------------------------


class ActionInvokeParams(BaseModel):
    """Parameters for the actions/invoke request (gateway -> app).

    Attributes:
        name: Action name (without the app.id__ prefix).
        invocation_id: Unique ID for this invocation.
        input: The arguments the agent passed.
        client: Optional contextual metadata.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    invocation_id: str = Field(alias="invocationId")
    input: Any = None
    client: dict[str, Any] | None = None


class InvocationResult(BaseModel):
    """The result payload of an actions/invoke response.

    Attributes:
        invocation_id: The invocationId from the request (echoed).
        output: The handler's return value.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    invocation_id: str = Field(alias="invocationId")
    output: Any


class ActionCancelParams(BaseModel):
    """Parameters for the actions/cancel notification (gateway -> app).

    Attributes:
        invocation_id: The invocation to cancel.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    invocation_id: str = Field(alias="invocationId")


class ActionProgressParams(BaseModel):
    """Parameters for the actions/progress notification (app -> gateway).

    Attributes:
        invocation_id: Correlates to the active invocation.
        message: Optional short status line shown to the user.
        percent: Optional completion percentage (0-100).
        data: Optional free-form structured data.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    invocation_id: str = Field(alias="invocationId")
    message: str | None = None
    percent: float | None = None
    data: Any | None = None


class ActionsListChangedParams(BaseModel):
    """Parameters for the actions/list_changed notification (app -> gateway).

    Attributes:
        actions: The full updated action manifest.

    """

    model_config = ConfigDict(extra="ignore")

    actions: list[ActionManifestEntry]


# ---------------------------------------------------------------------------
# Resource operation types
# ---------------------------------------------------------------------------


class ResourceReadParams(BaseModel):
    """Parameters for resources/read (gateway -> app, request).

    Attributes:
        name: Resource name.

    """

    model_config = ConfigDict(extra="ignore")

    name: str


class ResourceReadResult(BaseModel):
    """Result of resources/read.

    Attributes:
        value: The current resource value.

    """

    model_config = ConfigDict(extra="ignore")

    value: Any


class ResourceSubscribeParams(BaseModel):
    """Parameters for resources/subscribe (gateway -> app, request).

    Attributes:
        name: Resource name.
        subscription_id: Gateway-assigned subscription identifier.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    name: str
    subscription_id: str = Field(alias="subscriptionId")


class ResourceUnsubscribeParams(BaseModel):
    """Parameters for resources/unsubscribe (gateway -> app, request).

    Attributes:
        subscription_id: The subscription to cancel.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    subscription_id: str = Field(alias="subscriptionId")


class ResourceUpdatedParams(BaseModel):
    """Parameters for resources/updated notification (app -> gateway).

    Attributes:
        subscription_id: The subscription this update belongs to.
        value: The new resource value.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    subscription_id: str = Field(alias="subscriptionId")
    value: Any


class ResourcesListChangedParams(BaseModel):
    """Parameters for resources/list_changed notification (app -> gateway).

    Attributes:
        resources: The full updated resource manifest.

    """

    model_config = ConfigDict(extra="ignore")

    resources: list[ResourceManifestEntry]


# ---------------------------------------------------------------------------
# Sampling types
# ---------------------------------------------------------------------------


class SamplingRequestParams(BaseModel):
    """Parameters for sampling/request (app -> gateway, request).

    Attributes:
        invocation_id: The current invocation context.
        prompt: Prompt sent to the agent's LLM.
        json_schema: Optional JSON Schema to constrain the response.
            Aliased as "schema" on the wire.
        max_tokens: Optional maximum token count.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    invocation_id: str = Field(alias="invocationId")
    prompt: str
    json_schema: dict[str, Any] | None = Field(default=None, alias="schema")
    max_tokens: int | None = Field(default=None, alias="maxTokens")


class SamplingResult(BaseModel):
    """Result of sampling/request.

    Attributes:
        content: The LLM's response content.

    """

    model_config = ConfigDict(extra="ignore")

    content: str


# ---------------------------------------------------------------------------
# Elicitation types
# ---------------------------------------------------------------------------


class ElicitationRequestParams(BaseModel):
    """Parameters for elicitation/request (app -> gateway, request).

    Attributes:
        invocation_id: The current invocation context.
        question: Question shown to the user.
        json_schema: JSON Schema for the requested input.
            Aliased as "schema" on the wire.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    invocation_id: str = Field(alias="invocationId")
    question: str
    json_schema: dict[str, Any] = Field(alias="schema")


class ElicitationResult(BaseModel):
    """Result of elicitation/request.

    Attributes:
        action: The user's response (accept, decline, or cancel).
        value: Present only when action == "accept".

    """

    model_config = ConfigDict(extra="ignore")

    action: Literal["accept", "decline", "cancel"]
    value: Any | None = None


# ---------------------------------------------------------------------------
# Discovery manifest types
# ---------------------------------------------------------------------------


class WsTransport(BaseModel):
    """WebSocket transport descriptor in the instance manifest.

    Attributes:
        kind: Always "ws".
        url: WebSocket URL (must be loopback).

    """

    model_config = ConfigDict(extra="ignore")

    kind: Literal["ws"] = "ws"
    url: str


class UdsTransport(BaseModel):
    """Unix Domain Socket transport descriptor in the instance manifest.

    Attributes:
        kind: Always "uds".
        path: Absolute path to the socket file.

    """

    model_config = ConfigDict(extra="ignore")

    kind: Literal["uds"] = "uds"
    path: str


class InstanceManifest(BaseModel):
    """Instance manifest written to ~/.tesseron/instances/<instanceId>.json.

    Attributes:
        version: MUST be 2.
        instance_id: Unique ID for this running instance (should use inst- prefix).
        app_name: Human-readable name for logging.
        added_at: Unix epoch milliseconds when manifest was written.
        pid: Optional process ID of the SDK process.
        transport: Discriminated union of WsTransport or UdsTransport.

    """

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    version: Literal[2] = 2
    instance_id: str = Field(alias="instanceId")
    app_name: str = Field(alias="appName")
    added_at: int = Field(alias="addedAt")
    pid: int | None = None
    transport: WsTransport | UdsTransport


# ---------------------------------------------------------------------------
# Session state enum (stub for state transition tests)
# ---------------------------------------------------------------------------


class SessionState:
    """Enumeration of session lifecycle states.

    See spec §14.1 for the state definitions.

    States:
        DISCONNECTED: No transport connection.
        HANDSHAKING: Transport open, tesseron/hello in flight.
        AWAITING_CLAIM: welcome received with claimCode.
        CLAIMED: Agent submitted a matching claim. Actions can be invoked.
        CLOSED: Transport closed.
    """

    DISCONNECTED = "DISCONNECTED"
    HANDSHAKING = "HANDSHAKING"
    AWAITING_CLAIM = "AWAITING_CLAIM"
    CLAIMED = "CLAIMED"
    CLOSED = "CLOSED"
