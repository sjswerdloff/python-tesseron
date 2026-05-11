"""Error model tests — error codes, classes, and mapping.

Test IDs: ER-01 through ER-28
Source: Spec §13 (Error Model)

Tests verify:
- All 18 error codes trigger the correct code and message on the wire.
- Error mapping rules: TesseronError subclasses map to their code; other
  exceptions map to -32005 HandlerError.
- Error class hierarchy: each specialised error is a TesseronError subclass
  with the specified code.
- The confirm vs elicit asymmetry: confirm() returns False (never throws);
  elicit() raises ElicitationNotAvailableError.

Tests requiring SDK integration are marked xfail. Tests that verify only
the error class structure (code, hierarchy) can pass with stubs alone.
"""

from __future__ import annotations

import pytest

from python_tesseron.errors import (
    ActionNotFoundError,
    CancelledError,
    ElicitationNotAvailableError,
    HandlerError,
    InternalError,
    InvalidParamsError,
    InvalidRequestError,
    MethodNotFoundError,
    ParseError,
    ProtocolMismatchError,
    ResumeFailedError,
    SamplingDepthExceededError,
    SamplingNotAvailableError,
    TesseronError,
    TimeoutError,
    TransportClosedError,
    UnauthorizedError,
)
from tests.conftest import MockGateway

# ---------------------------------------------------------------------------
# Error code tests (ER-01 through ER-18) — wire-level trigger scenarios
# ---------------------------------------------------------------------------


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK parse error handling not yet implemented")
async def test_er01_parse_error_returns_32700(mock_gateway: MockGateway) -> None:
    """ER-01: REQ-010. ParseError: send malformed JSON, peer receives -32700.

    Sending a frame that is not valid JSON must produce a -32700 ParseError
    response from the receiving SDK.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK invalid request handling not yet implemented")
async def test_er02_invalid_request_returns_32600(mock_gateway: MockGateway) -> None:
    """ER-02: REQ-010. InvalidRequest: send valid JSON but invalid JSON-RPC, receive -32600.

    A JSON object that lacks the jsonrpc field is valid JSON but not a valid
    JSON-RPC request. The SDK should return -32600 InvalidRequest.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK method dispatch not yet implemented")
async def test_er03_method_not_found_returns_32601(mock_gateway: MockGateway) -> None:
    """ER-03: REQ-003. MethodNotFound: send unregistered method, receive -32601.

    A request for a method that is not registered in the dispatcher must
    return -32601 MethodNotFound.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK params validation not yet implemented")
async def test_er04_invalid_params_returns_32602(mock_gateway: MockGateway) -> None:
    """ER-04. InvalidParams: send request with wrong param shape, receive -32602.

    When the params do not match the expected shape for the method,
    the SDK must return -32602 InvalidParams.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK internal error handling not yet implemented")
async def test_er05_internal_error_returns_32603_with_message(mock_gateway: MockGateway) -> None:
    """ER-05: REQ-096. InternalError: handler raises unexpected exception, receive -32603.

    REQ-096: if the handler raises any other exception the dispatcher SHALL
    send -32603 InternalError with the exception's message.
    If a handler raises an unexpected (non-TesseronError) exception, the
    peer receives -32603 InternalError with the exception's message.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK protocol version check not yet implemented")
async def test_er06_protocol_mismatch_returns_32000(mock_gateway: MockGateway) -> None:
    """ER-06: REQ-030. ProtocolMismatch: incompatible major version, receive -32000.

    Sending tesseron/hello with a major version that differs from the
    gateway's supported version must produce -32000 ProtocolMismatch.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK cancellation handling not yet implemented")
async def test_er07_cancelled_returns_32001_to_handler(mock_gateway: MockGateway) -> None:
    """ER-07: REQ-052, REQ-053, REQ-054. Cancelled: agent sends actions/cancel during invocation.

    REQ-052: on receiving actions/cancel the SDK SHALL fire the cancellation
    signal for the corresponding invocation.
    REQ-054: on receiving actions/cancel the SDK SHALL return error code -32001 Cancelled.
    REQ-053: the handler SHOULD check for cancellation and clean up.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK timeout handling not yet implemented")
async def test_er08_timeout_returns_32002(mock_gateway: MockGateway) -> None:
    """ER-08: REQ-055. Timeout: action exceeds timeout_ms, agent receives -32002.

    When an action's handler takes longer than its configured timeoutMs,
    the agent receives -32002 Timeout and the cancellation signal fires.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK action routing not yet implemented")
async def test_er09_action_not_found_returns_32003(mock_gateway: MockGateway) -> None:
    """ER-09: REQ-003. ActionNotFound: invoke non-existent action, receive -32003.

    Invoking an action name that has no registered handler must produce
    -32003 ActionNotFound.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK input validation not yet implemented")
async def test_er10_input_validation_returns_32004_with_issues(mock_gateway: MockGateway) -> None:
    """ER-10: REQ-044, REQ-045. InputValidation: invalid input returns -32004 with issues in data.

    When the input fails schema validation, the SDK must return -32004
    with an array of validation issues in error.data. The handler must not run.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK handler error mapping not yet implemented")
async def test_er11_handler_exception_maps_to_32005(mock_gateway: MockGateway) -> None:
    """ER-11: REQ-079. HandlerError (exception): handler raises ValueError, agent receives -32005.

    A handler raising ValueError("Cart is locked") must produce
    -32005 HandlerError with the original exception message.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK strict output validation not yet implemented")
async def test_er12_strict_output_failure_maps_to_32005(mock_gateway: MockGateway) -> None:
    """ER-12: REQ-047, REQ-048. HandlerError (strict output): output violating schema returns -32005.

    When strict_output=True and the handler returns a value that does not
    match the output schema, the agent receives -32005 with validation issues
    in error.data.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK sampling capability check not yet implemented")
async def test_er13_sampling_not_available_when_capability_absent(mock_gateway: MockGateway) -> None:
    """ER-13: REQ-077. SamplingNotAvailable: ctx.sample() without sampling capability.

    When the agent does not support sampling and the handler calls
    ctx.sample(), SamplingNotAvailableError must be raised.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK elicitation capability check not yet implemented")
async def test_er14_elicitation_not_available_when_capability_absent(mock_gateway: MockGateway) -> None:
    """ER-14: REQ-065. ElicitationNotAvailable: ctx.elicit() without elicitation capability.

    When the agent does not support elicitation and the handler calls
    ctx.elicit(), ElicitationNotAvailableError must be raised.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK sampling depth limit not yet implemented")
async def test_er15_sampling_depth_exceeded_returns_32008(mock_gateway: MockGateway) -> None:
    """ER-15: REQ-058. SamplingDepthExceeded: chain > maxSamplingDepth (3), receive -32008.

    A sampling chain that exceeds the depth limit (3) must produce
    -32008 SamplingDepthExceeded with {depth, max} in error.data.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK claim code validation not yet implemented")
async def test_er16_unauthorized_returns_32009_for_wrong_claim_code(mock_gateway: MockGateway) -> None:
    """ER-16: REQ-076. Unauthorized: wrong claim code, receive -32009.

    Submitting an incorrect claim code must produce -32009 Unauthorized.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK pending request rejection not yet implemented")
async def test_er17_transport_closed_rejects_pending_with_32010(mock_gateway: MockGateway) -> None:
    """ER-17: REQ-008. TransportClosed: transport closes with pending requests.

    When the transport closes with pending requests outstanding, each
    pending request must be rejected with TransportClosedError (code -32010).
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK resume failure handling not yet implemented")
async def test_er18_resume_failed_returns_32011(mock_gateway: MockGateway) -> None:
    """ER-18: REQ-099. ResumeFailed: resume with expired TTL or wrong token, receive -32011.

    An unsuccessful resume attempt must produce -32011 ResumeFailed.
    The SDK must clear stored credentials and fall back to a fresh hello.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Error mapping tests (ER-19 through ER-21)
# ---------------------------------------------------------------------------


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK error mapping not yet implemented")
async def test_er19_tesseron_error_maps_to_matching_wire_error(mock_gateway: MockGateway) -> None:
    """ER-19: REQ-078, REQ-095. TesseronError from handler maps to JSON-RPC error with matching code/message/data.

    REQ-095: if the handler raises a TesseronError the dispatcher SHALL send
    an error response with its code, message, and data.
    A handler raising TesseronError(code=-32003, message="x", data={"y": 1})
    must produce exactly that error on the wire.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK error mapping not yet implemented")
async def test_er20_non_tesseron_error_maps_to_32005(mock_gateway: MockGateway) -> None:
    """ER-20: REQ-079. Non-TesseronError maps to -32005 HandlerError.

    A handler raising RuntimeError("oops") must produce -32005 with
    the message "oops" on the wire.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK error response handling not yet implemented")
async def test_er21_incoming_error_constructs_tesseron_error(mock_gateway: MockGateway) -> None:
    """ER-21: REQ-080. Incoming JSON-RPC error constructs TesseronError and rejects pending request.

    REQ-080: when an incoming JSON-RPC error response is received for a
    pending request the SDK SHALL construct a TesseronError with the error's
    code, message, and data and reject the pending request with it.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Error class structural tests (ER-22 through ER-26) — verifiable with stubs
# ---------------------------------------------------------------------------


@pytest.mark.error_model
def test_er22_sampling_not_available_is_tesseron_error_with_32006() -> None:
    """ER-22: REQ-059. SamplingNotAvailableError is subclass of TesseronError with code -32006."""
    err = SamplingNotAvailableError()

    assert isinstance(err, TesseronError)
    assert isinstance(err, SamplingNotAvailableError)
    assert err.code == -32006


@pytest.mark.error_model
def test_er23_elicitation_not_available_is_tesseron_error_with_32007() -> None:
    """ER-23: REQ-065. ElicitationNotAvailableError is subclass of TesseronError with code -32007."""
    err = ElicitationNotAvailableError()

    assert isinstance(err, TesseronError)
    assert isinstance(err, ElicitationNotAvailableError)
    assert err.code == -32007


@pytest.mark.error_model
def test_er24_cancelled_error_is_tesseron_error_with_32001() -> None:
    """ER-24: REQ-053. CancelledError is subclass of TesseronError with code -32001."""
    err = CancelledError()

    assert isinstance(err, TesseronError)
    assert isinstance(err, CancelledError)
    assert err.code == -32001


@pytest.mark.error_model
def test_er25_timeout_error_is_tesseron_error_with_32002() -> None:
    """ER-25: REQ-055. TimeoutError is subclass of TesseronError with code -32002."""
    err = TimeoutError()

    assert isinstance(err, TesseronError)
    assert isinstance(err, TimeoutError)
    assert err.code == -32002


@pytest.mark.error_model
def test_er26_transport_closed_error_is_tesseron_error_with_32010() -> None:
    """ER-26: REQ-008. TransportClosedError is subclass of TesseronError with code -32010."""
    err = TransportClosedError()

    assert isinstance(err, TesseronError)
    assert isinstance(err, TransportClosedError)
    assert err.code == -32010


# ---------------------------------------------------------------------------
# Confirm vs elicit asymmetry (ER-27, ER-28)
# ---------------------------------------------------------------------------


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK ctx.confirm() not yet implemented")
async def test_er27_confirm_returns_false_when_elicitation_not_available(mock_gateway: MockGateway) -> None:
    """ER-27: REQ-060, REQ-075. ctx.confirm() returns False when elicitation not available (NOT throw).

    ctx.confirm() is the safe gate: it never throws ElicitationNotAvailableError.
    When elicitation capability is absent, it silently returns False.
    """
    raise NotImplementedError


@pytest.mark.error_model
@pytest.mark.xfail(reason="implementation pending: SDK ctx.elicit() not yet implemented")
async def test_er28_elicit_throws_when_elicitation_not_available(mock_gateway: MockGateway) -> None:
    """ER-28: REQ-065. ctx.elicit() throws ElicitationNotAvailableError when capability absent.

    Unlike ctx.confirm(), ctx.elicit() raises ElicitationNotAvailableError
    when the agent does not support elicitation, because structured data
    has no safe default.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Additional structural tests for all error classes
# ---------------------------------------------------------------------------


@pytest.mark.error_model
def test_all_error_classes_are_exceptions() -> None:
    """All Tesseron error classes must be Exception subclasses."""
    error_classes = [
        ParseError,
        InvalidRequestError,
        MethodNotFoundError,
        InvalidParamsError,
        InternalError,
        ProtocolMismatchError,
        CancelledError,
        TimeoutError,
        ActionNotFoundError,
        HandlerError,
        SamplingNotAvailableError,
        ElicitationNotAvailableError,
        SamplingDepthExceededError,
        UnauthorizedError,
        TransportClosedError,
        ResumeFailedError,
    ]
    for cls in error_classes:
        instance = cls()
        assert isinstance(instance, Exception), f"{cls.__name__} must be Exception subclass"
        assert isinstance(instance, TesseronError), f"{cls.__name__} must be TesseronError subclass"


@pytest.mark.error_model
def test_all_error_codes_are_negative_integers() -> None:
    """All Tesseron error codes must be negative integers (JSON-RPC convention)."""
    error_instances = [
        ParseError(),
        InvalidRequestError(),
        MethodNotFoundError(),
        InvalidParamsError(),
        InternalError(),
        ProtocolMismatchError(),
        CancelledError(),
        TimeoutError(),
        ActionNotFoundError(),
        HandlerError(),
        SamplingNotAvailableError(),
        ElicitationNotAvailableError(),
        SamplingDepthExceededError(),
        UnauthorizedError(),
        TransportClosedError(),
        ResumeFailedError(),
    ]
    for err in error_instances:
        assert isinstance(err.code, int), f"{type(err).__name__}.code must be int, got {type(err.code)}"
        assert err.code < 0, f"{type(err).__name__}.code must be negative, got {err.code}"


@pytest.mark.error_model
def test_tesseron_error_accepts_custom_message_and_code() -> None:
    """TesseronError can be constructed with custom code, message, and data.

    This is used by handler code that wants to map custom errors to specific
    JSON-RPC codes (ER-19 pattern).
    """
    err = TesseronError(message="Order not found", code=-32003, data={"orderId": "x"})

    assert err.code == -32003
    assert err.message == "Order not found"
    assert err.data == {"orderId": "x"}
    assert str(err) == "Order not found"


@pytest.mark.error_model
def test_tesseron_error_default_message_preserved_without_override() -> None:
    """TesseronError subclasses retain their default message when no override is given."""
    err = ActionNotFoundError()
    assert err.message == "Action not found"
    assert err.code == -32003


@pytest.mark.error_model
def test_error_codes_match_spec() -> None:
    """All error code constants match the values in spec §13.1."""
    expected: list[tuple[type[TesseronError], int]] = [
        (ParseError, -32700),
        (InvalidRequestError, -32600),
        (MethodNotFoundError, -32601),
        (InvalidParamsError, -32602),
        (InternalError, -32603),
        (ProtocolMismatchError, -32000),
        (CancelledError, -32001),
        (TimeoutError, -32002),
        (ActionNotFoundError, -32003),
        (HandlerError, -32005),
        (SamplingNotAvailableError, -32006),
        (ElicitationNotAvailableError, -32007),
        (SamplingDepthExceededError, -32008),
        (UnauthorizedError, -32009),
        (TransportClosedError, -32010),
        (ResumeFailedError, -32011),
    ]
    for cls, expected_code in expected:
        instance = cls()
        assert instance.code == expected_code, f"{cls.__name__}.code: expected {expected_code}, got {instance.code}"
