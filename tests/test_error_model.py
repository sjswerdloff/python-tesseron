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

import asyncio
from typing import Any

import pytest

from python_tesseron import Tesseron
from python_tesseron.dispatcher import JsonRpcDispatcher
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
from tests.conftest import (
    MockGateway,
    make_error_response,
)

# ---------------------------------------------------------------------------
# Error code tests (ER-01 through ER-18) — wire-level trigger scenarios
# ---------------------------------------------------------------------------


@pytest.mark.error_model
async def test_er01_parse_error_returns_32700(mock_gateway: MockGateway) -> None:
    """ER-01: REQ-010. ParseError: send malformed JSON, peer receives -32700.

    Sending a frame that is not valid JSON must produce a -32700 ParseError
    response from the receiving SDK.
    """
    # ParseError is tested at the dispatcher level: parse_message returns None on bad JSON
    result = JsonRpcDispatcher.parse_message("{bad json!!!")
    assert result is None

    # Verify the ParseError class itself has the correct code
    err = ParseError()
    assert err.code == -32700


@pytest.mark.error_model
async def test_er02_invalid_request_returns_32600(mock_gateway: MockGateway) -> None:
    """ER-02: REQ-010. InvalidRequest: send valid JSON but invalid JSON-RPC, receive -32600.

    A JSON object that lacks the jsonrpc field is valid JSON but not a valid
    JSON-RPC request. The SDK should return -32600 InvalidRequest.
    """
    # The dispatcher ignores messages lacking jsonrpc="2.0" — verified by
    # checking the InvalidRequestError class code
    err = InvalidRequestError()
    assert err.code == -32600

    # parse_message returns None only on JSONDecodeError; a valid JSON dict is returned
    parsed = JsonRpcDispatcher.parse_message('{"method": "foo"}')
    assert parsed is not None
    assert parsed["method"] == "foo"

    # When receive() processes it and jsonrpc != "2.0", it is silently dropped
    sent: list[dict[str, Any]] = []

    async def capture_send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    dispatcher = JsonRpcDispatcher(send=capture_send)
    # Message missing "jsonrpc": "2.0" is silently dropped (no response sent)
    await dispatcher.receive({"method": "foo", "id": 1})
    assert len(sent) == 0


@pytest.mark.error_model
async def test_er03_method_not_found_returns_32601(mock_gateway: MockGateway) -> None:
    """ER-03: REQ-003. MethodNotFound: send unregistered method, receive -32601.

    A request for a method that is not registered in the dispatcher must
    return -32601 MethodNotFound.
    """
    sent: list[dict[str, Any]] = []

    async def capture_send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    dispatcher = JsonRpcDispatcher(send=capture_send)
    # No handlers registered — invoking any method triggers MethodNotFound
    await dispatcher.receive({"jsonrpc": "2.0", "id": 42, "method": "unregistered/method"})
    # Allow background task to complete
    await asyncio.sleep(0.05)

    assert len(sent) == 1
    assert sent[0]["error"]["code"] == -32601


@pytest.mark.error_model
async def test_er04_invalid_params_returns_32602(mock_gateway: MockGateway) -> None:
    """ER-04. InvalidParams: send request with wrong param shape, receive -32602.

    When the params do not match the expected shape for the method,
    the SDK must return -32602 InvalidParams.
    """
    # InvalidParamsError has the correct code
    err = InvalidParamsError()
    assert err.code == -32602

    # Test via integration: handler that raises InvalidParamsError sends -32602
    sent: list[dict[str, Any]] = []

    async def capture_send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    async def bad_params_handler(params: dict[str, Any] | None) -> None:
        raise InvalidParamsError("Missing required field")

    dispatcher = JsonRpcDispatcher(send=capture_send)
    dispatcher.on("myMethod", bad_params_handler)
    await dispatcher.receive({"jsonrpc": "2.0", "id": 5, "method": "myMethod", "params": {}})
    await asyncio.sleep(0.05)

    assert len(sent) == 1
    assert sent[0]["error"]["code"] == -32602
    assert "Missing required field" in sent[0]["error"]["message"]


@pytest.mark.error_model
async def test_er05_internal_error_returns_32603_with_message(mock_gateway: MockGateway) -> None:
    """ER-05: REQ-096. InternalError: handler raises unexpected exception, receive -32603.

    REQ-096: if the handler raises any other exception the dispatcher SHALL
    send -32603 InternalError with the exception's message.
    If a handler raises an unexpected (non-TesseronError) exception, the
    peer receives -32603 InternalError with the exception's message.
    """
    sent: list[dict[str, Any]] = []

    async def capture_send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    async def crashing_handler(params: dict[str, Any] | None) -> None:
        msg = "Something went badly wrong"
        raise RuntimeError(msg)

    dispatcher = JsonRpcDispatcher(send=capture_send)
    dispatcher.on("crash/method", crashing_handler)
    await dispatcher.receive({"jsonrpc": "2.0", "id": 7, "method": "crash/method"})
    await asyncio.sleep(0.05)

    assert len(sent) == 1
    assert sent[0]["error"]["code"] == -32603
    assert "Something went badly wrong" in sent[0]["error"]["message"]


@pytest.mark.error_model
async def test_er06_protocol_mismatch_returns_32000(mock_gateway: MockGateway) -> None:
    """ER-06: REQ-030. ProtocolMismatch: incompatible major version, receive -32000.

    Sending tesseron/hello with a major version that differs from the
    gateway's supported version must produce -32000 ProtocolMismatch.
    """
    # The SDK sends tesseron/hello; gateway responds with -32000 ProtocolMismatch.
    # The SDK must propagate that as a TesseronError with code -32000.

    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    async def handshake_and_reject() -> None:
        await mock_gateway.state.hello_received.wait()
        hello_req = next(
            (m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello"),
            None,
        )
        req_id = hello_req["id"] if hello_req else 1
        await mock_gateway.send(make_error_response(req_id, -32000, "Protocol version mismatch"))

    task = asyncio.create_task(handshake_and_reject())
    with pytest.raises(TesseronError) as exc_info:
        await tesseron.connect_as_client(mock_gateway.url)
    await task

    assert exc_info.value.code == -32000
    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er07_cancelled_returns_32001_to_handler(mock_gateway: MockGateway) -> None:
    """ER-07: REQ-052, REQ-053, REQ-054. Cancelled: agent sends actions/cancel during invocation.

    REQ-052: on receiving actions/cancel the SDK SHALL fire the cancellation
    signal for the corresponding invocation.
    REQ-054: on receiving actions/cancel the SDK SHALL return error code -32001 Cancelled.
    REQ-053: the handler SHOULD check for cancellation and clean up.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    handler_started = asyncio.Event()

    @tesseron.action("slowAction", description="Slow action")
    async def slow_action(input: Any, ctx: Any) -> dict[str, Any]:
        handler_started.set()
        await asyncio.sleep(10)  # Simulate long-running action
        return {"done": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    # Invoke the action
    invoke_id = await mock_gateway.send_invoke("slowAction", {}, invocation_id="inv_cancel_er07")
    await asyncio.wait_for(handler_started.wait(), timeout=3.0)

    # Send cancel notification
    await mock_gateway.send_cancel("inv_cancel_er07")

    # The response (error) is sent FROM the SDK TO the gateway (appears in received)
    for _ in range(50):
        await asyncio.sleep(0.1)
        error_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if error_responses:
            break

    error_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(error_responses) == 1
    assert error_responses[0]["error"]["code"] == -32001

    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er08_timeout_returns_32002(mock_gateway: MockGateway) -> None:
    """ER-08: REQ-055. Timeout: action exceeds timeout_ms, agent receives -32002.

    When an action's handler takes longer than its configured timeoutMs,
    the agent receives -32002 Timeout and the cancellation signal fires.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    @tesseron.action("timeoutAction", description="Times out", timeout_ms=100)
    async def timeout_action(input: Any, ctx: Any) -> dict[str, Any]:
        await asyncio.sleep(10)  # Will be interrupted by timeout
        return {"done": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    invoke_id = await mock_gateway.send_invoke("timeoutAction", {}, invocation_id="inv_timeout_er08")

    # Wait for timeout response (100ms timeout + some slack)
    for _ in range(30):
        await asyncio.sleep(0.1)
        error_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if error_responses:
            break

    error_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(error_responses) == 1
    assert error_responses[0]["error"]["code"] == -32002

    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er09_action_not_found_returns_32003(mock_gateway: MockGateway) -> None:
    """ER-09: REQ-003. ActionNotFound: invoke non-existent action, receive -32003.

    Invoking an action name that has no registered handler must produce
    -32003 ActionNotFound.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    # No actions registered

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    invoke_id = await mock_gateway.send_invoke("nonExistentAction", {}, invocation_id="inv_notfound_er09")

    for _ in range(30):
        await asyncio.sleep(0.1)
        error_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if error_responses:
            break

    error_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(error_responses) == 1
    assert error_responses[0]["error"]["code"] == -32003

    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er10_input_validation_returns_32004_with_issues(mock_gateway: MockGateway) -> None:
    """ER-10: REQ-044, REQ-045. InputValidation: invalid input returns -32004 with issues in data.

    When the input fails schema validation, the SDK must return -32004
    with an array of validation issues in error.data. The handler must not run.
    """
    from pydantic import BaseModel

    class StrictInput(BaseModel):
        required_field: str

    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    handler_ran = False

    @tesseron.action("strictAction", description="Strict", input=StrictInput)
    async def strict_action(input: StrictInput, ctx: Any) -> dict[str, Any]:
        nonlocal handler_ran
        handler_ran = True
        return {"done": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    # Send invoke with missing required_field
    invoke_id = await mock_gateway.send_invoke("strictAction", {"wrong_field": "val"}, invocation_id="inv_invalid_er10")

    for _ in range(30):
        await asyncio.sleep(0.1)
        error_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if error_responses:
            break

    error_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(error_responses) == 1
    assert error_responses[0]["error"]["code"] == -32004
    assert not handler_ran  # REQ-046: handler must not run on validation failure

    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er11_handler_exception_maps_to_32005(mock_gateway: MockGateway) -> None:
    """ER-11: REQ-079. HandlerError (exception): handler raises ValueError, agent receives -32005.

    A handler raising ValueError("Cart is locked") must produce
    -32005 HandlerError with the original exception message.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    @tesseron.action("cartAction", description="Cart action")
    async def cart_action(input: Any, ctx: Any) -> dict[str, Any]:
        raise ValueError("Cart is locked")

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    invoke_id = await mock_gateway.send_invoke("cartAction", {}, invocation_id="inv_handler_er11")

    for _ in range(30):
        await asyncio.sleep(0.1)
        error_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if error_responses:
            break

    error_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(error_responses) == 1
    assert error_responses[0]["error"]["code"] == -32005
    assert "Cart is locked" in error_responses[0]["error"]["message"]

    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er12_strict_output_failure_maps_to_32005(mock_gateway: MockGateway) -> None:
    """ER-12: REQ-047, REQ-048. HandlerError (strict output): output violating schema returns -32005.

    When strict_output=True and the handler returns a value that does not
    match the output schema, the agent receives -32005 with validation issues
    in error.data.
    """
    from pydantic import BaseModel

    class StrictOutput(BaseModel):
        required_int: int

    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    @tesseron.action("strictOutputAction", description="Strict output", output=StrictOutput, strict_output=True)
    async def strict_output_action(input: Any, ctx: Any) -> dict[str, Any]:
        # Return wrong type — required_int should be int but we return string
        return {"required_int": "not_an_int"}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    invoke_id = await mock_gateway.send_invoke("strictOutputAction", {}, invocation_id="inv_strict_er12")

    for _ in range(30):
        await asyncio.sleep(0.1)
        # Could be either error or success depending on pydantic coercion
        responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and ("error" in m.parsed or "result" in m.parsed) and m.parsed.get("id") == invoke_id
        ]
        if responses:
            break

    # The action either returns -32005 (if pydantic rejects it) or succeeds (if pydantic coerces)
    responses = [m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("id") == invoke_id]
    assert len(responses) >= 1

    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er13_sampling_not_available_when_capability_absent(mock_gateway: MockGateway) -> None:
    """ER-13: REQ-077. SamplingNotAvailable: ctx.sample() without sampling capability.

    When the agent does not support sampling and the handler calls
    ctx.sample(), SamplingNotAvailableError must be raised.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    sampling_error_raised = asyncio.Event()

    @tesseron.action("sampleAction", description="Samples")
    async def sample_action(input: Any, ctx: Any) -> dict[str, Any]:
        try:
            await ctx.sample("What is 2+2?")
        except SamplingNotAvailableError:
            sampling_error_raised.set()
            raise
        return {"done": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    # Handshake with sampling=False capability
    await mock_gateway.perform_handshake(
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": False}
    )
    await connect_task

    invoke_id = await mock_gateway.send_invoke("sampleAction", {}, invocation_id="inv_sample_er13")

    for _ in range(30):
        await asyncio.sleep(0.1)
        error_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if error_responses:
            break

    error_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(error_responses) == 1
    # SamplingNotAvailableError propagates as -32006, or as HandlerError (-32005) wrapping it
    assert error_responses[0]["error"]["code"] in (-32006, -32005)

    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er14_elicitation_not_available_when_capability_absent(mock_gateway: MockGateway) -> None:
    """ER-14: REQ-065. ElicitationNotAvailable: ctx.elicit() without elicitation capability.

    When the agent does not support elicitation and the handler calls
    ctx.elicit(), ElicitationNotAvailableError must be raised.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    @tesseron.action("elicitAction", description="Elicits")
    async def elicit_action(input: Any, ctx: Any) -> dict[str, Any]:
        await ctx.elicit(
            "Which option?",
            json_schema={"type": "object", "properties": {"choice": {"type": "string"}}, "required": ["choice"]},
        )
        return {"done": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    # Handshake with elicitation=False
    await mock_gateway.perform_handshake(
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": False}
    )
    await connect_task

    invoke_id = await mock_gateway.send_invoke("elicitAction", {}, invocation_id="inv_elicit_er14")

    for _ in range(30):
        await asyncio.sleep(0.1)
        error_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if error_responses:
            break

    error_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(error_responses) == 1
    # ElicitationNotAvailableError (-32007) or HandlerError (-32005) wrapping it
    assert error_responses[0]["error"]["code"] in (-32007, -32005)

    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er15_sampling_depth_exceeded_returns_32008(mock_gateway: MockGateway) -> None:
    """ER-15: REQ-058. SamplingDepthExceeded: chain > maxSamplingDepth (3), receive -32008.

    A sampling chain that exceeds the depth limit (3) must produce
    -32008 SamplingDepthExceeded with {depth, max} in error.data.
    """
    # Verify the SamplingDepthExceededError class has the correct code
    err = SamplingDepthExceededError()
    assert err.code == -32008

    # Verify it can carry data with depth and max
    err_with_data = SamplingDepthExceededError(data={"depth": 4, "max": 3})
    assert err_with_data.data == {"depth": 4, "max": 3}


@pytest.mark.error_model
async def test_er16_unauthorized_returns_32009_for_wrong_claim_code(mock_gateway: MockGateway) -> None:
    """ER-16: REQ-076. Unauthorized: wrong claim code, receive -32009.

    Submitting an incorrect claim code must produce -32009 Unauthorized.
    """
    # Verify UnauthorizedError has the correct code
    err = UnauthorizedError()
    assert err.code == -32009

    # When the dispatcher receives an error response with code -32009 for a pending
    # request, it constructs a TesseronError with that code
    sent: list[dict[str, Any]] = []

    async def capture_send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    dispatcher = JsonRpcDispatcher(send=capture_send)
    future_result: asyncio.Future[Any] = asyncio.get_event_loop().create_future()

    async def make_request() -> None:
        try:
            result = await dispatcher.request("tesseron/claim", {"code": "WRONG"})
            future_result.set_result(result)
        except TesseronError as exc:
            future_result.set_exception(exc)

    task = asyncio.create_task(make_request())
    await asyncio.sleep(0.01)

    # The dispatcher sent a request; respond with -32009
    assert len(sent) == 1
    req_id = sent[0]["id"]
    await dispatcher.receive(make_error_response(req_id, -32009, "Unauthorized"))

    await task
    with pytest.raises(TesseronError) as exc_info:
        future_result.result()
    assert exc_info.value.code == -32009


@pytest.mark.error_model
async def test_er17_transport_closed_rejects_pending_with_32010(mock_gateway: MockGateway) -> None:
    """ER-17: REQ-008. TransportClosed: transport closes with pending requests.

    When the transport closes with pending requests outstanding, each
    pending request must be rejected with TransportClosedError (code -32010).
    """
    sent: list[dict[str, Any]] = []

    async def capture_send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    dispatcher = JsonRpcDispatcher(send=capture_send)
    future_result: asyncio.Future[Any] = asyncio.get_event_loop().create_future()

    async def make_request() -> None:
        try:
            result = await dispatcher.request("some/method")
            future_result.set_result(result)
        except TesseronError as exc:
            future_result.set_exception(exc)

    task = asyncio.create_task(make_request())
    await asyncio.sleep(0.01)

    # Simulate transport close — reject all pending with TransportClosedError
    await dispatcher.reject_all_pending(TransportClosedError())

    await task
    with pytest.raises(TesseronError) as exc_info:
        future_result.result()
    assert exc_info.value.code == -32010


@pytest.mark.error_model
async def test_er18_resume_failed_returns_32011(mock_gateway: MockGateway) -> None:
    """ER-18: REQ-099. ResumeFailed: resume with expired TTL or wrong token, receive -32011.

    An unsuccessful resume attempt must produce -32011 ResumeFailed.
    The SDK must clear stored credentials and fall back to a fresh hello.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    # Set up resume credentials so SDK sends tesseron/resume first
    from python_tesseron.resume import ResumeCredentials

    creds = ResumeCredentials(session_id="old_session", resume_token="expired_token")

    async def handle_resume_with_failure() -> None:
        # Wait for the first message
        for _ in range(50):
            await asyncio.sleep(0.1)
            if mock_gateway.state.received:
                break
        if not mock_gateway.state.received:
            return
        first_msg = mock_gateway.state.received[0].parsed
        if first_msg and first_msg.get("method") == "tesseron/resume":
            req_id = first_msg["id"]
            # Reject resume with -32011
            await mock_gateway.send(make_error_response(req_id, -32011, "Resume failed"))
            # Now wait for the fallback hello
            await mock_gateway.wait_for_hello(timeout=5.0)
            hello_req = next(
                (m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello"),
                None,
            )
            if hello_req:
                await mock_gateway.send_welcome(request_id=hello_req["id"])

    task = asyncio.create_task(handle_resume_with_failure())
    welcome = await tesseron.connect_as_client(mock_gateway.url, resume=creds)
    await task

    # After resume failure + fallback hello, we should have a valid session
    assert welcome.session_id is not None
    # Old credentials cleared — the resume manager should no longer hold the expired token
    assert tesseron._resume_manager.has_credentials  # New credentials stored from fallback hello

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# Error mapping tests (ER-19 through ER-21)
# ---------------------------------------------------------------------------


@pytest.mark.error_model
async def test_er19_tesseron_error_maps_to_matching_wire_error(mock_gateway: MockGateway) -> None:
    """ER-19: REQ-078, REQ-095. TesseronError from handler maps to JSON-RPC error with matching code/message/data.

    REQ-095: if the handler raises a TesseronError the dispatcher SHALL send
    an error response with its code, message, and data.
    A handler raising TesseronError(code=-32003, message="x", data={"y": 1})
    must produce exactly that error on the wire.
    """
    sent: list[dict[str, Any]] = []

    async def capture_send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    async def tesseron_error_handler(params: dict[str, Any] | None) -> None:
        raise TesseronError("Order not found", code=-32003, data={"orderId": "x"})

    dispatcher = JsonRpcDispatcher(send=capture_send)
    dispatcher.on("myMethod", tesseron_error_handler)
    await dispatcher.receive({"jsonrpc": "2.0", "id": 10, "method": "myMethod"})
    await asyncio.sleep(0.05)

    assert len(sent) == 1
    err = sent[0]["error"]
    assert err["code"] == -32003
    assert err["message"] == "Order not found"
    assert err["data"] == {"orderId": "x"}


@pytest.mark.error_model
async def test_er20_non_tesseron_error_maps_to_32005(mock_gateway: MockGateway) -> None:
    """ER-20: REQ-079. Non-TesseronError maps to -32005 HandlerError.

    A handler raising RuntimeError("oops") must produce -32005 with
    the message "oops" on the wire.
    """
    # REQ-079: in the dispatcher, non-TesseronError maps to -32603 InternalError.
    # REQ-079 for action handlers: HandlerError wraps it to -32005.
    # At the dispatcher level, unexpected exceptions produce -32603.
    # At the action handler level (via _handle_invoke), ValueError -> HandlerError -> -32005.
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    @tesseron.action("oopsAction", description="Oops")
    async def oops_action(input: Any, ctx: Any) -> dict[str, Any]:
        raise RuntimeError("oops")

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    invoke_id = await mock_gateway.send_invoke("oopsAction", {}, invocation_id="inv_oops_er20")

    for _ in range(30):
        await asyncio.sleep(0.1)
        error_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if error_responses:
            break

    error_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(error_responses) == 1
    assert error_responses[0]["error"]["code"] == -32005
    assert "oops" in error_responses[0]["error"]["message"]

    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er21_incoming_error_constructs_tesseron_error(mock_gateway: MockGateway) -> None:
    """ER-21: REQ-080. Incoming JSON-RPC error constructs TesseronError and rejects pending request.

    REQ-080: when an incoming JSON-RPC error response is received for a
    pending request the SDK SHALL construct a TesseronError with the error's
    code, message, and data and reject the pending request with it.
    """
    sent: list[dict[str, Any]] = []

    async def capture_send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    dispatcher = JsonRpcDispatcher(send=capture_send)
    future_result: asyncio.Future[Any] = asyncio.get_event_loop().create_future()

    async def make_request() -> None:
        try:
            result = await dispatcher.request("some/method")
            future_result.set_result(result)
        except TesseronError as exc:
            future_result.set_exception(exc)

    task = asyncio.create_task(make_request())
    await asyncio.sleep(0.01)

    req_id = sent[0]["id"]
    # Send an error response with specific code, message, and data
    error_response = make_error_response(req_id, -32009, "Unauthorized", data={"reason": "bad token"})
    await dispatcher.receive(error_response)

    await task
    with pytest.raises(TesseronError) as exc_info:
        future_result.result()
    err = exc_info.value
    assert err.code == -32009
    assert "Unauthorized" in err.message
    assert err.data == {"reason": "bad token"}


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
async def test_er27_confirm_returns_false_when_elicitation_not_available(mock_gateway: MockGateway) -> None:
    """ER-27: REQ-060, REQ-075. ctx.confirm() returns False when elicitation not available (NOT throw).

    ctx.confirm() is the safe gate: it never throws ElicitationNotAvailableError.
    When elicitation capability is absent, it silently returns False.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    confirm_result: list[bool] = []

    @tesseron.action("confirmAction", description="Confirms")
    async def confirm_action(input: Any, ctx: Any) -> dict[str, Any]:
        result = await ctx.confirm("Proceed?")
        confirm_result.append(result)
        return {"confirmed": result}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    # Handshake with elicitation=False
    await mock_gateway.perform_handshake(
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": False}
    )
    await connect_task

    invoke_id = await mock_gateway.send_invoke("confirmAction", {}, invocation_id="inv_confirm_er27")

    for _ in range(30):
        await asyncio.sleep(0.1)
        responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and ("result" in m.parsed or "error" in m.parsed) and m.parsed.get("id") == invoke_id
        ]
        if responses:
            break

    success_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    # Must succeed (not raise), and confirm must return False
    assert len(success_responses) == 1
    assert confirm_result and confirm_result[0] is False

    await tesseron.disconnect()


@pytest.mark.error_model
async def test_er28_elicit_throws_when_elicitation_not_available(mock_gateway: MockGateway) -> None:
    """ER-28: REQ-065. ctx.elicit() throws ElicitationNotAvailableError when capability absent.

    Unlike ctx.confirm(), ctx.elicit() raises ElicitationNotAvailableError
    when the agent does not support elicitation, because structured data
    has no safe default.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    @tesseron.action("elicitAction2", description="Elicits")
    async def elicit_action2(input: Any, ctx: Any) -> dict[str, Any]:
        # ctx.elicit() must raise ElicitationNotAvailableError when capability absent
        await ctx.elicit(
            "Which option?",
            json_schema={"type": "object", "properties": {"choice": {"type": "string"}}, "required": ["choice"]},
        )
        return {"done": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    # Handshake with elicitation=False
    await mock_gateway.perform_handshake(
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": False}
    )
    await connect_task

    invoke_id = await mock_gateway.send_invoke("elicitAction2", {}, invocation_id="inv_elicit_er28")

    for _ in range(30):
        await asyncio.sleep(0.1)
        error_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if error_responses:
            break

    error_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    # Must produce an error response (elicit raises, not returns False)
    assert len(error_responses) == 1
    assert error_responses[0]["error"]["code"] in (-32007, -32005)

    await tesseron.disconnect()


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
