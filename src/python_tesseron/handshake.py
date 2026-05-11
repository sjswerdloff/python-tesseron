"""Handshake and claiming flow for the Tesseron protocol.

Design Contract: DC-005 (HandshakeManager)
Spec Reference: §5 (Handshake and Claiming)

Guarantees:
- Sends tesseron/hello as the FIRST message after transport open (REQ-009).
- Parses WelcomeResult from the response (REQ-033).
- Handles tesseron/claimed notification: updates agent identity, clears
  claimCode, overwrites capabilities if agentCapabilities present (REQ-034,
  REQ-035, REQ-036).
- Validates app.id against /^[a-z][a-z0-9_]*$/ and rejects reserved IDs
  (REQ-031, REQ-032).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from python_tesseron.capabilities import CapabilityNegotiation
from python_tesseron.errors import InvalidParamsError, UnauthorizedError
from python_tesseron.session import SessionStateMachine
from python_tesseron.types import (
    ActionManifestEntry,
    AgentIdentity,
    AppMetadata,
    ClaimedParams,
    HelloParams,
    ResourceManifestEntry,
    WelcomeResult,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App ID constraints — §5.2, §16, REQ-031, REQ-032
# ---------------------------------------------------------------------------

# Must match /^[a-z][a-z0-9_]*$/
_APP_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# Reserved app IDs that MUST NOT be used
_RESERVED_APP_IDS = frozenset({"tesseron", "mcp", "system"})


def validate_app_id(app_id: str) -> None:
    """Validate an app.id value against spec constraints.

    Per REQ-031, app.id MUST match /^[a-z][a-z0-9_]*$/.
    Per REQ-032, reserved IDs (tesseron, mcp, system) MUST NOT be used.

    Args:
        app_id: The app identifier string to validate.

    Raises:
        InvalidParamsError: If app_id does not match the pattern.
        UnauthorizedError: If app_id is a reserved identifier.

    """
    if not _APP_ID_PATTERN.match(app_id):
        raise InvalidParamsError(
            f"app.id {app_id!r} does not match /^[a-z][a-z0-9_]*$/. "
            "Must start with a lowercase letter and contain only lowercase letters, digits, and underscores."
        )
    if app_id in _RESERVED_APP_IDS:
        raise UnauthorizedError(f"app.id {app_id!r} is reserved. Reserved IDs: {sorted(_RESERVED_APP_IDS)}")


class HandshakeManager:
    """Manages the tesseron/hello -> welcome -> claimed handshake flow.

    Implements DC-005. Coordinates with the dispatcher to send the hello
    request and process the welcome response and claimed notification.

    Attributes:
        _app_meta: Validated AppMetadata for this app.
        _session: Session state machine.
        _capabilities: Capability negotiation manager.
        _welcome: Stored WelcomeResult after successful handshake.
        _agent: Current agent identity (pending until claimed).

    """

    def __init__(
        self,
        app_meta: AppMetadata,
        session: SessionStateMachine,
        capabilities: CapabilityNegotiation,
    ) -> None:
        """Initialise the handshake manager.

        Args:
            app_meta: App identity metadata.
            session: Session state machine.
            capabilities: Capability negotiation manager.

        Raises:
            InvalidParamsError: If app_meta.id does not match the pattern.
            UnauthorizedError: If app_meta.id is reserved.

        """
        validate_app_id(app_meta.id)
        self._app_meta = app_meta
        self._session = session
        self._capabilities = capabilities
        self._welcome: WelcomeResult | None = None
        self._agent = AgentIdentity(id="pending", name="Awaiting agent")

    @property
    def welcome(self) -> WelcomeResult | None:
        """The stored welcome result, or None if handshake not yet complete.

        Returns:
            WelcomeResult after handshake, None before.

        """
        return self._welcome

    @property
    def agent(self) -> AgentIdentity:
        """The current agent identity.

        Returns:
            AgentIdentity with id="pending" until claimed.

        """
        return self._agent

    @property
    def session_id(self) -> str | None:
        """The session ID from the welcome, or None if not yet connected.

        Returns:
            Session ID string or None.

        """
        return self._welcome.session_id if self._welcome else None

    @property
    def resume_token(self) -> str | None:
        """The resume token from the welcome, or None.

        Per REQ-038, this should be stored alongside sessionId.

        Returns:
            Resume token string or None.

        """
        return self._welcome.resume_token if self._welcome else None

    def build_hello_params(
        self,
        actions: list[ActionManifestEntry],
        resources: list[ResourceManifestEntry],
    ) -> dict[str, Any]:
        """Build the tesseron/hello params dict.

        Per REQ-009, this is always the FIRST message sent after connection.
        Per REQ-100, all capabilities are declared as true.

        Args:
            actions: Current action manifest entries.
            resources: Current resource manifest entries.

        Returns:
            HelloParams dict ready for JSON-RPC serialisation.

        """
        hello = HelloParams(
            app=self._app_meta,
            actions=actions,
            resources=resources,
            capabilities=self._capabilities.app_declared(),
        )
        return hello.model_dump(by_alias=True)

    def process_welcome(self, welcome_result: dict[str, Any]) -> WelcomeResult:
        """Parse and store the welcome result from tesseron/hello response.

        Per REQ-033, the welcome capabilities represent the intersection and
        are stored as authoritative. Transitions session to AWAITING_CLAIM.

        Args:
            welcome_result: The raw result dict from the JSON-RPC response.

        Returns:
            Parsed WelcomeResult.

        """
        welcome = WelcomeResult.model_validate(welcome_result)
        self._welcome = welcome
        self._capabilities.apply_welcome(welcome.capabilities)
        self._session.to_awaiting_claim()
        logger.info(
            "Handshake complete: sessionId=%s claimCode=%s",
            welcome.session_id,
            welcome.claim_code,
        )
        return welcome

    def process_claimed(self, params: dict[str, Any]) -> None:
        """Handle the tesseron/claimed notification.

        Per REQ-034: update agent identity.
        Per REQ-035: clear claimCode.
        Per REQ-036: overwrite capabilities if agentCapabilities present.

        Args:
            params: The raw notification params dict.

        """
        claimed = ClaimedParams.model_validate(params)

        # REQ-034: update agent identity
        self._agent = claimed.agent

        # REQ-035: clear claim code (it has been consumed)
        if self._welcome is not None:
            # Create updated welcome with claim_code cleared
            data = self._welcome.model_dump(by_alias=True)
            data["claimCode"] = None
            self._welcome = WelcomeResult.model_validate(data)

        # REQ-036: overwrite capabilities if present
        self._capabilities.apply_claimed(claimed.agent_capabilities)

        # Transition session to CLAIMED
        if self._session.state == "AWAITING_CLAIM":
            self._session.to_claimed()

        logger.info(
            "Session claimed by agent: id=%s name=%s",
            claimed.agent.id,
            claimed.agent.name,
        )
