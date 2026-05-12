"""Gateway Action Router tests — GatewayActionRouter (DC-021).

Test IDs: GW-50 through GW-60
Source: traceability/gateway_tests.md §DC-021
Design Contract: DC-021 — GatewayActionRouter

All tests are marked xfail pending gateway implementation.

Requirements covered:
    REQ-121: actions/invoke forwarded as JSON-RPC request to app
    REQ-122: actions/progress forwarded when progressToken supplied
    REQ-123: actions/cancel sent on agent cancellation
    REQ-124: Timeout enforcement (default 60000ms, custom via timeoutMs)
    REQ-136: Authorization — unclaimed session invocations rejected with -32009
    REQ-140: Routing by app_id prefix to the correct app
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Routing (REQ-140, REQ-121)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw50_routing_by_app_id() -> None:
    """GW-50: Tool call routed to correct app by app_id prefix.

    Verifies: DC-021 — with two apps connected, invoking myapp_a__action
    routes to app A and not app B.
    REQ-140
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw51_invoke_forwarded() -> None:
    """GW-51: actions/invoke forwarded to app as JSON-RPC request.

    Verifies: DC-021 — when an MCP tool call arrives, the router sends an
    actions/invoke JSON-RPC request to the target app with the correct params.
    REQ-121
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw52_unknown_app_id() -> None:
    """GW-52: Unknown app_id prefix returns ActionNotFoundError (-32003).

    Verifies: DC-021 — invoking "nonexistent_app__action" where no app with
    that id is connected results in error code -32003.
    REQ-140
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# Progress Forwarding (REQ-122)
# EP: {progressToken supplied, progressToken absent}
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw53_progress_with_token() -> None:
    """GW-53: actions/progress forwarded as MCP notifications/progress when progressToken supplied.

    Verifies: DC-021 — when an invocation carries a progressToken and the app
    sends actions/progress, the router forwards an MCP notifications/progress
    message to the agent.
    REQ-122
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw54_progress_without_token() -> None:
    """GW-54: actions/progress not forwarded when no progressToken supplied.

    Verifies: DC-021 — when an invocation has no progressToken and the app
    sends actions/progress, no MCP notification is forwarded to the agent.
    REQ-122
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# Cancellation (REQ-123)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw55_cancel_on_agent_cancel() -> None:
    """GW-55: actions/cancel sent to app on agent cancellation.

    Verifies: DC-021 — when the agent cancels an in-flight invocation, the
    router sends an actions/cancel notification to the app.
    REQ-123
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw56_cancel_on_timeout() -> None:
    """GW-56: actions/cancel sent to app when invocation times out.

    Verifies: DC-021 — when an invocation exceeds its timeout, the router
    sends an actions/cancel notification to the app before returning -32002.
    REQ-123
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# Timeout BVA (REQ-124)
# BVA: default 60000ms, custom values
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw57_default_timeout() -> None:
    """GW-57: Default 60000ms timeout enforced when no timeoutMs supplied.

    Verifies: DC-021 — invoking an action without timeoutMs and having it
    take more than 60 seconds results in error code -32002 Timeout.
    REQ-124
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw58_custom_timeout() -> None:
    """GW-58: Custom timeoutMs respected for invocation.

    Verifies: DC-021 — invoking with timeoutMs=1000 and having the action
    take more than 1 second results in -32002 after approximately 1 second.
    REQ-124
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw59_action_before_timeout() -> None:
    """GW-59: Action completing before timeout returns success (no timeout error).

    Verifies: DC-021 — invoking with timeoutMs=5000 and having the action
    complete in 100ms results in a successful response, not -32002.
    REQ-124
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# Authorization (REQ-136)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw60_unclaimed_invocation() -> None:
    """GW-60: Invocation routed to unclaimed session rejected with -32009.

    Verifies: DC-021 — routing a tool call to a session that has not yet
    been claimed results in error code -32009 Unauthorized.
    REQ-136
    """
    pytest.fail("Not implemented")
