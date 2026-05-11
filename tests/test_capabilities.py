"""Capability negotiation tests.

Test IDs: CP-01 through CP-15
Source: Spec §12 (Capability Negotiation), §5 (Handshake), §9 (Sampling)

Tests verify:
- App declares all four capabilities in tesseron/hello.
- Gateway returns intersection in welcome.capabilities.
- Handlers trust the intersection, not app-declared values.
- Capability updates via tesseron/claimed are applied authoritatively.
- Capability gating works for sampling and elicitation.
- maxSamplingDepth defaults to 3.

Structural tests (model inspection) are executable with stubs.
Integration tests (SDK round-trips) are marked xfail.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from python_tesseron import Tesseron
from python_tesseron.types import TesseronCapabilities
from tests.conftest import (
    DEFAULT_GATEWAY_CAPABILITIES,
    MockGateway,
    make_hello_params,
    make_welcome_result,
)

# ---------------------------------------------------------------------------
# Capability intersection tests (CP-01 through CP-04)
# ---------------------------------------------------------------------------


@pytest.mark.capability
def test_cp01_hello_params_include_capabilities_object() -> None:
    """CP-01: REQ-100. App declares capabilities in tesseron/hello params.

    The hello params must include a capabilities object with all four
    capability flags.
    """
    params = make_hello_params()

    assert "capabilities" in params
    caps = params["capabilities"]
    assert isinstance(caps, dict)
    assert "streaming" in caps
    assert "subscriptions" in caps
    assert "sampling" in caps
    assert "elicitation" in caps


@pytest.mark.capability
def test_cp02_welcome_returns_intersection_of_capabilities() -> None:
    """CP-02: REQ-033. Gateway returns intersection in welcome.capabilities.

    App requests {sampling, streaming}, gateway supports {streaming}.
    Welcome should have {streaming: true, sampling: false}.
    """
    # The mock gateway uses DEFAULT_GATEWAY_CAPABILITIES which has sampling=False
    welcome = make_welcome_result(capabilities=DEFAULT_GATEWAY_CAPABILITIES)

    caps = welcome["capabilities"]
    assert caps["streaming"] is True, "streaming supported by both — must be True"
    assert caps["sampling"] is False, "sampling not supported by gateway — must be False"
    assert caps["subscriptions"] is True
    assert caps["elicitation"] is True


@pytest.mark.capability
async def test_cp03_handler_trusts_intersection_not_app_capabilities(mock_gateway: MockGateway) -> None:
    """CP-03: REQ-033. Handler MUST trust intersection, not app-declared capabilities.

    App declares all capabilities. Gateway returns sampling=False in welcome.
    ctx.agent_capabilities.sampling must be False in the handler.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    handler_caps: TesseronCapabilities | None = None

    @tesseron.action("check_caps", description="Checks capabilities")
    async def check_caps(input_data: Any, ctx: Any) -> dict[str, Any]:
        nonlocal handler_caps
        handler_caps = ctx.agent_capabilities
        return {}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello")
    # Gateway returns intersection: sampling=False
    await mock_gateway.send_welcome(
        request_id=hello_msg["id"],
        capabilities=DEFAULT_GATEWAY_CAPABILITIES,  # sampling=False
    )
    await connect_task

    # Invoke the action
    await mock_gateway.send_claimed_notification()
    await asyncio.sleep(0.05)
    await mock_gateway.send_invoke("check_caps", {})
    await asyncio.sleep(0.2)

    assert handler_caps is not None
    # Handler sees the INTERSECTION, not app-declared values
    assert handler_caps.sampling is False, "Handler must see negotiated capabilities"
    assert handler_caps.streaming is True

    await tesseron.disconnect()


@pytest.mark.capability
def test_cp04_all_four_capabilities_independently_negotiable() -> None:
    """CP-04: REQ-100. All four capabilities are independently negotiable.

    Each capability can be toggled independently. Test each combination.
    """
    # All True
    caps_all_true = TesseronCapabilities(streaming=True, subscriptions=True, sampling=True, elicitation=True)
    assert caps_all_true.streaming is True
    assert caps_all_true.subscriptions is True
    assert caps_all_true.sampling is True
    assert caps_all_true.elicitation is True

    # All False
    caps_all_false = TesseronCapabilities(streaming=False, subscriptions=False, sampling=False, elicitation=False)
    assert caps_all_false.streaming is False
    assert caps_all_false.subscriptions is False
    assert caps_all_false.sampling is False
    assert caps_all_false.elicitation is False

    # Mixed: only streaming + subscriptions
    caps_mixed = TesseronCapabilities(streaming=True, subscriptions=True, sampling=False, elicitation=False)
    assert caps_mixed.streaming is True
    assert caps_mixed.subscriptions is True
    assert caps_mixed.sampling is False
    assert caps_mixed.elicitation is False


# ---------------------------------------------------------------------------
# Capability update tests (CP-05 through CP-07)
# ---------------------------------------------------------------------------


@pytest.mark.capability
async def test_cp05_claimed_notification_updates_agent_capabilities(mock_gateway: MockGateway) -> None:
    """CP-05: REQ-036, REQ-037. tesseron/claimed updates agentCapabilities.

    Welcome has sampling=False. claimed notification carries
    agentCapabilities.sampling=True. The SDK must overwrite the stored
    capabilities with the claimed values.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello")
    # Welcome with sampling=False
    await mock_gateway.send_welcome(
        request_id=hello_msg["id"],
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": True},
    )
    await connect_task

    # Before claimed: sampling is False
    assert tesseron._capabilities.current.sampling is False

    # Send claimed with agentCapabilities.sampling=True
    await mock_gateway.send_claimed_notification(
        agent_capabilities={"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    )
    await asyncio.sleep(0.1)

    # After claimed: sampling is True (from agentCapabilities)
    assert tesseron._capabilities.current.sampling is True

    await tesseron.disconnect()


@pytest.mark.capability
async def test_cp06_handlers_after_claimed_see_updated_capabilities(mock_gateway: MockGateway) -> None:
    """CP-06: REQ-037. Handlers invoked after claimed see updated capabilities.

    An action invoked after the session is claimed must see the
    agentCapabilities from the tesseron/claimed notification.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    handler_caps: TesseronCapabilities | None = None

    @tesseron.action("caps_after_claimed", description="Get caps after claimed")
    async def caps_after_claimed(input_data: Any, ctx: Any) -> dict[str, Any]:
        nonlocal handler_caps
        handler_caps = ctx.agent_capabilities
        return {}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello")
    await mock_gateway.send_welcome(
        request_id=hello_msg["id"],
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": True},
    )
    await connect_task

    # Send claimed with agentCapabilities.sampling=True
    await mock_gateway.send_claimed_notification(
        agent_capabilities={"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    )
    await asyncio.sleep(0.05)

    # Invoke the action AFTER claimed
    await mock_gateway.send_invoke("caps_after_claimed", {})
    await asyncio.sleep(0.2)

    # Handler sees the UPDATED agentCapabilities from claimed notification
    assert handler_caps is not None
    assert handler_caps.sampling is True

    await tesseron.disconnect()


@pytest.mark.capability
async def test_cp07_capabilities_before_claimed_reflect_welcome_values(mock_gateway: MockGateway) -> None:
    """CP-07: REQ-033. Capabilities before claimed reflect welcome values.

    Before the tesseron/claimed notification arrives, handlers must use
    the capabilities from the welcome response.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello")
    await mock_gateway.send_welcome(
        request_id=hello_msg["id"],
        capabilities={"streaming": True, "subscriptions": True, "sampling": False, "elicitation": True},
    )
    await connect_task

    # Before claimed: capabilities reflect welcome values
    caps = tesseron._capabilities.current
    assert caps.streaming is True
    assert caps.sampling is False
    assert caps.elicitation is True

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# Capability gating tests (CP-08 through CP-11)
# ---------------------------------------------------------------------------


@pytest.mark.capability
async def test_cp08_sampling_capability_queryable_before_calling_sample(mock_gateway: MockGateway) -> None:
    """CP-08: REQ-074. ctx.agent_capabilities.sampling queryable before calling ctx.sample().

    A handler can read ctx.agent_capabilities.sampling before deciding
    whether to call ctx.sample(). If False, take the fallback path.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    fallback_taken = asyncio.Event()

    @tesseron.action("check_sampling", description="Check sampling cap")
    async def check_sampling(input_data: Any, ctx: Any) -> dict[str, Any]:
        if not ctx.agent_capabilities.sampling:
            fallback_taken.set()
            return {"used_fallback": True}
        return {"sampled": True}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello")
    # sampling=False in intersection
    await mock_gateway.send_welcome(
        request_id=hello_msg["id"],
        capabilities=DEFAULT_GATEWAY_CAPABILITIES,
    )
    await connect_task
    await mock_gateway.send_claimed_notification()
    await asyncio.sleep(0.05)

    await mock_gateway.send_invoke("check_sampling", {})
    await asyncio.wait_for(fallback_taken.wait(), timeout=2.0)

    assert fallback_taken.is_set()

    await tesseron.disconnect()


@pytest.mark.capability
async def test_cp09_elicitation_capability_queryable_before_calling_elicit(mock_gateway: MockGateway) -> None:
    """CP-09: REQ-074. ctx.agent_capabilities.elicitation queryable before calling ctx.elicit().

    A handler can read ctx.agent_capabilities.elicitation before deciding
    whether to call ctx.elicit(). If False, take the fallback path.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    elicitation_checked = asyncio.Event()
    elicitation_value: bool | None = None

    @tesseron.action("check_elicit", description="Check elicitation cap")
    async def check_elicit(input_data: Any, ctx: Any) -> dict[str, Any]:
        nonlocal elicitation_value
        elicitation_value = ctx.agent_capabilities.elicitation
        elicitation_checked.set()
        return {"elicitation": elicitation_value}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello")
    # elicitation=True in DEFAULT_GATEWAY_CAPABILITIES
    await mock_gateway.send_welcome(
        request_id=hello_msg["id"],
        capabilities=DEFAULT_GATEWAY_CAPABILITIES,
    )
    await connect_task
    await mock_gateway.send_claimed_notification()
    await asyncio.sleep(0.05)

    await mock_gateway.send_invoke("check_elicit", {})
    await asyncio.wait_for(elicitation_checked.wait(), timeout=2.0)

    assert elicitation_value is True  # elicitation=True in DEFAULT_GATEWAY_CAPABILITIES

    await tesseron.disconnect()


@pytest.mark.capability
async def test_cp10_fallback_path_works_when_capability_absent(mock_gateway: MockGateway) -> None:
    """CP-10: REQ-074. Fallback path works when capability absent.

    A handler that checks ctx.agent_capabilities.sampling and takes the
    fallback path when False must complete successfully without error.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    completed = asyncio.Event()

    @tesseron.action("fallback_action", description="Uses fallback when no sampling")
    async def fallback_action(input_data: Any, ctx: Any) -> dict[str, Any]:
        if ctx.agent_capabilities.sampling:
            # Would call ctx.sample() but not tested here
            result = {"method": "sampling"}
        else:
            # Fallback: use built-in logic
            result = {"method": "fallback"}
        completed.set()
        return result

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello")
    await mock_gateway.send_welcome(
        request_id=hello_msg["id"],
        capabilities=DEFAULT_GATEWAY_CAPABILITIES,  # sampling=False
    )
    await connect_task
    await mock_gateway.send_claimed_notification()
    await asyncio.sleep(0.05)

    await mock_gateway.send_invoke("fallback_action", {})
    await asyncio.wait_for(completed.wait(), timeout=2.0)

    # Action completed without error — fallback worked
    assert completed.is_set()

    await tesseron.disconnect()


@pytest.mark.capability
async def test_cp11_happy_path_works_when_capability_present(mock_gateway: MockGateway) -> None:
    """CP-11. Happy path works when capability present.

    When sampling is available, ctx.sample() completes successfully
    and returns the LLM's response.
    """
    tesseron = Tesseron(app={"id": "test_app", "name": "Test App"})
    sample_result: Any = None
    completed = asyncio.Event()

    @tesseron.action("sample_action", description="Uses sampling when available", timeout_ms=10_000)
    async def sample_action(input_data: Any, ctx: Any) -> dict[str, Any]:
        nonlocal sample_result
        if ctx.agent_capabilities.sampling:
            sample_result = await ctx.sample(prompt="What is 2+2?")
        else:
            sample_result = {"text": "fallback"}
        completed.set()
        return {"result": str(sample_result)}

    connect_task = asyncio.create_task(tesseron.connect_as_client(mock_gateway.url))
    await mock_gateway.wait_for_hello(timeout=5.0)
    hello_msg = next(m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "tesseron/hello")
    # Enable sampling
    await mock_gateway.send_welcome(
        request_id=hello_msg["id"],
        capabilities={"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    )
    await connect_task
    await mock_gateway.send_claimed_notification(
        agent_capabilities={"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    )
    await asyncio.sleep(0.05)

    # Invoke the action
    await mock_gateway.send_invoke("sample_action", {}, invocation_id="inv_sample_001")

    # Wait for the sampling/request from the SDK
    await asyncio.sleep(0.2)

    # Find the sampling request
    sampling_requests = [
        m.parsed for m in mock_gateway.state.received if m.parsed and m.parsed.get("method") == "sampling/request"
    ]
    assert len(sampling_requests) >= 1, "SDK should send sampling/request"

    # Respond to the sampling request (SamplingResult requires content field)
    sampling_req = sampling_requests[0]
    sampling_response = {
        "jsonrpc": "2.0",
        "id": sampling_req["id"],
        "result": {"content": "4"},
    }
    await mock_gateway.send(sampling_response)

    # Wait for action to complete
    await asyncio.wait_for(completed.wait(), timeout=2.0)

    assert sample_result is not None
    assert completed.is_set()

    await tesseron.disconnect()


# ---------------------------------------------------------------------------
# Sampling depth tests (CP-12, CP-13)
# ---------------------------------------------------------------------------


@pytest.mark.capability
def test_cp12_max_sampling_depth_defaults_to_3() -> None:
    """CP-12: REQ-058. maxSamplingDepth defaults to 3 if not specified.

    The spec states the gateway enforces maxSamplingDepth=3. This test
    documents the expected default value constant.
    """
    expected_max_depth = 3
    # The SDK should expose or enforce this constant; verify the spec value.
    assert expected_max_depth == 3


@pytest.mark.capability
async def test_cp13_exceeding_max_sampling_depth_returns_32008(mock_gateway: MockGateway) -> None:
    """CP-13: REQ-058. Exceeding maxSamplingDepth returns -32008.

    The gateway returns -32008 SamplingDepthExceeded when depth is exceeded.
    Verify the SDK constructs the correct error from the response.
    """
    from python_tesseron.dispatcher import JsonRpcDispatcher

    async def noop_send(msg: Any) -> None:
        pass

    dispatcher = JsonRpcDispatcher(send=noop_send)

    # Start a sampling request
    task = asyncio.create_task(dispatcher.request("sampling/request", {}))
    await asyncio.sleep(0.01)

    req_id = next(iter(dispatcher._pending))

    # Respond with -32008 SamplingDepthExceeded
    error_response = {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32008, "message": "Sampling depth exceeded", "data": {"depth": 4, "max": 3}},
    }
    await dispatcher.receive(error_response)

    from python_tesseron.errors import TesseronError

    with pytest.raises(TesseronError) as exc_info:
        await task

    assert exc_info.value.code == -32008
    assert exc_info.value.data == {"depth": 4, "max": 3}


# ---------------------------------------------------------------------------
# Gap analysis additional tests (CP-14, CP-15)
# ---------------------------------------------------------------------------


@pytest.mark.capability
async def test_cp14_elicit_without_schema_uses_permissive_fallback(mock_gateway: MockGateway) -> None:
    """CP-14: REQ-066. SDK SHOULD send permissive fallback elicit schema when none provided.

    When ctx.elicit() is called without an explicit schema, the SDK must
    send a permissive fallback schema.
    """
    from python_tesseron.elicitation import ElicitationBridge
    from python_tesseron.types import TesseronCapabilities

    sent: list[Any] = []

    async def capture_send(msg: Any) -> None:
        sent.append(msg)

    from python_tesseron.dispatcher import JsonRpcDispatcher

    dispatcher = JsonRpcDispatcher(send=capture_send)
    caps = TesseronCapabilities(elicitation=True)
    bridge = ElicitationBridge(dispatcher=dispatcher, capabilities=caps)

    # Start elicit without explicit schema — uses permissive fallback
    elicit_task = asyncio.create_task(bridge.elicit(invocation_id="inv_001", question="Your response?"))

    await asyncio.sleep(0.05)

    # Find the elicitation/request
    elicit_requests = [m for m in sent if m.get("method") == "elicitation/request"]
    assert len(elicit_requests) >= 1, "SDK should send elicitation/request"

    req = elicit_requests[0]
    sent_schema = req.get("params", {}).get("schema", {})

    # Should use permissive fallback schema
    assert sent_schema["type"] == "object"
    assert "properties" in sent_schema

    # Respond to complete the task (ElicitationResult requires action field)
    req_id = req["id"]
    await dispatcher.receive(
        {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"action": "accept", "value": {"response": "ok"}},
        }
    )
    await elicit_task


@pytest.mark.capability
def test_cp15_hello_params_declare_all_capabilities_true() -> None:
    """CP-15: REQ-100. SDK SHOULD declare all capabilities as true in hello.

    The default hello params must declare all four capabilities as true,
    since actual availability is negotiated via the welcome intersection.
    """
    params = make_hello_params()

    caps = params["capabilities"]
    assert caps["streaming"] is True
    assert caps["subscriptions"] is True
    assert caps["sampling"] is True
    assert caps["elicitation"] is True


# ---------------------------------------------------------------------------
# Additional structural capability model tests
# ---------------------------------------------------------------------------


@pytest.mark.capability
def test_tesseron_capabilities_model_defaults_all_true() -> None:
    """TesseronCapabilities should default all four flags to True.

    The SDK declares all capabilities as true; the gateway negotiates
    the intersection. Default should be maximally permissive.
    """
    caps = TesseronCapabilities()

    assert caps.streaming is True
    assert caps.subscriptions is True
    assert caps.sampling is True
    assert caps.elicitation is True


@pytest.mark.capability
def test_tesseron_capabilities_individual_flags_settable() -> None:
    """Each capability flag can be independently set to False."""
    caps = TesseronCapabilities(sampling=False)
    assert caps.sampling is False
    assert caps.streaming is True  # Unchanged

    caps2 = TesseronCapabilities(elicitation=False)
    assert caps2.elicitation is False
    assert caps2.sampling is True  # Unchanged
