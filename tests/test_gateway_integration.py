"""Gateway cross-cutting integration tests.

Test IDs: GW-93 through GW-97
Source: Gateway Requirements REQ-108 through REQ-147
Design Contracts: DC-018 through DC-025

These tests verify behaviour that spans multiple design contracts and
cannot be attributed to a single component in isolation.

GW-93  Multi-app isolation        DC-019, DC-020, DC-021
GW-94  Zombie no-blocking         DC-019, DC-024
GW-95  Concurrent claims          DC-019
GW-96  Concurrent invocations     DC-021
GW-97  Full lifecycle e2e         DC-018 through DC-021

All tests are marked xfail — the gateway implementation does not yet
exist.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Cross-cutting: Multi-App Isolation
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw93_multi_app_isolation() -> None:
    """GW-93: Actions from app A never reach app B.

    Verifies: DC-019 (GatewaySessionManager), DC-020 (GatewayMcpBridge),
    DC-021 (GatewayActionRouter) — routing isolation between independent
    app sessions.

    Connect two apps (app_a, app_b), each declaring their own actions.
    Invoke myapp_a__action via the MCP meta-tool and verify that app_b
    receives no messages while app_a receives the actions/invoke request.
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw94_zombie_no_blocking() -> None:
    """GW-94: Zombie session for app A does not block app B connections.

    Verifies: DC-019 (GatewaySessionManager), DC-024 (GatewayResumeManager)
    — a retained zombie session must not prevent other apps from connecting
    and completing their handshake.

    Connect app_a, complete the handshake and claim, then disconnect
    app_a so it becomes a zombie.  While app_a is in zombie state,
    connect app_b and verify that app_b can complete its own handshake
    and claim without delay or error.
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# Cross-cutting: Concurrent Operations
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw95_concurrent_claims() -> None:
    """GW-95: Concurrent claim attempts on same session — only first succeeds.

    Verifies: DC-019 (GatewaySessionManager) — claim-code consumption is
    atomic; a race between two agents attempting to claim the same session
    must result in exactly one success and one -32009 Unauthorized error.

    Create a session in AWAITING_CLAIM state.  Fire two concurrent
    tesseron__claim_session invocations with the same claim code and verify
    that exactly one returns success and the other returns error code -32009.
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw96_concurrent_invocations() -> None:
    """GW-96: Concurrent action invocations on same session routed correctly.

    Verifies: DC-021 (GatewayActionRouter) — multiple in-flight tool calls
    on the same claimed session are dispatched and correlated independently
    without interference.

    Claim a session for an app that declares two actions.  Fire two
    concurrent MCP tool calls (one per action) and verify that both
    actions/invoke requests arrive at the app, each with the correct action
    name, and that both results are returned to the correct MCP caller
    without cross-contamination.
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# Cross-cutting: End-to-End Gateway Flow
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw97_full_lifecycle_e2e() -> None:
    """GW-97: Full gateway lifecycle end-to-end.

    Verifies: DC-018 (GatewayWebSocketServer), DC-019 (GatewaySessionManager),
    DC-020 (GatewayMcpBridge), DC-021 (GatewayActionRouter) — the complete
    happy-path flow from app connection through agent tool invocation.

    Steps:
    1. App connects to the gateway via WebSocket using the
       tesseron-gateway subprotocol.
    2. App sends tesseron/hello; gateway returns a welcome response
       containing sessionId, claimCode, resumeToken, and capabilities.
    3. Agent invokes tesseron__claim_session with the printed claim code;
       gateway marks the session CLAIMED and emits tesseron/claimed to
       the app.
    4. Agent invokes an app action via its MCP tool name
       (e.g. myapp__do_thing); gateway forwards actions/invoke to the app.
    5. App returns a result; gateway returns the result to the agent as
       the MCP tool call response.

    All five steps must complete without error.
    """
    pytest.fail("Not implemented")
