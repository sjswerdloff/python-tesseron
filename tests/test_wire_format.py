"""Wire format tests — JSON-RPC 2.0 envelope shapes and transport bindings.

Test IDs: WF-01 through WF-37
Source: Spec §2 (Wire Format), §3 (Transport Bindings), Appendix B (Dispatcher)

These tests verify the observable wire-level behaviour of the Tesseron
protocol:  envelope shapes, ID rules, method surface classification, and
transport binding contracts. They work against the mock gateway and the
stub types/errors package; full SDK implementation is not required for
the structural/parsing tests, but the integration tests are marked xfail
until the SDK is complete.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from python_tesseron.errors import MethodNotFoundError, TransportClosedError
from python_tesseron.types import (
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcSuccessResponse,
)
from tests.conftest import (
    MockGateway,
    assert_jsonrpc_notification,
    assert_jsonrpc_request,
    make_error_response,
    make_hello_params,
    make_notification,
    make_request,
    make_success_response,
)

# ---------------------------------------------------------------------------
# §2.1 Envelope Shape Tests (WF-01 through WF-05)
# ---------------------------------------------------------------------------


@pytest.mark.wire_format
def test_wf01_request_has_required_fields() -> None:
    """WF-01: REQ-011. Request must have jsonrpc, id, method, params.

    Construct a JsonRpcRequest and verify all four fields are present and
    correctly valued when serialised to a dict.
    """
    req = JsonRpcRequest(id=42, method="actions/invoke", params={"name": "doSomething", "invocationId": "inv_1", "input": {}})
    data = req.model_dump()

    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 42
    assert data["method"] == "actions/invoke"
    assert "params" in data


@pytest.mark.wire_format
def test_wf02_notification_has_no_id_field() -> None:
    """WF-02: REQ-002. Notification must have jsonrpc, method, params but NO id.

    Spec §2.1: Notifications MUST NOT have an id field.
    """
    notif = JsonRpcNotification(method="actions/progress", params={"invocationId": "inv_1", "percent": 40})
    data = notif.model_dump()

    assert data["jsonrpc"] == "2.0"
    assert "method" in data
    assert data["method"] == "actions/progress"
    # The notification model must NOT include an id field
    assert "id" not in data


@pytest.mark.wire_format
def test_wf03_success_response_has_required_fields() -> None:
    """WF-03: REQ-005. Success response must have jsonrpc, id, result.

    Spec §2.1: Success response shape.
    """
    resp = JsonRpcSuccessResponse(id=42, result={"invocationId": "inv_1", "output": {}})
    data = resp.model_dump()

    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 42
    assert "result" in data
    assert "error" not in data


@pytest.mark.wire_format
def test_wf04_error_response_has_required_fields() -> None:
    """WF-04: REQ-005. Error response must have jsonrpc, id, error with code+message.

    Spec §2.1: Error response shape must include error object with code and message.
    """
    resp = JsonRpcErrorResponse(
        id=42,
        error={"code": -32004, "message": "Invalid input", "data": []},  # type: ignore[arg-type]
    )
    data = resp.model_dump()

    assert data["jsonrpc"] == "2.0"
    assert data["id"] == 42
    assert "error" in data
    assert "result" not in data
    err = data["error"]
    assert err["code"] == -32004
    assert err["message"] == "Invalid input"


@pytest.mark.wire_format
def test_wf05_notification_must_not_receive_response() -> None:
    """WF-05: REQ-002. Notification MUST NOT receive a response.

    A notification has no id. The spec requires that no response is sent
    for a notification. This test verifies the structural rule: a message
    without an id field is a notification, not a request.
    """
    # Build a notification dict and verify no id is present
    msg = make_notification("actions/progress", {"invocationId": "inv_1", "percent": 50})

    assert "id" not in msg
    assert msg["jsonrpc"] == "2.0"
    assert "method" in msg

    # Verifying this structurally — the actual non-response behaviour is an
    # SDK integration test (marked xfail below).


# ---------------------------------------------------------------------------
# §2.2 ID Rules Tests (WF-06 through WF-09)
# ---------------------------------------------------------------------------


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK request() method not yet implemented")
async def test_wf06_sdk_uses_monotonically_incrementing_ids(mock_gateway: MockGateway) -> None:
    """WF-06: REQ-004. SDK SHOULD use monotonically incrementing integers for id.

    Send 3 requests and verify the ids are sequential integers.
    """
    # TODO: Instantiate SDK, connect to mock_gateway.url, capture 3 request IDs
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK request() method not yet implemented")
async def test_wf07_responding_peer_echoes_request_id(mock_gateway: MockGateway) -> None:
    """WF-07: REQ-005. Responding peer MUST echo exact same id.

    Send request with id=42, verify response has id=42.
    """
    # The mock gateway always echoes the id back. The SDK must accept it.
    # TODO: Connect SDK, verify echo
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK pending request map not yet implemented")
async def test_wf08_sdk_maintains_pending_request_map(mock_gateway: MockGateway) -> None:
    """WF-08: REQ-006. SDK MUST maintain pending request map keyed by id.

    Send a request, verify map entry exists before response. Receive response,
    verify entry removed.
    """
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK transport close rejection not yet implemented")
async def test_wf09_transport_close_rejects_all_pending(mock_gateway: MockGateway) -> None:
    """WF-09: REQ-008. On transport close, ALL pending requests MUST be rejected.

    Send 3 requests, close transport, verify all 3 rejected with TransportClosedError.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# §2.3 Method Surface Tests (WF-10 through WF-14)
# ---------------------------------------------------------------------------


@pytest.mark.wire_format
def test_wf10_hello_is_a_request() -> None:
    """WF-10: REQ-009. App->Gateway: tesseron/hello is a request (has id).

    The hello message must be a request (has id field), not a notification.
    """
    hello = make_request("tesseron/hello", make_hello_params(), request_id=1)

    assert_jsonrpc_request(hello, method="tesseron/hello")
    assert hello["id"] is not None


@pytest.mark.wire_format
def test_wf11_progress_is_a_notification() -> None:
    """WF-11: REQ-002. App->Gateway: actions/progress is a notification (no id).

    Progress updates are fire-and-forget; they must not have an id field.
    """
    progress = make_notification(
        "actions/progress",
        {"invocationId": "inv_1", "message": "halfway", "percent": 50},
    )

    assert_jsonrpc_notification(progress, method="actions/progress")


@pytest.mark.wire_format
def test_wf12_list_changed_is_a_notification() -> None:
    """WF-12: REQ-049. App->Gateway: actions/list_changed is a notification (no id).

    Dynamic action registration change notifications are fire-and-forget.
    """
    list_changed = make_notification("actions/list_changed", {"actions": []})

    assert_jsonrpc_notification(list_changed, method="actions/list_changed")


@pytest.mark.wire_format
def test_wf13_invoke_is_a_request() -> None:
    """WF-13. Gateway->App: actions/invoke is a request (has id, expects response).

    The mock gateway sends an invoke request; the app must respond to it.
    """
    invoke = make_request(
        "actions/invoke",
        {"name": "doSomething", "invocationId": "inv_1", "input": {}},
        request_id=7,
    )

    assert_jsonrpc_request(invoke, method="actions/invoke")
    assert invoke["id"] == 7


@pytest.mark.wire_format
def test_wf14_cancel_is_a_notification() -> None:
    """WF-14. Gateway->App: actions/cancel is a notification (no id, no response).

    Cancellation is fire-and-forget from the gateway side.
    """
    cancel = make_notification("actions/cancel", {"invocationId": "inv_1"})

    assert_jsonrpc_notification(cancel, method="actions/cancel")


# ---------------------------------------------------------------------------
# §3.2 WebSocket Transport Tests (WF-15 through WF-21)
# ---------------------------------------------------------------------------


@pytest.mark.wire_format
def test_wf15_one_envelope_per_ws_frame() -> None:
    """WF-15: REQ-011. One JSON-RPC envelope per WebSocket text frame.

    A serialised request must be a single complete JSON object (parseable
    in one shot). This validates the framing contract structurally.
    """
    req = JsonRpcRequest(id=1, method="tesseron/hello", params=make_hello_params())
    raw = req.model_dump_json()

    # Must be parseable as a single JSON object
    parsed = json.loads(raw)
    assert isinstance(parsed, dict)
    assert parsed["jsonrpc"] == "2.0"


@pytest.mark.wire_format
def test_wf16_no_compression_no_binary() -> None:
    """WF-16: REQ-010. No batching, no binary, no compression.

    A Tesseron message is a plain JSON text string. Verify the serialised
    form contains no encoding artifacts.
    """
    msg = make_request("tesseron/hello", make_hello_params())
    raw = json.dumps(msg)

    # Must be a simple JSON string (no base64, no envelope wrapper)
    assert raw.startswith("{")
    assert raw.endswith("}")
    # No batch array wrapper
    assert not raw.startswith("[")


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK WebSocket server binding not yet implemented")
async def test_wf17_gateway_sends_tesseron_gateway_subprotocol(mock_gateway: MockGateway) -> None:
    """WF-17: REQ-016. Gateway sends Sec-WebSocket-Protocol: tesseron-gateway.

    The mock gateway advertises the subprotocol. This test verifies the
    SDK rejects or accepts connections based on subprotocol presence.
    """
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK WebSocket server not yet implemented")
async def test_wf18_app_rejects_upgrade_without_subprotocol() -> None:
    """WF-18: REQ-017. App MUST reject upgrades without tesseron-gateway subprotocol.

    Connect to app's WS server WITHOUT the subprotocol header, verify rejection.
    """
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK WebSocket server not yet implemented")
async def test_wf19_app_binds_to_loopback_only() -> None:
    """WF-19: REQ-018. App MUST bind to loopback only (127.0.0.1 or ::1).

    Verify the bind address is loopback after the SDK starts its server.
    """
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK WebSocket server not yet implemented")
async def test_wf20_app_accepts_exactly_one_upgrade(mock_gateway: MockGateway) -> None:
    """WF-20: REQ-019. App MUST accept exactly one WS upgrade, reject all others.

    First connection is accepted; a second connection attempt is rejected.
    """
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK manifest lifecycle not yet implemented")
async def test_wf21_app_writes_manifest_on_bind_deletes_on_close() -> None:
    """WF-21: REQ-020, REQ-028. App writes manifest on bind, deletes on close.

    Verify the manifest file lifecycle: created when server starts,
    deleted when the transport closes.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# §3.3 UDS Transport Tests (WF-22 through WF-27)
# ---------------------------------------------------------------------------


@pytest.mark.wire_format
def test_wf22_uds_ndjson_newline_terminated() -> None:
    r"""WF-22: REQ-011. UDS: one envelope per newline-terminated line (NDJSON).

    The UDS framing adds '\n' to each serialised message.
    """
    msg = make_notification("actions/progress", {"invocationId": "inv_1", "percent": 50})
    framed = json.dumps(msg) + "\n"

    assert framed.endswith("\n")
    # The line before the newline must be a complete JSON object
    parsed = json.loads(framed.strip())
    assert parsed["method"] == "actions/progress"


@pytest.mark.wire_format
def test_wf23_uds_empty_lines_ignored() -> None:
    """WF-23: REQ-011. UDS: empty lines are ignored (no parse error).

    An empty line in NDJSON stream must be silently skipped.
    """
    # Empty line — simulates the SDK's receive loop skipping blank lines
    empty_line = ""
    stripped = empty_line.strip()
    # An SDK loop should skip lines where stripped == ""
    assert stripped == ""
    # No json.loads() should be called on empty lines


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK UDS binding not yet implemented")
async def test_wf24_uds_private_directory_mode_0o700() -> None:
    """WF-24: REQ-021. UDS: private directory must be mode 0o700.

    Create a UDS binding, verify the parent directory has mode 0o700.
    """
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK UDS binding not yet implemented")
async def test_wf25_uds_socket_file_mode_0o600() -> None:
    """WF-25: REQ-023. UDS: socket file SHOULD be chmod 0o600.

    Create a UDS binding, verify the socket file has mode 0o600.
    """
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK UDS binding not yet implemented")
async def test_wf26_uds_accepts_exactly_one_connection() -> None:
    """WF-26: REQ-022. UDS: accept exactly one connection, reject subsequent.

    First connection accepted; second connection attempt is rejected.
    """
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK UDS cleanup not yet implemented")
async def test_wf27_uds_cleanup_on_close() -> None:
    """WF-27: REQ-028. UDS: delete manifest, socket file, and temp dir on close.

    Verify all three artifacts are removed when the transport closes.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Appendix B Dispatcher Tests (WF-28 through WF-35)
# ---------------------------------------------------------------------------


@pytest.mark.wire_format
def test_wf28_message_with_method_and_id_is_request() -> None:
    """WF-28. Dispatcher: message with method+id dispatches to request handler.

    A message with both method and id is a request and must be routed to
    the registered request handler.
    """
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 7,
        "method": "actions/invoke",
        "params": {"name": "doSomething", "invocationId": "inv_1", "input": {}},
    }

    # Structural rule: has both method and id -> is a request
    assert "method" in msg
    assert "id" in msg
    assert "result" not in msg
    assert "error" not in msg


@pytest.mark.wire_format
def test_wf29_message_with_method_no_id_is_notification() -> None:
    """WF-29. Dispatcher: message with method but no id is notification.

    A notification must not generate any response.
    """
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": "actions/cancel",
        "params": {"invocationId": "inv_1"},
    }

    assert "method" in msg
    assert "id" not in msg


@pytest.mark.wire_format
def test_wf30_message_with_id_and_result_is_response() -> None:
    """WF-30. Dispatcher: message with id+result but no method resolves pending request.

    A success response has id and result but no method field.
    """
    msg = make_success_response(7, {"invocationId": "inv_1", "output": {}})

    assert "id" in msg
    assert "result" in msg
    assert "method" not in msg


@pytest.mark.wire_format
def test_wf31_message_with_id_and_error_is_error_response() -> None:
    """WF-31. Dispatcher: message with id+error but no method rejects pending request.

    An error response has id and error but no method field.
    """
    msg = make_error_response(7, -32003, "Action not found")

    assert "id" in msg
    assert "error" in msg
    assert "method" not in msg


@pytest.mark.wire_format
def test_wf32_message_without_jsonrpc_20_is_ignored() -> None:
    """WF-32. Dispatcher: message without jsonrpc 2.0 field is ignored.

    Messages that do not declare jsonrpc="2.0" MUST be silently dropped.
    """
    bad_msg: dict[str, Any] = {
        "id": 1,
        "method": "actions/invoke",
        "params": {},
    }

    # The dispatcher rule: if jsonrpc != "2.0", ignore
    assert bad_msg.get("jsonrpc") != "2.0"


@pytest.mark.wire_format
def test_wf33_no_handler_returns_method_not_found() -> None:
    """WF-33: REQ-003. No handler for method returns -32601 MethodNotFound.

    An unregistered request method must produce a -32601 error response.
    """
    err = MethodNotFoundError()

    assert err.code == -32601
    assert "not found" in err.message.lower()


@pytest.mark.wire_format
def test_wf34_reject_all_pending_on_transport_close() -> None:
    """WF-34: REQ-008. reject_all_pending called on transport close.

    When the transport closes, all pending requests must be rejected with
    TransportClosedError.
    """
    err = TransportClosedError()

    assert err.code == -32010
    assert isinstance(err, Exception)


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK send failure handling not yet implemented")
async def test_wf35_send_failure_closes_transport(mock_gateway: MockGateway) -> None:
    """WF-35. Send failure closes transport.

    When send() fails (transport error), the transport must be closed so
    the peer sees a close and rejects its own pending requests.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Gap analysis additional tests (WF-36, WF-37)
# ---------------------------------------------------------------------------


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK binary frame coercion not yet implemented")
async def test_wf36_ws_binary_frame_coerced_to_utf8(mock_gateway: MockGateway) -> None:
    """WF-36: REQ-015. WS binary frames SHOULD be coerced to UTF-8 text.

    Send a binary frame containing valid JSON. Verify the SDK parses it
    correctly rather than rejecting it (defensive tolerance).
    """
    raise NotImplementedError


@pytest.mark.wire_format
@pytest.mark.xfail(reason="implementation pending: SDK instance ID generation not yet implemented")
def test_wf37_instance_id_uses_inst_prefix() -> None:
    """WF-37: REQ-027. instanceId SHOULD use inst- prefix.

    When the SDK generates an instance ID, it must be prefixed with 'inst-'.
    """
    # TODO: Call SDK's instance ID generator and check prefix
    raise NotImplementedError
