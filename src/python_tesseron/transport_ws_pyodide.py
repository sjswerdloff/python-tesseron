"""Pyodide-compatible WebSocket transport for the Tesseron protocol.

Design Contract: DC-017 (PyodideWebSocketTransport)
Spec Reference: §3.2 (WebSocket Binding)

This module provides a WebSocket transport for environments where Python runs
inside a browser via Pyodide (WebAssembly). The ``websockets`` library cannot
run in that context because it requires raw TCP sockets; instead we delegate
to the browser's native ``WebSocket`` API via Pyodide's FFI layer.

Event model: the browser WebSocket API is callback-based (onopen, onmessage,
onclose, onerror). Since Pyodide shares the browser's single-threaded event
loop with asyncio, the callbacks execute in the same thread and may safely
call ``queue.put_nowait()`` and ``event.set()`` directly — no thread-safety
primitives are needed.

Guarantees:
- Connects to a given ws:// URL with the tesseron-gateway subprotocol (REQ-016).
- One JSON-RPC envelope per text frame (REQ-011).
- Binary frames coerced to UTF-8 string (REQ-015).
- Proxy references are destroyed on close to prevent JS memory leaks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

# These imports are only available inside Pyodide (browser WebAssembly).
# They are imported at the top level so that the mock strategy used in tests
# (patching sys.modules before import) intercepts them correctly.
from js import WebSocket  # type: ignore[import-not-found,unused-ignore]
from pyodide.ffi import create_proxy  # type: ignore[import-not-found,unused-ignore]

logger = logging.getLogger(__name__)

# Subprotocol name — REQ-016
_SUBPROTOCOL = "tesseron-gateway"


class PyodideWebSocketTransport:
    """Pyodide-compatible WebSocket transport for the Tesseron SDK.

    Uses the browser's native WebSocket API via Pyodide's FFI. The transport
    bridges event-driven JS callbacks into asyncio primitives so that callers
    can use the same ``async/await`` interface as the standard
    ``WebSocketClientTransport``.

    Attributes:
        _url: The WebSocket URL to connect to.
        _ws: The native browser WebSocket object.
        _connection_event: Set when onopen fires.
        _message_queue: Queue of incoming text frames (None signals close).
        _closed: True once close() has been called.
        _proxies: List of JS proxies to destroy on close.

    """

    def __init__(self, url: str) -> None:
        """Initialise the transport in a not-connected state.

        Args:
            url: The WebSocket URL to connect to (e.g., ws://127.0.0.1:12345/).

        """
        self._url = url
        self._ws: Any = None
        self._connection_event: asyncio.Event = asyncio.Event()
        self._message_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._closed: bool = False
        self._proxies: list[Any] = []

    async def start(self) -> None:
        """Connect to the WebSocket server using the browser native API.

        Creates a ``js.WebSocket`` with the ``tesseron-gateway`` subprotocol
        and wires up the four event callbacks (onopen, onmessage, onclose,
        onerror). Returns as soon as the callbacks are registered; use
        ``wait_for_connection`` to block until the connection is actually open.

        Per REQ-016: uses tesseron-gateway subprotocol.
        Per REQ-015: binary frames coerced to UTF-8.

        Raises:
            RuntimeError: If the transport has already been started.

        """
        if self._ws is not None:
            raise RuntimeError("PyodideWebSocketTransport already started")

        self._ws = WebSocket.new(self._url, [_SUBPROTOCOL])

        # --- onopen ---
        def _on_open(event: Any) -> None:
            logger.info("PyodideWebSocketTransport connected to %s", self._url)
            self._connection_event.set()

        # --- onmessage ---
        def _on_message(event: Any) -> None:
            data = event.data
            if isinstance(data, str):
                text = data
            elif isinstance(data, (bytes, bytearray)):
                # REQ-015: coerce binary frames to UTF-8
                text = data.decode("utf-8", errors="replace")
            else:
                # JS ArrayBuffer / Blob or any other type — coerce via str
                try:
                    text = str(data)
                except Exception:
                    logger.exception("PyodideWebSocketTransport: cannot coerce message data to str")
                    return
            self._message_queue.put_nowait(text)

        # --- onclose ---
        def _on_close(event: Any) -> None:
            logger.info("PyodideWebSocketTransport connection closed")
            if not self._closed:
                # Signal the messages() iterator to stop
                self._message_queue.put_nowait(None)

        # --- onerror ---
        def _on_error(event: Any) -> None:
            logger.error("PyodideWebSocketTransport connection error")
            if not self._closed:
                self._message_queue.put_nowait(None)

        # Wrap callables as JS-safe proxies and store refs so we can destroy them.
        proxy_open = create_proxy(_on_open)
        proxy_message = create_proxy(_on_message)
        proxy_close = create_proxy(_on_close)
        proxy_error = create_proxy(_on_error)

        self._proxies = [proxy_open, proxy_message, proxy_close, proxy_error]

        self._ws.onopen = proxy_open
        self._ws.onmessage = proxy_message
        self._ws.onclose = proxy_close
        self._ws.onerror = proxy_error

        logger.debug("PyodideWebSocketTransport: WebSocket.new() called for %s", self._url)

    async def wait_for_connection(self, timeout: float = 30.0) -> None:
        """Wait until the WebSocket connection is open.

        Args:
            timeout: Maximum seconds to wait before raising TimeoutError.

        Raises:
            asyncio.TimeoutError: If the connection is not established within
                ``timeout`` seconds.

        """
        await asyncio.wait_for(self._connection_event.wait(), timeout=timeout)

    async def send(self, message: dict[str, Any]) -> None:
        """Send a JSON-RPC envelope as a single WebSocket text frame.

        Per REQ-011: one JSON-RPC envelope per text frame.

        Args:
            message: The dict to serialise and send.

        Raises:
            RuntimeError: If not connected.

        """
        if self._ws is None:
            raise RuntimeError("PyodideWebSocketTransport not connected")
        raw = json.dumps(message)
        self._ws.send(raw)

    async def close(self) -> None:
        """Close the WebSocket connection and destroy all JS proxies.

        Destroying proxies is mandatory in Pyodide to prevent JS garbage-
        collector memory leaks. This method is idempotent.

        """
        if self._closed:
            return
        self._closed = True

        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                logger.exception("PyodideWebSocketTransport: error calling ws.close()")
            self._ws = None

        # Destroy all proxy references to allow JS GC to reclaim them.
        for proxy in self._proxies:
            try:
                proxy.destroy()
            except Exception:
                logger.exception("PyodideWebSocketTransport: error destroying proxy")
        self._proxies = []

        # Ensure the messages() iterator can terminate.
        self._message_queue.put_nowait(None)

        logger.info("PyodideWebSocketTransport closed")

    async def messages(self) -> AsyncIterator[str]:
        """Iterate over incoming text frames.

        Yields raw JSON strings, one per WebSocket frame. Stops when the
        connection is closed (sentinel ``None`` placed in queue by onclose or
        onerror callbacks, or by ``close()``).

        Yields:
            Raw JSON string for each received frame.

        """
        while True:
            text = await self._message_queue.get()
            if text is None:
                break
            yield text
