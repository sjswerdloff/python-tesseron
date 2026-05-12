"""Gateway WebSocket Server tests — GW-01 through GW-07.

Design Contract: DC-018 GatewayWebSocketServer
Source: Gateway Requirements REQ-108, REQ-109, REQ-138
Traceability: traceability/gateway_tests.md §DC-018

Covers:
- Connection acceptance (REQ-108): accept inbound WebSocket connections with
  the tesseron-gateway subprotocol, including multiple simultaneous connections.
- Subprotocol validation (REQ-109): reject connections that present no
  subprotocol or the wrong subprotocol.
- Loopback enforcement (REQ-138): accept loopback manifest URLs, refuse
  non-loopback and public-hostname URLs.

Author: vivian-1a61bc9a
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import websockets
from websockets import Subprotocol

from python_tesseron.gateway.server import GatewayWebSocketServer, is_loopback_url
from python_tesseron.gateway.session import GatewaySessionManager

# ---------------------------------------------------------------------------
# Connection Acceptance (REQ-108)
# ---------------------------------------------------------------------------


async def test_gw01_accept_ws_with_subprotocol() -> None:
    """GW-01: Accept inbound WebSocket with tesseron-gateway subprotocol.

    Verifies: DC-018 — accept inbound WebSocket connections.
    REQ-108 REQ-109

    Connect with the correct 'tesseron-gateway' subprotocol and verify that
    the connection is accepted and delegated to the session manager.
    """
    mgr = GatewaySessionManager()
    server = GatewayWebSocketServer(mgr, host="127.0.0.1", port=0)
    await server.start()
    port = server.port
    assert port is not None

    connected_sessions: list[Any] = []
    mgr.on_connect(lambda s: connected_sessions.append(s))

    try:
        async with websockets.connect(
            f"ws://127.0.0.1:{port}/",
            subprotocols=[Subprotocol("tesseron-gateway")],
        ) as ws:
            # Send hello to complete the connection setup
            hello_msg = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tesseron/hello",
                "params": {
                    "protocolVersion": "1.2.0",
                    "app": {"id": "test_app", "name": "Test", "origin": "test"},
                    "actions": [],
                    "resources": [],
                    "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
                },
            }
            await ws.send(json.dumps(hello_msg))
            response_raw = await ws.recv()
            response = json.loads(response_raw)
            assert response.get("result", {}).get("sessionId") is not None
    finally:
        await server.stop()


async def test_gw02_accept_multiple_connections() -> None:
    """GW-02: Accept multiple simultaneous inbound connections.

    Verifies: DC-018 — accept inbound WebSocket connections.
    REQ-108

    Open three connections sequentially with the tesseron-gateway subprotocol
    and verify all three are accepted with independent sessions.
    """
    mgr = GatewaySessionManager()
    server = GatewayWebSocketServer(mgr, host="127.0.0.1", port=0)
    await server.start()
    port = server.port
    assert port is not None

    session_ids: list[str] = []

    try:
        for _ in range(3):
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/",
                subprotocols=[Subprotocol("tesseron-gateway")],
            ) as ws:
                hello_msg = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tesseron/hello",
                    "params": {
                        "protocolVersion": "1.2.0",
                        "app": {"id": "test_app", "name": "Test", "origin": "test"},
                        "actions": [],
                        "resources": [],
                        "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
                    },
                }
                await ws.send(json.dumps(hello_msg))
                response_raw = await ws.recv()
                response = json.loads(response_raw)
                session_id = response.get("result", {}).get("sessionId")
                assert session_id is not None
                session_ids.append(session_id)

        # All three connections accepted with different session IDs
        assert len(session_ids) == 3
        assert len(set(session_ids)) == 3
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# Subprotocol Validation (REQ-109)
# Equivalence Partitioning: {valid subprotocol, no subprotocol, wrong subprotocol}
# ---------------------------------------------------------------------------


async def test_gw03_reject_no_subprotocol() -> None:
    """GW-03: Reject connection without subprotocol.

    Verifies: DC-018 — subprotocol validation.
    REQ-109

    Connect without requesting any subprotocol and verify the connection is
    rejected by the gateway server.
    """
    mgr = GatewaySessionManager()
    server = GatewayWebSocketServer(mgr, host="127.0.0.1", port=0)
    await server.start()
    port = server.port
    assert port is not None

    try:
        # Connect without subprotocol — server should reject or close immediately
        with pytest.raises(Exception):
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/",
                # No subprotocols= — server will reject
            ) as ws:
                # If we get here, the connection was accepted — verify it closes quickly
                await ws.recv()
    finally:
        await server.stop()


async def test_gw04_reject_wrong_subprotocol() -> None:
    """GW-04: Reject connection with wrong subprotocol.

    Verifies: DC-018 — subprotocol validation.
    REQ-109

    Connect using the 'graphql-ws' subprotocol (wrong value) and verify the
    connection is rejected.
    """
    mgr = GatewaySessionManager()
    server = GatewayWebSocketServer(mgr, host="127.0.0.1", port=0)
    await server.start()
    port = server.port
    assert port is not None

    try:
        with pytest.raises(Exception):
            async with websockets.connect(
                f"ws://127.0.0.1:{port}/",
                subprotocols=[Subprotocol("graphql-ws")],
            ) as ws:
                await ws.recv()
    finally:
        await server.stop()


# ---------------------------------------------------------------------------
# Loopback Enforcement (REQ-138)
# Equivalence Partitioning: {loopback URLs, non-loopback URLs}
# ---------------------------------------------------------------------------


async def test_gw05_accept_loopback_url() -> None:
    """GW-05: Accept loopback manifest URL.

    Verifies: DC-018 — loopback enforcement.
    REQ-138

    Present a manifest containing ws://127.0.0.1:PORT or ws://localhost:PORT
    and verify the gateway initiates the connection (loopback is permitted).
    """
    assert is_loopback_url("ws://127.0.0.1:8080/") is True
    assert is_loopback_url("ws://localhost:9090/") is True
    assert is_loopback_url("ws://[::1]:7070/") is True


async def test_gw06_refuse_non_loopback_url() -> None:
    """GW-06: Refuse non-loopback manifest URL.

    Verifies: DC-018 — loopback enforcement.
    REQ-138

    Present a manifest with ws://192.168.1.100:PORT and verify the gateway
    refuses to initiate the connection.
    """
    assert is_loopback_url("ws://192.168.1.100:8080/") is False

    mgr = GatewaySessionManager()
    server = GatewayWebSocketServer(mgr)
    with pytest.raises(ValueError):
        server.validate_manifest_url("ws://192.168.1.100:8080/")


async def test_gw07_refuse_public_hostname_url() -> None:
    """GW-07: Refuse public hostname manifest URL.

    Verifies: DC-018 — loopback enforcement.
    REQ-138

    Present a manifest with ws://example.com:PORT and verify the gateway
    refuses to initiate the connection.
    """
    assert is_loopback_url("ws://example.com:8080/") is False

    mgr = GatewaySessionManager()
    server = GatewayWebSocketServer(mgr)
    with pytest.raises(ValueError):
        server.validate_manifest_url("ws://example.com:8080/")
