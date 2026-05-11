"""Tests for the Pyodide-compatible WebSocket transport.

Test IDs: PY-01 through PY-08
Design Contract: DC-017 (PyodideWebSocketTransport)

Since Pyodide (and therefore ``js`` / ``pyodide.ffi``) is not available in a
desktop pytest environment we mock those modules at the top of this file,
*before* importing the transport under test.  The mock strategy:

- ``js.WebSocket`` is a ``MagicMock``; its ``.new()`` class-method returns a
  fresh ``MockWebSocket`` instance that records calls and allows the test to
  trigger event callbacks directly.
- ``pyodide.ffi.create_proxy`` is a passthrough so that the transport stores
  the original Python callables in ``_proxies`` — allowing tests to invoke them
  as normal functions.
"""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Inject mock modules BEFORE importing the transport under test.
# ---------------------------------------------------------------------------

_mock_js = MagicMock()
_mock_pyodide = MagicMock()
_mock_pyodide_ffi = MagicMock()

# create_proxy is a passthrough so tests can call the stored callables directly.
_mock_pyodide_ffi.create_proxy = lambda fn: fn

sys.modules.setdefault("js", _mock_js)
sys.modules.setdefault("pyodide", _mock_pyodide)
sys.modules.setdefault("pyodide.ffi", _mock_pyodide_ffi)

# Patch the names that transport_ws_pyodide imports at module level.
with (
    patch.dict(sys.modules, {"js": _mock_js, "pyodide": _mock_pyodide, "pyodide.ffi": _mock_pyodide_ffi}),
    patch("builtins.__import__", side_effect=None),
):
    pass  # dict already patched above

# Now we can safely import the transport.
from python_tesseron.transport_ws_pyodide import PyodideWebSocketTransport  # noqa: E402  # isort: skip


# ---------------------------------------------------------------------------
# Helper: mock WebSocket instance
# ---------------------------------------------------------------------------


class MockWebSocket:
    """Minimal stand-in for the browser WebSocket object.

    Stores callback assignments (onopen, onmessage, onclose, onerror) and
    records calls to ``send()`` and ``close()``.

    Attributes:
        send_calls: List of raw strings passed to ``send()``.
        close_called: True if ``close()`` was invoked.
        onopen: Callback registered by the transport.
        onmessage: Callback registered by the transport.
        onclose: Callback registered by the transport.
        onerror: Callback registered by the transport.

    """

    def __init__(self) -> None:
        """Initialise with empty state."""
        self.send_calls: list[str] = []
        self.close_called: bool = False
        self.onopen: Any = None
        self.onmessage: Any = None
        self.onclose: Any = None
        self.onerror: Any = None

    def send(self, data: str) -> None:
        """Record an outgoing text frame.

        Args:
            data: The raw text sent by the transport.

        """
        self.send_calls.append(data)

    def close(self) -> None:
        """Mark the connection as closed."""
        self.close_called = True

    # --- helpers used by tests to simulate browser events ---

    def trigger_open(self) -> None:
        """Simulate the browser firing the WebSocket open event."""
        if self.onopen is not None:
            self.onopen(MagicMock())

    def trigger_message(self, data: Any) -> None:
        """Simulate the browser delivering a message.

        Args:
            data: The ``event.data`` value (str, bytes, or other).

        """
        if self.onmessage is not None:
            event = MagicMock()
            event.data = data
            self.onmessage(event)

    def trigger_close(self) -> None:
        """Simulate the browser firing the WebSocket close event."""
        if self.onclose is not None:
            self.onclose(MagicMock())

    def trigger_error(self) -> None:
        """Simulate the browser firing the WebSocket error event."""
        if self.onerror is not None:
            self.onerror(MagicMock())


# ---------------------------------------------------------------------------
# Fixture: transport wired to a MockWebSocket
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_ws() -> MockWebSocket:
    """Return a fresh MockWebSocket and install it as the return value of WebSocket.new().

    Resets the ``WebSocket.new`` call history before each test so that
    ``assert_called_once_with`` in PY-08 only sees the call made by that test.

    Returns:
        The MockWebSocket instance that WebSocket.new() will return.

    """
    ws_instance = MockWebSocket()
    _mock_js.WebSocket.new.reset_mock()
    _mock_js.WebSocket.new.return_value = ws_instance
    return ws_instance


# ---------------------------------------------------------------------------
# Tests PY-01 through PY-08
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_py01_connect_sets_connection_event(mock_ws: MockWebSocket) -> None:
    """PY-01: REQ-011. Transport connects and sets connection event.

    Calling ``start()`` registers event handlers on the browser WebSocket.
    When the browser fires ``onopen``, the transport's connection event is set
    so that ``wait_for_connection`` resolves.
    """
    transport = PyodideWebSocketTransport("ws://127.0.0.1:9999/")
    await transport.start()

    # Connection event must not be set yet — open hasn't fired.
    assert not transport._connection_event.is_set()

    # Simulate browser firing the open event.
    mock_ws.trigger_open()

    assert transport._connection_event.is_set()

    # wait_for_connection must now return immediately.
    await transport.wait_for_connection(timeout=1.0)

    await transport.close()


@pytest.mark.asyncio
async def test_py02_send_serialises_dict_as_json(mock_ws: MockWebSocket) -> None:
    """PY-02: REQ-011. Send serializes dict as JSON string via ws.send.

    One JSON-RPC envelope per text frame. The transport must call the native
    WebSocket ``send()`` with the JSON-serialised dict and nothing else.
    """
    transport = PyodideWebSocketTransport("ws://127.0.0.1:9999/")
    await transport.start()
    mock_ws.trigger_open()
    await transport.wait_for_connection(timeout=1.0)

    message = {"jsonrpc": "2.0", "id": 1, "method": "tesseron/hello", "params": {}}
    await transport.send(message)

    assert len(mock_ws.send_calls) == 1
    parsed = json.loads(mock_ws.send_calls[0])
    assert parsed == message

    await transport.close()


@pytest.mark.asyncio
async def test_py03_incoming_message_queued_via_onmessage(mock_ws: MockWebSocket) -> None:
    """PY-03: REQ-011. Incoming message queued via onmessage callback.

    When the browser fires ``onmessage`` with a text payload the transport
    must place the raw string on its internal queue so that ``messages()``
    yields it.
    """
    transport = PyodideWebSocketTransport("ws://127.0.0.1:9999/")
    await transport.start()
    mock_ws.trigger_open()

    raw_json = json.dumps({"jsonrpc": "2.0", "method": "actions/cancel", "params": {}})
    mock_ws.trigger_message(raw_json)

    received: list[str] = []
    async for text in transport.messages():
        received.append(text)
        break  # stop after first message

    assert received == [raw_json]

    await transport.close()


@pytest.mark.asyncio
async def test_py04_binary_data_coerced_to_utf8(mock_ws: MockWebSocket) -> None:
    """PY-04: REQ-015. Binary data coerced to UTF-8 string.

    The browser may deliver binary frames. The transport MUST decode them to a
    UTF-8 string before enqueuing, so callers always receive ``str``.
    """
    transport = PyodideWebSocketTransport("ws://127.0.0.1:9999/")
    await transport.start()
    mock_ws.trigger_open()

    payload = {"jsonrpc": "2.0", "method": "tesseron/ping", "params": {}}
    binary_payload = json.dumps(payload).encode("utf-8")
    mock_ws.trigger_message(binary_payload)

    received: list[str] = []
    async for text in transport.messages():
        received.append(text)
        break

    assert len(received) == 1
    assert isinstance(received[0], str)
    assert json.loads(received[0]) == payload

    await transport.close()


@pytest.mark.asyncio
async def test_py05_close_calls_ws_close_and_destroys_proxies(mock_ws: MockWebSocket) -> None:
    """PY-05: Memory leak prevention. Close calls ws.close() and destroys proxies.

    Every proxy created via ``create_proxy`` must have ``destroy()`` called on
    it when the transport closes, otherwise JS objects are never garbage-collected.
    """
    # Use a spy version of create_proxy that wraps callables in objects with a
    # trackable destroy() method.
    destroyed_count = 0

    class TrackingProxy:
        """Wrapper that tracks destroy() calls."""

        def __init__(self, fn: Any) -> None:
            """Store the wrapped function."""
            self._fn = fn

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            """Forward calls to the wrapped function."""
            return self._fn(*args, **kwargs)

        def destroy(self) -> None:
            """Record that destroy was called."""
            nonlocal destroyed_count
            destroyed_count += 1

    tracking_proxies: list[TrackingProxy] = []

    def tracking_create_proxy(fn: Any) -> TrackingProxy:
        proxy = TrackingProxy(fn)
        tracking_proxies.append(proxy)
        return proxy

    with patch("python_tesseron.transport_ws_pyodide.create_proxy", side_effect=tracking_create_proxy):
        transport = PyodideWebSocketTransport("ws://127.0.0.1:9999/")
        await transport.start()

    # Four proxies must have been created (onopen, onmessage, onclose, onerror).
    assert len(tracking_proxies) == 4
    assert destroyed_count == 0

    await transport.close()

    # All proxies must have been destroyed.
    assert mock_ws.close_called
    assert destroyed_count == 4


@pytest.mark.asyncio
async def test_py06_connection_error_terminates_messages_iterator(mock_ws: MockWebSocket) -> None:
    """PY-06: Connection error triggers onerror/onclose properly.

    When the browser fires an error event the transport must enqueue the
    sentinel ``None`` so that the ``messages()`` iterator terminates cleanly
    instead of blocking forever.
    """
    transport = PyodideWebSocketTransport("ws://127.0.0.1:9999/")
    await transport.start()
    mock_ws.trigger_open()

    # Simulate a network error.
    mock_ws.trigger_error()

    received: list[str] = []
    async for text in transport.messages():
        received.append(text)
        # If the iterator does not terminate this loop would hang.

    # No messages were delivered before the error — iterator must have stopped.
    assert received == []

    await transport.close()


@pytest.mark.asyncio
async def test_py07_messages_iterator_yields_until_close(mock_ws: MockWebSocket) -> None:
    """PY-07: Messages iterator yields until close.

    The iterator must yield every message enqueued before the connection
    closes, then stop when the close sentinel is placed in the queue.
    """
    transport = PyodideWebSocketTransport("ws://127.0.0.1:9999/")
    await transport.start()
    mock_ws.trigger_open()

    payloads = [json.dumps({"jsonrpc": "2.0", "id": i, "method": "test", "params": {}}) for i in range(3)]
    for p in payloads:
        mock_ws.trigger_message(p)

    # Signal close to terminate the iterator.
    mock_ws.trigger_close()

    received: list[str] = []
    async for text in transport.messages():
        received.append(text)

    assert received == payloads

    await transport.close()


@pytest.mark.asyncio
async def test_py08_subprotocol_tesseron_gateway_passed_to_constructor(mock_ws: MockWebSocket) -> None:
    """PY-08: Subprotocol tesseron-gateway passed to WebSocket constructor.

    The transport MUST pass the tesseron-gateway subprotocol when constructing
    the native WebSocket object so the server can identify the Tesseron client.
    """
    transport = PyodideWebSocketTransport("ws://127.0.0.1:9999/")
    await transport.start()

    # Verify WebSocket.new() was called with the correct URL and subprotocol list.
    _mock_js.WebSocket.new.assert_called_once_with(
        "ws://127.0.0.1:9999/",
        ["tesseron-gateway"],
    )

    await transport.close()
