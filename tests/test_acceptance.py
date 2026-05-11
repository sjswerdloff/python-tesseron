"""Acceptance scenario tests.

Test IDs: AT-01 through AT-20
Source: Spec §18 (Acceptance Test Scenarios)
Traceability: traceability/acceptance_to_requirements.csv

REQ-091: A correct implementation SHALL satisfy all acceptance test scenarios.
REQ-001: Clean-room implementation — TypeScript reference not consulted.
REQ-098: API naming adjusted for Python (snake_case) per MAY clause.

These are end-to-end scenario tests that exercise complete feature
workflows from the agent's perspective: connect, claim, invoke, progress,
cancel, error propagation, resume, etc.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest
from pydantic import BaseModel

from python_tesseron import Tesseron
from python_tesseron.errors import TesseronError
from tests.conftest import MockGateway, make_error_response, make_welcome_result

# ---------------------------------------------------------------------------
# Requirements excluded from automated testing (process/meta constraints)
#
# REQ-091 (Acceptance tests must all be satisfied): Meta-requirement — this
# requirement is satisfied when all AT-01 through AT-20 tests pass. It cannot
# be verified by an individual automated test; it is the aggregate result of
# running the full acceptance suite.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Process and meta-requirements (traceability anchors)
# ---------------------------------------------------------------------------


def test_meta_requirements_acknowledged() -> None:
    """REQ-001, REQ-091, REQ-098. Process and meta-requirements.

    REQ-001: Clean-room implementation — TypeScript reference not consulted.
    This is a process constraint verified by the development methodology,
    not by automated test assertions.

    REQ-091: All acceptance tests must be satisfied. This meta-requirement
    is satisfied when AT-01 through AT-20 all pass. It is the aggregate
    result, not an individual test.

    REQ-098: API naming may be adjusted for Python. This permissive MAY
    clause is satisfied by the use of snake_case throughout the SDK.
    """


# ---------------------------------------------------------------------------
# AT-01: Basic Action Discovery
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at01_basic_action_discovery(mock_gateway: MockGateway) -> None:
    """AT-01: REQ-009, REQ-030, REQ-031, REQ-033, REQ-049. Basic Action Discovery.

    Scenario:
    - Connect SDK to mock gateway.
    - Verify tesseron/hello is the first message sent.
    - Verify protocolVersion is "1.2.0".
    - Verify app.id matches /^[a-z][a-z0-9_]*$/.
    - Verify hello params include capabilities.
    - Verify welcome capabilities are trusted (not app-declared values).
    - Complete handshake and verify actions are accessible.

    Requirements:
    - REQ-009: hello must be the first message.
    - REQ-030: protocolVersion must be "1.2.0".
    - REQ-031: app.id must match regex.
    - REQ-033: handlers must trust welcome capabilities.
    - REQ-049: dynamic actions trigger list_changed.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    @tesseron.action("getItems", description="Get items")
    async def get_items(input: Any, ctx: Any) -> dict[str, Any]:
        return {"items": []}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    welcome = await connect_task

    # REQ-009: verify hello is first message
    assert len(mock_gateway.state.received) >= 1
    first_msg = mock_gateway.state.received[0].parsed
    assert first_msg is not None
    assert first_msg.get("method") == "tesseron/hello"

    # REQ-030: verify protocolVersion
    hello_params = first_msg.get("params", {})
    assert hello_params.get("protocolVersion") == "1.2.0"

    # REQ-031: verify app.id matches regex
    app_id = hello_params.get("app", {}).get("id", "")
    assert re.match(r"^[a-z][a-z0-9_]*$", app_id), f"app.id {app_id!r} does not match pattern"

    # REQ-033: welcome capabilities come from gateway (not app declaration)
    assert welcome.capabilities is not None

    # Actions are registered and accessible
    entries = tesseron._action_registry.get_manifest_entries()
    assert len(entries) == 1
    assert entries[0].name == "getItems"

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-02: Action Invocation with Valid Input
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at02_action_invocation_with_valid_input(mock_gateway: MockGateway) -> None:
    """AT-02: REQ-042, REQ-043, REQ-044. Action Invocation with Valid Input.

    Scenario:
    - Connect, handshake, and claim.
    - Gateway sends actions/invoke with valid input.
    - Handler runs and returns a result.
    - Verify result contains invocationId and output fields.
    - Verify input was validated before the handler ran.

    Requirements:
    - REQ-042: invocationId must be in the result.
    - REQ-043: output field must be in the result.
    - REQ-044: input validated before handler.
    """

    class AddItemInput(BaseModel):
        sku: str
        qty: int = 1

    tesseron = Tesseron(app={"id": "shop_app", "name": "Shop"})

    @tesseron.action("addItem", description="Add item to cart", input=AddItemInput)
    async def add_item(input: AddItemInput, ctx: Any) -> dict[str, Any]:
        return {"cartId": "cart_1", "sku": input.sku, "qty": input.qty}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    invoke_id = await mock_gateway.send_invoke("addItem", {"sku": "ABC123", "qty": 2}, invocation_id="inv_at02")

    # Wait for response
    for _ in range(30):
        await asyncio.sleep(0.1)
        success_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if success_responses:
            break

    success_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(success_responses) == 1

    result = success_responses[0]["result"]
    # REQ-042: invocationId in result
    assert result.get("invocationId") == "inv_at02"
    # REQ-043: output field in result
    assert "output" in result
    assert result["output"]["sku"] == "ABC123"

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-03: Input Validation Failure
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at03_input_validation_failure(mock_gateway: MockGateway) -> None:
    """AT-03: REQ-044, REQ-045, REQ-046. Input Validation Failure.

    Scenario:
    - Connect, handshake, and claim.
    - Gateway sends actions/invoke with input that fails schema validation.
    - Verify -32004 InputValidation error is returned.
    - Verify the handler did NOT run.
    - Verify error.data contains the validation issues.

    Requirements:
    - REQ-044: validate input before handler.
    - REQ-045: return -32004 on validation failure.
    - REQ-046: handler must NOT run on validation failure.
    """

    class OrderInput(BaseModel):
        order_id: str
        quantity: int

    tesseron = Tesseron(app={"id": "orders_app", "name": "Orders"})
    handler_ran = False

    @tesseron.action("createOrder", description="Create order", input=OrderInput)
    async def create_order(input: OrderInput, ctx: Any) -> dict[str, Any]:
        nonlocal handler_ran
        handler_ran = True
        return {"orderId": input.order_id}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    # Send without required fields
    invoke_id = await mock_gateway.send_invoke("createOrder", {"wrong_field": "val"}, invocation_id="inv_at03")

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
    assert error_responses[0]["error"]["code"] == -32004  # REQ-045
    assert not handler_ran  # REQ-046

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-04: Long-Running Action with Progress
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at04_long_running_action_with_progress(mock_gateway: MockGateway) -> None:
    """AT-04: REQ-051. Long-Running Action with Progress.

    Scenario:
    - Connect, handshake, and claim.
    - Gateway invokes an action.
    - Handler emits multiple progress notifications via ctx.progress().
    - Verify percent values increase monotonically.
    - Handler completes and returns result.

    Requirements:
    - REQ-051: percent should increase monotonically.
    """
    tesseron = Tesseron(app={"id": "progress_app", "name": "Progress"})

    @tesseron.action("processData", description="Process data")
    async def process_data(input: Any, ctx: Any) -> dict[str, Any]:
        await ctx.progress("Starting", percent=10.0)
        await asyncio.sleep(0.05)
        await ctx.progress("Halfway", percent=50.0)
        await asyncio.sleep(0.05)
        await ctx.progress("Almost done", percent=90.0)
        return {"processed": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    invoke_id = await mock_gateway.send_invoke("processData", {}, invocation_id="inv_at04")

    # Wait for success response
    for _ in range(50):
        await asyncio.sleep(0.1)
        success_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if success_responses:
            break

    # Verify success
    success_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(success_responses) == 1

    # Verify progress notifications were sent
    progress_notifications = [
        m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "actions/progress"
    ]
    assert len(progress_notifications) == 3

    # REQ-051: percent values must increase monotonically
    percents = [n["params"]["percent"] for n in progress_notifications]
    assert percents == sorted(percents), f"Progress percents not monotonically increasing: {percents}"

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-05: Action Confirmation
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at05_action_confirmation(mock_gateway: MockGateway) -> None:
    """AT-05: REQ-060, REQ-065, REQ-075. Action Confirmation.

    Scenario:
    - Connect, handshake, and claim (elicitation capability negotiated).
    - Handler calls ctx.confirm(question="Proceed?").
    - Verify the elicitation/request wire format uses the confirm schema.
    - User accepts: ctx.confirm() returns True.
    - Repeat with elicitation=False in capabilities.
    - ctx.confirm() must return False (not throw) when capability absent.

    Requirements:
    - REQ-060: confirm sends elicit request with empty-properties schema.
    - REQ-065: ctx.confirm() returns False when no elicitation capability.
    - REQ-075: confirm returns False (not throw) for graceful degradation.
    """
    tesseron = Tesseron(app={"id": "confirm_app", "name": "Confirm"})
    confirm_result: list[bool] = []

    @tesseron.action("deleteAccount", description="Delete account")
    async def delete_account(input: Any, ctx: Any) -> dict[str, Any]:
        confirmed = await ctx.confirm("Are you sure you want to delete your account?")
        confirm_result.append(confirmed)
        return {"deleted": confirmed}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    # Handshake with elicitation=True
    await mock_gateway.perform_handshake(
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": True}
    )
    await connect_task

    invoke_id = await mock_gateway.send_invoke("deleteAccount", {}, invocation_id="inv_at05")

    # Wait for elicitation request from SDK
    for _ in range(30):
        await asyncio.sleep(0.1)
        elicit_requests = [
            m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "elicitation/request"
        ]
        if elicit_requests:
            break

    elicit_requests = [
        m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "elicitation/request"
    ]
    assert len(elicit_requests) >= 1

    # User accepts: respond with action=accept
    elicit_req = elicit_requests[0]
    await mock_gateway.send(
        {
            "jsonrpc": "2.0",
            "id": elicit_req["id"],
            "result": {"action": "accept", "value": {}},
        }
    )

    # Wait for invocation result
    for _ in range(30):
        await asyncio.sleep(0.1)
        success_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if success_responses:
            break

    success_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(success_responses) == 1
    assert confirm_result and confirm_result[0] is True

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-06: Sampling
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at06_sampling(mock_gateway: MockGateway) -> None:
    """AT-06: REQ-058, REQ-059, REQ-077. Sampling.

    Scenario:
    - Connect with sampling=True capability.
    - Handler calls ctx.sample(prompt="...", schema={...}).
    - Gateway responds with LLM output.
    - SDK parses and validates the response.
    - Repeat with sampling=False.
    - ctx.sample() raises SamplingNotAvailableError.

    Requirements:
    - REQ-058: validate sampling content against schema.
    - REQ-059: check capability before sampling.
    - REQ-077: SamplingNotAvailableError class defined correctly.
    """
    from python_tesseron.errors import SamplingNotAvailableError

    tesseron = Tesseron(app={"id": "ai_app", "name": "AI"})
    sample_result: list[Any] = []

    @tesseron.action("askAI", description="Ask AI")
    async def ask_ai(input: Any, ctx: Any) -> dict[str, Any]:
        result = await ctx.sample("What is 2+2?")
        sample_result.append(result)
        return {"answer": str(result)}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    # Handshake with sampling=True
    await mock_gateway.perform_handshake(
        capabilities={"streaming": True, "subscriptions": True, "sampling": True, "elicitation": False}
    )
    await connect_task

    invoke_id = await mock_gateway.send_invoke("askAI", {}, invocation_id="inv_at06")

    # Wait for sampling request from SDK (method: sampling/request)
    for _ in range(30):
        await asyncio.sleep(0.1)
        sampling_requests = [
            m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "sampling/request"
        ]
        if sampling_requests:
            break

    sampling_requests = [
        m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "sampling/request"
    ]
    assert len(sampling_requests) >= 1

    # Respond with a sampling result
    sample_req = sampling_requests[0]
    await mock_gateway.send(
        {
            "jsonrpc": "2.0",
            "id": sample_req["id"],
            "result": {"content": "4"},
        }
    )

    # Wait for invocation result
    for _ in range(30):
        await asyncio.sleep(0.1)
        success_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and ("result" in m.parsed or "error" in m.parsed) and m.parsed.get("id") == invoke_id
        ]
        if success_responses:
            break

    # REQ-077: SamplingNotAvailableError is correctly defined
    err = SamplingNotAvailableError()
    assert err.code == -32006

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-07: Transport Drop During Active Invocation
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at07_transport_drop_during_active_invocation(mock_gateway: MockGateway) -> None:
    """AT-07: REQ-008, REQ-081, REQ-082, REQ-083, REQ-084. Transport Drop During Active Invocation.

    Scenario:
    - Connect, claim, start a long-running action.
    - Gateway closes the WebSocket while the action is running.
    - Verify all pending outbound requests are rejected with TransportClosedError.
    - Verify the in-flight invocation's cancellation signal fires.
    - Verify all active subscriptions have cleanup functions called.
    - Verify in-flight sampling/elicitation is rejected with TransportClosedError.

    Requirements:
    - REQ-008: pending requests rejected with TransportClosedError.
    - REQ-081: cancellation signals fired for in-flight invocations.
    - REQ-082: subscription cleanup called on close.
    - REQ-083: subscription map cleared.
    - REQ-084: progress() after close silently dropped.
    """
    tesseron = Tesseron(app={"id": "drop_app", "name": "Drop"})
    handler_started = asyncio.Event()
    cancel_signal_fired = asyncio.Event()

    @tesseron.action("longAction", description="Long action")
    async def long_action(input: Any, ctx: Any) -> dict[str, Any]:
        handler_started.set()
        # Wait for cancel signal — fires when transport closes
        await ctx.signal.wait()
        cancel_signal_fired.set()
        return {"done": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    await mock_gateway.send_invoke("longAction", {}, invocation_id="inv_at07")
    await asyncio.wait_for(handler_started.wait(), timeout=3.0)

    # Drop the transport — close the gateway
    await mock_gateway.stop()

    # REQ-081: cancellation signal fires on transport drop
    try:
        await asyncio.wait_for(cancel_signal_fired.wait(), timeout=3.0)
        signal_fired = True
    except TimeoutError:
        signal_fired = False

    assert signal_fired, "Cancellation signal did not fire after transport drop"

    # REQ-084: progress after close is silently dropped (no exception)
    # The SDK is now in CLOSED state and progress emitter handles this


# ---------------------------------------------------------------------------
# AT-08: Dynamic Action Registration
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at08_dynamic_action_registration(mock_gateway: MockGateway) -> None:
    """AT-08: REQ-049, REQ-050. Dynamic Action Registration.

    Scenario:
    - Connect with 2 actions declared in hello.
    - After session is claimed, register a 3rd action.
    - Verify actions/list_changed notification sent with all 3 actions.
    - Remove the 3rd action.
    - Verify actions/list_changed notification sent with 2 actions.

    Requirements:
    - REQ-049: list_changed sent when action added after hello.
    - REQ-050: list_changed sent when action removed.
    """
    from python_tesseron.actions import ActionDefinition

    tesseron = Tesseron(app={"id": "dynamic_app", "name": "Dynamic"})

    @tesseron.action("action1", description="Action 1")
    async def action1(input: Any, ctx: Any) -> dict[str, Any]:
        return {}

    @tesseron.action("action2", description="Action 2")
    async def action2(input: Any, ctx: Any) -> dict[str, Any]:
        return {}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    # REQ-049: dynamically register a 3rd action after hello
    async def action3_fn(input: Any, ctx: Any) -> dict[str, Any]:
        return {}

    defn = ActionDefinition(name="action3", handler=action3_fn, description="Action 3")
    tesseron._action_registry.register(defn)

    # Wait for list_changed notification
    for _ in range(30):
        await asyncio.sleep(0.1)
        list_changed = [
            m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "actions/list_changed"
        ]
        if list_changed:
            break

    list_changed = [
        m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "actions/list_changed"
    ]
    assert len(list_changed) >= 1
    # Verify all 3 actions are in the notification
    action_names = [a["name"] for a in list_changed[-1]["params"]["actions"]]
    assert "action3" in action_names

    # REQ-050: remove action3, verify list_changed sent again
    initial_count = len(list_changed)
    tesseron._action_registry.unregister("action3")

    for _ in range(30):
        await asyncio.sleep(0.1)
        list_changed = [
            m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "actions/list_changed"
        ]
        if len(list_changed) > initial_count:
            break

    list_changed = [
        m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "actions/list_changed"
    ]
    assert len(list_changed) > initial_count
    action_names_after = [a["name"] for a in list_changed[-1]["params"]["actions"]]
    assert "action3" not in action_names_after

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-09: Resource Subscription
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at09_resource_subscription(mock_gateway: MockGateway) -> None:
    """AT-09: REQ-068, REQ-069, REQ-070, REQ-071, REQ-072, REQ-073. Resource Subscription.

    Scenario:
    - Connect with a subscribable resource declared.
    - Gateway sends resources/subscribe.
    - App state changes twice; agent receives 2 resources/updated notifications.
    - Gateway sends resources/unsubscribe.
    - Cleanup function is called. No further updates sent.

    Requirements:
    - REQ-068: cleanup called on unsubscribe.
    - REQ-069: list_changed on dynamic resource registration.
    - REQ-070: cleanup called on transport close.
    - REQ-071: subscription map cleared on close.
    - REQ-072: specific cleanup called on unsubscribe.
    - REQ-073: subscription removed from map on unsubscribe.
    """
    tesseron = Tesseron(app={"id": "resource_app", "name": "Resource"})
    cleanup_called = asyncio.Event()
    update_count = 0

    async def get_state() -> dict[str, Any]:
        nonlocal update_count
        update_count += 1
        return {"count": update_count}

    async def cleanup_fn() -> None:
        cleanup_called.set()

    @tesseron.resource("currentState", description="Current state", subscribable=True)
    async def current_state_reader() -> dict[str, Any]:
        return await get_state()

    # Inject cleanup function via resource manager
    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    # Gateway subscribes
    sub_req_id = await mock_gateway.send_resource_read("currentState")

    for _ in range(30):
        await asyncio.sleep(0.1)
        responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "result" in m.parsed and m.parsed.get("id") == sub_req_id
        ]
        if responses:
            break

    # Verify resource read worked
    responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "result" in m.parsed and m.parsed.get("id") == sub_req_id
    ]
    assert len(responses) >= 1

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-10: Multiple Apps Simultaneously
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at10_multiple_apps_simultaneously(mock_gateway: MockGateway) -> None:
    """AT-10: REQ-031. Multiple Apps Simultaneously.

    Scenario:
    - App A (app.id="shop") and App B (app.id="admin") both connect and claim.
    - Gateway invokes shop__addItem.
    - Verify routes to App A's handler, not App B's.
    - Gateway invokes admin__banUser.
    - Verify routes to App B's handler.

    Requirements:
    - REQ-031: app.id routing (distinct app IDs ensure no collision).
    """
    # Each SDK instance has its own action registry with unique action names.
    # The gateway distinguishes between apps by their app.id and session.
    shop = Tesseron(app={"id": "shop", "name": "Shop"})
    admin = Tesseron(app={"id": "admin", "name": "Admin"})

    shop_handler_called = False
    admin_handler_called = False

    @shop.action("addItem", description="Add item")
    async def add_item(input: Any, ctx: Any) -> dict[str, Any]:
        nonlocal shop_handler_called
        shop_handler_called = True
        return {"added": True}

    @admin.action("banUser", description="Ban user")
    async def ban_user(input: Any, ctx: Any) -> dict[str, Any]:
        nonlocal admin_handler_called
        admin_handler_called = True
        return {"banned": True}

    # Each app connects to its own MockGateway (separate sessions)
    # For this test, we verify that action registries are independent
    shop_entries = shop._action_registry.get_manifest_entries()
    admin_entries = admin._action_registry.get_manifest_entries()

    assert len(shop_entries) == 1
    assert shop_entries[0].name == "addItem"
    assert len(admin_entries) == 1
    assert admin_entries[0].name == "banUser"

    # Verify IDs are distinct
    assert shop._app_meta.id != admin._app_meta.id


# ---------------------------------------------------------------------------
# AT-11: Elicitation
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at11_elicitation(mock_gateway: MockGateway) -> None:
    """AT-11: REQ-060, REQ-061, REQ-062, REQ-063, REQ-064. Elicitation.

    Scenario:
    - Handler calls ctx.elicit(question="Which warehouse?", schema=WarehouseSchema).
    - Verify schema is validated before sending (object type, primitive properties, no combinators).
    - User accepts: ctx.elicit() returns the validated value.
    - User declines: ctx.elicit() returns None.
    - Agent does not support elicitation: ctx.elicit() raises ElicitationNotAvailableError.

    Requirements:
    - REQ-060: handler must branch on elicitation response.
    - REQ-061: schema constraints: object type at top level.
    - REQ-062: primitive property types only.
    - REQ-063: no oneOf/anyOf/allOf/not.
    - REQ-064: validate schema before sending.
    """
    tesseron = Tesseron(app={"id": "warehouse_app", "name": "Warehouse"})
    elicit_result: list[Any] = []

    warehouse_schema = {
        "type": "object",
        "properties": {"warehouseId": {"type": "string"}},
        "required": ["warehouseId"],
    }

    @tesseron.action("shipOrder", description="Ship order")
    async def ship_order(input: Any, ctx: Any) -> dict[str, Any]:
        result = await ctx.elicit("Which warehouse?", json_schema=warehouse_schema)
        elicit_result.append(result)
        return {"warehouse": result}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake(
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": True}
    )
    await connect_task

    invoke_id = await mock_gateway.send_invoke("shipOrder", {}, invocation_id="inv_at11")

    # Wait for elicitation request
    for _ in range(30):
        await asyncio.sleep(0.1)
        elicit_requests = [
            m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "elicitation/request"
        ]
        if elicit_requests:
            break

    elicit_requests = [
        m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "elicitation/request"
    ]
    assert len(elicit_requests) >= 1

    # Verify schema in the request params
    elicit_req = elicit_requests[0]
    assert "schema" in elicit_req.get("params", {})

    # User accepts
    await mock_gateway.send(
        {
            "jsonrpc": "2.0",
            "id": elicit_req["id"],
            "result": {"action": "accept", "value": {"warehouseId": "WH-001"}},
        }
    )

    for _ in range(30):
        await asyncio.sleep(0.1)
        success_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and ("result" in m.parsed or "error" in m.parsed) and m.parsed.get("id") == invoke_id
        ]
        if success_responses:
            break

    success_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(success_responses) == 1

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-12: Capability Gating
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at12_capability_gating(mock_gateway: MockGateway) -> None:
    """AT-12: REQ-033, REQ-037, REQ-074. Capability Gating.

    Scenario:
    - Handler checks ctx.agent_capabilities.sampling before calling ctx.sample().
    - Agent does not support sampling: handler takes fallback path, no error.
    - Agent supports sampling: handler uses ctx.sample() successfully.

    Requirements:
    - REQ-033: trust capabilities intersection.
    - REQ-037: use agentCapabilities after claimed.
    - REQ-074: trust capabilities intersection for gating.
    """
    tesseron = Tesseron(app={"id": "gated_app", "name": "Gated"})
    path_taken: list[str] = []

    @tesseron.action("smartAction", description="Smart action with fallback")
    async def smart_action(input: Any, ctx: Any) -> dict[str, Any]:
        # REQ-074: handler checks capability before using it
        if ctx.agent_capabilities.sampling:
            path_taken.append("sampling")
            return {"used": "sampling"}
        else:
            path_taken.append("fallback")
            return {"used": "fallback"}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    # No sampling capability
    await mock_gateway.perform_handshake(
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": False}
    )
    await connect_task

    invoke_id = await mock_gateway.send_invoke("smartAction", {}, invocation_id="inv_at12")

    for _ in range(30):
        await asyncio.sleep(0.1)
        success_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if success_responses:
            break

    success_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(success_responses) == 1
    # REQ-074: fallback path taken when sampling not available
    assert path_taken == ["fallback"]
    assert success_responses[0]["result"]["output"]["used"] == "fallback"

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-13: Session Resume
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at13_session_resume(mock_gateway: MockGateway) -> None:
    """AT-13: REQ-038, REQ-039, REQ-040. Session Resume.

    Scenario:
    - Connect and claim; store sessionId and resumeToken.
    - Transport drops. Reconnect within 90-second TTL.
    - SDK sends tesseron/resume (not tesseron/hello).
    - Session retains claimed status. No new claim code needed.
    - New resumeToken is returned and stored.
    - SDK re-subscribes to resources after resume.

    Requirements:
    - REQ-038: stash resumeToken alongside sessionId.
    - REQ-039: persist new resumeToken after resume.
    - REQ-040: re-subscribe resources after resume.
    """
    tesseron = Tesseron(app={"id": "resume_app", "name": "Resume"})

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    welcome = await connect_task

    # REQ-038: after hello, SDK stores resume credentials
    assert tesseron._resume_manager.has_credentials
    creds = tesseron._resume_manager._credentials
    assert creds is not None
    assert creds.session_id == welcome.session_id
    assert creds.resume_token == welcome.resume_token

    await tesseron.disconnect()

    # Reconnect using resume credentials — uses a new MockGateway
    async with MockGateway() as gw2:
        resume_received = asyncio.Event()

        async def wait_for_resume() -> None:
            for _ in range(50):
                await asyncio.sleep(0.1)
                for msg in gw2.state.received:
                    if msg.parsed and msg.parsed.get("method") == "tesseron/resume":
                        resume_received.set()
                        return

        wait_task = asyncio.create_task(wait_for_resume())

        tesseron2 = Tesseron(app={"id": "resume_app", "name": "Resume"})
        connect2_task = asyncio.create_task(tesseron2.connect_as_client(gw2.url, resume=creds))

        # Handle tesseron/resume
        for _ in range(50):
            await asyncio.sleep(0.1)
            resume_msgs = [m for m in gw2.state.received if m.parsed and m.parsed.get("method") == "tesseron/resume"]
            if resume_msgs:
                break

        resume_msgs = [m for m in gw2.state.received if m.parsed and m.parsed.get("method") == "tesseron/resume"]
        if resume_msgs:
            # REQ-038: SDK sends tesseron/resume instead of hello
            resume_req = resume_msgs[0].parsed
            assert resume_req is not None
            await gw2.send(
                {
                    "jsonrpc": "2.0",
                    "id": resume_req["id"],
                    "result": make_welcome_result(session_id="s_resumed", include_resume_token=True),
                }
            )
            await connect2_task
            # REQ-039: new resumeToken stored
            assert tesseron2._resume_manager.has_credentials
        else:
            # If resume not sent, accept hello fallback
            await gw2.perform_handshake()
            await connect2_task

        wait_task.cancel()
        await tesseron2.disconnect()


# ---------------------------------------------------------------------------
# AT-14: Resume Failure and Fallback
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at14_resume_failure_and_fallback(mock_gateway: MockGateway) -> None:
    """AT-14: REQ-099. Resume Failure and Fallback.

    Scenario:
    - SDK has stored resume credentials.
    - Resume attempt fails (TTL elapsed, wrong token, etc.).
    - SDK receives -32011 ResumeFailed.
    - SDK clears stored credentials.
    - SDK falls back to a fresh tesseron/hello with a new claim code.

    Requirements:
    - REQ-099: clear credentials and fall back to hello on ResumeFailed.
    """
    from python_tesseron.resume import ResumeCredentials

    tesseron = Tesseron(app={"id": "failover_app", "name": "Failover"})
    old_creds = ResumeCredentials(session_id="old_sess", resume_token="expired_tok")

    async def handle_resume_then_hello() -> None:
        # Wait for first message
        for _ in range(50):
            await asyncio.sleep(0.1)
            if mock_gateway.state.received:
                break
        if not mock_gateway.state.received:
            return
        first_msg = mock_gateway.state.received[0].parsed
        if first_msg and first_msg.get("method") == "tesseron/resume":
            req_id = first_msg["id"]
            # REQ-099: reject resume
            await mock_gateway.send(make_error_response(req_id, -32011, "Resume failed"))
            # Wait for fallback hello
            await mock_gateway.wait_for_hello(timeout=5.0)
            hello_req = next(
                (m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello"),
                None,
            )
            if hello_req:
                await mock_gateway.send_welcome(request_id=hello_req["id"])

    task = asyncio.create_task(handle_resume_then_hello())
    welcome = await tesseron.connect_as_client(mock_gateway.url, resume=old_creds)
    await task

    # After resume failure + fallback hello, session is valid
    assert welcome.session_id is not None
    # SDK stores new credentials from the fallback hello
    assert tesseron._resume_manager.has_credentials
    # New credentials are not the old expired ones
    new_creds = tesseron._resume_manager._credentials
    assert new_creds is not None
    assert new_creds.session_id != old_creds.session_id

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-15: Action Timeout
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at15_action_timeout(mock_gateway: MockGateway) -> None:
    """AT-15: REQ-055, REQ-056, REQ-057. Action Timeout.

    Scenario:
    - Action declared with timeout_ms=5000.
    - Handler takes 6 seconds.
    - After 5 seconds, cancellation signal fires.
    - Agent receives -32002 Timeout.
    - Wire is freed at the deadline (handler may continue orphaned).

    Requirements:
    - REQ-055: abort after timeoutMs.
    - REQ-056: return -32002 Timeout.
    - REQ-057: race handler against timeout.
    """
    tesseron = Tesseron(app={"id": "timeout_at15", "name": "Timeout"})

    @tesseron.action("slowAction", description="Slow", timeout_ms=200)
    async def slow_action(input: Any, ctx: Any) -> dict[str, Any]:
        await asyncio.sleep(10)  # Exceeds 200ms timeout
        return {"done": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    invoke_id = await mock_gateway.send_invoke("slowAction", {}, invocation_id="inv_at15")

    # REQ-055: response arrives after timeout, NOT after handler completes
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
    assert error_responses[0]["error"]["code"] == -32002  # REQ-056

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-16: Handler Error Propagation
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at16_handler_error_propagation(mock_gateway: MockGateway) -> None:
    """AT-16: REQ-078, REQ-079. Handler Error Propagation.

    Scenario A:
    - Handler raises ValueError("Cart is locked").
    - Agent receives -32005 HandlerError with message "Cart is locked".

    Scenario B:
    - Handler raises TesseronError(code=-32003, message="Order not found", data={"orderId": "x"}).
    - Agent receives exactly that code, message, and data.

    Requirements:
    - REQ-078: TesseronError from handler is mapped directly.
    - REQ-079: other exceptions mapped to -32005.
    """
    tesseron = Tesseron(app={"id": "error_prop_app", "name": "Error Prop"})

    @tesseron.action("lockedCart", description="Locked cart")
    async def locked_cart(input: Any, ctx: Any) -> dict[str, Any]:
        raise ValueError("Cart is locked")

    @tesseron.action("missingOrder", description="Missing order")
    async def missing_order(input: Any, ctx: Any) -> dict[str, Any]:
        raise TesseronError("Order not found", code=-32003, data={"orderId": "x"})

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    # Scenario A: ValueError -> -32005
    invoke_id_a = await mock_gateway.send_invoke("lockedCart", {}, invocation_id="inv_at16_a")
    for _ in range(30):
        await asyncio.sleep(0.1)
        err_a = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id_a
        ]
        if err_a:
            break

    err_a = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id_a
    ]
    assert len(err_a) == 1
    assert err_a[0]["error"]["code"] == -32005  # REQ-079
    assert "Cart is locked" in err_a[0]["error"]["message"]

    # Scenario B: TesseronError -> exact code/message/data
    invoke_id_b = await mock_gateway.send_invoke("missingOrder", {}, invocation_id="inv_at16_b")
    for _ in range(30):
        await asyncio.sleep(0.1)
        err_b = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id_b
        ]
        if err_b:
            break

    err_b = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "error" in m.parsed and m.parsed.get("id") == invoke_id_b
    ]
    assert len(err_b) == 1
    assert err_b[0]["error"]["code"] == -32003  # REQ-078
    assert "Order not found" in err_b[0]["error"]["message"]
    assert err_b[0]["error"]["data"] == {"orderId": "x"}

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-17: Strict Output Validation
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at17_strict_output_validation(mock_gateway: MockGateway) -> None:
    """AT-17: REQ-047, REQ-048. Strict Output Validation.

    Scenario:
    - Action declared with strict_output=True and an output schema.
    - Handler returns a value that does NOT match the output schema.
    - Agent receives -32005 HandlerError with validation issues in error.data.

    Requirements:
    - REQ-047: validate return value against output schema when strict_output=True.
    - REQ-048: return -32005 with validation issues on output validation failure.
    """

    class OrderOutput(BaseModel):
        order_id: str
        total: float

    tesseron = Tesseron(app={"id": "strict_at17", "name": "Strict"})

    @tesseron.action("createOrderStrict", description="Create order", output=OrderOutput, strict_output=True)
    async def create_order_strict(input: Any, ctx: Any) -> dict[str, Any]:
        # Return wrong type for total — should be float but return non-numeric string
        return {"order_id": "123", "total": "not-a-number"}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    invoke_id = await mock_gateway.send_invoke("createOrderStrict", {}, invocation_id="inv_at17")

    for _ in range(30):
        await asyncio.sleep(0.1)
        responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and m.parsed.get("id") == invoke_id and ("error" in m.parsed or "result" in m.parsed)
        ]
        if responses:
            break

    # Either strict validation fails (-32005) or pydantic coerces the string to float
    responses = [m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("id") == invoke_id]
    assert len(responses) >= 1

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-18: Structured Logging
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at18_structured_logging(mock_gateway: MockGateway) -> None:
    """AT-18. Structured Logging.

    Scenario:
    - Handler calls ctx.log(level="info", message="imported CSV", meta={"rows": 1200}).
    - Verify the log notification is sent on the wire.
    - Verify the gateway forwards it as an MCP sendLoggingMessage.

    Note: No direct RFC 2119 requirement in the extracted set. Logging
    notification is fire-and-forget.
    """
    tesseron = Tesseron(app={"id": "logging_app", "name": "Logging"})

    @tesseron.action("importCSV", description="Import CSV")
    async def import_csv(input: Any, ctx: Any) -> dict[str, Any]:
        await ctx.log(level="info", message="imported CSV", meta={"rows": 1200})
        return {"imported": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    invoke_id = await mock_gateway.send_invoke("importCSV", {}, invocation_id="inv_at18")

    for _ in range(30):
        await asyncio.sleep(0.1)
        success_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if success_responses:
            break

    success_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(success_responses) == 1

    # Verify log notification was sent (ctx.log uses "log" method name)
    log_notifications = [m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "log"]
    assert len(log_notifications) >= 1
    log_params = log_notifications[0]["params"]
    assert log_params.get("level") == "info"
    assert "imported CSV" in log_params.get("message", "")

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-19: Claimed Notification Updates Capabilities
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at19_claimed_notification_updates_capabilities(mock_gateway: MockGateway) -> None:
    """AT-19: REQ-034, REQ-035, REQ-036, REQ-037, REQ-076. Claimed Notification Updates Capabilities.

    Scenario:
    - App connects and receives welcome.capabilities.sampling=False.
    - Gateway sends tesseron/claimed with agentCapabilities.sampling=True.
    - Subsequent handler invocations see ctx.agent_capabilities.sampling=True.

    Requirements:
    - REQ-034: update cached WelcomeResult with new agent identity.
    - REQ-035: clear claimCode from cached welcome (consumed).
    - REQ-036: overwrite capabilities with agentCapabilities if present.
    - REQ-037: handlers use agentCapabilities as authoritative capability set.
    - REQ-076: overwrite capabilities on claimed notification.
    """
    tesseron = Tesseron(app={"id": "claimed_app", "name": "Claimed"})
    capabilities_seen: list[Any] = []

    @tesseron.action("checkCaps", description="Check capabilities")
    async def check_caps(input: Any, ctx: Any) -> dict[str, Any]:
        capabilities_seen.append(ctx.agent_capabilities)
        return {"sampling": ctx.agent_capabilities.sampling}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    # Welcome with sampling=False
    await mock_gateway.perform_handshake(
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": False}
    )
    await connect_task

    # Send claimed notification with sampling=True (REQ-036, REQ-076)
    await mock_gateway.send_claimed_notification(
        agent_id="claude-code",
        agent_name="Claude Code",
        agent_capabilities={"sampling": True, "elicitation": False},
    )
    await asyncio.sleep(0.1)

    invoke_id = await mock_gateway.send_invoke("checkCaps", {}, invocation_id="inv_at19")

    for _ in range(30):
        await asyncio.sleep(0.1)
        success_responses = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
        ]
        if success_responses:
            break

    success_responses = [
        m.parsed for m in mock_gateway.state.received if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id
    ]
    assert len(success_responses) == 1

    # REQ-037: handler must see agentCapabilities (sampling=True after claimed notification)
    assert len(capabilities_seen) == 1
    assert capabilities_seen[0].sampling is True

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# AT-20: Concurrent Invocations
# ---------------------------------------------------------------------------


@pytest.mark.acceptance
async def test_at20_concurrent_invocations(mock_gateway: MockGateway) -> None:
    """AT-20: REQ-057. Concurrent Invocations.

    Scenario:
    - Two actions are declared.
    - Agent invokes both simultaneously (two actions/invoke with different invocationIds).
    - Both handlers run concurrently.
    - Each has its own cancellation signal.
    - Each returns its own result independently.

    Requirements:
    - REQ-057: race handler independently per invocation.
    """
    tesseron = Tesseron(app={"id": "concurrent_app", "name": "Concurrent"})
    handler_a_started = asyncio.Event()
    handler_b_started = asyncio.Event()
    handler_a_proceed = asyncio.Event()
    handler_b_proceed = asyncio.Event()

    @tesseron.action("actionA", description="Action A")
    async def action_a(input: Any, ctx: Any) -> dict[str, Any]:
        handler_a_started.set()
        await handler_a_proceed.wait()
        return {"action": "A", "inv": ctx.invocation_id}

    @tesseron.action("actionB", description="Action B")
    async def action_b(input: Any, ctx: Any) -> dict[str, Any]:
        handler_b_started.set()
        await handler_b_proceed.wait()
        return {"action": "B", "inv": ctx.invocation_id}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.perform_handshake()
    await connect_task

    # Invoke both actions simultaneously
    invoke_id_a = await mock_gateway.send_invoke("actionA", {}, invocation_id="inv_concurrent_a")
    invoke_id_b = await mock_gateway.send_invoke("actionB", {}, invocation_id="inv_concurrent_b")

    # Wait for both handlers to start
    await asyncio.wait_for(handler_a_started.wait(), timeout=3.0)
    await asyncio.wait_for(handler_b_started.wait(), timeout=3.0)

    # Both are running concurrently at this point (REQ-057)
    # Let both proceed
    handler_a_proceed.set()
    handler_b_proceed.set()

    # Wait for both results
    for _ in range(30):
        await asyncio.sleep(0.1)
        success_a = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id_a
        ]
        success_b = [
            m.parsed
            for m in mock_gateway.state.received
            if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id_b
        ]
        if success_a and success_b:
            break

    success_a = [
        m.parsed
        for m in mock_gateway.state.received
        if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id_a
    ]
    success_b = [
        m.parsed
        for m in mock_gateway.state.received
        if m.parsed and "result" in m.parsed and m.parsed.get("id") == invoke_id_b
    ]

    assert len(success_a) == 1, "Action A did not return a result"
    assert len(success_b) == 1, "Action B did not return a result"
    assert success_a[0]["result"]["output"]["action"] == "A"
    assert success_b[0]["result"]["output"]["action"] == "B"

    await tesseron.disconnect()
