"""Session resume flow for the Tesseron protocol.

Design Contract: DC-014 (SessionResume)
Spec Reference: §6 (Session Resume)

Guarantees:
- Sends tesseron/resume with stored sessionId + resumeToken (REQ-038).
- Persists rotated token on success (REQ-039).
- Clears credentials and falls back to fresh hello on failure (REQ-099).
- Re-subscribes resources after successful resume (REQ-040).
"""

from __future__ import annotations

import logging
from typing import Any

from python_tesseron.capabilities import CapabilityNegotiation
from python_tesseron.errors import TesseronError
from python_tesseron.session import SessionStateMachine
from python_tesseron.types import (
    ActionManifestEntry,
    AppMetadata,
    ResourceManifestEntry,
    ResumeParams,
    WelcomeResult,
)

logger = logging.getLogger(__name__)


class ResumeCredentials:
    """Stored credentials for session resume.

    Attributes:
        session_id: Session ID from the previous welcome.
        resume_token: Token for resuming the session.

    """

    def __init__(self, session_id: str, resume_token: str) -> None:
        """Initialise with session credentials.

        Args:
            session_id: The session ID.
            resume_token: The resume token.

        """
        self.session_id = session_id
        self.resume_token = resume_token

    def as_dict(self) -> dict[str, str]:
        """Serialise to a dict for storage.

        Returns:
            Dict with session_id and resume_token keys.

        """
        return {
            "session_id": self.session_id,
            "resume_token": self.resume_token,
        }

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> ResumeCredentials:
        """Deserialise from a stored dict.

        Args:
            data: Dict with session_id and resume_token keys.

        Returns:
            ResumeCredentials instance.

        """
        return cls(
            session_id=data["session_id"],
            resume_token=data["resume_token"],
        )


class SessionResumeManager:
    """Manages the session resume flow.

    Implements DC-014. On transport reconnect, attempts to resume a previously
    claimed session using stored credentials. On failure, clears credentials
    and falls back to fresh tesseron/hello.

    Attributes:
        _credentials: Stored session credentials, or None.
        _session: Session state machine.
        _capabilities: Capability negotiation manager.

    """

    def __init__(
        self,
        session: SessionStateMachine,
        capabilities: CapabilityNegotiation,
    ) -> None:
        """Initialise with empty credentials.

        Args:
            session: Session state machine.
            capabilities: Capability negotiation manager.

        """
        self._credentials: ResumeCredentials | None = None
        self._session = session
        self._capabilities = capabilities

    def store_credentials(self, session_id: str, resume_token: str) -> None:
        """Store credentials from a welcome response.

        Per REQ-038: stash resumeToken alongside sessionId.

        Args:
            session_id: The session ID.
            resume_token: The resume token.

        """
        self._credentials = ResumeCredentials(
            session_id=session_id,
            resume_token=resume_token,
        )
        logger.debug("Stored resume credentials for session %s", session_id)

    def clear_credentials(self) -> None:
        """Clear stored credentials.

        Per REQ-099: called on resume failure.

        """
        self._credentials = None
        logger.debug("Cleared resume credentials")

    @property
    def has_credentials(self) -> bool:
        """True if stored credentials are available for resume.

        Returns:
            True if credentials are stored.

        """
        return self._credentials is not None

    def build_resume_params(
        self,
        app_meta: AppMetadata,
        actions: list[ActionManifestEntry],
        resources: list[ResourceManifestEntry],
    ) -> dict[str, Any]:
        """Build the tesseron/resume params dict.

        Per §6.2: resume carries same app/actions/resources/capabilities as hello.

        Args:
            app_meta: App identity metadata.
            actions: Current action manifest entries.
            resources: Current resource manifest entries.

        Returns:
            ResumeParams dict.

        Raises:
            RuntimeError: If no credentials are stored.

        """
        if self._credentials is None:
            raise RuntimeError("Cannot build resume params: no stored credentials")

        from python_tesseron.capabilities import CapabilityNegotiation

        caps = CapabilityNegotiation().app_declared()

        resume = ResumeParams(
            session_id=self._credentials.session_id,
            resume_token=self._credentials.resume_token,
            app=app_meta,
            actions=actions,
            resources=resources,
            capabilities=caps,
        )
        return resume.model_dump(by_alias=True)

    def process_resume_welcome(self, result: dict[str, Any]) -> WelcomeResult:
        """Parse and store the resume welcome result.

        Per REQ-039: persist new resumeToken. The resumed session skips
        AWAITING_CLAIM and goes directly to CLAIMED (or stays there).

        Args:
            result: Raw result dict from tesseron/resume response.

        Returns:
            Parsed WelcomeResult.

        """
        welcome = WelcomeResult.model_validate(result)

        # REQ-039: persist rotated token
        if welcome.resume_token and self._credentials:
            self._credentials = ResumeCredentials(
                session_id=welcome.session_id,
                resume_token=welcome.resume_token,
            )
            logger.debug("Resume token rotated for session %s", welcome.session_id)

        self._capabilities.apply_welcome(welcome.capabilities)

        # Transition: resume skips AWAITING_CLAIM (session was already claimed)
        if self._session.state == "DISCONNECTED":
            self._session.to_handshaking()
        if self._session.state == "HANDSHAKING":
            self._session.to_awaiting_claim()
            self._session.to_claimed()

        return welcome

    async def attempt_resume(
        self,
        dispatcher: Any,
        app_meta: AppMetadata,
        actions: list[ActionManifestEntry],
        resources: list[ResourceManifestEntry],
    ) -> WelcomeResult | None:
        """Attempt a session resume.

        Sends tesseron/resume. On success, returns the WelcomeResult.
        On ResumeFailedError, clears credentials and returns None (caller
        should fall back to hello).

        Per REQ-099: clear credentials and fall back on failure.

        Args:
            dispatcher: JsonRpcDispatcher for sending the request.
            app_meta: App identity metadata.
            actions: Current action manifest.
            resources: Current resource manifest.

        Returns:
            WelcomeResult on success, None on failure.

        """
        if self._credentials is None:
            return None

        params = self.build_resume_params(app_meta, actions, resources)

        try:
            result = await dispatcher.request("tesseron/resume", params)
            return self.process_resume_welcome(result)
        except TesseronError as exc:
            if exc.code == -32011:  # ResumeFailedError
                logger.warning("Session resume failed: %s", exc.message)
                self.clear_credentials()
                return None
            raise
