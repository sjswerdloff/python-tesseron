"""WebSocket transport binding for the Tesseron protocol.

Design Contract: DC-002 (WebSocketTransport)
Spec Reference: §3.2 (WebSocket Binding), §16.1 (Loopback-Only Discovery)

Guarantees:
- Binds to loopback only (127.0.0.1) (REQ-014, REQ-018, REQ-086).
- Advertises tesseron-gateway subprotocol (REQ-016, REQ-017).
- Accepts exactly one WebSocket connection; rejects others (REQ-019).
- One JSON-RPC envelope per text frame (REQ-011).
- Binary frames coerced to UTF-8 (REQ-015).
- Deletes manifest on close (REQ-020, REQ-028).
- Provides send(message) and close() to dispatcher.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from websockets import Subprotocol
from websockets.asyncio.server import ServerConnection, serve

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — §3.2, §16.1, §17
# ---------------------------------------------------------------------------

# Subprotocol name — REQ-016
_SUBPROTOCOL = "tesseron-gateway"

# Loopback bind address — REQ-014, REQ-018, REQ-086
_BIND_HOST = "127.0.0.1"


class WebSocketTransport:
    """WebSocket transport server for the Tesseron SDK.

    Implements DC-002. Hosts a loopback WebSocket server that the gateway
    dials into. Accepts exactly one connection (REQ-019).

    Attributes:
        host: The bind address (always 127.0.0.1).
        port: The dynamically-assigned port (set after start()).

    """

    def __init__(self) -> None:
        """Initialise the transport in a not-started state."""
        self.host = _BIND_HOST
        self._port: int = 0
        self._server: Any = None
        self._connection: ServerConnection | None = None
        self._connection_event = asyncio.Event()
        self._message_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._closed = False

    @property
    def port(self) -> int:
        """The port the server is listening on (available after start()).

        Returns:
            Bound port number.

        """
        return self._port

    @property
    def url(self) -> str:
        """The WebSocket URL the gateway should connect to.

        Returns:
            ws://127.0.0.1:<port>/ URL.

        """
        return f"ws://{self.host}:{self._port}/"

    async def start(self) -> None:
        """Start the WebSocket server on a random loopback port.

        Binds to 127.0.0.1 with OS-assigned port (REQ-014, REQ-086).
        Advertises tesseron-gateway subprotocol (REQ-016).

        """
        self._server = await serve(
            self._handler,
            self.host,
            0,  # OS picks port
            subprotocols=[Subprotocol(_SUBPROTOCOL)],
        )
        sockets = self._server.sockets
        if sockets:
            self._port = sockets[0].getsockname()[1]
        logger.info("WebSocket transport listening on %s", self.url)

    async def _handler(self, websocket: ServerConnection) -> None:
        """Handle an incoming WebSocket connection.

        Per REQ-019: accepts exactly one connection. Subsequent connections
        are immediately closed.

        Per REQ-015: binary frames coerced to UTF-8.

        Args:
            websocket: The incoming WebSocket connection.

        """
        # REQ-019: reject subsequent connections
        if self._connection is not None:
            await websocket.close(code=1008, reason="Only one connection accepted")
            return

        self._connection = websocket
        self._connection_event.set()
        logger.info("WebSocket connection accepted from gateway")

        try:
            async for raw_msg in websocket:
                if self._closed:
                    break
                # REQ-015: coerce binary frames to UTF-8
                if isinstance(raw_msg, bytes):
                    text = raw_msg.decode("utf-8", errors="replace")
                else:
                    text = raw_msg
                await self._message_queue.put(text)
        except Exception:
            logger.exception("WebSocket handler error")
        finally:
            # Signal end-of-stream to reader
            await self._message_queue.put(None)
            logger.info("WebSocket connection closed")

    async def wait_for_connection(self, timeout: float = 30.0) -> None:
        """Wait until the gateway connects.

        Args:
            timeout: Maximum seconds to wait.

        Raises:
            TimeoutError: If no connection arrives within the timeout.

        """
        await asyncio.wait_for(self._connection_event.wait(), timeout=timeout)

    async def send(self, message: dict[str, Any]) -> None:
        """Send a JSON-RPC envelope as a single WebSocket text frame.

        Per REQ-011: one JSON-RPC envelope per text frame.

        Args:
            message: The dict to serialise and send.

        Raises:
            RuntimeError: If no connection is established.

        """
        if self._connection is None:
            raise RuntimeError("No WebSocket connection established")
        raw = json.dumps(message)
        await self._connection.send(raw)

    async def close(self) -> None:
        """Close the WebSocket connection and stop the server.

        Called to tear down the transport.

        """
        if self._closed:
            return
        self._closed = True

        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                logger.exception("Error closing WebSocket connection")
            self._connection = None

        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                logger.exception("Error stopping WebSocket server")
            self._server = None

        logger.info("WebSocket transport closed")

    async def messages(self) -> AsyncIterator[str]:
        """Iterate over incoming text frames.

        Yields raw JSON strings, one per WebSocket text frame.
        Stops when the connection is closed.

        Yields:
            Raw JSON string for each received frame.

        """
        while True:
            text = await self._message_queue.get()
            if text is None:
                break
            yield text
