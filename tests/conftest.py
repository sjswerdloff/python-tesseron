"""Shared pytest fixtures for python-tesseron test suite.

This module provides:
- MockGateway: An in-process mock of the Tesseron gateway that accepts
  WebSocket connections and speaks the Tesseron JSON-RPC protocol.
- Transport helpers: Utilities for creating connections to the mock gateway,
  sending raw envelopes, and asserting on response structure.
- Standard protocol fixtures: pre-built message dicts for common test scenarios.

All fixtures operate on loopback (127.0.0.1) and use the tesseron-gateway
WebSocket subprotocol, matching the real gateway's behaviour.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import websockets
from websockets import Subprotocol
from websockets.asyncio.server import ServerConnection, serve

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SUBPROTOCOL = "tesseron-gateway"
PROTOCOL_VERSION = "1.2.0"

# Default app metadata used in most tests
DEFAULT_APP_ID = "test_app"
DEFAULT_APP_META: dict[str, Any] = {
    "id": DEFAULT_APP_ID,
    "name": "Test App",
    "description": "App used in automated tests",
    "origin": f"python:{DEFAULT_APP_ID}",
}

# Default welcome result returned by mock gateway
DEFAULT_SESSION_ID = "s_test1234567890"
DEFAULT_CLAIM_CODE = "AB3X-7K"
DEFAULT_RESUME_TOKEN = "Xk9f3nN9kOeGqR7mWpLc2v"

# Default gateway capabilities (intersection returned in welcome)
DEFAULT_GATEWAY_CAPABILITIES: dict[str, bool] = {
    "streaming": True,
    "subscriptions": True,
    "sampling": False,
    "elicitation": True,
}


# ---------------------------------------------------------------------------
# Message construction helpers
# ---------------------------------------------------------------------------


def make_request(
    method: str,
    params: dict[str, Any] | None,
    request_id: int | str = 1,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 request dict.

    Args:
        method: The method name.
        params: The params payload (may be None).
        request_id: The request identifier.

    Returns:
        A JSON-RPC request dict with all required fields.

    """
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return msg


def make_notification(
    method: str,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 notification dict (no id field).

    Args:
        method: The method name.
        params: The params payload (may be None).

    Returns:
        A JSON-RPC notification dict without the id field.

    """
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return msg


def make_success_response(
    request_id: int | str | None,
    result: Any,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 success response dict.

    Args:
        request_id: The id from the original request.
        result: The result payload.

    Returns:
        A JSON-RPC success response dict.

    """
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result,
    }


def make_error_response(
    request_id: int | str | None,
    code: int,
    message: str,
    data: Any = None,
) -> dict[str, Any]:
    """Build a JSON-RPC 2.0 error response dict.

    Args:
        request_id: The id from the original request.
        code: JSON-RPC error code.
        message: Human-readable error message.
        data: Optional structured error payload.

    Returns:
        A JSON-RPC error response dict.

    """
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": error,
    }


def make_hello_params(
    app_id: str = DEFAULT_APP_ID,
    actions: list[dict[str, Any]] | None = None,
    resources: list[dict[str, Any]] | None = None,
    capabilities: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build tesseron/hello request params.

    Args:
        app_id: The app identifier.
        actions: Optional list of action manifest entries.
        resources: Optional list of resource manifest entries.
        capabilities: Optional capabilities override.

    Returns:
        HelloParams dict suitable for use in a tesseron/hello request.

    """
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "app": {**DEFAULT_APP_META, "id": app_id},
        "actions": actions or [],
        "resources": resources or [],
        "capabilities": capabilities or {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    }


def make_welcome_result(
    session_id: str = DEFAULT_SESSION_ID,
    capabilities: dict[str, bool] | None = None,
    include_claim_code: bool = True,
    include_resume_token: bool = True,
) -> dict[str, Any]:
    """Build a tesseron/hello welcome result dict.

    Args:
        session_id: The session identifier to include.
        capabilities: Capability intersection to return.
        include_claim_code: Whether to include the claimCode field.
        include_resume_token: Whether to include the resumeToken field.

    Returns:
        WelcomeResult dict suitable as the result of a hello response.

    """
    result: dict[str, Any] = {
        "sessionId": session_id,
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": capabilities or DEFAULT_GATEWAY_CAPABILITIES,
        "agent": {"id": "pending", "name": "Awaiting agent"},
    }
    if include_claim_code:
        result["claimCode"] = DEFAULT_CLAIM_CODE
    if include_resume_token:
        result["resumeToken"] = DEFAULT_RESUME_TOKEN
    return result


# ---------------------------------------------------------------------------
# Mock gateway implementation
# ---------------------------------------------------------------------------


@dataclass
class ReceivedMessage:
    """A message captured by the mock gateway.

    Attributes:
        raw: The raw JSON string received over the wire.
        parsed: The parsed Python dict (or None if parse failed).

    """

    raw: str
    parsed: dict[str, Any] | None = None


@dataclass
class MockGatewayState:
    """Mutable state tracked by a MockGateway instance.

    Attributes:
        received: List of all messages received from the app.
        sent: List of all messages sent to the app (raw JSON strings).
        connection: The active WebSocket connection, once established.
        connection_ready: Event that fires when the first connection is accepted.
        hello_received: Event that fires when tesseron/hello is received.
        hello_params: The params from the most recently received hello request.
        claimed: Whether the session has been marked claimed.

    """

    received: list[ReceivedMessage] = field(default_factory=list)
    sent: list[str] = field(default_factory=list)
    connection: ServerConnection | None = None
    connection_ready: asyncio.Event = field(default_factory=asyncio.Event)
    hello_received: asyncio.Event = field(default_factory=asyncio.Event)
    hello_params: dict[str, Any] | None = None
    claimed: bool = False


class MockGateway:
    """In-process mock of the Tesseron gateway's app-facing WebSocket server.

    The mock gateway accepts WebSocket connections from an app, records all
    messages it receives, and can send scripted responses. It supports the
    full Tesseron handshake flow (hello -> welcome -> claimed) and arbitrary
    test scenarios.

    Usage::

        async with MockGateway() as gw:
            # gw.url is the WebSocket URL to connect to
            # Connect your app to gw.url, then:
            await gw.perform_handshake()
            msg = await gw.send_invoke("addItem", {"sku": "X"})
            response = await gw.receive_response()

    Attributes:
        state: Mutable state accumulated during a test.
        host: Bind address (always 127.0.0.1).
        port: Dynamically-assigned port (0 = let OS choose).

    """

    def __init__(self) -> None:
        """Initialise MockGateway with empty state."""
        self.state = MockGatewayState()
        self.host = "127.0.0.1"
        self._server: Any = None
        self._port: int = 0
        self._server_task: asyncio.Task[None] | None = None
        self._request_id_counter = 100  # Start above app IDs to avoid collision

    @property
    def port(self) -> int:
        """The port the server is listening on (available after start)."""
        return self._port

    @property
    def url(self) -> str:
        """The WebSocket URL for connecting to this mock gateway."""
        return f"ws://{self.host}:{self._port}/"

    async def _handler(self, websocket: ServerConnection) -> None:
        """Handle a single WebSocket connection from an app.

        Args:
            websocket: The accepted WebSocket connection.

        """
        # Only accept one connection; reject subsequent attempts.
        if self.state.connection is not None:
            await websocket.close(code=1008, reason="Already connected")
            return

        self.state.connection = websocket
        self.state.connection_ready.set()

        try:
            async for raw_msg in websocket:
                text = raw_msg if isinstance(raw_msg, str) else raw_msg.decode("utf-8")
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = None

                received = ReceivedMessage(raw=text, parsed=parsed)
                self.state.received.append(received)
                logger.debug("MockGateway received: %s", text)

                # Auto-handle tesseron/hello with default welcome response
                if parsed and parsed.get("method") == "tesseron/hello":
                    self.state.hello_params = parsed.get("params")
                    self.state.hello_received.set()

        except Exception:
            logger.exception("MockGateway connection handler error")

    async def start(self) -> None:
        """Start the WebSocket server on a random loopback port."""
        self._server = await serve(
            self._handler,
            self.host,
            0,  # OS picks port
            subprotocols=[Subprotocol(SUBPROTOCOL)],
        )
        # Retrieve the actual bound port
        sockets = self._server.sockets
        if sockets:
            self._port = sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """Shut down the WebSocket server."""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def __aenter__(self) -> MockGateway:
        """Start the server and return self."""
        await self.start()
        return self

    async def __aexit__(self, *args: Any) -> None:
        """Stop the server."""
        await self.stop()

    async def send(self, msg: dict[str, Any]) -> None:
        """Send a message to the connected app.

        Args:
            msg: The message dict to serialise and send.

        Raises:
            RuntimeError: If no app is connected yet.

        """
        if self.state.connection is None:
            raise RuntimeError("No app connected to MockGateway")
        raw = json.dumps(msg)
        self.state.sent.append(raw)
        await self.state.connection.send(raw)

    async def send_welcome(
        self,
        request_id: int | str = 1,
        session_id: str = DEFAULT_SESSION_ID,
        capabilities: dict[str, bool] | None = None,
    ) -> None:
        """Send a welcome response for the hello request.

        Args:
            request_id: The id from the hello request.
            session_id: Session ID to return.
            capabilities: Capability intersection to return.

        """
        response = make_success_response(
            request_id,
            make_welcome_result(session_id=session_id, capabilities=capabilities),
        )
        await self.send(response)

    async def send_claimed_notification(
        self,
        agent_id: str = "claude-code",
        agent_name: str = "Claude Code",
        agent_capabilities: dict[str, bool] | None = None,
    ) -> None:
        """Send a tesseron/claimed notification to the app.

        Args:
            agent_id: The agent identifier.
            agent_name: Human-readable agent name.
            agent_capabilities: Updated capabilities after claim.

        """
        params: dict[str, Any] = {
            "agent": {"id": agent_id, "name": agent_name},
            "claimedAt": 1714145210123,
        }
        if agent_capabilities is not None:
            params["agentCapabilities"] = agent_capabilities
        notification = make_notification("tesseron/claimed", params)
        await self.send(notification)

    async def send_invoke(
        self,
        action_name: str,
        input_data: dict[str, Any] | None = None,
        invocation_id: str = "inv_test001",
        client: dict[str, Any] | None = None,
    ) -> int | str:
        """Send an actions/invoke request to the app.

        Args:
            action_name: The action to invoke.
            input_data: The input arguments.
            invocation_id: Unique invocation identifier.
            client: Optional client context metadata.

        Returns:
            The request id used (for correlating the response).

        """
        self._request_id_counter += 1
        req_id = self._request_id_counter
        params: dict[str, Any] = {
            "name": action_name,
            "invocationId": invocation_id,
            "input": input_data or {},
        }
        if client is not None:
            params["client"] = client
        await self.send(make_request("actions/invoke", params, request_id=req_id))
        return req_id

    async def send_cancel(self, invocation_id: str) -> None:
        """Send an actions/cancel notification to the app.

        Args:
            invocation_id: The invocation to cancel.

        """
        notification = make_notification("actions/cancel", {"invocationId": invocation_id})
        await self.send(notification)

    async def send_resource_read(self, resource_name: str, request_id: int | str | None = None) -> int | str:
        """Send a resources/read request to the app.

        Args:
            resource_name: The resource to read.
            request_id: Optional explicit request id.

        Returns:
            The request id used.

        """
        if request_id is None:
            self._request_id_counter += 1
            request_id = self._request_id_counter
        await self.send(make_request("resources/read", {"name": resource_name}, request_id=request_id))
        return request_id

    async def wait_for_hello(self, timeout: float = 5.0) -> dict[str, Any]:
        """Wait until tesseron/hello is received from the app.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            The hello params dict.

        Raises:
            TimeoutError: If hello is not received within the timeout.

        """
        await asyncio.wait_for(self.state.hello_received.wait(), timeout=timeout)
        assert self.state.hello_params is not None
        return self.state.hello_params

    async def perform_handshake(
        self,
        session_id: str = DEFAULT_SESSION_ID,
        capabilities: dict[str, bool] | None = None,
        timeout: float = 5.0,
    ) -> dict[str, Any]:
        """Perform the full handshake: wait for hello, send welcome.

        Args:
            session_id: Session ID to return in welcome.
            capabilities: Capability intersection to return.
            timeout: Maximum seconds to wait for hello.

        Returns:
            The hello params received from the app.

        """
        hello_params = await self.wait_for_hello(timeout=timeout)
        # Echo the id from the hello request
        hello_req = next(
            (m.parsed for m in self.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello"),
            None,
        )
        req_id = hello_req["id"] if hello_req else 1
        await self.send_welcome(request_id=req_id, session_id=session_id, capabilities=capabilities)
        return hello_params

    def get_last_sent(self) -> dict[str, Any] | None:
        """Return the last message sent by the mock gateway (parsed).

        Returns:
            The last sent message as a dict, or None if nothing was sent.

        """
        if not self.state.sent:
            return None
        return json.loads(self.state.sent[-1])  # type: ignore[no-any-return]

    def get_received_by_method(self, method: str) -> list[dict[str, Any]]:
        """Return all received messages with the given method.

        Args:
            method: The method to filter by.

        Returns:
            List of parsed message dicts.

        """
        return [m.parsed for m in self.state.received if m.parsed and m.parsed.get("method") == method]

    def get_notifications_sent(self, method: str) -> list[dict[str, Any]]:
        """Return all notifications sent by app with the given method.

        Args:
            method: The notification method to filter by.

        Returns:
            List of parsed notification dicts.

        """
        return [
            m.parsed for m in self.state.received if m.parsed and m.parsed.get("method") == method and "id" not in m.parsed
        ]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def mock_gateway() -> AsyncGenerator[MockGateway, None]:
    """Provide a running MockGateway for each test.

    Yields:
        A started MockGateway instance. Automatically stopped after the test.

    """
    async with MockGateway() as gw:
        yield gw


@pytest.fixture
def default_hello_params() -> dict[str, Any]:
    """Return default tesseron/hello params for testing.

    Returns:
        HelloParams dict with default test app metadata.

    """
    return make_hello_params()


@pytest.fixture
def default_welcome_result() -> dict[str, Any]:
    """Return default welcome result for testing.

    Returns:
        WelcomeResult dict with default test session data.

    """
    return make_welcome_result()


@pytest.fixture
def minimal_action() -> dict[str, Any]:
    """Return a minimal valid action manifest entry.

    Returns:
        ActionManifestEntry dict with required fields only.

    """
    return {
        "name": "doSomething",
        "description": "Performs a test operation",
        "inputSchema": {
            "type": "object",
            "properties": {"param1": {"type": "string"}},
            "required": ["param1"],
        },
    }


@pytest.fixture
def minimal_resource() -> dict[str, Any]:
    """Return a minimal valid resource manifest entry.

    Returns:
        ResourceManifestEntry dict with required fields only.

    """
    return {
        "name": "currentState",
        "description": "The current application state",
        "subscribable": True,
    }


# ---------------------------------------------------------------------------
# Transport helpers (standalone async functions)
# ---------------------------------------------------------------------------


async def connect_to_gateway(url: str, timeout: float = 5.0) -> AsyncIterator[Any]:
    """Connect to a MockGateway using the tesseron-gateway subprotocol.

    Args:
        url: WebSocket URL of the mock gateway.
        timeout: Connection timeout in seconds.

    Yields:
        An open WebSocket connection.

    """
    async with websockets.connect(
        url,
        subprotocols=[Subprotocol(SUBPROTOCOL)],
        open_timeout=timeout,
    ) as ws:
        yield ws


async def send_json(ws: Any, msg: dict[str, Any]) -> None:
    """Send a JSON-RPC message as a WebSocket text frame.

    Args:
        ws: An open WebSocket connection.
        msg: The message dict to serialise.

    """
    await ws.send(json.dumps(msg))


async def recv_json(ws: Any, timeout: float = 5.0) -> dict[str, Any]:
    """Receive one JSON-RPC message from the WebSocket.

    Args:
        ws: An open WebSocket connection.
        timeout: Maximum seconds to wait.

    Returns:
        The parsed message dict.

    Raises:
        asyncio.TimeoutError: If no message arrives within timeout.

    """
    raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
    return json.loads(raw)  # type: ignore[no-any-return]


def assert_jsonrpc_request(msg: dict[str, Any], method: str | None = None) -> None:
    """Assert that a dict is a valid JSON-RPC request.

    Args:
        msg: The message dict to check.
        method: Optional expected method name.

    Raises:
        AssertionError: If the message does not satisfy JSON-RPC request shape.

    """
    assert msg.get("jsonrpc") == "2.0", f"Expected jsonrpc='2.0', got {msg.get('jsonrpc')!r}"
    assert "id" in msg, "Request must have id field"
    assert "method" in msg, "Request must have method field"
    if method is not None:
        assert msg["method"] == method, f"Expected method={method!r}, got {msg['method']!r}"


def assert_jsonrpc_notification(msg: dict[str, Any], method: str | None = None) -> None:
    """Assert that a dict is a valid JSON-RPC notification (no id).

    Args:
        msg: The message dict to check.
        method: Optional expected method name.

    Raises:
        AssertionError: If the message does not satisfy JSON-RPC notification shape.

    """
    assert msg.get("jsonrpc") == "2.0", f"Expected jsonrpc='2.0', got {msg.get('jsonrpc')!r}"
    assert "id" not in msg, "Notification must NOT have id field"
    assert "method" in msg, "Notification must have method field"
    if method is not None:
        assert msg["method"] == method, f"Expected method={method!r}, got {msg['method']!r}"


def assert_jsonrpc_success_response(
    msg: dict[str, Any],
    expected_id: int | str | None = None,
) -> None:
    """Assert that a dict is a valid JSON-RPC success response.

    Args:
        msg: The message dict to check.
        expected_id: Optional expected id value.

    Raises:
        AssertionError: If the message is not a success response.

    """
    assert msg.get("jsonrpc") == "2.0", f"Expected jsonrpc='2.0', got {msg.get('jsonrpc')!r}"
    assert "id" in msg, "Response must have id field"
    assert "result" in msg, "Success response must have result field"
    assert "error" not in msg, "Success response must not have error field"
    if expected_id is not None:
        assert msg["id"] == expected_id, f"Expected id={expected_id!r}, got {msg['id']!r}"


def assert_jsonrpc_error_response(
    msg: dict[str, Any],
    expected_code: int | None = None,
    expected_id: int | str | None = None,
) -> None:
    """Assert that a dict is a valid JSON-RPC error response.

    Args:
        msg: The message dict to check.
        expected_code: Optional expected error code.
        expected_id: Optional expected id value.

    Raises:
        AssertionError: If the message is not an error response.

    """
    assert msg.get("jsonrpc") == "2.0", f"Expected jsonrpc='2.0', got {msg.get('jsonrpc')!r}"
    assert "id" in msg, "Error response must have id field"
    assert "error" in msg, "Error response must have error field"
    assert "result" not in msg, "Error response must not have result field"
    err = msg["error"]
    assert isinstance(err, dict), "error field must be a dict"
    assert "code" in err, "error must have code field"
    assert "message" in err, "error must have message field"
    if expected_code is not None:
        assert err["code"] == expected_code, f"Expected error code {expected_code}, got {err['code']}"
    if expected_id is not None:
        assert msg["id"] == expected_id, f"Expected id={expected_id!r}, got {msg['id']!r}"
