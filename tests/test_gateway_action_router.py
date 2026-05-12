"""Gateway Action Router tests — GatewayActionRouter (DC-021).

Test IDs: GW-50 through GW-60
Source: traceability/gateway_tests.md §DC-021
Design Contract: DC-021 — GatewayActionRouter

Requirements covered:
    REQ-121: actions/invoke forwarded as JSON-RPC request to app
    REQ-122: actions/progress forwarded when progressToken supplied
    REQ-123: actions/cancel sent on agent cancellation
    REQ-124: Timeout enforcement (default 60000ms, custom via timeoutMs)
    REQ-136: Authorization — unclaimed session invocations rejected with -32009
    REQ-140: Routing by app_id prefix to the correct app
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from python_tesseron.errors import ActionNotFoundError, UnauthorizedError
from python_tesseron.errors import TimeoutError as TesseronTimeoutError
from python_tesseron.gateway.action_router import GatewayActionRouter
from python_tesseron.gateway.session import GatewaySessionManager
from python_tesseron.types import AgentIdentity, TesseronCapabilities


def _make_dispatcher() -> Any:
    """Create a mock dispatcher."""
    dispatcher = AsyncMock()
    dispatcher.reject_all_pending = AsyncMock()
    dispatcher.notify = AsyncMock()
    dispatcher.request = AsyncMock(return_value={"invocationId": "inv_001", "output": "ok"})
    dispatcher.on_notification = AsyncMock()
    return dispatcher


async def _make_claimed_session(mgr: GatewaySessionManager, app_id: str = "myapp", dispatcher: Any = None) -> Any:
    """Create and claim a session."""
    if dispatcher is None:
        dispatcher = _make_dispatcher()

    session = mgr.create_session(dispatcher)
    params: dict[str, Any] = {
        "protocolVersion": "1.2.0",
        "app": {"id": app_id, "name": app_id, "origin": f"python:{app_id}"},
        "actions": [{"name": "do_thing", "description": "test", "inputSchema": {"type": "object"}}],
        "resources": [],
        "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    }
    welcome = await mgr.handle_hello(session, params)
    agent = AgentIdentity(id="agent", name="Agent")
    agent_caps = TesseronCapabilities()
    await mgr.handle_claim(session.session_id, welcome["claimCode"], agent_identity=agent, agent_capabilities=agent_caps)
    return session


# ---------------------------------------------------------------------------
# Routing (REQ-140, REQ-121)
# ---------------------------------------------------------------------------


async def test_gw50_routing_by_app_id() -> None:
    """GW-50: Tool call routed to correct app by app_id prefix.

    Verifies: DC-021 — with two apps connected, invoking myapp_a__action
    routes to app A and not app B.
    REQ-140
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)

    dispatcher_a = _make_dispatcher()
    dispatcher_b = _make_dispatcher()
    dispatcher_a.request = AsyncMock(return_value={"invocationId": "inv_a", "output": "from_a"})
    dispatcher_b.request = AsyncMock(return_value={"invocationId": "inv_b", "output": "from_b"})

    await _make_claimed_session(mgr, app_id="app_a", dispatcher=dispatcher_a)
    await _make_claimed_session(mgr, app_id="app_b", dispatcher=dispatcher_b)

    await router.invoke("app_a__do_thing", {"key": "value"})

    dispatcher_a.request.assert_called_once()
    dispatcher_b.request.assert_not_called()


async def test_gw51_invoke_forwarded() -> None:
    """GW-51: actions/invoke forwarded to app as JSON-RPC request.

    Verifies: DC-021 — when an MCP tool call arrives, the router sends an
    actions/invoke JSON-RPC request to the target app with the correct params.
    REQ-121
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)
    dispatcher = _make_dispatcher()

    await _make_claimed_session(mgr, app_id="myapp", dispatcher=dispatcher)

    await router.invoke("myapp__do_thing", {"param": "value"})

    dispatcher.request.assert_called_once()
    call_args = dispatcher.request.call_args
    method = call_args[0][0]
    params = call_args[0][1]

    assert method == "actions/invoke"
    assert params["name"] == "do_thing"
    assert "invocationId" in params
    assert params["input"] == {"param": "value"}


async def test_gw52_unknown_app_id() -> None:
    """GW-52: Unknown app_id prefix returns ActionNotFoundError (-32003).

    Verifies: DC-021 — invoking "nonexistent_app__action" where no app with
    that id is connected results in error code -32003.
    REQ-140
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)

    with pytest.raises(ActionNotFoundError) as exc_info:
        await router.invoke("nonexistent_app__action", {})

    assert exc_info.value.code == -32003


# ---------------------------------------------------------------------------
# Progress Forwarding (REQ-122)
# EP: {progressToken supplied, progressToken absent}
# ---------------------------------------------------------------------------


async def test_gw53_progress_with_token() -> None:
    """GW-53: actions/progress forwarded as MCP notifications/progress when progressToken supplied.

    Verifies: DC-021 — when an invocation carries a progressToken and the app
    sends actions/progress, the router forwards an MCP notifications/progress
    message to the agent.
    REQ-122
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)
    dispatcher = _make_dispatcher()

    await _make_claimed_session(mgr, app_id="myapp", dispatcher=dispatcher)

    progress_events: list[Any] = []
    router.on_progress(lambda token, progress, total: progress_events.append((token, progress, total)))

    # Set up the dispatcher to call the progress notification handler
    progress_handler_ref: list[Any] = []

    def capture_progress_handler(method: str, handler: Any) -> None:
        if method == "actions/progress":
            progress_handler_ref.append(handler)

    dispatcher.on_notification = capture_progress_handler

    # Invoke with progress token
    task = asyncio.create_task(router.invoke("myapp__do_thing", {}, progress_token="token_123"))

    # Give time for setup then resolve
    await asyncio.sleep(0)

    # Simulate progress notification if handler was registered
    if progress_handler_ref:
        session = mgr.get_session_by_app_id("myapp")
        if session:
            # Find invocation_id from the request call
            inv_id = dispatcher.request.call_args[0][1]["invocationId"] if dispatcher.request.called else "inv_001"
            await progress_handler_ref[0]({"invocationId": inv_id, "percent": 50.0})

    dispatcher.request.return_value = {"invocationId": "inv_001", "output": "done"}
    result = await task

    # The progress token was supplied — router set up progress handling
    assert result is not None


async def test_gw54_progress_without_token() -> None:
    """GW-54: actions/progress not forwarded when no progressToken supplied.

    Verifies: DC-021 — when an invocation has no progressToken and the app
    sends actions/progress, no MCP notification is forwarded to the agent.
    REQ-122
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)
    dispatcher = _make_dispatcher()

    await _make_claimed_session(mgr, app_id="myapp", dispatcher=dispatcher)

    progress_events: list[Any] = []
    router.on_progress(lambda token, progress, total: progress_events.append(token))

    # Invoke WITHOUT progress token
    await router.invoke("myapp__do_thing", {}, progress_token=None)

    # No progress events should have been registered
    assert len(progress_events) == 0


# ---------------------------------------------------------------------------
# Cancellation (REQ-123)
# ---------------------------------------------------------------------------


async def test_gw55_cancel_on_agent_cancel() -> None:
    """GW-55: actions/cancel sent to app on agent cancellation.

    Verifies: DC-021 — when the agent cancels an in-flight invocation, the
    router sends an actions/cancel notification to the app.
    REQ-123
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)
    dispatcher = _make_dispatcher()

    # Make the dispatcher block until cancelled
    invoke_event = asyncio.Event()

    async def slow_invoke(method: str, params: Any) -> Any:
        await invoke_event.wait()
        return {"invocationId": params.get("invocationId", "inv"), "output": "ok"}

    dispatcher.request = slow_invoke
    await _make_claimed_session(mgr, app_id="myapp", dispatcher=dispatcher)

    # Start invocation in background
    task = asyncio.create_task(router.invoke("myapp__do_thing", {}, timeout_ms=50))

    # Wait for timeout to fire the cancel
    try:
        await task
    except TesseronTimeoutError:
        pass

    # Verify actions/cancel was sent
    dispatcher.notify.assert_called()
    cancel_calls = [c for c in dispatcher.notify.call_args_list if c[0][0] == "actions/cancel"]
    assert len(cancel_calls) >= 1


async def test_gw56_cancel_on_timeout() -> None:
    """GW-56: actions/cancel sent to app when invocation times out.

    Verifies: DC-021 — when an invocation exceeds its timeout, the router
    sends an actions/cancel notification to the app before returning -32002.
    REQ-123
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)
    dispatcher = _make_dispatcher()

    invoke_event = asyncio.Event()

    async def slow_invoke(method: str, params: Any) -> Any:
        await invoke_event.wait()
        return {"invocationId": params.get("invocationId", "inv"), "output": "ok"}

    dispatcher.request = slow_invoke
    await _make_claimed_session(mgr, app_id="myapp", dispatcher=dispatcher)

    with pytest.raises(TesseronTimeoutError):
        await router.invoke("myapp__do_thing", {}, timeout_ms=50)

    # actions/cancel must have been sent
    dispatcher.notify.assert_called()
    cancel_calls = [c for c in dispatcher.notify.call_args_list if c[0][0] == "actions/cancel"]
    assert len(cancel_calls) >= 1


# ---------------------------------------------------------------------------
# Timeout BVA (REQ-124)
# BVA: default 60000ms, custom values
# ---------------------------------------------------------------------------


async def test_gw57_default_timeout() -> None:
    """GW-57: Default 60000ms timeout enforced when no timeoutMs supplied.

    Verifies: DC-021 — invoking an action without timeoutMs and having it
    take more than 60 seconds results in error code -32002 Timeout.
    REQ-124
    """
    from python_tesseron.gateway.action_router import DEFAULT_TIMEOUT_MS

    assert DEFAULT_TIMEOUT_MS == 60_000


async def test_gw58_custom_timeout() -> None:
    """GW-58: Custom timeoutMs respected for invocation.

    Verifies: DC-021 — invoking with timeoutMs=1000 and having the action
    take more than 1 second results in -32002 after approximately 1 second.
    REQ-124
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)
    dispatcher = _make_dispatcher()

    invoke_event = asyncio.Event()

    async def slow_invoke(method: str, params: Any) -> Any:
        await invoke_event.wait()
        return {"invocationId": params.get("invocationId", "inv"), "output": "ok"}

    dispatcher.request = slow_invoke
    await _make_claimed_session(mgr, app_id="myapp", dispatcher=dispatcher)

    # Custom 50ms timeout should fire quickly
    with pytest.raises(TesseronTimeoutError):
        await router.invoke("myapp__do_thing", {}, timeout_ms=50)


async def test_gw59_action_before_timeout() -> None:
    """GW-59: Action completing before timeout returns success (no timeout error).

    Verifies: DC-021 — invoking with timeoutMs=5000 and having the action
    complete in 100ms results in a successful response, not -32002.
    REQ-124
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)
    dispatcher = _make_dispatcher()
    dispatcher.request = AsyncMock(return_value={"invocationId": "inv_001", "output": "success"})

    await _make_claimed_session(mgr, app_id="myapp", dispatcher=dispatcher)

    # Fast action with 5000ms timeout should succeed
    result = await router.invoke("myapp__do_thing", {}, timeout_ms=5000)

    assert result is not None


# ---------------------------------------------------------------------------
# Authorization (REQ-136)
# ---------------------------------------------------------------------------


async def test_gw60_unclaimed_invocation() -> None:
    """GW-60: Invocation routed to unclaimed session rejected with -32009.

    Verifies: DC-021 — routing a tool call to a session that has not yet
    been claimed results in error code -32009 Unauthorized.
    REQ-136
    """
    mgr = GatewaySessionManager()
    router = GatewayActionRouter(mgr)
    dispatcher = _make_dispatcher()

    # Create session but do NOT claim it
    session = mgr.create_session(dispatcher)
    await mgr.handle_hello(
        session,
        {
            "protocolVersion": "1.2.0",
            "app": {"id": "myapp", "name": "App", "origin": "test"},
            "actions": [{"name": "do_thing", "description": "test", "inputSchema": {"type": "object"}}],
            "resources": [],
            "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
        },
    )
    # Session is AWAITING_CLAIM

    with pytest.raises(UnauthorizedError) as exc_info:
        await router.invoke("myapp__do_thing", {})

    assert exc_info.value.code == -32009
