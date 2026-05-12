"""Gateway resume manager.

Design Contract: DC-024 (GatewayResumeManager)
Spec Reference: §15 (Session Resume)

Manages zombie sessions for resumption after transport disconnect.

Guarantees:
- Retain disconnected sessions as zombies for configurable TTL (default 90s) (REQ-132).
- Constant-time token comparison (hmac.compare_digest) to prevent timing attacks (REQ-133).
- Rotate resumeToken on successful resume (REQ-134).
- Old token rejected after rotation (REQ-134).
- Return -32011 ResumeFailed for unknown session, bad token, TTL elapsed,
  cross-app, unclaimed zombie (REQ-135).
"""

from __future__ import annotations

import hmac
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from python_tesseron.errors import ResumeFailedError
from python_tesseron.types import SessionState

logger = logging.getLogger(__name__)

# Default zombie TTL in seconds (REQ-132)
DEFAULT_ZOMBIE_TTL_S = 90


@dataclass
class ZombieSession:
    """A disconnected session retained for potential resume.

    Attributes:
        session_id: The original session ID.
        app_id: The app that owned the session.
        resume_token: Current valid resume token.
        disconnected_at: Unix timestamp when the session disconnected.
        was_claimed: Whether the session was in CLAIMED state when it disconnected.
        actions: Actions from the session.
        resources: Resources from the session.
        negotiated_capabilities: The negotiated capabilities.

    """

    session_id: str
    app_id: str
    resume_token: str
    disconnected_at: float
    was_claimed: bool
    actions: list[Any] = field(default_factory=list)
    resources: list[Any] = field(default_factory=list)
    negotiated_capabilities: Any = None


class GatewayResumeManager:
    """Manages zombie sessions for session resumption.

    Design Contract: DC-024 (GatewayResumeManager)

    Retains disconnected sessions as zombies for a configurable TTL and
    validates resume attempts with constant-time token comparison.

    Attributes:
        _zombie_ttl_s: TTL in seconds for zombie sessions.
        _zombies: Map of session_id -> ZombieSession.

    """

    def __init__(self, zombie_ttl_s: float = DEFAULT_ZOMBIE_TTL_S) -> None:
        """Initialise the resume manager.

        Args:
            zombie_ttl_s: TTL for zombie sessions in seconds. Default 90s (REQ-132).

        """
        self._zombie_ttl_s = zombie_ttl_s
        self._zombies: dict[str, ZombieSession] = {}

    def retain_as_zombie(self, session: Any) -> None:
        """Retain a disconnected session as a zombie for potential resume.

        Called when a CLAIMED session's transport closes.
        Unclaimed sessions (never claimed) cannot be resumed (REQ-135).

        REQ-132: retain disconnected sessions as zombies.

        Args:
            session: The GatewaySession that disconnected.

        """
        # Only retain if the session was claimed (REQ-135: unclaimed zombie fails)
        if session.state == SessionState.CLAIMED or session.is_claimed:
            was_claimed = True
        else:
            was_claimed = False

        if session.resume_token is None:
            logger.debug("Session %s has no resume token, not retaining as zombie", session.session_id)
            return

        zombie = ZombieSession(
            session_id=session.session_id,
            app_id=session.app_id or "",
            resume_token=session.resume_token,
            disconnected_at=time.time(),
            was_claimed=was_claimed,
            actions=list(session.actions),
            resources=list(session.resources),
            negotiated_capabilities=session.negotiated_capabilities,
        )
        self._zombies[session.session_id] = zombie
        logger.info(
            "Retained zombie: session=%s app=%s was_claimed=%s ttl=%ss",
            session.session_id,
            session.app_id,
            was_claimed,
            self._zombie_ttl_s,
        )

    def _is_ttl_valid(self, zombie: ZombieSession, now: float | None = None) -> bool:
        """Check if a zombie is still within its TTL.

        Per REQ-132: resume at exactly TTL seconds succeeds (boundary valid).

        Args:
            zombie: The zombie to check.
            now: Override current time for testing (defaults to time.time()).

        Returns:
            True if zombie is within TTL (elapsed <= ttl).

        """
        if now is None:
            now = time.time()
        elapsed = now - zombie.disconnected_at
        return elapsed <= self._zombie_ttl_s

    def validate_and_resume(
        self,
        session_id: str,
        resume_token: str,
        requesting_app_id: str | None = None,
        now: float | None = None,
    ) -> ZombieSession:
        """Validate a resume attempt and return the zombie session if valid.

        REQ-133: constant-time comparison.
        REQ-134: token rotation (caller must call rotate_token after use).
        REQ-135: failure conditions.

        Args:
            session_id: Session ID to resume.
            resume_token: Resume token to validate.
            requesting_app_id: Optional app ID for cross-app validation (REQ-135).
            now: Override current time for testing.

        Returns:
            The valid ZombieSession ready for resumption.

        Raises:
            ResumeFailedError: For any failure condition (-32011).

        """
        zombie = self._zombies.get(session_id)

        # REQ-135: unknown session
        if zombie is None:
            raise ResumeFailedError("Session not found or already cleaned up")

        # REQ-135: unclaimed zombie
        if not zombie.was_claimed:
            raise ResumeFailedError("Session was never claimed and cannot be resumed")

        # REQ-135: cross-app validation
        if requesting_app_id is not None and zombie.app_id != requesting_app_id:
            raise ResumeFailedError("Cross-app resume is not permitted")

        # REQ-133: constant-time comparison
        tokens_match = hmac.compare_digest(
            zombie.resume_token.encode(),
            resume_token.encode(),
        )

        # REQ-135: bad token
        if not tokens_match:
            raise ResumeFailedError("Invalid resume token")

        # REQ-135: TTL elapsed
        if not self._is_ttl_valid(zombie, now):
            # Remove expired zombie
            self._zombies.pop(session_id, None)
            raise ResumeFailedError("Session resume TTL has elapsed")

        return zombie

    def rotate_token(self, session_id: str) -> str:
        """Rotate the resume token for a zombie session.

        Per REQ-134: rotate the resumeToken on successful resume.
        The old token must be rejected after rotation.

        Args:
            session_id: Session whose token to rotate.

        Returns:
            The new resume token.

        Raises:
            ResumeFailedError: If session_id not found in zombies.

        """
        zombie = self._zombies.get(session_id)
        if zombie is None:
            raise ResumeFailedError("Session not found for token rotation")

        new_token = secrets.token_urlsafe(32)
        zombie.resume_token = new_token
        logger.debug("Rotated resume token for session %s", session_id)
        return new_token

    def remove_zombie(self, session_id: str) -> None:
        """Remove a zombie session (after successful resume or TTL expiry).

        Args:
            session_id: Session to remove from zombie registry.

        """
        self._zombies.pop(session_id, None)
        logger.debug("Removed zombie session %s", session_id)

    def get_zombie(self, session_id: str) -> ZombieSession | None:
        """Retrieve a zombie session by ID.

        Args:
            session_id: Session ID to look up.

        Returns:
            ZombieSession if found, None otherwise.

        """
        return self._zombies.get(session_id)

    def purge_expired(self, now: float | None = None) -> int:
        """Remove all zombie sessions whose TTL has elapsed.

        Args:
            now: Override current time for testing.

        Returns:
            Number of zombies purged.

        """
        if now is None:
            now = time.time()
        expired = [sid for sid, z in self._zombies.items() if not self._is_ttl_valid(z, now)]
        for sid in expired:
            self._zombies.pop(sid, None)
            logger.debug("Purged expired zombie session %s", sid)
        return len(expired)
