"""Capability negotiation for the Tesseron protocol.

Design Contract: DC-011 (CapabilityNegotiation)
Spec Reference: §12 (Capability Negotiation)

Guarantees:
- App declares all four capabilities as true in hello (REQ-100).
- Welcome capabilities represent the negotiated intersection.
- On tesseron/claimed: overwrite with agentCapabilities if present (REQ-036).
- Provides authoritative capability set for handler context (REQ-037).
"""

from __future__ import annotations

import logging

from python_tesseron.types import TesseronCapabilities

logger = logging.getLogger(__name__)


class CapabilityNegotiation:
    """Tracks negotiated capabilities through the session lifecycle.

    Implements DC-011. Starts with the app-declared capabilities (all True),
    then stores the intersection from the welcome response. On claimed
    notification, overwrites with agentCapabilities if provided.

    Attributes:
        _capabilities: The current authoritative capability set.

    """

    def __init__(self) -> None:
        """Initialise with all capabilities declared as true.

        Per REQ-100, the SDK SHOULD declare all capabilities as true in hello.
        The actual effective set is determined by the gateway's welcome response.

        """
        # Start maximally permissive; welcome will return the intersection
        self._capabilities = TesseronCapabilities(
            streaming=True,
            subscriptions=True,
            sampling=True,
            elicitation=True,
        )

    @property
    def current(self) -> TesseronCapabilities:
        """The current authoritative capability set.

        Per REQ-033, REQ-037: handlers MUST trust this value, not the
        app-declared values.

        Returns:
            Current TesseronCapabilities.

        """
        return self._capabilities

    def app_declared(self) -> TesseronCapabilities:
        """Return the capabilities the SDK will declare in tesseron/hello.

        Per REQ-100, always returns all-true — the gateway computes the
        intersection with the agent's capabilities.

        Returns:
            TesseronCapabilities with all flags set to True.

        """
        return TesseronCapabilities(
            streaming=True,
            subscriptions=True,
            sampling=True,
            elicitation=True,
        )

    def apply_welcome(self, capabilities: TesseronCapabilities) -> None:
        """Store the intersection from the welcome response.

        Called when the tesseron/hello welcome is received. The welcome
        capabilities are the intersection computed by the gateway (REQ-033).

        Args:
            capabilities: The TesseronCapabilities from the WelcomeResult.

        """
        self._capabilities = capabilities
        logger.debug(
            "Capabilities after welcome: streaming=%s subscriptions=%s sampling=%s elicitation=%s",
            capabilities.streaming,
            capabilities.subscriptions,
            capabilities.sampling,
            capabilities.elicitation,
        )

    def apply_claimed(self, agent_capabilities: TesseronCapabilities | None) -> None:
        """Overwrite capabilities from tesseron/claimed agentCapabilities.

        Per REQ-036, REQ-037, REQ-076: if agentCapabilities is present in the
        claimed notification, overwrite the stored capabilities. These are the
        authoritative values for the remainder of the session.

        Args:
            agent_capabilities: The agentCapabilities from ClaimedParams, or
                None if not present (capabilities remain unchanged).

        """
        if agent_capabilities is None:
            return
        self._capabilities = agent_capabilities
        logger.debug(
            "Capabilities after claimed: streaming=%s subscriptions=%s sampling=%s elicitation=%s",
            agent_capabilities.streaming,
            agent_capabilities.subscriptions,
            agent_capabilities.sampling,
            agent_capabilities.elicitation,
        )
