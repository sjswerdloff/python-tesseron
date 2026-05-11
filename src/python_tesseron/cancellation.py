"""Progress notifications and cancellation/timeout for Tesseron actions.

Design Contract: DC-008 (ProgressCancellation)
Spec Reference: §8 (Progress and Cancellation)

Guarantees:
- Progress notifications are fire-and-forget (REQ-051).
- Cancel signal: asyncio.Event (REQ-052, REQ-054).
- Timeout: abort after timeoutMs, default 60,000 ms (REQ-055, REQ-056).
- Race handler against timeout/cancel — agent gets response immediately (REQ-057).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from python_tesseron.errors import CancelledError as TesseronCancelledError
from python_tesseron.errors import TimeoutError as TesseronTimeoutError
from python_tesseron.errors import TransportClosedError

logger = logging.getLogger(__name__)

# Default action timeout per §17, REQ-055
_DEFAULT_TIMEOUT_MS = 60_000


class InvocationController:
    """Manages cancellation and timeout for a single action invocation.

    Per DC-008, each invocation has its own cancel signal (asyncio.Event)
    and optional timeout. The handler is raced against both.

    Attributes:
        invocation_id: Correlates to the actions/invoke request.
        cancel_event: asyncio.Event fired on cancel or timeout.
        timeout_ms: Milliseconds until timeout; None for infinite.
        _cancelled: Whether cancelled explicitly (vs timeout).
        _timed_out: Whether the timeout fired first.

    """

    def __init__(self, invocation_id: str, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> None:
        """Initialise with invocation ID and timeout.

        Args:
            invocation_id: The invocation ID string.
            timeout_ms: Timeout in milliseconds. Default 60,000 ms.

        """
        self.invocation_id = invocation_id
        self.timeout_ms = timeout_ms
        self.cancel_event = asyncio.Event()
        self._cancelled = False
        self._timed_out = False

    def cancel(self) -> None:
        """Fire the cancellation signal.

        Per REQ-052: fires when actions/cancel is received for this invocation.

        """
        self._cancelled = True
        self.cancel_event.set()
        logger.debug("Invocation %s: cancellation signal fired", self.invocation_id)

    def fire_timeout(self) -> None:
        """Fire the cancellation signal due to timeout.

        Per REQ-055: fires when the handler exceeds timeoutMs.

        """
        self._timed_out = True
        self.cancel_event.set()
        logger.debug("Invocation %s: timeout signal fired", self.invocation_id)

    @property
    def was_cancelled(self) -> bool:
        """True if explicitly cancelled (not via timeout).

        Returns:
            True if cancel() was called.

        """
        return self._cancelled

    @property
    def was_timed_out(self) -> bool:
        """True if the timeout fired.

        Returns:
            True if fire_timeout() was called.

        """
        return self._timed_out

    async def run_handler(
        self,
        coro: Any,
        send_error: Any,
        send_result: Any,
    ) -> None:
        """Race handler coroutine against timeout and cancellation.

        Per REQ-057: race handler independently per invocation. The agent gets
        its error response immediately on cancel/timeout; the handler may
        continue orphaned.

        When timeout fires: REQ-056 — return -32002 Timeout.
        When cancel fires: REQ-054 — return -32001 Cancelled.

        Args:
            coro: The handler coroutine to race.
            send_error: Async callable to send error response.
            send_result: Async callable to send success response.

        """
        timeout_s = self.timeout_ms / 1000.0

        handler_task = asyncio.create_task(coro)
        timeout_task = asyncio.create_task(asyncio.sleep(timeout_s))
        cancel_task = asyncio.create_task(self.cancel_event.wait())

        done, pending = await asyncio.wait(
            {handler_task, timeout_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        # Cancel the monitoring tasks — they are no longer needed
        for t in pending:
            t.cancel()

        if handler_task in done:
            # Handler completed first — cancel remaining
            timeout_task.cancel()
            cancel_task.cancel()
            try:
                result = handler_task.result()
                await send_result(result)
            except Exception as exc:
                await send_error(exc)
        elif timeout_task in done and cancel_task not in done:
            # Timeout fired before cancel or handler
            self.fire_timeout()
            await send_error(TesseronTimeoutError())
            # Handler task continues orphaned per REQ-057
        else:
            # Cancellation signal fired (explicit cancel or transport close)
            if self._cancelled:
                await send_error(TesseronCancelledError())
            else:
                # Transport closed
                await send_error(TransportClosedError())
            # Handler task continues orphaned per REQ-057


class ProgressEmitter:
    """Emits progress notifications for an action invocation.

    Per REQ-051 and §8.1: progress is fire-and-forget. Calls after transport
    close are silently dropped (REQ-084).

    Attributes:
        _invocation_id: Correlates progress to the invocation.
        _notify: Dispatcher.notify callback.
        _closed: Whether the transport is closed.

    """

    def __init__(self, invocation_id: str, notify: Any) -> None:
        """Initialise the emitter.

        Args:
            invocation_id: The invocation ID for correlation.
            notify: Async callable dispatcher.notify(method, params).

        """
        self._invocation_id = invocation_id
        self._notify = notify
        self._closed = False

    def mark_closed(self) -> None:
        """Mark the transport as closed; subsequent progress is silently dropped.

        Per REQ-084.

        """
        self._closed = True

    async def emit(
        self,
        message: str | None = None,
        percent: float | None = None,
        data: Any = None,
    ) -> None:
        """Send an actions/progress notification.

        Per REQ-051, §8.1: fire-and-forget, never raises. After transport close,
        silently dropped (REQ-084).

        Args:
            message: Optional short status message.
            percent: Optional completion percentage (0-100).
            data: Optional free-form structured data.

        """
        if self._closed:
            return

        params: dict[str, Any] = {"invocationId": self._invocation_id}
        if message is not None:
            params["message"] = message
        if percent is not None:
            params["percent"] = percent
        if data is not None:
            params["data"] = data

        try:
            await self._notify("actions/progress", params)
        except Exception:
            # Progress is fire-and-forget — swallow errors silently
            logger.debug(
                "Progress notification for %s silently swallowed",
                self._invocation_id,
            )
