"""Bidirectional JSON-RPC 2.0 dispatcher for the Tesseron protocol.

Design Contract: DC-001 (JsonRpcDispatcher)
Spec Reference: §2 (Wire Format), Appendix B (Dispatcher)

Guarantees:
- Registers handlers for incoming requests and notifications.
- Sends outbound requests with auto-incrementing integer IDs.
- Maintains a pending-request map; resolves or rejects on response.
- Dispatches incoming messages by shape (request / notification / response).
- Rejects all pending requests with TransportClosedError on close.
- Send callback injected via constructor — dispatcher is transport-agnostic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from python_tesseron.errors import (
    InternalError,
    MethodNotFoundError,
    TesseronError,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Type aliases — REQ-092
# ---------------------------------------------------------------------------

RequestHandler = Callable[[dict[str, Any] | None], Awaitable[Any]]
NotificationHandler = Callable[[dict[str, Any] | None], Awaitable[None]]
SendCallback = Callable[[dict[str, Any]], Awaitable[None]]

# JSON-RPC 2.0 version string — spec §2.1
_JSONRPC_VERSION = "2.0"


class JsonRpcDispatcher:
    """Bidirectional JSON-RPC 2.0 dispatcher.

    Implements DC-001. Handles both outbound requests (from the SDK to the
    gateway) and inbound requests (from the gateway to the SDK).

    The dispatcher is transport-agnostic — it receives a ``send`` callback at
    construction time and never directly touches WebSocket or UDS state.

    Attributes:
        _send: Async callback that puts serialised dicts on the wire.
        _next_id: Auto-incrementing request ID counter (REQ-004).
        _pending: Map of id -> Future for outbound requests in flight (REQ-006).
        _request_handlers: Registry of method -> handler for inbound requests.
        _notification_handlers: Registry of method -> handler for notifications.

    """

    def __init__(self, send: SendCallback) -> None:
        """Initialise the dispatcher with a send callback.

        Args:
            send: Async callable that accepts a dict and transmits it.

        """
        self._send = send
        self._next_id: int = 1
        self._pending: dict[int | str, asyncio.Future[Any]] = {}
        self._request_handlers: dict[str, RequestHandler] = {}
        self._notification_handlers: dict[str, NotificationHandler] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def on(self, method: str, handler: RequestHandler) -> None:
        """Register a handler for an incoming request.

        Per REQ-092, the dispatcher must support registering request handlers.
        If a request arrives for an unregistered method, -32601 MethodNotFound
        is returned (REQ-094).

        Args:
            method: The JSON-RPC method name.
            handler: Async callable receiving params, returning a result or
                raising TesseronError.

        """
        self._request_handlers[method] = handler

    def on_notification(self, method: str, handler: NotificationHandler) -> None:
        """Register a handler for an incoming notification.

        Per REQ-092, the dispatcher must support notification handlers.
        Notifications have no id, so no response is ever sent.

        Args:
            method: The JSON-RPC method name.
            handler: Async callable receiving params, returning nothing.

        """
        self._notification_handlers[method] = handler

    # ------------------------------------------------------------------
    # Outbound
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        signal: asyncio.Event | None = None,
    ) -> Any:
        """Send a request and await its response.

        Assigns an auto-incrementing id (REQ-004). Maintains a pending map
        entry (REQ-006). Resolves the Future when the matching response arrives
        (REQ-007). Raises TesseronError if the response is an error.

        Args:
            method: The JSON-RPC method name.
            params: Optional params dict.
            signal: Optional asyncio.Event; if set before the response arrives,
                the pending request is cancelled.

        Returns:
            The ``result`` payload from the success response.

        Raises:
            TesseronError: If the response is an error response, or if the
                transport closes before the response arrives.

        """
        req_id = self._next_id
        self._next_id += 1

        loop = asyncio.get_event_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[req_id] = future

        envelope: dict[str, Any] = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": req_id,
            "method": method,
        }
        if params is not None:
            envelope["params"] = params

        try:
            await self._send(envelope)
        except Exception:
            # If send fails, clean up the pending entry (REQ-097)
            self._pending.pop(req_id, None)
            raise

        if signal is not None:
            # Race response against cancellation signal
            signal_task = asyncio.ensure_future(_wait_for_event(signal))
            done, _ = await asyncio.wait(
                {asyncio.ensure_future(future), signal_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            signal_task.cancel()
            if future.done():
                return future.result()
            # Signal fired before response
            self._pending.pop(req_id, None)
            future.cancel()
            raise TesseronError("Request cancelled via signal")
        else:
            return await future

    async def notify(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Send a fire-and-forget notification (no id, no response).

        Per REQ-002, notifications MUST NOT have an id field and MUST NOT
        receive a response.

        Args:
            method: The JSON-RPC method name.
            params: Optional params dict.

        """
        envelope: dict[str, Any] = {
            "jsonrpc": _JSONRPC_VERSION,
            "method": method,
        }
        if params is not None:
            envelope["params"] = params
        await self._send(envelope)

    # ------------------------------------------------------------------
    # Inbound dispatch
    # ------------------------------------------------------------------

    async def receive(self, message: dict[str, Any]) -> None:
        """Dispatch an incoming parsed JSON-RPC envelope.

        Routes by message shape per Appendix B dispatch rules:
        - method + id -> inbound request -> call handler, send response.
        - method, no id -> notification -> call handler, no response.
        - id + result/error, no method -> response -> resolve/reject pending.
        - missing jsonrpc "2.0" -> silently ignored.

        Args:
            message: A parsed JSON-RPC 2.0 dict.

        """
        # REQ-032 (implicit): ignore non-2.0 messages
        if message.get("jsonrpc") != _JSONRPC_VERSION:
            logger.debug("Ignoring message with wrong jsonrpc version: %r", message.get("jsonrpc"))
            return

        has_method = "method" in message
        has_id = "id" in message
        has_result = "result" in message
        has_error = "error" in message

        if has_method and has_id:
            # Inbound request — gateway expects a response
            await self._dispatch_request(message)
        elif has_method and not has_id:
            # Inbound notification — fire-and-forget, no response
            await self._dispatch_notification(message)
        elif has_id and (has_result or has_error) and not has_method:
            # Response to one of our outbound requests
            self._dispatch_response(message)
        else:
            logger.debug("Unclassifiable JSON-RPC message; dropping: %r", message)

    async def _dispatch_request(self, message: dict[str, Any]) -> None:
        """Handle an inbound request and send a success or error response.

        REQ-094: if no handler registered, send -32601 MethodNotFound.
        REQ-095: TesseronError from handler -> send its code/message/data.
        REQ-096: other exception -> send -32603 InternalError.

        Long-running handlers (e.g., actions/invoke) are dispatched as background
        tasks so the receive loop can continue processing notifications (e.g.,
        actions/cancel) while a handler is running. REQ-057 requires this
        concurrency for cancel/timeout to work correctly.

        Args:
            message: Parsed request envelope with method and id.

        """
        method = message["method"]
        req_id = message["id"]
        params = message.get("params")

        handler = self._request_handlers.get(method)
        if handler is None:
            await self._send_error(req_id, MethodNotFoundError())
            return

        async def run_and_respond() -> None:
            try:
                result = await handler(params)
            except TesseronError as exc:
                await self._send_error(req_id, exc)
                return
            except Exception as exc:
                logger.exception("Unexpected exception in handler for %r", method)
                err = InternalError(str(exc))
                await self._send_error(req_id, err)
                return
            else:
                await self._send_success(req_id, result)

        # Dispatch as background task so the receive loop is not blocked.
        # This allows cancel notifications to arrive while the handler runs.
        asyncio.ensure_future(run_and_respond())

    async def _dispatch_notification(self, message: dict[str, Any]) -> None:
        """Handle an inbound notification (no response sent).

        Args:
            message: Parsed notification envelope with method but no id.

        """
        method = message["method"]
        params = message.get("params")

        handler = self._notification_handlers.get(method)
        if handler is None:
            logger.debug("No notification handler for method %r; dropping", method)
            return

        try:
            await handler(params)
        except Exception:
            logger.exception("Notification handler for %r raised an exception", method)

    def _dispatch_response(self, message: dict[str, Any]) -> None:
        """Resolve or reject a pending outbound request.

        REQ-007: on receiving a response, look up the id, resolve/reject, remove.
        REQ-080: incoming JSON-RPC error -> construct TesseronError, reject.

        Args:
            message: Parsed response envelope with id and result or error.

        """
        req_id = message["id"]
        future = self._pending.pop(req_id, None)
        if future is None:
            logger.debug("Received response for unknown id %r; dropping", req_id)
            return

        if future.done():
            return

        if "error" in message:
            err_obj = message["error"]
            code = err_obj.get("code", -32603)
            msg = err_obj.get("message", "Unknown error")
            data = err_obj.get("data")
            future.set_exception(TesseronError(msg, code=code, data=data))
        else:
            future.set_result(message.get("result"))

    # ------------------------------------------------------------------
    # Transport close
    # ------------------------------------------------------------------

    async def reject_all_pending(self, error: TesseronError) -> None:
        """Reject all pending outbound requests with the given error.

        Called on transport close per REQ-008, REQ-093.

        Args:
            error: The error to reject all pending futures with.

        """
        pending = dict(self._pending)
        self._pending.clear()
        for req_id, future in pending.items():
            if not future.done():
                future.set_exception(error)
                logger.debug("Rejected pending request id=%r with %r", req_id, error)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_success(self, req_id: int | str | None, result: Any) -> None:
        """Send a JSON-RPC success response.

        Args:
            req_id: The id from the original request.
            result: The result payload.

        """
        envelope = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": req_id,
            "result": result,
        }
        try:
            await self._send(envelope)
        except Exception:
            logger.exception("Failed to send success response for id=%r", req_id)

    async def _send_error(self, req_id: int | str | None, error: TesseronError) -> None:
        """Send a JSON-RPC error response.

        Args:
            req_id: The id from the original request.
            error: The TesseronError to encode.

        """
        err_obj: dict[str, Any] = {
            "code": error.code,
            "message": error.message,
        }
        if error.data is not None:
            err_obj["data"] = error.data
        envelope = {
            "jsonrpc": _JSONRPC_VERSION,
            "id": req_id,
            "error": err_obj,
        }
        try:
            await self._send(envelope)
        except Exception:
            logger.exception("Failed to send error response for id=%r", req_id)

    @staticmethod
    def parse_message(raw: str) -> dict[str, Any] | None:
        """Parse a raw JSON string into a dict.

        Returns None if parsing fails (caller should respond with -32700
        ParseError if the message was a request).

        Args:
            raw: Raw JSON string from the transport.

        Returns:
            Parsed dict or None on parse failure.

        """
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                return None
        except json.JSONDecodeError:
            logger.debug("Failed to parse JSON message: %r", raw[:200])
            return None
        else:
            return parsed


# ---------------------------------------------------------------------------
# Helper coroutine
# ---------------------------------------------------------------------------


async def _wait_for_event(event: asyncio.Event) -> None:
    """Await an asyncio.Event and return.

    Args:
        event: The event to wait for.

    """
    await event.wait()
