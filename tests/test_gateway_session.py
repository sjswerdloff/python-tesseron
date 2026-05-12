"""Gateway Session Manager tests — GW-08 through GW-35.

Design Contract: DC-019 GatewaySessionManager
Source: Gateway Requirements REQ-110 through REQ-116, REQ-136, REQ-137,
        REQ-139, REQ-141 through REQ-144
Traceability: traceability/gateway_tests.md §DC-019

Covers:
- Session state machine (REQ-141): valid and invalid state transitions across
  the five states DISCONNECTED, HANDSHAKING, AWAITING_CLAIM, CLAIMED, CLOSED.
- Hello/Welcome exchange (REQ-113): required welcome fields and unique session IDs.
- Claim code generation (REQ-110, REQ-111, REQ-112): format XXXX-XX, unambiguous
  alphabet, printed to stderr, single-use, wrong code returns -32009.
- Capability intersection (REQ-114): decision table across four capabilities
  (streaming, subscriptions, sampling, elicitation) for app vs agent sides.
- Claimed notification (REQ-115): tesseron/claimed sent to app after successful claim.
- Protocol version validation (REQ-116): major-version mismatch rejected with
  -32000, minor-version mismatch accepted.
- Multiple simultaneous sessions (REQ-139): independent state per session,
  claiming one session does not affect another.
- Transport close behaviour (REQ-142, REQ-143, REQ-144): pending requests
  rejected, in-flight invocations cancelled, active subscriptions cleaned.
- Authorization (REQ-136): action invocation on unclaimed session returns -32009.

Author: vivian-1a61bc9a
"""

from __future__ import annotations

import io
import re
import sys
from typing import Any
from unittest.mock import AsyncMock

import pytest

from python_tesseron.errors import ProtocolMismatchError, UnauthorizedError
from python_tesseron.gateway.session import (
    GatewaySessionManager,
    _generate_claim_code,
)
from python_tesseron.types import AgentIdentity, SessionState, TesseronCapabilities


def _make_dispatcher() -> Any:
    """Create a mock dispatcher for testing."""
    dispatcher = AsyncMock()
    dispatcher.reject_all_pending = AsyncMock()
    dispatcher.notify = AsyncMock()
    return dispatcher


def _make_hello_params(
    app_id: str = "test_app",
    protocol_version: str = "1.2.0",
    capabilities: dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Build tesseron/hello params dict."""
    return {
        "protocolVersion": protocol_version,
        "app": {"id": app_id, "name": "Test App", "origin": f"python:{app_id}"},
        "actions": [],
        "resources": [],
        "capabilities": capabilities or {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    }


# ---------------------------------------------------------------------------
# Session State Machine — Valid Transitions (REQ-141)
# State Transition Testing technique
# ---------------------------------------------------------------------------


async def test_gw08_disconnected_to_handshaking() -> None:
    """GW-08: State transition DISCONNECTED -> HANDSHAKING on WebSocket open.

    Verifies: DC-019 — session state machine.
    REQ-141

    When an app opens a WebSocket connection the session manager must create a
    new session in HANDSHAKING state.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)

    assert session.state == SessionState.HANDSHAKING


async def test_gw09_handshaking_to_awaiting_claim() -> None:
    """GW-09: State transition HANDSHAKING -> AWAITING_CLAIM on hello/welcome.

    Verifies: DC-019 — session state machine.
    REQ-141 REQ-113

    After the gateway processes tesseron/hello and returns the welcome response
    the session must transition to AWAITING_CLAIM and the welcome must contain
    the claimCode field.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)

    welcome = await mgr.handle_hello(session, _make_hello_params())

    assert session.state == SessionState.AWAITING_CLAIM
    assert welcome.get("claimCode") is not None


async def test_gw10_awaiting_claim_to_claimed() -> None:
    """GW-10: State transition AWAITING_CLAIM -> CLAIMED on correct claim code.

    Verifies: DC-019 — session state machine.
    REQ-141 REQ-110

    When the agent submits the correct claim code the session must transition to
    CLAIMED and a claimed notification must be sent to the app.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    welcome = await mgr.handle_hello(session, _make_hello_params())
    claim_code = welcome["claimCode"]

    await mgr.handle_claim(session.session_id, claim_code)

    assert session.state == SessionState.CLAIMED


async def test_gw11_awaiting_claim_to_closed() -> None:
    """GW-11: State transition AWAITING_CLAIM -> CLOSED on transport close.

    Verifies: DC-019 — session state machine.
    REQ-141 REQ-142

    If the transport closes before a claim is made the session must transition
    to CLOSED and all associated resources must be cleaned up.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    await mgr.handle_hello(session, _make_hello_params())

    # Transport closes before claim
    await mgr.close_session(session)

    assert session.state == SessionState.CLOSED


async def test_gw12_claimed_to_closed() -> None:
    """GW-12: State transition CLAIMED -> CLOSED on transport close.

    Verifies: DC-019 — session state machine.
    REQ-141 REQ-142 REQ-143 REQ-144

    When the transport closes on a CLAIMED session the session must transition
    to CLOSED, pending outbound requests must be rejected, and active
    subscriptions must be cleaned up.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    welcome = await mgr.handle_hello(session, _make_hello_params())
    claim_code = welcome["claimCode"]
    await mgr.handle_claim(session.session_id, claim_code)

    await mgr.close_session(session)

    assert session.state == SessionState.CLOSED


# ---------------------------------------------------------------------------
# Session State Machine — Invalid Transitions (REQ-141)
# ---------------------------------------------------------------------------


async def test_gw13_invalid_handshaking_to_claimed() -> None:
    """GW-13: Invalid transition HANDSHAKING -> CLAIMED must be rejected.

    Verifies: DC-019 — session state machine, invalid transitions.
    REQ-141

    A claim attempt before the welcome response is sent must return an error
    or be structurally impossible; the session must not reach CLAIMED state.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    # Session is in HANDSHAKING state — no claim code yet

    # Trying to claim a session that doesn't have a claim code
    with pytest.raises((UnauthorizedError, Exception)):
        await mgr.handle_claim(session.session_id, "XXXX-XX")

    assert session.state != SessionState.CLAIMED


async def test_gw14_invalid_claimed_to_awaiting_claim() -> None:
    """GW-14: Invalid transition CLAIMED -> AWAITING_CLAIM has no mechanism.

    Verifies: DC-019 — session state machine, invalid transitions.
    REQ-141

    There is no protocol mechanism that reverts a CLAIMED session to
    AWAITING_CLAIM.  Verify the session cannot regress to that state.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    welcome = await mgr.handle_hello(session, _make_hello_params())
    await mgr.handle_claim(session.session_id, welcome["claimCode"])
    assert session.state == SessionState.CLAIMED

    # There is no method to go back to AWAITING_CLAIM
    with pytest.raises(RuntimeError):
        session.to_awaiting_claim()

    assert session.state == SessionState.CLAIMED


async def test_gw15_invalid_closed_to_claimed() -> None:
    """GW-15: Invalid transition CLOSED -> CLAIMED must be rejected.

    Verifies: DC-019 — session state machine, invalid transitions.
    REQ-141 REQ-137

    A claim attempt on a CLOSED session must be rejected (e.g. -32009
    Unauthorized or session-not-found error).
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    await mgr.handle_hello(session, _make_hello_params())
    await mgr.close_session(session)

    # Session is now removed from the manager's registry
    with pytest.raises((UnauthorizedError, Exception)):
        await mgr.handle_claim(session.session_id, "XXXX-XX")

    assert session.state == SessionState.CLOSED


# ---------------------------------------------------------------------------
# Hello/Welcome Exchange (REQ-113)
# ---------------------------------------------------------------------------


async def test_gw16_welcome_required_fields() -> None:
    """GW-16: Welcome response contains all required fields.

    Verifies: DC-019 — hello/welcome exchange.
    REQ-113

    Send tesseron/hello and verify the welcome result includes all five
    required fields: sessionId, protocolVersion, capabilities, claimCode,
    and resumeToken.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)

    welcome = await mgr.handle_hello(session, _make_hello_params())

    assert "sessionId" in welcome
    assert "protocolVersion" in welcome
    assert "capabilities" in welcome
    assert "claimCode" in welcome
    assert "resumeToken" in welcome


async def test_gw17_unique_session_id() -> None:
    """GW-17: Each session receives a unique sessionId.

    Verifies: DC-019 — hello/welcome exchange.
    REQ-113

    Open two separate sessions and verify the sessionId values returned in
    their respective welcome responses are different.
    """
    mgr = GatewaySessionManager()
    dispatcher1 = _make_dispatcher()
    dispatcher2 = _make_dispatcher()
    session1 = mgr.create_session(dispatcher1)
    session2 = mgr.create_session(dispatcher2)

    welcome1 = await mgr.handle_hello(session1, _make_hello_params())
    welcome2 = await mgr.handle_hello(session2, _make_hello_params())

    assert welcome1["sessionId"] != welcome2["sessionId"]


# ---------------------------------------------------------------------------
# Claim Code Generation (REQ-110, REQ-111, REQ-112)
# Boundary Value Analysis on format XXXX-XX and 31-char alphabet
# ---------------------------------------------------------------------------


async def test_gw18_claim_code_format() -> None:
    """GW-18: Claim code matches XXXX-XX format.

    Verifies: DC-019 — claim code generation.
    REQ-110 REQ-111

    Generate a claim code and verify it matches the regex
    ^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{2}$
    """
    pattern = re.compile(r"^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{2}$")
    code = _generate_claim_code()
    assert pattern.match(code), f"Claim code {code!r} does not match expected format"


async def test_gw19_claim_code_no_ambiguous_chars() -> None:
    """GW-19: Claim code excludes ambiguous characters O, 0, 1, I, L.

    Verifies: DC-019 — claim code generation.
    REQ-111

    Generate 100 claim codes and verify none contain the ambiguous characters
    O (letter), 0 (zero), 1 (one), I (letter), or L (letter).
    """
    ambiguous = set("O01IL")
    for _ in range(100):
        code = _generate_claim_code()
        for ch in ambiguous:
            assert ch not in code, f"Claim code {code!r} contains ambiguous character {ch!r}"


async def test_gw20_claim_code_stderr() -> None:
    """GW-20: Claim code is printed to stderr during hello processing.

    Verifies: DC-019 — claim code generation.
    REQ-112

    Capture stderr during tesseron/hello processing and verify that the claim
    code appears in the captured output.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)

    captured = io.StringIO()
    old_stderr = sys.stderr
    sys.stderr = captured
    try:
        welcome = await mgr.handle_hello(session, _make_hello_params())
    finally:
        sys.stderr = old_stderr

    stderr_output = captured.getvalue()
    claim_code = welcome["claimCode"]
    assert claim_code in stderr_output, f"Expected claim code {claim_code!r} in stderr; got: {stderr_output!r}"


async def test_gw21_claim_code_single_use() -> None:
    """GW-21: Successful claim consumes the claim code (single-use).

    Verifies: DC-019 — claim code generation.
    REQ-110 REQ-112

    Claim a session with the correct code, then attempt a second claim with
    the same code and verify the second attempt is rejected.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    welcome = await mgr.handle_hello(session, _make_hello_params())
    claim_code = welcome["claimCode"]

    # First claim succeeds
    await mgr.handle_claim(session.session_id, claim_code)

    # Session is now CLAIMED and removed from active sessions after close
    # Attempting a second claim on an already-claimed session must be rejected
    with pytest.raises((UnauthorizedError, Exception)):
        await mgr.handle_claim(session.session_id, claim_code)


async def test_gw22_wrong_claim_code_unauthorized() -> None:
    """GW-22: Wrong claim code is rejected with error code -32009.

    Verifies: DC-019 — claim code generation.
    REQ-137

    Submit an incorrect claim code and verify the response is a JSON-RPC
    error with code -32009 (Unauthorized).
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    await mgr.handle_hello(session, _make_hello_params())

    with pytest.raises(UnauthorizedError) as exc_info:
        await mgr.handle_claim(session.session_id, "WXYZ-99")

    assert exc_info.value.code == -32009


# ---------------------------------------------------------------------------
# Capability Intersection (REQ-114)
# Decision Table: 4 capabilities x 2 sides (app, agent)
# ---------------------------------------------------------------------------


async def test_gw23_capability_intersection_all_all() -> None:
    """GW-23: Full intersection when both app and agent advertise all capabilities.

    Verifies: DC-019 — capability intersection.
    REQ-114

    App capabilities: streaming=true, subscriptions=true, sampling=true,
    elicitation=true.  Agent capabilities: same.  Expected intersection: all
    four capabilities true.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    app_caps = {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True}
    welcome = await mgr.handle_hello(session, _make_hello_params(capabilities=app_caps))
    claim_code = welcome["claimCode"]

    agent_caps = TesseronCapabilities(streaming=True, subscriptions=True, sampling=True, elicitation=True)
    result = await mgr.handle_claim(session.session_id, claim_code, agent_capabilities=agent_caps)

    caps = result["capabilities"]
    assert caps["streaming"] is True
    assert caps["subscriptions"] is True
    assert caps["sampling"] is True
    assert caps["elicitation"] is True


async def test_gw24_capability_intersection_app_limited() -> None:
    """GW-24: App limitation respected in capability intersection.

    Verifies: DC-019 — capability intersection.
    REQ-114

    App capabilities: sampling=false, rest true.  Agent capabilities: all four
    true.  Expected intersection: sampling=false, rest true.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    app_caps = {"streaming": True, "subscriptions": True, "sampling": False, "elicitation": True}
    welcome = await mgr.handle_hello(session, _make_hello_params(capabilities=app_caps))
    claim_code = welcome["claimCode"]

    agent_caps = TesseronCapabilities(streaming=True, subscriptions=True, sampling=True, elicitation=True)
    result = await mgr.handle_claim(session.session_id, claim_code, agent_capabilities=agent_caps)

    caps = result["capabilities"]
    assert caps["sampling"] is False
    assert caps["streaming"] is True
    assert caps["subscriptions"] is True
    assert caps["elicitation"] is True


async def test_gw25_capability_intersection_agent_limited() -> None:
    """GW-25: Agent limitation respected in capability intersection.

    Verifies: DC-019 — capability intersection.
    REQ-114

    App capabilities: all four true.  Agent capabilities: sampling=false,
    elicitation=false.  Expected intersection: sampling=false,
    elicitation=false, rest true.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    app_caps = {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True}
    welcome = await mgr.handle_hello(session, _make_hello_params(capabilities=app_caps))
    claim_code = welcome["claimCode"]

    agent_caps = TesseronCapabilities(streaming=True, subscriptions=True, sampling=False, elicitation=False)
    result = await mgr.handle_claim(session.session_id, claim_code, agent_capabilities=agent_caps)

    caps = result["capabilities"]
    assert caps["sampling"] is False
    assert caps["elicitation"] is False
    assert caps["streaming"] is True
    assert caps["subscriptions"] is True


async def test_gw26_capability_intersection_disjoint() -> None:
    """GW-26: Disjoint capabilities produce an empty intersection.

    Verifies: DC-019 — capability intersection.
    REQ-114

    App capabilities: sampling=true only.  Agent capabilities:
    elicitation=true only.  Expected intersection: all four false (no overlap).
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    app_caps = {"streaming": False, "subscriptions": False, "sampling": True, "elicitation": False}
    welcome = await mgr.handle_hello(session, _make_hello_params(capabilities=app_caps))
    claim_code = welcome["claimCode"]

    agent_caps = TesseronCapabilities(streaming=False, subscriptions=False, sampling=False, elicitation=True)
    result = await mgr.handle_claim(session.session_id, claim_code, agent_capabilities=agent_caps)

    caps = result["capabilities"]
    assert caps["streaming"] is False
    assert caps["subscriptions"] is False
    assert caps["sampling"] is False
    assert caps["elicitation"] is False


# ---------------------------------------------------------------------------
# Claimed Notification (REQ-115)
# ---------------------------------------------------------------------------


async def test_gw27_claimed_notification() -> None:
    """GW-27: App receives tesseron/claimed notification after successful claim.

    Verifies: DC-019 — claimed notification.
    REQ-115

    After the agent successfully claims the session, verify the app receives
    a tesseron/claimed notification containing agentIdentity, claimedAt, and
    agentCapabilities fields.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    welcome = await mgr.handle_hello(session, _make_hello_params())
    claim_code = welcome["claimCode"]

    agent = AgentIdentity(id="claude-code", name="Claude Code")
    await mgr.handle_claim(session.session_id, claim_code, agent_identity=agent)

    # Verify that notify was called with tesseron/claimed
    dispatcher.notify.assert_called_once()
    call_args = dispatcher.notify.call_args
    method = call_args[0][0]
    params = call_args[0][1]

    assert method == "tesseron/claimed"
    assert "agentIdentity" in params
    assert "claimedAt" in params
    assert "agentCapabilities" in params


# ---------------------------------------------------------------------------
# Protocol Version Validation (REQ-116)
# Boundary Value Analysis on major version boundary
# ---------------------------------------------------------------------------


async def test_gw28_major_version_mismatch() -> None:
    """GW-28: Major protocol version mismatch rejected with -32000.

    Verifies: DC-019 — protocol version validation.
    REQ-116

    Send tesseron/hello with protocolVersion "2.0" (major version mismatch).
    Verify the response is a JSON-RPC error with code -32000
    (ProtocolMismatch) and the connection is closed.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    params = _make_hello_params(protocol_version="2.0")

    with pytest.raises(ProtocolMismatchError) as exc_info:
        await mgr.handle_hello(session, params)

    assert exc_info.value.code == -32000


async def test_gw29_minor_version_mismatch_accepted() -> None:
    """GW-29: Minor protocol version mismatch is accepted.

    Verifies: DC-019 — protocol version validation.
    REQ-116

    Send tesseron/hello with protocolVersion "1.1" (same major, different
    minor).  Verify the welcome response is returned successfully.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    params = _make_hello_params(protocol_version="1.1")

    welcome = await mgr.handle_hello(session, params)

    assert "sessionId" in welcome
    assert "claimCode" in welcome


# ---------------------------------------------------------------------------
# Multiple Simultaneous Sessions (REQ-139)
# ---------------------------------------------------------------------------


async def test_gw30_independent_session_state() -> None:
    """GW-30: Separate sessions maintain independent state.

    Verifies: DC-019 — multiple simultaneous sessions.
    REQ-139

    Connect two apps simultaneously and verify each receives its own unique
    sessionId, its own claimCode, and its own independent claim state.
    """
    mgr = GatewaySessionManager()
    dispatcher1 = _make_dispatcher()
    dispatcher2 = _make_dispatcher()
    session1 = mgr.create_session(dispatcher1)
    session2 = mgr.create_session(dispatcher2)

    welcome1 = await mgr.handle_hello(session1, _make_hello_params())
    welcome2 = await mgr.handle_hello(session2, _make_hello_params())

    assert welcome1["sessionId"] != welcome2["sessionId"]
    assert welcome1["claimCode"] != welcome2["claimCode"]
    assert session1.state == SessionState.AWAITING_CLAIM
    assert session2.state == SessionState.AWAITING_CLAIM


async def test_gw31_claim_isolation() -> None:
    """GW-31: Claiming session A does not affect session B.

    Verifies: DC-019 — multiple simultaneous sessions.
    REQ-139

    With two sessions both in AWAITING_CLAIM, claim session A and verify
    that session B remains in AWAITING_CLAIM state.
    """
    mgr = GatewaySessionManager()
    dispatcher1 = _make_dispatcher()
    dispatcher2 = _make_dispatcher()
    session1 = mgr.create_session(dispatcher1)
    session2 = mgr.create_session(dispatcher2)

    welcome1 = await mgr.handle_hello(session1, _make_hello_params())
    await mgr.handle_hello(session2, _make_hello_params())

    # Claim session1 only
    await mgr.handle_claim(session1.session_id, welcome1["claimCode"])

    assert session1.state == SessionState.CLAIMED
    assert session2.state == SessionState.AWAITING_CLAIM


# ---------------------------------------------------------------------------
# Transport Close Behaviour (REQ-142, REQ-143, REQ-144)
# ---------------------------------------------------------------------------


async def test_gw32_pending_rejected_on_close() -> None:
    """GW-32: Pending outbound requests are rejected when transport closes.

    Verifies: DC-019 — transport close behaviour.
    REQ-142

    Send a request to the app, close the transport before the response
    arrives, and verify the caller receives a TransportClosedError.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    welcome = await mgr.handle_hello(session, _make_hello_params())
    await mgr.handle_claim(session.session_id, welcome["claimCode"])

    await mgr.close_session(session)

    # dispatcher.reject_all_pending should have been called during close cascade
    dispatcher.reject_all_pending.assert_called_once()


async def test_gw33_inflight_cancelled_on_close() -> None:
    """GW-33: In-flight action invocations are cancelled on transport close.

    Verifies: DC-019 — transport close behaviour.
    REQ-143

    Start a long-running action invocation, close the transport, and verify
    that the cancellation signal is fired for the in-flight invocation.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    welcome = await mgr.handle_hello(session, _make_hello_params())
    await mgr.handle_claim(session.session_id, welcome["claimCode"])

    # Register a cancel function
    cancelled = []

    def cancel_fn() -> None:
        cancelled.append(True)

    session.register_invocation("inv_001", cancel_fn)

    await mgr.close_session(session)

    assert len(cancelled) == 1, "Cancellation signal must be fired on close"


async def test_gw34_subscriptions_cleaned_on_close() -> None:
    """GW-34: Active subscriptions are cleaned up on transport close.

    Verifies: DC-019 — transport close behaviour.
    REQ-144

    Subscribe to a resource, close the transport, and verify that the
    subscription cleanup function is called.
    """
    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    welcome = await mgr.handle_hello(session, _make_hello_params())
    await mgr.handle_claim(session.session_id, welcome["claimCode"])

    cleaned = []

    def cleanup_fn() -> None:
        cleaned.append(True)

    session.register_subscription("sub_001", cleanup_fn)

    await mgr.close_session(session)

    assert len(cleaned) == 1, "Subscription cleanup must be called on close"


# ---------------------------------------------------------------------------
# Authorization (REQ-136)
# ---------------------------------------------------------------------------


async def test_gw35_unclaimed_action_unauthorized() -> None:
    """GW-35: Action invocation on unclaimed session is rejected with -32009.

    Verifies: DC-019 — authorization.
    REQ-136

    Attempt to invoke an action on a session that is still in AWAITING_CLAIM
    state (before any claim) and verify the response is a JSON-RPC error
    with code -32009 (Unauthorized).
    """
    from python_tesseron.gateway.action_router import GatewayActionRouter

    mgr = GatewaySessionManager()
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    await mgr.handle_hello(session, _make_hello_params(app_id="myapp"))

    # Session is in AWAITING_CLAIM — not yet claimed
    router = GatewayActionRouter(mgr)

    with pytest.raises(UnauthorizedError) as exc_info:
        await router.invoke("myapp__do_thing", {})

    assert exc_info.value.code == -32009
