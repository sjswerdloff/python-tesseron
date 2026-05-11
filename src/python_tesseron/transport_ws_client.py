"""WebSocket CLIENT transport for the Tesseron protocol.

Design Contract: DC-002 (WebSocketTransport) — Client variant
Spec Reference: §3.2 (WebSocket Binding)

This module provides a WebSocket CLIENT transport, used when an SDK instance
needs to CONNECT OUTBOUND to a WebSocket server (e.g., in test scenarios
where the MockGateway acts as the server).

In production the SDK is always the SERVER (gateway dials in). In tests,
the MockGateway is the server and the SDK dials outward using this transport.

Guarantees:
- Connects to a given ws:// URL with the tesseron-gateway subprotocol.
- One JSON-RPC envelope per text frame (REQ-011).
- Binary frames coerced to UTF-8 (REQ-015).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import websockets
from websockets import Subprotocol

logger = logging.getLogger(__name__)

# Subprotocol name — REQ-016
_SUBPROTOCOL = "tesseron-gateway"


class WebSocketClientTransport:
    """WebSocket CLIENT transport for the Tesseron SDK.

    Connects outbound to a WebSocket server. Used in tests where the
    MockGateway acts as server and the SDK dials in.

    Attributes:
        _url: The WebSocket URL to connect to.
        _connection: The active WebSocket connection.

    """

    def __init__(self, url: str) -> None:
        """Initialise the client transport in a not-connected state.

        Args:
            url: The WebSocket URL to connect to (e.g., ws://127.0.0.1:12345/).

        """
        self._url = url
        self._connection: Any = None
        self._connection_event = asyncio.Event()
        self._message_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._closed = False
        self._receive_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Connect to the WebSocket server.

        Per REQ-016: uses tesseron-gateway subprotocol.
        Per REQ-015: binary frames coerced to UTF-8.

        Raises:
            OSError: If the connection cannot be established.

        """
        self._connection = await websockets.connect(
            self._url,
            subprotocols=[Subprotocol(_SUBPROTOCOL)],
        )
        self._connection_event.set()
        logger.info("WebSocket client transport connected to %s", self._url)

        # Start receive loop in background
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        """Receive messages from the server and queue them.

        Per REQ-015: coerce binary frames to UTF-8.

        """
        try:
            async for raw_msg in self._connection:
                if self._closed:
                    break
                if isinstance(raw_msg, bytes):
                    text = raw_msg.decode("utf-8", errors="replace")
                else:
                    text = raw_msg
                await self._message_queue.put(text)
        except Exception:
            logger.exception("WebSocket client receive loop error")
        finally:
            await self._message_queue.put(None)
            logger.info("WebSocket client receive loop ended")

    async def wait_for_connection(self, timeout: float = 30.0) -> None:
        """Wait until connected (no-op for client — connection is immediate on start).

        Args:
            timeout: Maximum seconds to wait (unused in client mode).

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
        if self._connection is None:
            raise RuntimeError("WebSocket client transport not connected")
        raw = json.dumps(message)
        await self._connection.send(raw)

    async def close(self) -> None:
        """Close the WebSocket connection.

        Called to tear down the transport.

        """
        if self._closed:
            return
        self._closed = True

        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._connection is not None:
            try:
                await self._connection.close()
            except Exception:
                logger.exception("Error closing WebSocket client connection")
            self._connection = None

        logger.info("WebSocket client transport closed")

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
