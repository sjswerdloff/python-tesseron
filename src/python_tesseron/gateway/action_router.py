"""Gateway action router.

Design Contract: DC-021 (GatewayActionRouter)
Spec Reference: §6 (Action Invocation), §10 (Cancellation), §11 (Timeout)

Routes MCP tool calls to the correct Tesseron app session.

Guarantees:
- Route tool calls to correct app session by parsing app_id prefix (REQ-140).
- Forward actions/invoke as JSON-RPC request to app (REQ-121).
- Forward actions/progress to MCP as notifications/progress (REQ-122).
- Send actions/cancel on agent cancellation or timeout (REQ-123).
- Enforce default 60000ms timeout; respect custom timeoutMs (REQ-124).
- Reject invocations on unclaimed sessions with -32009 (REQ-136).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from python_tesseron.errors import (
    ActionNotFoundError,
    UnauthorizedError,
)
from python_tesseron.errors import (
    TimeoutError as TesseronTimeoutError,
)
from python_tesseron.types import SessionState

logger = logging.getLogger(__name__)

# Default action invocation timeout (REQ-124)
DEFAULT_TIMEOUT_MS = 60_000


class GatewayActionRouter:
    """Routes MCP tool calls to the correct Tesseron app session.

    Design Contract: DC-021 (GatewayActionRouter)

    Parses the app_id__ prefix from MCP tool names to locate the target
    session, forwards the invocation, tracks in-flight calls, and handles
    timeouts and cancellation.

    Attributes:
        _session_manager: GatewaySessionManager for session lookup.
        _progress_callbacks: Callbacks to emit MCP progress notifications.

    """

    def __init__(self, session_manager: Any) -> None:
        """Initialise the action router.

        Args:
            session_manager: GatewaySessionManager instance.

        """
        self._session_manager = session_manager
        self._progress_callbacks: list[Any] = []

    def on_progress(self, cb: Any) -> None:
        """Register a callback for MCP progress notifications.

        REQ-122: progress forwarded when progressToken supplied.

        Args:
            cb: Callable receiving (progress_token, progress_value, total).

        """
        self._progress_callbacks.append(cb)

    def _emit_progress(self, progress_token: Any, progress: float, total: float | None) -> None:
        """Emit a progress notification to registered callbacks.

        Args:
            progress_token: MCP progress token.
            progress: Current progress value.
            total: Optional total value.

        """
        for cb in self._progress_callbacks:
            try:
                cb(progress_token, progress, total)
            except Exception:
                logger.exception("Error emitting progress notification")

    async def invoke(
        self,
        tool_name: str,
        tool_input: dict[str, Any] | None,
        *,
        progress_token: Any | None = None,
        timeout_ms: int | None = None,
    ) -> Any:
        """Route an MCP tool call to the correct app session.

        Parses the app_id__ prefix to find the target session, forwards
        the invocation as actions/invoke, and handles timeout/cancellation.

        REQ-140: routing by app_id prefix.
        REQ-121: forward actions/invoke as JSON-RPC.
        REQ-122: forward progress when progressToken supplied.
        REQ-123: send actions/cancel on cancellation or timeout.
        REQ-124: enforce timeout.
        REQ-136: reject unclaimed sessions.

        Args:
            tool_name: MCP tool name (format: app_id__action_name).
            tool_input: Arguments passed to the tool.
            progress_token: Optional MCP progress token for progress forwarding.
            timeout_ms: Custom timeout override in milliseconds.

        Returns:
            The action result from the app.

        Raises:
            ActionNotFoundError: If no session found for app_id (-32003).
            UnauthorizedError: If session exists but is not CLAIMED (-32009).
            TimeoutError: If invocation exceeds timeout (-32002).

        """
        from python_tesseron.gateway.mcp_bridge import parse_tool_name

        # Parse tool name to extract app_id and action name
        parsed = parse_tool_name(tool_name)
        if parsed is None:
            raise ActionNotFoundError(f"Tool name {tool_name!r} is not a valid Tesseron tool")

        app_id, action_name = parsed

        # Find the session (REQ-140)
        session = self._session_manager.get_session_by_app_id(app_id)
        if session is None:
            # Check if there's a session for this app in a non-claimed state
            for s in self._session_manager.all_sessions():
                if s.app_id == app_id:
                    if s.state != SessionState.CLAIMED:
                        raise UnauthorizedError(f"Session for app {app_id!r} is not claimed")
            raise ActionNotFoundError(f"No active session for app_id {app_id!r}")

        if not session.is_claimed:
            raise UnauthorizedError(f"Session for app {app_id!r} is not claimed")

        if session.dispatcher is None:
            raise ActionNotFoundError(f"Session for app {app_id!r} has no dispatcher")

        # Effective timeout (REQ-124)
        effective_timeout_ms = timeout_ms if timeout_ms is not None else DEFAULT_TIMEOUT_MS
        effective_timeout_s = effective_timeout_ms / 1000.0

        # Unique invocation ID
        invocation_id = str(uuid.uuid4())

        # Cancellation event for this invocation
        cancel_event = asyncio.Event()

        # Register cancellation handler
        def on_cancel() -> None:
            cancel_event.set()

        session.register_invocation(invocation_id, on_cancel)

        # Register progress handler on the app dispatcher
        if progress_token is not None:

            async def handle_progress(params: dict[str, Any] | None) -> None:
                if params is None:
                    return
                # Only forward if this matches our invocation
                if params.get("invocationId") == invocation_id:
                    percent = params.get("percent", 0.0) or 0.0
                    self._emit_progress(progress_token, percent, 100.0)

            session.dispatcher.on_notification("actions/progress", handle_progress)

        try:
            # Build invocation params (REQ-121)
            invoke_params: dict[str, Any] = {
                "name": action_name,
                "invocationId": invocation_id,
                "input": tool_input or {},
            }

            # Race invocation against timeout (REQ-124)
            try:
                result = await asyncio.wait_for(
                    session.dispatcher.request("actions/invoke", invoke_params),
                    timeout=effective_timeout_s,
                )
            except TimeoutError:
                # REQ-123: send cancel on timeout
                await self._send_cancel(session, invocation_id)
                raise TesseronTimeoutError(f"Action {tool_name!r} timed out after {effective_timeout_ms}ms")
            except Exception:
                # On any error, attempt cancel
                await self._send_cancel(session, invocation_id)
                raise

        finally:
            session.unregister_invocation(invocation_id)

        return result

    async def _send_cancel(self, session: Any, invocation_id: str) -> None:
        """Send actions/cancel notification to the app.

        REQ-123: send cancellation notification to app.

        Args:
            session: The target session.
            invocation_id: The invocation to cancel.

        """
        if session.dispatcher is None:
            return
        try:
            await session.dispatcher.notify(
                "actions/cancel",
                {"invocationId": invocation_id},
            )
        except Exception:
            logger.exception("Error sending actions/cancel for %s", invocation_id)
