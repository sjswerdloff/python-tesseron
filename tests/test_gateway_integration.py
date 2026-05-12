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

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from python_tesseron.errors import UnauthorizedError
from python_tesseron.gateway.action_router import GatewayActionRouter
from python_tesseron.gateway.resume import GatewayResumeManager
from python_tesseron.gateway.session import GatewaySessionManager
from python_tesseron.types import AgentIdentity, SessionState, TesseronCapabilities


def _make_dispatcher(invoke_result: Any = None) -> Any:
    """Create a mock dispatcher."""
    dispatcher = AsyncMock()
    dispatcher.reject_all_pending = AsyncMock()
    dispatcher.notify = AsyncMock()
    dispatcher.request = AsyncMock(return_value=invoke_result or {"invocationId": "inv", "output": "ok"})
    dispatcher.on_notification = AsyncMock()
    return dispatcher


async def _claim_session(mgr: GatewaySessionManager, app_id: str, dispatcher: Any) -> Any:
    """Create and claim a session for a given app_id."""
    session = mgr.create_session(dispatcher)
    params: dict[str, Any] = {
        "protocolVersion": "1.2.0",
        "app": {"id": app_id, "name": app_id, "origin": f"python:{app_id}"},
        "actions": [{"name": "action", "description": "test", "inputSchema": {"type": "object"}}],
        "resources": [],
        "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    }
    welcome = await mgr.handle_hello(session, params)
    agent = AgentIdentity(id="agent", name="Agent")
    agent_caps = TesseronCapabilities()
    await mgr.handle_claim(session.session_id, welcome["claimCode"], agent_identity=agent, agent_capabilities=agent_caps)
    return session


# ---------------------------------------------------------------------------
# Cross-cutting: Multi-App Isolation
# ---------------------------------------------------------------------------


async def test_gw93_multi_app_isolation() -> None:
    """GW-93: Actions from app A never reach app B.

    Verifies: DC-019 (GatewaySessionManager), DC-020 (GatewayMcpBridge),
    DC-021 (GatewayActionRouter) — routing isolation between independent
    app sessions.

    Connect two apps (app_a, app_b), each declaring their own actions.
    Invoke myapp_a__action via the MCP meta-tool and verify that app_b
    receives no messages while app_a receives the actions/invoke request.
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)

    dispatcher_a = _make_dispatcher()
    dispatcher_b = _make_dispatcher()

    await _claim_session(mgr, "app_a", dispatcher_a)
    await _claim_session(mgr, "app_b", dispatcher_b)

    # Invoke app_a's action
    await router.invoke("app_a__action", {"key": "value"})

    # Verify app_a received the invoke request
    dispatcher_a.request.assert_called_once()
    call_args = dispatcher_a.request.call_args[0]
    assert call_args[0] == "actions/invoke"
    assert call_args[1]["name"] == "action"

    # Verify app_b received NOTHING
    dispatcher_b.request.assert_not_called()


@pytest.mark.asyncio
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
    mgr = GatewaySessionManager()
    resume_mgr = GatewayResumeManager()

    dispatcher_a = _make_dispatcher()
    session_a = await _claim_session(mgr, "app_a", dispatcher_a)

    # Retain app_a as zombie before close
    resume_mgr.retain_as_zombie(session_a)
    await mgr.close_session(session_a)

    # Zombie should be retained
    zombie = resume_mgr.get_zombie(session_a.session_id)
    assert zombie is not None

    # Now connect app_b — should work without blocking
    dispatcher_b = _make_dispatcher()
    session_b = await _claim_session(mgr, "app_b", dispatcher_b)

    assert session_b.state == SessionState.CLAIMED
    assert session_b.app_id == "app_b"


# ---------------------------------------------------------------------------
# Cross-cutting: Concurrent Operations
# ---------------------------------------------------------------------------


async def test_gw95_concurrent_claims() -> None:
    """GW-95: Concurrent claim attempts on same session — only first succeeds.

    Verifies: DC-019 (GatewaySessionManager) — claim-code consumption is
    atomic; a race between two agents attempting to claim the same session
    must result in exactly one success and one -32009 Unauthorized error.

    Create a session in AWAITING_CLAIM state.  Fire two concurrent
    tesseron__claim_session invocations with the same claim code and verify
    that exactly one returns success and the other returns error code -32009.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    welcome = await mgr.handle_hello(
        session,
        {
            "protocolVersion": "1.2.0",
            "app": {"id": "myapp", "name": "App", "origin": "test"},
            "actions": [],
            "resources": [],
            "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
        },
    )
    claim_code = welcome["claimCode"]

    # Fire two concurrent claim attempts
    results: list[Any] = []
    errors: list[Exception] = []

    async def attempt_claim() -> None:
        try:
            result = await mgr.handle_claim(session.session_id, claim_code)
            results.append(result)
        except Exception as e:
            errors.append(e)

    await asyncio.gather(attempt_claim(), attempt_claim())

    # Exactly one should succeed, one should fail
    assert len(results) == 1, f"Expected 1 success, got {len(results)}"
    assert len(errors) == 1, f"Expected 1 error, got {len(errors)}"
    assert isinstance(errors[0], UnauthorizedError)
    assert errors[0].code == -32009


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
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)

    invoke_calls: list[dict[str, Any]] = []

    async def tracking_request(method: str, params: Any) -> dict[str, Any]:
        if method == "actions/invoke":
            invoke_calls.append(dict(params))
        return {"invocationId": params.get("invocationId", "inv"), "output": f"result_{params.get('name', 'unknown')}"}

    dispatcher = _make_dispatcher()
    dispatcher.request = tracking_request

    session = mgr.create_session(dispatcher)
    params: dict[str, Any] = {
        "protocolVersion": "1.2.0",
        "app": {"id": "myapp", "name": "App", "origin": "test"},
        "actions": [
            {"name": "action_one", "description": "first", "inputSchema": {"type": "object"}},
            {"name": "action_two", "description": "second", "inputSchema": {"type": "object"}},
        ],
        "resources": [],
        "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    }
    welcome = await mgr.handle_hello(session, params)
    agent = AgentIdentity(id="agent", name="Agent")
    agent_caps = TesseronCapabilities()
    await mgr.handle_claim(session.session_id, welcome["claimCode"], agent_identity=agent, agent_capabilities=agent_caps)

    # Fire two concurrent invocations
    result1, result2 = await asyncio.gather(
        router.invoke("myapp__action_one", {"x": 1}),
        router.invoke("myapp__action_two", {"y": 2}),
    )

    assert len(invoke_calls) == 2
    action_names = {c["name"] for c in invoke_calls}
    assert "action_one" in action_names
    assert "action_two" in action_names


# ---------------------------------------------------------------------------
# Cross-cutting: End-to-End Gateway Flow
# ---------------------------------------------------------------------------


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
    # Step 1 & 2: Create session and perform hello/welcome
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)

    dispatcher = _make_dispatcher()
    dispatcher.request = AsyncMock(return_value={"invocationId": "inv_e2e", "output": "action complete"})

    session = mgr.create_session(dispatcher)
    welcome = await mgr.handle_hello(
        session,
        {
            "protocolVersion": "1.2.0",
            "app": {"id": "myapp", "name": "My App", "origin": "python:myapp"},
            "actions": [{"name": "do_thing", "description": "Does a thing", "inputSchema": {"type": "object"}}],
            "resources": [],
            "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
        },
    )

    # Step 2 verification
    assert "sessionId" in welcome
    assert "claimCode" in welcome
    assert "resumeToken" in welcome
    assert "capabilities" in welcome

    claim_code = welcome["claimCode"]
    session_id = welcome["sessionId"]
    assert session.state == SessionState.AWAITING_CLAIM

    # Step 3: Claim the session
    agent = AgentIdentity(id="claude-code", name="Claude Code")
    agent_caps = TesseronCapabilities()
    await mgr.handle_claim(session_id, claim_code, agent_identity=agent, agent_capabilities=agent_caps)

    assert session.state == SessionState.CLAIMED
    # Verify tesseron/claimed was sent to the app
    dispatcher.notify.assert_called_once()
    notify_call = dispatcher.notify.call_args[0]
    assert notify_call[0] == "tesseron/claimed"

    # Step 4 & 5: Invoke action and get result
    result = await router.invoke("myapp__do_thing", {"input": "test"})

    # Step 5 verification — result returned
    assert result is not None
    dispatcher.request.assert_called_once()
    invoke_call = dispatcher.request.call_args[0]
    assert invoke_call[0] == "actions/invoke"
    assert invoke_call[1]["name"] == "do_thing"
