"""Gateway session manager.

Design Contract: DC-019 (GatewaySessionManager)
Spec Reference: §5, §14.1, §14.3, §16.1

Manages the server-side session state machine for inbound app connections.

States: DISCONNECTED -> HANDSHAKING -> AWAITING_CLAIM -> CLAIMED -> CLOSED

Guarantees:
- Session state machine with valid/invalid transition enforcement (REQ-141).
- Claim code generation: CSPRNG, format XXXX-XX, unambiguous alphabet,
  printed to stderr (REQ-110, REQ-111, REQ-112).
- Single-use claim codes; wrong code returns -32009 (REQ-110, REQ-137).
- Capability intersection: AND across four capabilities (REQ-114).
- Welcome response: sessionId, protocolVersion, capabilities, claimCode,
  resumeToken (REQ-113).
- Claimed notification: agentIdentity, claimedAt, agentCapabilities (REQ-115).
- Protocol version validation: reject major mismatch with -32000 (REQ-116).
- Multi-session support: independent state per session (REQ-139).
- Close cascade: reject pending, fire cancellation signals, clean
  subscriptions (REQ-142, REQ-143, REQ-144).
- Authorization: reject actions on unclaimed sessions with -32009 (REQ-136).
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import sys
import time
import uuid
from collections.abc import Callable
from typing import Any

from python_tesseron.dispatcher import JsonRpcDispatcher
from python_tesseron.errors import (
    ProtocolMismatchError,
    TransportClosedError,
    UnauthorizedError,
)
from python_tesseron.types import (
    ActionManifestEntry,
    AgentIdentity,
    HelloParams,
    ResourceManifestEntry,
    SessionState,
    TesseronCapabilities,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Claim code alphabet and format (REQ-110, REQ-111)
# ---------------------------------------------------------------------------

# 31-char unambiguous alphabet: excludes O, 0, 1, I, L
_CLAIM_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# Gateway protocol version
_GATEWAY_PROTOCOL_VERSION = "1.2.0"


def _generate_claim_code() -> str:
    """Generate a single-use CSPRNG claim code in XXXX-XX format.

    Uses secrets.choice for cryptographic randomness (REQ-110).
    Alphabet excludes ambiguous characters O, 0, 1, I, L (REQ-111).

    Returns:
        Claim code string matching ^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{2}$.

    """
    part1 = "".join(secrets.choice(_CLAIM_ALPHABET) for _ in range(4))
    part2 = "".join(secrets.choice(_CLAIM_ALPHABET) for _ in range(2))
    return f"{part1}-{part2}"


def _intersect_capabilities(
    app_caps: TesseronCapabilities,
    agent_caps: TesseronCapabilities,
) -> TesseronCapabilities:
    """Compute the capability intersection for a session.

    Per REQ-114: a capability is enabled only when BOTH app and agent
    declare it as true.

    Args:
        app_caps: Capabilities declared by the app in tesseron/hello.
        agent_caps: Capabilities declared by the agent when claiming.

    Returns:
        TesseronCapabilities with each flag set to the AND of both sides.

    """
    return TesseronCapabilities(
        streaming=app_caps.streaming and agent_caps.streaming,
        subscriptions=app_caps.subscriptions and agent_caps.subscriptions,
        sampling=app_caps.sampling and agent_caps.sampling,
        elicitation=app_caps.elicitation and agent_caps.elicitation,
    )


class GatewaySession:
    """Server-side session object representing one connected app.

    Tracks the state machine, dispatcher, metadata, and cleanup state
    for a single inbound app connection.

    Attributes:
        session_id: Unique session identifier.
        state: Current session lifecycle state.
        app_id: The app identifier from tesseron/hello (set after handshake).
        actions: Actions declared by the app.
        resources: Resources declared by the app.
        app_capabilities: Capabilities declared by the app.
        negotiated_capabilities: Intersection capabilities after claim.
        claim_code: Current one-time claim code; None after consumed.
        resume_token: Current resume token for this session.
        dispatcher: JsonRpcDispatcher for this session's connection.
        agent_identity: Agent identity after claim; None before.

    """

    def __init__(self) -> None:
        """Initialise a new gateway session in DISCONNECTED state."""
        self.session_id: str = str(uuid.uuid4())
        self.state: str = SessionState.DISCONNECTED
        self.app_id: str | None = None
        self.actions: list[ActionManifestEntry] = []
        self.resources: list[ResourceManifestEntry] = []
        self.app_capabilities: TesseronCapabilities = TesseronCapabilities()
        self.negotiated_capabilities: TesseronCapabilities = TesseronCapabilities()
        self.claim_code: str | None = None
        self.resume_token: str | None = None
        self.dispatcher: JsonRpcDispatcher | None = None
        self.agent_identity: AgentIdentity | None = None
        self.claimed_at: int | None = None

        # Close cascade tracking
        self._closed = False
        self._invocation_cancel_fns: dict[str, Callable[[], None]] = {}
        self._subscription_cleanup_fns: dict[str, Callable[[], None]] = {}

        # Callbacks fired when session events occur
        self._on_connect_callbacks: list[Callable[[GatewaySession], Any]] = []
        self._on_claimed_callbacks: list[Callable[[GatewaySession], Any]] = []
        self._on_drop_callbacks: list[Callable[[GatewaySession], Any]] = []

    # ------------------------------------------------------------------
    # State transitions (REQ-141)
    # ------------------------------------------------------------------

    def to_handshaking(self) -> None:
        """Transition DISCONNECTED -> HANDSHAKING.

        REQ-141: valid transition on WebSocket open.

        Raises:
            RuntimeError: If current state is not DISCONNECTED.

        """
        if self.state != SessionState.DISCONNECTED:
            raise RuntimeError(f"Cannot transition to HANDSHAKING from {self.state}")
        self.state = SessionState.HANDSHAKING
        logger.debug("GatewaySession %s: DISCONNECTED -> HANDSHAKING", self.session_id)

    def to_awaiting_claim(self) -> None:
        """Transition HANDSHAKING -> AWAITING_CLAIM.

        REQ-141: valid transition after welcome is sent.

        Raises:
            RuntimeError: If current state is not HANDSHAKING.

        """
        if self.state != SessionState.HANDSHAKING:
            raise RuntimeError(f"Cannot transition to AWAITING_CLAIM from {self.state}")
        self.state = SessionState.AWAITING_CLAIM
        logger.debug("GatewaySession %s: HANDSHAKING -> AWAITING_CLAIM", self.session_id)

    def to_claimed(self) -> None:
        """Transition AWAITING_CLAIM -> CLAIMED.

        REQ-141: valid transition when agent claims session.

        Raises:
            RuntimeError: If current state is not AWAITING_CLAIM.

        """
        if self.state != SessionState.AWAITING_CLAIM:
            raise RuntimeError(f"Cannot transition to CLAIMED from {self.state}")
        self.state = SessionState.CLAIMED
        logger.debug("GatewaySession %s: AWAITING_CLAIM -> CLAIMED", self.session_id)

    def to_closed(self) -> None:
        """Transition to CLOSED from any non-CLOSED state.

        REQ-141: valid from any state. No-op if already closed.

        """
        if self.state == SessionState.CLOSED:
            return
        previous = self.state
        self.state = SessionState.CLOSED
        logger.debug("GatewaySession %s: %s -> CLOSED", self.session_id, previous)

    # ------------------------------------------------------------------
    # Close cascade (REQ-142, REQ-143, REQ-144)
    # ------------------------------------------------------------------

    def register_invocation(self, invocation_id: str, cancel_fn: Callable[[], None]) -> None:
        """Track an in-flight action invocation for cancellation on close.

        REQ-143: in-flight invocations must receive cancellation signals on close.

        Args:
            invocation_id: Unique invocation identifier.
            cancel_fn: Zero-argument callable that fires the cancellation signal.

        """
        self._invocation_cancel_fns[invocation_id] = cancel_fn

    def unregister_invocation(self, invocation_id: str) -> None:
        """Remove a completed invocation from cancellation tracking.

        Args:
            invocation_id: Invocation to remove.

        """
        self._invocation_cancel_fns.pop(invocation_id, None)

    def register_subscription(self, subscription_id: str, cleanup_fn: Callable[[], None]) -> None:
        """Track an active subscription for cleanup on close.

        REQ-144: active subscriptions must be cleaned up on transport close.

        Args:
            subscription_id: Unique subscription identifier.
            cleanup_fn: Zero-argument callable to run on cleanup.

        """
        self._subscription_cleanup_fns[subscription_id] = cleanup_fn

    def unregister_subscription(self, subscription_id: str) -> None:
        """Unsubscribe and call cleanup function.

        Args:
            subscription_id: Subscription to clean up.

        """
        cleanup_fn = self._subscription_cleanup_fns.pop(subscription_id, None)
        if cleanup_fn is not None:
            try:
                cleanup_fn()
            except Exception:
                logger.exception("Cleanup fn failed for subscription %s", subscription_id)

    async def perform_close_cascade(self) -> None:
        """Execute the close cascade operations.

        REQ-142: pending outbound requests rejected with TransportClosedError.
        REQ-143: in-flight invocations receive cancellation signals.
        REQ-144: active subscriptions cleaned up.

        """
        if self._closed:
            return
        self._closed = True

        error = TransportClosedError()

        # REQ-143: cancel in-flight invocations
        cancel_fns = dict(self._invocation_cancel_fns)
        self._invocation_cancel_fns.clear()
        for inv_id, cancel_fn in cancel_fns.items():
            try:
                cancel_fn()
                logger.debug("Fired cancel for invocation %s", inv_id)
            except Exception:
                logger.exception("Error firing cancel for invocation %s", inv_id)

        # REQ-144: clean up subscriptions
        cleanup_fns = dict(self._subscription_cleanup_fns)
        self._subscription_cleanup_fns.clear()
        for sub_id, cleanup_fn in cleanup_fns.items():
            try:
                cleanup_fn()
                logger.debug("Cleaned up subscription %s", sub_id)
            except Exception:
                logger.exception("Error cleaning up subscription %s", sub_id)

        # REQ-142: reject pending dispatcher requests
        if self.dispatcher is not None:
            await self.dispatcher.reject_all_pending(error)

        # Fire drop callbacks
        for cb in self._on_drop_callbacks:
            try:
                cb(self)
            except Exception:
                logger.exception("Error in drop callback for session %s", self.session_id)

    @property
    def is_claimed(self) -> bool:
        """True when session is in CLAIMED state.

        Returns:
            True if and only if state == CLAIMED.

        """
        return self.state == SessionState.CLAIMED


class GatewaySessionManager:
    """Manages all active gateway sessions.

    Design Contract: DC-019 (GatewaySessionManager)

    Provides hello/welcome exchange, claim code generation and validation,
    capability intersection, multi-session tracking, and close cascade.

    Attributes:
        _sessions: Map of session_id -> GatewaySession.
        _on_connect_callbacks: Called when a new session connects.
        _on_claimed_callbacks: Called when a session is claimed.
        _on_drop_callbacks: Called when a session drops.

    """

    def __init__(self) -> None:
        """Initialise the session manager with empty session registry."""
        self._sessions: dict[str, GatewaySession] = {}
        self._on_connect_callbacks: list[Callable[[GatewaySession], Any]] = []
        self._on_claimed_callbacks: list[Callable[[GatewaySession], Any]] = []
        self._on_drop_callbacks: list[Callable[[GatewaySession], Any]] = []
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_connect(self, cb: Callable[[GatewaySession], Any]) -> None:
        """Register a callback invoked when a new session is created.

        Args:
            cb: Callable receiving the GatewaySession.

        """
        self._on_connect_callbacks.append(cb)

    def on_claimed(self, cb: Callable[[GatewaySession], Any]) -> None:
        """Register a callback invoked when a session is claimed.

        Args:
            cb: Callable receiving the GatewaySession.

        """
        self._on_claimed_callbacks.append(cb)

    def on_drop(self, cb: Callable[[GatewaySession], Any]) -> None:
        """Register a callback invoked when a session closes.

        Args:
            cb: Callable receiving the GatewaySession.

        """
        self._on_drop_callbacks.append(cb)

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def create_session(self, dispatcher: JsonRpcDispatcher) -> GatewaySession:
        """Create a new session and register it.

        Transitions the session to HANDSHAKING immediately.

        Per REQ-139: each session has independent state.

        Args:
            dispatcher: JsonRpcDispatcher for this connection.

        Returns:
            Newly created GatewaySession in HANDSHAKING state.

        """
        session = GatewaySession()
        session.dispatcher = dispatcher
        session.to_handshaking()
        self._sessions[session.session_id] = session

        # Fire connect callbacks
        for cb in self._on_connect_callbacks:
            try:
                cb(session)
            except Exception:
                logger.exception("Error in connect callback")

        logger.debug("Created session %s", session.session_id)
        return session

    def get_session(self, session_id: str) -> GatewaySession | None:
        """Retrieve a session by ID.

        Args:
            session_id: The session identifier.

        Returns:
            GatewaySession if found, None otherwise.

        """
        return self._sessions.get(session_id)

    def get_session_by_app_id(self, app_id: str) -> GatewaySession | None:
        """Find an active CLAIMED session by app_id.

        Args:
            app_id: The app identifier.

        Returns:
            The first CLAIMED session for that app_id, or None.

        """
        for session in self._sessions.values():
            if session.app_id == app_id and session.is_claimed:
                return session
        return None

    def all_sessions(self) -> list[GatewaySession]:
        """Return a snapshot list of all sessions.

        Returns:
            List of all GatewaySession objects.

        """
        return list(self._sessions.values())

    def pending_sessions(self) -> list[GatewaySession]:
        """Return all sessions awaiting claim.

        Returns:
            List of sessions in AWAITING_CLAIM state.

        """
        return [s for s in self._sessions.values() if s.state == SessionState.AWAITING_CLAIM]

    async def close_session(self, session: GatewaySession) -> None:
        """Transition a session to CLOSED and run close cascade.

        REQ-142, REQ-143, REQ-144.

        Args:
            session: The GatewaySession to close.

        """
        was_claimed = session.is_claimed
        session.to_closed()
        await session.perform_close_cascade()
        self._sessions.pop(session.session_id, None)

        if was_claimed:
            for cb in self._on_drop_callbacks:
                try:
                    cb(session)
                except Exception:
                    logger.exception("Error in drop callback for session %s", session.session_id)

    # ------------------------------------------------------------------
    # Hello / Welcome exchange (REQ-113, REQ-116)
    # ------------------------------------------------------------------

    async def handle_hello(
        self,
        session: GatewaySession,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Process tesseron/hello and return welcome result.

        REQ-113: welcome must contain sessionId, protocolVersion,
                 capabilities, claimCode, resumeToken.
        REQ-116: reject major version mismatch with -32000.
        REQ-110, REQ-111, REQ-112: generate and print claim code.

        Args:
            session: The session receiving the hello.
            params: Raw params from the JSON-RPC request.

        Returns:
            Welcome result dict.

        Raises:
            ProtocolMismatchError: If major version in hello doesn't match.

        """
        if params is None:
            params = {}

        hello = HelloParams.model_validate(params)

        # REQ-116: validate major version
        gateway_major = int(_GATEWAY_PROTOCOL_VERSION.split(".")[0])
        try:
            app_major = int(hello.protocol_version.split(".")[0])
        except (ValueError, IndexError) as exc:
            raise ProtocolMismatchError(f"Cannot parse protocolVersion: {hello.protocol_version!r}") from exc

        if app_major != gateway_major:
            raise ProtocolMismatchError(
                f"Protocol major version mismatch: app={hello.protocol_version!r}, gateway={_GATEWAY_PROTOCOL_VERSION!r}"
            )

        # Store app metadata
        session.app_id = hello.app.id
        session.actions = hello.actions
        session.resources = hello.resources
        session.app_capabilities = hello.capabilities

        # Generate claim code (REQ-110, REQ-111)
        claim_code = _generate_claim_code()
        session.claim_code = claim_code

        # Generate resume token
        resume_token = secrets.token_urlsafe(32)
        session.resume_token = resume_token

        # Print claim code to stderr (REQ-112)
        print(f"Tesseron claim code: {claim_code}", file=sys.stderr, flush=True)

        # Transition to AWAITING_CLAIM
        session.to_awaiting_claim()

        # Build welcome result (REQ-113)
        # At hello time, capabilities are not yet intersected (agent not yet known).
        # Return app capabilities as initial; will be updated on claim.
        welcome: dict[str, Any] = {
            "sessionId": session.session_id,
            "protocolVersion": _GATEWAY_PROTOCOL_VERSION,
            "capabilities": session.app_capabilities.model_dump(),
            "claimCode": claim_code,
            "resumeToken": resume_token,
        }

        # Fire connect callbacks (session now has app_id)
        for cb in self._on_connect_callbacks:
            try:
                cb(session)
            except Exception:
                logger.exception("Error in connect callback after hello")

        logger.info(
            "Hello processed: session=%s app=%s claimCode=%s",
            session.session_id,
            session.app_id,
            claim_code,
        )
        return welcome

    # ------------------------------------------------------------------
    # Claim (REQ-110, REQ-114, REQ-115, REQ-136, REQ-137)
    # ------------------------------------------------------------------

    async def handle_claim(
        self,
        session_id: str,
        claim_code: str,
        agent_identity: AgentIdentity | None = None,
        agent_capabilities: TesseronCapabilities | None = None,
    ) -> dict[str, Any]:
        """Validate claim code and transition session to CLAIMED.

        REQ-110: claim code is single-use.
        REQ-114: compute capability intersection.
        REQ-115: send tesseron/claimed notification to app.
        REQ-136, REQ-137: wrong code -> -32009 Unauthorized.

        Args:
            session_id: Session to claim.
            claim_code: The claim code submitted by the agent.
            agent_identity: Agent identity (defaults to pending).
            agent_capabilities: Agent-declared capabilities (defaults to all-true).

        Returns:
            Result dict with sessionId and negotiated capabilities.

        Raises:
            UnauthorizedError: If session not found, not in AWAITING_CLAIM,
                or claim code does not match.

        """
        async with self._lock:
            session = self._sessions.get(session_id)

            if session is None or session.state != SessionState.AWAITING_CLAIM:
                raise UnauthorizedError("Session not found or not awaiting claim")

            if session.claim_code is None:
                raise UnauthorizedError("Claim code already consumed")

            # Constant-time comparison is not needed here since we're checking
            # claim codes (short-lived, not crypto tokens). But we use hmac for
            # resume tokens.  For claim codes, equality check is fine.
            if claim_code != session.claim_code:
                raise UnauthorizedError("Invalid claim code")

            # Consume the claim code (REQ-110: single-use)
            session.claim_code = None

            # Default agent identity and capabilities
            if agent_identity is None:
                agent_identity = AgentIdentity(id="agent", name="Agent")
            if agent_capabilities is None:
                agent_capabilities = TesseronCapabilities()

            # Compute capability intersection (REQ-114)
            negotiated = _intersect_capabilities(session.app_capabilities, agent_capabilities)
            session.negotiated_capabilities = negotiated
            session.agent_identity = agent_identity
            session.claimed_at = int(time.time() * 1000)

            # Transition to CLAIMED
            session.to_claimed()

        # Send tesseron/claimed notification to the app (REQ-115)
        if session.dispatcher is not None:
            claimed_params: dict[str, Any] = {
                "agentIdentity": agent_identity.model_dump(),
                "claimedAt": session.claimed_at,
                "agentCapabilities": agent_capabilities.model_dump(),
            }
            await session.dispatcher.notify("tesseron/claimed", claimed_params)

        # Fire claimed callbacks
        for cb in self._on_claimed_callbacks:
            try:
                cb(session)
            except Exception:
                logger.exception("Error in claimed callback for session %s", session_id)

        logger.info(
            "Session claimed: session=%s agent=%s",
            session_id,
            agent_identity.id,
        )
        return {
            "sessionId": session_id,
            "capabilities": negotiated.model_dump(),
        }
