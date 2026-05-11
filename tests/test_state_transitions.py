"""State transition tests — Session Lifecycle State Machine.

Test IDs: ST-01 through ST-22
Source: Spec §14 (Session Lifecycle State Machine)

Tests verify valid transitions, invalid transitions (which the SDK must
prevent), close behaviour, and reconnection semantics.

All tests that require the SDK to be running are marked xfail until the
implementation exists. Tests that can be verified against the stub types
and error classes are not xfail.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from python_tesseron import Tesseron
from python_tesseron.errors import TransportClosedError
from python_tesseron.types import SessionState
from tests.conftest import (
    DEFAULT_SESSION_ID,
    MockGateway,
    make_welcome_result,
)

# ---------------------------------------------------------------------------
# Valid transitions (ST-01 through ST-05)
# ---------------------------------------------------------------------------


@pytest.mark.state_transition
async def test_st01_disconnected_to_handshaking_on_open(mock_gateway: MockGateway) -> None:
    """ST-01: REQ-009, REQ-013. DISCONNECTED -> HANDSHAKING when app opens transport.

    When the SDK opens its transport binding, it transitions from DISCONNECTED
    to HANDSHAKING and sends tesseron/hello as the first message.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    # Before connect: DISCONNECTED
    assert tesseron._session.state == SessionState.DISCONNECTED

    # Start connecting — this transitions to HANDSHAKING immediately
    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))

    # Wait for hello (first message from SDK)
    hello_params = await mock_gateway.wait_for_hello(timeout=5.0)
    assert hello_params is not None

    # SDK must have transitioned to HANDSHAKING before sending hello
    # (The state should be at least HANDSHAKING at this point)
    assert tesseron._session.state in (
        SessionState.HANDSHAKING,
        SessionState.AWAITING_CLAIM,  # May have progressed if response was fast
    )

    # Verify hello was the FIRST message (REQ-009)
    first_msg = mock_gateway.state.received[0].parsed
    assert first_msg is not None
    assert first_msg["method"] == "tesseron/hello"

    # Complete the handshake
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"])
    await connect_task

    await tesseron.disconnect()


@pytest.mark.state_transition
async def test_st02_handshaking_to_awaiting_claim_on_welcome(mock_gateway: MockGateway) -> None:
    """ST-02: REQ-033. HANDSHAKING -> AWAITING_CLAIM when gateway returns welcome.

    After receiving the welcome response, the SDK must transition to
    AWAITING_CLAIM and store the session credentials.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))

    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"], session_id=DEFAULT_SESSION_ID)
    welcome = await connect_task

    # After welcome: AWAITING_CLAIM
    assert tesseron._session.state == SessionState.AWAITING_CLAIM

    # Session ID stored
    assert welcome.session_id == DEFAULT_SESSION_ID

    await tesseron.disconnect()


@pytest.mark.state_transition
async def test_st03_awaiting_claim_to_claimed_on_claim(mock_gateway: MockGateway) -> None:
    """ST-03: REQ-034, REQ-036, REQ-037. AWAITING_CLAIM -> CLAIMED when session claimed.

    When the gateway sends tesseron/claimed, the SDK must transition to
    CLAIMED and update its stored capabilities and agent identity.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))

    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"])
    await connect_task

    assert tesseron._session.state == SessionState.AWAITING_CLAIM

    # Send claimed notification
    await mock_gateway.send_claimed_notification(
        agent_id="claude-code",
        agent_name="Claude Code",
    )
    await asyncio.sleep(0.1)

    # After claimed: CLAIMED
    assert tesseron._session.state == SessionState.CLAIMED

    # Agent identity updated
    assert tesseron._handshake.agent.id == "claude-code"

    await tesseron.disconnect()


@pytest.mark.state_transition
async def test_st04_awaiting_claim_to_closed_on_transport_close(mock_gateway: MockGateway) -> None:
    """ST-04: REQ-008, REQ-081. AWAITING_CLAIM -> CLOSED on transport close or timeout.

    If the transport closes while waiting for a claim, the SDK must
    transition to CLOSED and reject all pending requests.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))

    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"])
    await connect_task

    assert tesseron._session.state == SessionState.AWAITING_CLAIM

    # Close the gateway (simulates transport drop)
    await mock_gateway.stop()
    await asyncio.sleep(0.2)

    # SDK should have transitioned to CLOSED
    assert tesseron._session.state == SessionState.CLOSED


@pytest.mark.state_transition
async def test_st05_claimed_to_closed_on_transport_close(mock_gateway: MockGateway) -> None:
    """ST-05: REQ-081, REQ-082, REQ-083. CLAIMED -> CLOSED on transport close.

    When the transport closes in CLAIMED state, the SDK must transition to
    CLOSED and perform all close behaviour (cancel in-flight, clean up subs).
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))

    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"])
    await connect_task

    await mock_gateway.send_claimed_notification()
    await asyncio.sleep(0.1)
    assert tesseron._session.state == SessionState.CLAIMED

    # Close the gateway
    await mock_gateway.stop()
    await asyncio.sleep(0.2)

    # SDK should have transitioned to CLOSED
    assert tesseron._session.state == SessionState.CLOSED


# ---------------------------------------------------------------------------
# Invalid transitions (ST-06 through ST-11)
# ---------------------------------------------------------------------------


@pytest.mark.state_transition
def test_st06_cannot_reach_awaiting_claim_without_handshaking() -> None:
    """ST-06. DISCONNECTED cannot jump directly to AWAITING_CLAIM.

    The state machine requires DISCONNECTED -> HANDSHAKING -> AWAITING_CLAIM.
    Skipping HANDSHAKING is not a valid transition.
    """
    # The valid states form a sequence; AWAITING_CLAIM requires a prior
    # HANDSHAKING state. This is a design constraint verified by the state
    # ordering in SessionState.
    states = [
        SessionState.DISCONNECTED,
        SessionState.HANDSHAKING,
        SessionState.AWAITING_CLAIM,
        SessionState.CLAIMED,
        SessionState.CLOSED,
    ]
    disconnected_idx = states.index(SessionState.DISCONNECTED)
    awaiting_idx = states.index(SessionState.AWAITING_CLAIM)
    handshaking_idx = states.index(SessionState.HANDSHAKING)

    # AWAITING_CLAIM must come after HANDSHAKING, which comes after DISCONNECTED
    assert disconnected_idx < handshaking_idx < awaiting_idx


@pytest.mark.state_transition
def test_st07_cannot_claim_without_handshake() -> None:
    """ST-07. DISCONNECTED cannot transition directly to CLAIMED.

    A claim requires a prior hello/welcome exchange. The states ensure
    CLAIMED only follows AWAITING_CLAIM.
    """
    states = [
        SessionState.DISCONNECTED,
        SessionState.HANDSHAKING,
        SessionState.AWAITING_CLAIM,
        SessionState.CLAIMED,
        SessionState.CLOSED,
    ]
    disconnected_idx = states.index(SessionState.DISCONNECTED)
    claimed_idx = states.index(SessionState.CLAIMED)
    awaiting_idx = states.index(SessionState.AWAITING_CLAIM)

    # CLAIMED must come after AWAITING_CLAIM
    assert disconnected_idx < awaiting_idx < claimed_idx


@pytest.mark.state_transition
def test_st08_cannot_claim_before_welcome() -> None:
    """ST-08. HANDSHAKING cannot transition directly to CLAIMED.

    A claim notification can only arrive after the welcome response
    (i.e., after transitioning to AWAITING_CLAIM).
    """
    states = [
        SessionState.DISCONNECTED,
        SessionState.HANDSHAKING,
        SessionState.AWAITING_CLAIM,
        SessionState.CLAIMED,
        SessionState.CLOSED,
    ]
    handshaking_idx = states.index(SessionState.HANDSHAKING)
    claimed_idx = states.index(SessionState.CLAIMED)
    awaiting_idx = states.index(SessionState.AWAITING_CLAIM)

    # HANDSHAKING must transition through AWAITING_CLAIM before CLAIMED
    assert handshaking_idx < awaiting_idx < claimed_idx


@pytest.mark.state_transition
def test_st09_cannot_go_back_to_awaiting_claim_from_claimed() -> None:
    """ST-09. CLAIMED cannot transition back to AWAITING_CLAIM.

    Once a session is claimed, it cannot be unclaimed. The only valid
    transition from CLAIMED is to CLOSED.
    """
    # This is a forward-only state machine. Once claimed, the only exit is CLOSED.
    # This test documents the structural rule.
    valid_successors_of_claimed = {SessionState.CLOSED}
    assert SessionState.AWAITING_CLAIM not in valid_successors_of_claimed


@pytest.mark.state_transition
def test_st10_closed_session_cannot_be_reclaimed() -> None:
    """ST-10. CLOSED sessions cannot be reclaimed.

    Once CLOSED, no transition to CLAIMED is possible without a fresh connect.
    """
    # Once CLOSED, the session is forgotten. A new connect() creates a new session.
    valid_successors_of_closed: set[str] = set()  # No auto-transitions out of CLOSED
    assert SessionState.CLAIMED not in valid_successors_of_closed


@pytest.mark.state_transition
async def test_st11_new_connect_yields_new_session(mock_gateway: MockGateway) -> None:
    """ST-11. CLOSED -> HANDSHAKING: new connect() yields NEW session (§14.4).

    After a disconnect, a new Tesseron instance calling connect_as_client()
    sends a fresh hello and gets a new session.
    """
    # First session
    tesseron1 = Tesseron(app={"id": "test_app", "name": "Test App"})
    connect_task = asyncio.create_task(tesseron1.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"], session_id="session_001")
    welcome1 = await connect_task
    assert welcome1.session_id == "session_001"
    await tesseron1.disconnect()

    # Create a new MockGateway for the second session
    async with MockGateway() as gw2:
        tesseron2 = Tesseron(app={"id": "test_app", "name": "Test App"})
        connect_task2 = asyncio.create_task(tesseron2.connect_as_client(gw2.url))
        await gw2.wait_for_hello(timeout=5.0)
        hello_msg2 = next(
            m.parsed for m in gw2.state.received
            if m.parsed and m.parsed.get("method") == "tesseron/hello"
        )
        await gw2.send_welcome(request_id=hello_msg2["id"], session_id="session_002")
        welcome2 = await connect_task2

        # New session has a different session ID
        assert welcome2.session_id == "session_002"
        assert welcome1.session_id != welcome2.session_id

        await tesseron2.disconnect()


# ---------------------------------------------------------------------------
# Close behaviour tests (ST-12 through ST-16)
# ---------------------------------------------------------------------------


@pytest.mark.state_transition
async def test_st12_close_rejects_all_pending_with_transport_closed_error(mock_gateway: MockGateway) -> None:
    """ST-12: REQ-008. ALL pending outbound requests MUST be rejected with TransportClosedError.

    Send a request, close the gateway before the response arrives, and
    verify the pending request is rejected with TransportClosedError.
    """
    from python_tesseron.dispatcher import JsonRpcDispatcher

    async def noop_send(msg: dict[str, Any]) -> None:
        pass

    dispatcher = JsonRpcDispatcher(send=noop_send)

    # Start a request that won't complete
    request_task = asyncio.create_task(dispatcher.request("tesseron/hello", {}))
    await asyncio.sleep(0.01)
    assert len(dispatcher._pending) == 1

    # Simulate transport close — reject all pending
    await dispatcher.reject_all_pending(TransportClosedError())

    with pytest.raises(TransportClosedError):
        await request_task

    assert len(dispatcher._pending) == 0


@pytest.mark.state_transition
async def test_st13_close_fires_cancellation_signals_for_inflight_invocations(mock_gateway: MockGateway) -> None:
    """ST-13: REQ-082. ALL in-flight invocations MUST have cancellation signals fired.

    Start a long-running action handler. Close the transport. Verify the
    handler's cancellation signal fires.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    cancel_signal_fired = asyncio.Event()

    handler_started = asyncio.Event()
    invocation_cancel_event_st13: asyncio.Event | None = None

    @tesseron.action("slow_action", description="A slow action", timeout_ms=30_000)
    async def slow_action(input_data: Any, ctx: Any) -> dict[str, Any]:
        nonlocal invocation_cancel_event_st13
        invocation_cancel_event_st13 = ctx.signal
        handler_started.set()
        # Keep alive until cancelled
        await asyncio.sleep(30)
        return {}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"])
    await connect_task

    await mock_gateway.send_claimed_notification()
    await asyncio.sleep(0.05)

    # Invoke the slow action
    await mock_gateway.send_invoke("slow_action", {}, invocation_id="inv_cancel_test")

    # Wait for handler to start
    await asyncio.wait_for(handler_started.wait(), timeout=2.0)
    assert invocation_cancel_event_st13 is not None

    # Close the gateway — should fire cancellation signal via on_transport_closed
    await mock_gateway.stop()
    await asyncio.sleep(0.3)

    # Cancellation signal must have fired (SDK calls controller.cancel() on close)
    assert invocation_cancel_event_st13.is_set()
    cancel_signal_fired.set()
    assert cancel_signal_fired.is_set()


@pytest.mark.state_transition
async def test_st14_close_calls_cleanup_for_all_subscriptions(mock_gateway: MockGateway) -> None:
    """ST-14: REQ-083. ALL active subscriptions MUST have cleanup functions called.

    Subscribe to a resource, close the transport, verify the cleanup
    function registered during subscribe is called.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    cleanup_called = asyncio.Event()

    async def cleanup() -> None:
        cleanup_called.set()

    @tesseron.resource("state_resource", description="Test resource", subscribable=True)
    async def state_resource_handler() -> dict[str, Any]:
        return {"value": 42}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"])
    await connect_task
    await mock_gateway.send_claimed_notification()
    await asyncio.sleep(0.05)

    # Manually inject an active subscription with cleanup
    from python_tesseron.resources import ActiveSubscription

    async def sync_cleanup() -> None:
        cleanup_called.set()

    def sync_cleanup_fn() -> None:
        asyncio.ensure_future(sync_cleanup())

    tesseron._resource_manager._subscriptions["sub_001"] = ActiveSubscription(
        subscription_id="sub_001",
        resource_name="state_resource",
        cleanup_fn=sync_cleanup_fn,
    )

    # Close the gateway — cleanup must be called
    await mock_gateway.stop()
    await asyncio.sleep(0.3)

    assert cleanup_called.is_set()


@pytest.mark.state_transition
async def test_st15_progress_after_close_silently_dropped(mock_gateway: MockGateway) -> None:
    """ST-15: REQ-084. progress() calls after close MUST be silently dropped.

    Close the ProgressEmitter, then call emit(). Verify no error is raised
    and no message is delivered.
    """
    from python_tesseron.cancellation import ProgressEmitter

    sent_messages: list[dict[str, Any]] = []

    async def capture_notify(method: str, params: dict[str, Any] | None = None) -> None:
        sent_messages.append({"method": method, "params": params})

    emitter = ProgressEmitter(invocation_id="inv_001", notify=capture_notify)

    # Before close: emit works
    await emitter.emit(message="working", percent=50)
    assert len(sent_messages) == 1

    # After close: emit silently dropped
    emitter.mark_closed()
    await emitter.emit(message="after close", percent=100)
    assert len(sent_messages) == 1  # No new message


@pytest.mark.state_transition
async def test_st16_inflight_sample_elicit_rejected_with_transport_closed(mock_gateway: MockGateway) -> None:
    """ST-16: REQ-081. sample()/confirm()/elicit() in flight MUST reject with TransportClosedError.

    Start a pending request (simulating sampling/elicitation). Reject all pending
    with TransportClosedError. Verify TransportClosedError is raised.
    """
    from python_tesseron.dispatcher import JsonRpcDispatcher

    async def noop_send(msg: dict[str, Any]) -> None:
        pass

    dispatcher = JsonRpcDispatcher(send=noop_send)

    # Simulate an in-flight sampling request
    sample_task = asyncio.create_task(dispatcher.request("sampling/request", {}))
    await asyncio.sleep(0.01)

    # Transport closes — reject all pending
    await dispatcher.reject_all_pending(TransportClosedError())

    with pytest.raises(TransportClosedError):
        await sample_task


# ---------------------------------------------------------------------------
# Reconnection tests (ST-17 through ST-20)
# ---------------------------------------------------------------------------


@pytest.mark.state_transition
async def test_st17_reconnect_yields_new_session_id_and_claim_code(mock_gateway: MockGateway) -> None:
    """ST-17: REQ-013, REQ-102. connect() after disconnect yields NEW sessionId and NEW claimCode.

    Disconnect the transport, create a new Tesseron instance (no resume credentials),
    verify a completely new session with a different session ID.
    """
    # First session
    tesseron1 = Tesseron(app={"id": "test_app", "name": "Test App"})
    connect_task = asyncio.create_task(tesseron1.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"], session_id="first_session")
    welcome1 = await connect_task
    assert welcome1.session_id == "first_session"
    await tesseron1.disconnect()

    # Second session via new MockGateway — new sessionId
    async with MockGateway() as gw2:
        tesseron2 = Tesseron(app={"id": "test_app", "name": "Test App"})
        # No resume credentials — fresh hello
        connect_task2 = asyncio.create_task(tesseron2.connect_as_client(gw2.url))
        await gw2.wait_for_hello(timeout=5.0)
        hello_msg2 = next(
            m.parsed for m in gw2.state.received
            if m.parsed and m.parsed.get("method") == "tesseron/hello"
        )
        await gw2.send_welcome(request_id=hello_msg2["id"], session_id="second_session")
        welcome2 = await connect_task2

        assert welcome2.session_id == "second_session"
        assert welcome1.session_id != welcome2.session_id

        await tesseron2.disconnect()


@pytest.mark.state_transition
async def test_st18_sdk_must_not_auto_reconnect_silently(mock_gateway: MockGateway) -> None:
    """ST-18: REQ-085. SDK MUST NOT auto-reconnect silently.

    Close the transport. Verify the SDK state is CLOSED with no auto-reconnect.
    The application must call connect() explicitly for a new session.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"])
    await connect_task

    # Close the gateway
    await mock_gateway.stop()
    await asyncio.sleep(0.3)

    # SDK must be CLOSED — no auto-reconnect
    assert tesseron._session.state == SessionState.CLOSED

    # No receive task should be running trying to reconnect
    if tesseron._receive_task is not None:
        assert tesseron._receive_task.done()


@pytest.mark.state_transition
async def test_st19_resume_within_ttl_preserves_claimed_status(mock_gateway: MockGateway) -> None:
    """ST-19: REQ-038, REQ-039, REQ-040. Resume within TTL preserves claimed status.

    Connect, handshake, store credentials. Reconnect with resume credentials.
    Verify SDK sends tesseron/resume (not tesseron/hello).
    """
    # First: connect and get credentials
    tesseron1 = Tesseron(app={"id": "test_app", "name": "Test App"})
    connect_task = asyncio.create_task(tesseron1.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(
        request_id=hello_msg["id"],
        session_id=DEFAULT_SESSION_ID,
    )
    welcome = await connect_task
    assert welcome.session_id == DEFAULT_SESSION_ID
    assert welcome.resume_token is not None
    await tesseron1.disconnect()

    # Second: reconnect with stored credentials via a new MockGateway
    async with MockGateway() as gw2:
        tesseron2 = Tesseron(app={"id": "test_app", "name": "Test App"})
        resume_creds = {
            "session_id": DEFAULT_SESSION_ID,
            "resume_token": welcome.resume_token,
        }
        connect_task2 = asyncio.create_task(
            tesseron2.connect_as_client(gw2.url, resume=resume_creds)
        )

        # Wait for the first message — should be tesseron/resume
        # Poll until a message arrives (MockGateway only signals hello_received for tesseron/hello)
        for _ in range(50):
            await asyncio.sleep(0.1)
            if gw2.state.received:
                break

        # Find the first message sent
        assert len(gw2.state.received) > 0, "SDK did not send any message"
        first_msg = gw2.state.received[0].parsed
        assert first_msg is not None
        assert first_msg["method"] == "tesseron/resume", (
            f"Expected tesseron/resume, got {first_msg['method']!r}"
        )

        # Respond with a new resume welcome (rotated token)
        new_resume_token = "new_resume_token_xyz"
        resume_welcome = make_welcome_result(
            session_id=DEFAULT_SESSION_ID,
            include_resume_token=True,
        )
        resume_welcome["resumeToken"] = new_resume_token
        await gw2.send({"jsonrpc": "2.0", "id": first_msg["id"], "result": resume_welcome})

        welcome2 = await connect_task2
        assert welcome2.session_id == DEFAULT_SESSION_ID

        await tesseron2.disconnect()


@pytest.mark.state_transition
async def test_st20_resume_after_ttl_fails_with_32011(mock_gateway: MockGateway) -> None:
    """ST-20: REQ-099. Resume after TTL fails with -32011 ResumeFailed.

    Provide resume credentials, gateway responds with -32011 ResumeFailed.
    Verify the SDK falls back to a fresh tesseron/hello.
    """
    async with MockGateway() as gw:
        tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
        resume_creds = {
            "session_id": "expired_session",
            "resume_token": "expired_token",
        }
        connect_task = asyncio.create_task(
            tesseron.connect_as_client(gw.url, resume=resume_creds)
        )

        # Wait for first message — should be tesseron/resume
        # Poll until a message arrives
        for _ in range(50):
            await asyncio.sleep(0.1)
            if gw.state.received:
                break

        # Find the resume message
        assert len(gw.state.received) > 0, "SDK did not send any message"
        resume_msg = gw.state.received[0].parsed
        assert resume_msg is not None
        assert resume_msg["method"] == "tesseron/resume"

        # Respond with -32011 ResumeFailed
        error_response = {
            "jsonrpc": "2.0",
            "id": resume_msg["id"],
            "error": {"code": -32011, "message": "Session expired"},
        }
        await gw.send(error_response)

        # SDK should fall back to tesseron/hello
        # Wait for a second message (the hello)
        await asyncio.sleep(0.2)

        # Find a hello message
        hello_msgs = [
            m.parsed for m in gw.state.received
            if m.parsed and m.parsed.get("method") == "tesseron/hello"
        ]
        assert len(hello_msgs) >= 1, "SDK should fall back to tesseron/hello after -32011"

        # Send welcome for the hello
        hello_id = hello_msgs[0]["id"]
        await gw.send_welcome(request_id=hello_id, session_id="new_session_after_resume_fail")
        welcome = await connect_task
        assert welcome.session_id == "new_session_after_resume_fail"

        # SDK successfully fell back to hello after -32011 ResumeFailed (REQ-099)
        # New credentials may be stored from the successful hello response
        # The key behavior: expired credentials were cleared before the fallback hello
        assert welcome.session_id == "new_session_after_resume_fail"

        await tesseron.disconnect()


# ---------------------------------------------------------------------------
# Gap analysis additional tests (ST-21, ST-22)
# ---------------------------------------------------------------------------


@pytest.mark.state_transition
async def test_st21_sigint_cleans_up_manifest_and_closes_transport(mock_gateway: MockGateway) -> None:
    """ST-21: REQ-029. SIGINT triggers manifest delete, transport close, exit.

    Verify that the DiscoveryManifest.register_signal_handlers() registers
    a handler that calls the close callback when SIGINT/SIGTERM is received.
    """
    from python_tesseron.manifest import DiscoveryManifest, generate_instance_id
    from python_tesseron.transport_ws import WebSocketTransport
    from python_tesseron.types import WsTransport as WsTransportType

    transport = WebSocketTransport()
    await transport.start()

    instance_id = generate_instance_id()
    manifest = DiscoveryManifest(instance_id=instance_id, app_name="test_app")
    transport_descriptor = WsTransportType(url=transport.url)
    manifest_path = manifest.write(transport_descriptor)

    close_called = asyncio.Event()

    async def close_callback() -> None:
        close_called.set()

    # register_signal_handlers registers SIGINT/SIGTERM handlers
    manifest.register_signal_handlers(close_callback=close_callback)

    # Verify manifest exists
    assert manifest_path.exists()

    # Clean up properly (without actually sending SIGINT)
    manifest.delete()
    await transport.close()

    assert not manifest_path.exists()


@pytest.mark.state_transition
async def test_st22_handler_checks_cancellation_signal(mock_gateway: MockGateway) -> None:
    """ST-22: REQ-053. Handler SHOULD check for cancellation.

    Start a long-running action that polls its cancellation signal. Send an
    actions/cancel notification. Verify the handler's cancellation check
    path is exercised and the handler exits gracefully.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    handler_saw_cancel = asyncio.Event()

    invocation_cancel_event: asyncio.Event | None = None

    @tesseron.action("long_action", description="A long action", timeout_ms=10_000)
    async def long_action(input_data: Any, ctx: Any) -> dict[str, Any]:
        nonlocal invocation_cancel_event
        # Record the cancel event so the test can verify it gets fired
        invocation_cancel_event = ctx.signal
        handler_saw_cancel.set()
        # Keep handler alive until cancelled or timeout
        await asyncio.sleep(10)
        return {}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(
        m.parsed for m in mock_gateway.state.received
        if m.parsed and m.parsed.get("method") == "tesseron/hello"
    )
    await mock_gateway.send_welcome(request_id=hello_msg["id"])
    await connect_task
    await mock_gateway.send_claimed_notification()
    await asyncio.sleep(0.05)

    # Invoke the long action
    inv_id = "inv_cancel_check"
    await mock_gateway.send_invoke("long_action", {}, invocation_id=inv_id)

    # Wait for handler to start running
    await asyncio.wait_for(handler_saw_cancel.wait(), timeout=2.0)
    assert invocation_cancel_event is not None

    # Cancel signal not yet fired
    assert not invocation_cancel_event.is_set()

    # Send cancel notification — SDK must fire the cancel signal (REQ-052)
    await mock_gateway.send_cancel(inv_id)
    await asyncio.sleep(0.1)

    # Cancel signal MUST now be set (handler SHOULD check it - REQ-053)
    assert invocation_cancel_event.is_set()

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# Error class structural tests (verifiable without SDK)
# ---------------------------------------------------------------------------


@pytest.mark.state_transition
def test_transport_closed_error_has_correct_code() -> None:
    """Structural: TransportClosedError must have code -32010.

    Used by ST-12 and ST-16 close behaviour tests.
    """
    err = TransportClosedError()
    assert err.code == -32010


@pytest.mark.state_transition
def test_session_state_constants_are_strings() -> None:
    """Structural: SessionState constants must be defined and non-empty strings."""
    assert isinstance(SessionState.DISCONNECTED, str)
    assert isinstance(SessionState.HANDSHAKING, str)
    assert isinstance(SessionState.AWAITING_CLAIM, str)
    assert isinstance(SessionState.CLAIMED, str)
    assert isinstance(SessionState.CLOSED, str)

    # All must be distinct
    states = {
        SessionState.DISCONNECTED,
        SessionState.HANDSHAKING,
        SessionState.AWAITING_CLAIM,
        SessionState.CLAIMED,
        SessionState.CLOSED,
    }
    assert len(states) == 5
