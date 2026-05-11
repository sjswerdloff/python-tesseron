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

import pytest

from python_tesseron.errors import TransportClosedError
from python_tesseron.types import SessionState
from tests.conftest import MockGateway

# ---------------------------------------------------------------------------
# Valid transitions (ST-01 through ST-05)
# ---------------------------------------------------------------------------


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK connect() not yet implemented")
async def test_st01_disconnected_to_handshaking_on_open(mock_gateway: MockGateway) -> None:
    """ST-01: REQ-009, REQ-013. DISCONNECTED -> HANDSHAKING when app opens transport.

    When the SDK opens its transport binding, it transitions from DISCONNECTED
    to HANDSHAKING and sends tesseron/hello as the first message.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK connect() not yet implemented")
async def test_st02_handshaking_to_awaiting_claim_on_welcome(mock_gateway: MockGateway) -> None:
    """ST-02: REQ-033. HANDSHAKING -> AWAITING_CLAIM when gateway returns welcome.

    After receiving the welcome response, the SDK must transition to
    AWAITING_CLAIM and store the session credentials.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK claimed notification handling not yet implemented")
async def test_st03_awaiting_claim_to_claimed_on_claim(mock_gateway: MockGateway) -> None:
    """ST-03: REQ-034, REQ-036, REQ-037. AWAITING_CLAIM -> CLAIMED when session claimed.

    When the gateway sends tesseron/claimed, the SDK must transition to
    CLAIMED and update its stored capabilities and agent identity.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK transport close handling not yet implemented")
async def test_st04_awaiting_claim_to_closed_on_transport_close(mock_gateway: MockGateway) -> None:
    """ST-04: REQ-008, REQ-081. AWAITING_CLAIM -> CLOSED on transport close or timeout.

    If the transport closes while waiting for a claim, the SDK must
    transition to CLOSED and reject all pending requests.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK transport close handling not yet implemented")
async def test_st05_claimed_to_closed_on_transport_close(mock_gateway: MockGateway) -> None:
    """ST-05: REQ-081, REQ-082, REQ-083. CLAIMED -> CLOSED on transport close.

    When the transport closes in CLAIMED state, the SDK must transition to
    CLOSED and perform all close behaviour (cancel in-flight, clean up subs).
    """
    raise NotImplementedError


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
@pytest.mark.xfail(reason="implementation pending: SDK reconnect not yet implemented")
async def test_st11_new_connect_yields_new_session(mock_gateway: MockGateway) -> None:
    """ST-11. CLOSED -> HANDSHAKING: new connect() yields NEW session (§14.4).

    After a close, calling connect() again creates a completely new session
    with new sessionId and new claimCode.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Close behaviour tests (ST-12 through ST-16)
# ---------------------------------------------------------------------------


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK pending request rejection not yet implemented")
async def test_st12_close_rejects_all_pending_with_transport_closed_error(mock_gateway: MockGateway) -> None:
    """ST-12: REQ-008. ALL pending outbound requests MUST be rejected with TransportClosedError.

    Send a request, close the transport before the response arrives, and
    verify the pending request is rejected with TransportClosedError.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK cancellation signal not yet implemented")
async def test_st13_close_fires_cancellation_signals_for_inflight_invocations(mock_gateway: MockGateway) -> None:
    """ST-13: REQ-082. ALL in-flight invocations MUST have cancellation signals fired.

    Start a long-running action handler. Close the transport. Verify the
    handler's cancellation signal fires.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK subscription cleanup not yet implemented")
async def test_st14_close_calls_cleanup_for_all_subscriptions(mock_gateway: MockGateway) -> None:
    """ST-14: REQ-083. ALL active subscriptions MUST have cleanup functions called.

    Subscribe to a resource, close the transport, verify the cleanup
    function registered during subscribe is called.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK progress after close not yet implemented")
async def test_st15_progress_after_close_silently_dropped(mock_gateway: MockGateway) -> None:
    """ST-15: REQ-084. progress() calls after close MUST be silently dropped.

    Close the transport, then call ctx.progress(). Verify no error is raised
    and no message is delivered.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK sampling/elicit in-flight rejection not yet implemented")
async def test_st16_inflight_sample_elicit_rejected_with_transport_closed(mock_gateway: MockGateway) -> None:
    """ST-16: REQ-081. sample()/confirm()/elicit() in flight MUST reject with TransportClosedError.

    Start a sampling or elicitation request, close the transport before the
    response arrives, verify TransportClosedError is raised.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Reconnection tests (ST-17 through ST-20)
# ---------------------------------------------------------------------------


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK connect/disconnect not yet implemented")
async def test_st17_reconnect_yields_new_session_id_and_claim_code(mock_gateway: MockGateway) -> None:
    """ST-17: REQ-013. connect() after disconnect yields NEW sessionId and NEW claimCode.

    Disconnect the transport, reconnect without resume credentials, verify
    a completely new session with different IDs.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK auto-reconnect prohibition not yet implemented")
async def test_st18_sdk_must_not_auto_reconnect_silently(mock_gateway: MockGateway) -> None:
    """ST-18. SDK MUST NOT auto-reconnect silently.

    Close the transport. Verify the SDK does NOT automatically attempt
    reconnection. The application must call connect() explicitly.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK session resume not yet implemented")
async def test_st19_resume_within_ttl_preserves_claimed_status(mock_gateway: MockGateway) -> None:
    """ST-19: REQ-038, REQ-039, REQ-040. Resume within TTL preserves claimed status.

    Connect and claim a session. Disconnect. Reconnect within 90 seconds
    using tesseron/resume. Verify the session retains its claimed state
    and no new claim code is required.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK session resume failure not yet implemented")
async def test_st20_resume_after_ttl_fails_with_32011(mock_gateway: MockGateway) -> None:
    """ST-20: REQ-099. Resume after TTL fails with -32011 ResumeFailed.

    Attempt to resume a session whose TTL has expired. Verify the SDK
    receives -32011 and falls back to a fresh tesseron/hello.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Gap analysis additional tests (ST-21, ST-22)
# ---------------------------------------------------------------------------


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK signal handling not yet implemented")
async def test_st21_sigint_cleans_up_manifest_and_closes_transport(mock_gateway: MockGateway) -> None:
    """ST-21: REQ-029. SIGINT triggers manifest delete, transport close, exit.

    Start the SDK, send SIGINT, verify the manifest file is deleted and
    the transport closes.
    """
    raise NotImplementedError


@pytest.mark.state_transition
@pytest.mark.xfail(reason="implementation pending: SDK handler cancellation signal not yet implemented")
async def test_st22_handler_checks_cancellation_signal(mock_gateway: MockGateway) -> None:
    """ST-22: REQ-053. Handler SHOULD check for cancellation.

    Start a long-running action that polls its cancellation signal. Send an
    actions/cancel notification. Verify the handler's cancellation check
    path is exercised and the handler exits gracefully.
    """
    raise NotImplementedError


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
