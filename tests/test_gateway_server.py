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

All tests are marked xfail because the GatewayWebSocketServer implementation
does not yet exist.  When the implementation lands, remove the xfail markers
and wire up the real server under test.

Author: vivian-1a61bc9a
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Connection Acceptance (REQ-108)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw01_accept_ws_with_subprotocol() -> None:
    """GW-01: Accept inbound WebSocket with tesseron-gateway subprotocol.

    Verifies: DC-018 — accept inbound WebSocket connections.
    REQ-108 REQ-109

    Connect with the correct 'tesseron-gateway' subprotocol and verify that
    the connection is accepted and delegated to the session manager.
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw02_accept_multiple_connections() -> None:
    """GW-02: Accept multiple simultaneous inbound connections.

    Verifies: DC-018 — accept inbound WebSocket connections.
    REQ-108

    Open three connections sequentially with the tesseron-gateway subprotocol
    and verify all three are accepted with independent sessions.
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# Subprotocol Validation (REQ-109)
# Equivalence Partitioning: {valid subprotocol, no subprotocol, wrong subprotocol}
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw03_reject_no_subprotocol() -> None:
    """GW-03: Reject connection without subprotocol.

    Verifies: DC-018 — subprotocol validation.
    REQ-109

    Connect without requesting any subprotocol and verify the connection is
    rejected by the gateway server.
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw04_reject_wrong_subprotocol() -> None:
    """GW-04: Reject connection with wrong subprotocol.

    Verifies: DC-018 — subprotocol validation.
    REQ-109

    Connect using the 'graphql-ws' subprotocol (wrong value) and verify the
    connection is rejected.
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# Loopback Enforcement (REQ-138)
# Equivalence Partitioning: {loopback URLs, non-loopback URLs}
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw05_accept_loopback_url() -> None:
    """GW-05: Accept loopback manifest URL.

    Verifies: DC-018 — loopback enforcement.
    REQ-138

    Present a manifest containing ws://127.0.0.1:PORT or ws://localhost:PORT
    and verify the gateway initiates the connection (loopback is permitted).
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw06_refuse_non_loopback_url() -> None:
    """GW-06: Refuse non-loopback manifest URL.

    Verifies: DC-018 — loopback enforcement.
    REQ-138

    Present a manifest with ws://192.168.1.100:PORT and verify the gateway
    refuses to initiate the connection.
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw07_refuse_public_hostname_url() -> None:
    """GW-07: Refuse public hostname manifest URL.

    Verifies: DC-018 — loopback enforcement.
    REQ-138

    Present a manifest with ws://example.com:PORT and verify the gateway
    refuses to initiate the connection.
    """
    pytest.fail("Not implemented")
