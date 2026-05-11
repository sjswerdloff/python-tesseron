"""Session lifecycle state machine for the Tesseron protocol.

Design Contract: DC-004 (SessionStateMachine)
Spec Reference: §14 (Session Lifecycle State Machine)

States:
    DISCONNECTED -> HANDSHAKING -> AWAITING_CLAIM -> CLAIMED -> CLOSED

Guarantees:
- No auto-reconnect (REQ-085).
- On CLOSED: rejects pending requests, fires cancellation signals, clears
  subscription map, drops progress, rejects in-flight sample/confirm/elicit.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from python_tesseron.errors import TransportClosedError
from python_tesseron.types import SessionState

logger = logging.getLogger(__name__)


class SessionStateMachine:
    """Tracks the current session lifecycle state.

    Implements DC-004. State transitions are one-directional; no auto-reconnect
    is performed (REQ-085). Consumers may register close listeners.

    Attributes:
        state: Current session state string.
        _close_listeners: Callbacks to invoke when transitioning to CLOSED.

    """

    def __init__(self) -> None:
        """Initialise in DISCONNECTED state."""
        self.state: str = SessionState.DISCONNECTED
        self._close_listeners: list[Callable[[], Any]] = []

    def to_handshaking(self) -> None:
        """Transition from DISCONNECTED to HANDSHAKING.

        Called when the transport is opened and tesseron/hello is sent.

        Raises:
            RuntimeError: If current state is not DISCONNECTED.

        """
        if self.state != SessionState.DISCONNECTED:
            raise RuntimeError(f"Cannot transition to HANDSHAKING from {self.state}")
        self.state = SessionState.HANDSHAKING
        logger.debug("Session state: %s -> %s", SessionState.DISCONNECTED, SessionState.HANDSHAKING)

    def to_awaiting_claim(self) -> None:
        """Transition from HANDSHAKING to AWAITING_CLAIM.

        Called when the welcome response is received.

        Raises:
            RuntimeError: If current state is not HANDSHAKING.

        """
        if self.state != SessionState.HANDSHAKING:
            raise RuntimeError(f"Cannot transition to AWAITING_CLAIM from {self.state}")
        self.state = SessionState.AWAITING_CLAIM
        logger.debug("Session state: %s -> %s", SessionState.HANDSHAKING, SessionState.AWAITING_CLAIM)

    def to_claimed(self) -> None:
        """Transition from AWAITING_CLAIM to CLAIMED.

        Called when tesseron/claimed notification is received.

        Raises:
            RuntimeError: If current state is not AWAITING_CLAIM.

        """
        if self.state != SessionState.AWAITING_CLAIM:
            raise RuntimeError(f"Cannot transition to CLAIMED from {self.state}")
        self.state = SessionState.CLAIMED
        logger.debug("Session state: %s -> %s", SessionState.AWAITING_CLAIM, SessionState.CLAIMED)

    def to_closed(self) -> None:
        """Transition to CLOSED from any non-CLOSED state.

        Called when the transport closes. Invokes all registered close listeners.
        No-op if already CLOSED.

        """
        if self.state == SessionState.CLOSED:
            return
        previous = self.state
        self.state = SessionState.CLOSED
        logger.debug("Session state: %s -> %s", previous, SessionState.CLOSED)

        for listener in self._close_listeners:
            try:
                listener()
            except Exception:
                logger.exception("Exception in close listener")

    def add_close_listener(self, listener: Callable[[], Any]) -> None:
        """Register a callback to be invoked when the session closes.

        Args:
            listener: Zero-argument callable invoked on transition to CLOSED.

        """
        self._close_listeners.append(listener)

    @property
    def is_connected(self) -> bool:
        """True if the session is in an active (non-closed, non-disconnected) state.

        Returns:
            True for HANDSHAKING, AWAITING_CLAIM, and CLAIMED states.

        """
        return self.state not in (SessionState.DISCONNECTED, SessionState.CLOSED)

    @property
    def is_claimed(self) -> bool:
        """True if the session is in CLAIMED state.

        Returns:
            True only for CLAIMED state.

        """
        return self.state == SessionState.CLAIMED


class CloseCoordinator:
    """Handles the cascade of cleanup operations on transport close.

    On transport close (§14.3), the SDK must:
    1. Reject all pending dispatcher requests with TransportClosedError.
    2. Fire cancellation signals for in-flight invocations.
    3. Call cleanup functions for all active subscriptions.
    4. Drop progress calls after close.
    5. Reject in-flight sample/confirm/elicit with TransportClosedError.

    Per REQ-081, REQ-082, REQ-083, REQ-084.

    """

    def __init__(self) -> None:
        """Initialise with empty cleanup registries."""
        self._closed = False
        self._dispatcher: Any = None
        self._invocation_cancel_fns: dict[str, Any] = {}
        self._subscription_cleanup_fns: dict[str, Any] = {}

    @property
    def is_closed(self) -> bool:
        """True after close() has been called.

        Returns:
            True if transport is closed.

        """
        return self._closed

    def set_dispatcher(self, dispatcher: Any) -> None:
        """Register the dispatcher for pending-request rejection.

        Args:
            dispatcher: JsonRpcDispatcher instance.

        """
        self._dispatcher = dispatcher

    def register_invocation(self, invocation_id: str, cancel_fn: Any) -> None:
        """Track an in-flight action invocation.

        Args:
            invocation_id: The invocation ID.
            cancel_fn: Callable that fires the cancellation signal.

        """
        self._invocation_cancel_fns[invocation_id] = cancel_fn

    def unregister_invocation(self, invocation_id: str) -> None:
        """Remove a completed invocation from tracking.

        Args:
            invocation_id: The invocation ID to remove.

        """
        self._invocation_cancel_fns.pop(invocation_id, None)

    def register_subscription(self, subscription_id: str, cleanup_fn: Any) -> None:
        """Track an active resource subscription.

        Args:
            subscription_id: The subscription ID.
            cleanup_fn: Callable to invoke on unsubscribe or close.

        """
        self._subscription_cleanup_fns[subscription_id] = cleanup_fn

    def unregister_subscription(self, subscription_id: str) -> None:
        """Remove a subscription and call its cleanup function.

        Per REQ-072, REQ-073: on unsubscribe, call cleanup and remove from map.

        Args:
            subscription_id: The subscription ID to remove.

        """
        cleanup_fn = self._subscription_cleanup_fns.pop(subscription_id, None)
        if cleanup_fn is not None:
            try:
                cleanup_fn()
            except Exception:
                logger.exception("Exception in subscription cleanup for %s", subscription_id)

    async def close(self) -> None:
        """Perform all close-cascade operations.

        Called on transport close. Executes all cleanup steps per §14.3:
        1. Mark as closed (progress calls are then silently dropped — REQ-084).
        2. Cancel all in-flight invocations (REQ-082).
        3. Call all subscription cleanup functions (REQ-083).
        4. Reject all pending dispatcher requests (REQ-081).

        """
        if self._closed:
            return
        self._closed = True

        error = TransportClosedError()

        # REQ-082: fire cancellation signals for in-flight invocations
        cancel_fns = dict(self._invocation_cancel_fns)
        self._invocation_cancel_fns.clear()
        for inv_id, cancel_fn in cancel_fns.items():
            try:
                cancel_fn()
                logger.debug("Fired cancellation for invocation %s", inv_id)
            except Exception:
                logger.exception("Exception firing cancellation for %s", inv_id)

        # REQ-083: call cleanup for all active subscriptions
        cleanup_fns = dict(self._subscription_cleanup_fns)
        self._subscription_cleanup_fns.clear()
        for sub_id, cleanup_fn in cleanup_fns.items():
            try:
                cleanup_fn()
                logger.debug("Called cleanup for subscription %s", sub_id)
            except Exception:
                logger.exception("Exception in cleanup for subscription %s", sub_id)

        # REQ-081, REQ-008: reject all pending dispatcher requests
        if self._dispatcher is not None:
            await self._dispatcher.reject_all_pending(error)
