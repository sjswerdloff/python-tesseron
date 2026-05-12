"""Gateway WebSocket server.

Design Contract: DC-018 (GatewayWebSocketServer)
Spec Reference: §3.2, §16.1

Accepts inbound WebSocket connections from Tesseron apps.

Guarantees:
- Accept inbound WebSocket connections with tesseron-gateway subprotocol (REQ-108).
- Validate tesseron-gateway subprotocol; reject other subprotocols (REQ-109).
- Refuse non-loopback manifest URLs (REQ-138).
- Delegate to GatewaySessionManager on connect.
- Use JsonRpcDispatcher from SDK for message handling.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# The required WebSocket subprotocol for app connections (REQ-109)
TESSERON_SUBPROTOCOL = "tesseron-gateway"

# Loopback hostnames and addresses (REQ-138)
_LOOPBACK_HOSTNAMES = frozenset({"localhost", "127.0.0.1", "::1"})


def is_loopback_url(url: str) -> bool:
    """Determine whether a WebSocket URL references a loopback address.

    Per REQ-138, only loopback addresses (127.x.x.x, ::1, localhost) are
    permitted in manifest URLs for inbound connections.

    Args:
        url: WebSocket URL string to check.

    Returns:
        True if the URL host is a loopback address or hostname.

    """
    try:
        parsed = urlparse(url)
        host = parsed.hostname
        if host is None:
            return False
        if host in _LOOPBACK_HOSTNAMES:
            return True
        # Check IP address ranges
        try:
            addr = ipaddress.ip_address(host)
        except ValueError:
            return False
        else:
            return addr.is_loopback
    except Exception:
        return False


class GatewayWebSocketServer:
    """WebSocket server accepting inbound Tesseron app connections.

    Design Contract: DC-018 (GatewayWebSocketServer)

    Accepts inbound connections, validates the subprotocol, creates sessions,
    and dispatches messages to the session manager.

    Attributes:
        _session_manager: The GatewaySessionManager for session lifecycle.
        _host: Bind host for the server.
        _port: Bind port for the server.
        _server: The running websockets server instance.

    """

    def __init__(
        self,
        session_manager: Any,
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        """Initialise the server.

        Args:
            session_manager: GatewaySessionManager instance.
            host: Host to bind to. Defaults to loopback.
            port: Port to bind to. 0 = OS-assigned ephemeral port.

        """
        self._session_manager = session_manager
        self._host = host
        self._port = port
        self._server: Any = None
        self._message_handler_factory: Callable[[Any, Any], Any] | None = None

    @property
    def port(self) -> int | None:
        """The actual bound port after server starts.

        Returns:
            Bound port number, or None if server not started.

        """
        if self._server is None:
            return None
        sockets = self._server.sockets
        if sockets:
            addr = sockets[0].getsockname()
            return int(addr[1])
        return None

    async def start(self) -> None:
        """Start the WebSocket server.

        Binds to host:port and begins accepting connections with the
        tesseron-gateway subprotocol.

        REQ-108, REQ-109.

        """
        try:
            import websockets.asyncio.server as ws_server
        except ImportError:
            import websockets.server as ws_server  # type: ignore[no-redef]

        from websockets.typing import Subprotocol

        self._server = await ws_server.serve(
            self._handle_connection,
            self._host,
            self._port,
            subprotocols=[Subprotocol(TESSERON_SUBPROTOCOL)],
        )
        logger.info("GatewayWebSocketServer started on %s:%s", self._host, self.port)

    async def stop(self) -> None:
        """Stop the WebSocket server and close all connections."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.info("GatewayWebSocketServer stopped")

    async def _handle_connection(self, websocket: Any) -> None:
        """Handle a single inbound WebSocket connection.

        Validates subprotocol, creates a session, dispatches messages.

        REQ-108, REQ-109.

        Args:
            websocket: The accepted WebSocket connection.

        """
        from python_tesseron.dispatcher import JsonRpcDispatcher

        # REQ-109: validate subprotocol
        subprotocol = getattr(websocket, "subprotocol", None)
        if subprotocol != TESSERON_SUBPROTOCOL:
            logger.warning(
                "Rejected connection with subprotocol %r (expected %r)",
                subprotocol,
                TESSERON_SUBPROTOCOL,
            )
            await websocket.close(1002, "Invalid subprotocol")
            return

        # Create send callback for dispatcher
        async def send(message: dict[str, Any]) -> None:
            await websocket.send(json.dumps(message))

        # Create dispatcher
        dispatcher = JsonRpcDispatcher(send)

        # Create session (transitions to HANDSHAKING)
        session = self._session_manager.create_session(dispatcher)

        # Register hello handler
        async def handle_hello(params: dict[str, Any] | None) -> Any:
            return await self._session_manager.handle_hello(session, params)

        dispatcher.on("tesseron/hello", handle_hello)

        logger.debug("New connection accepted: session=%s", session.session_id)

        try:
            async for raw_message in websocket:
                message = dispatcher.parse_message(raw_message)
                if message is None:
                    logger.debug("Failed to parse message, ignoring")
                    continue
                await dispatcher.receive(message)
        except Exception:
            logger.exception("Error in WebSocket handler for session %s", session.session_id)
        finally:
            await self._session_manager.close_session(session)
            logger.debug("Connection closed: session=%s", session.session_id)

    def validate_manifest_url(self, url: str) -> None:
        """Validate that a manifest URL references a loopback address.

        Per REQ-138, only loopback addresses are accepted in manifests.

        Args:
            url: The WebSocket URL from the manifest.

        Raises:
            ValueError: If the URL is not a loopback address.

        """
        if not is_loopback_url(url):
            raise ValueError(
                f"Manifest URL {url!r} is not a loopback address. "
                "Only ws://127.x.x.x or ws://localhost connections are permitted."
            )

    async def dial(self, url: str, session_manager: Any | None = None) -> Any:
        """Connect to a discovered app at the given WebSocket URL.

        Per REQ-138: validate the URL is loopback before connecting.

        Args:
            url: WebSocket URL to dial.
            session_manager: Override session manager for this dial (defaults
                to self._session_manager).

        Returns:
            The GatewaySession created for this connection.

        Raises:
            ValueError: If the URL is not a loopback address.

        """
        self.validate_manifest_url(url)

        mgr = session_manager if session_manager is not None else self._session_manager

        try:
            import websockets.asyncio.client as ws_client
        except ImportError:
            import websockets.client as ws_client  # type: ignore[no-redef]

        from python_tesseron.dispatcher import JsonRpcDispatcher

        websocket = await ws_client.connect(url, additional_headers={})

        async def send(message: dict[str, Any]) -> None:
            await websocket.send(json.dumps(message))

        dispatcher = JsonRpcDispatcher(send)
        session = mgr.create_session(dispatcher)

        async def handle_hello(params: dict[str, Any] | None) -> Any:
            return await mgr.handle_hello(session, params)

        dispatcher.on("tesseron/hello", handle_hello)

        # Start background task to pump messages
        asyncio.create_task(self._pump_messages(websocket, dispatcher, session, mgr))

        return session

    async def _pump_messages(
        self,
        websocket: Any,
        dispatcher: Any,
        session: Any,
        session_manager: Any,
    ) -> None:
        """Pump incoming messages from a dialled WebSocket connection.

        Args:
            websocket: Connected WebSocket.
            dispatcher: Dispatcher for this connection.
            session: Gateway session.
            session_manager: Session manager.

        """
        try:
            async for raw_message in websocket:
                message = dispatcher.parse_message(raw_message)
                if message is None:
                    continue
                await dispatcher.receive(message)
        except Exception:
            logger.exception("Error pumping messages for session %s", session.session_id)
        finally:
            await session_manager.close_session(session)
