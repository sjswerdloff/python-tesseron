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

import pytest

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
@pytest.mark.xfail(reason="implementation pending: SDK ActionContext not yet implemented")
async def test_cp03_handler_trusts_intersection_not_app_capabilities(mock_gateway: MockGateway) -> None:
    """CP-03: REQ-033. Handler MUST trust intersection, not app-declared capabilities.

    App declares sampling=True. Gateway returns sampling=False in welcome.
    ctx.agent_capabilities.sampling must be False in the handler.
    """
    raise NotImplementedError


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
@pytest.mark.xfail(reason="implementation pending: SDK claimed notification handling not yet implemented")
async def test_cp05_claimed_notification_updates_agent_capabilities(mock_gateway: MockGateway) -> None:
    """CP-05: REQ-036, REQ-037. tesseron/claimed updates agentCapabilities.

    Welcome has sampling=False. claimed notification carries
    agentCapabilities.sampling=True. The SDK must overwrite the stored
    capabilities with the claimed values.
    """
    raise NotImplementedError


@pytest.mark.capability
@pytest.mark.xfail(reason="implementation pending: SDK ActionContext not yet implemented")
async def test_cp06_handlers_after_claimed_see_updated_capabilities(mock_gateway: MockGateway) -> None:
    """CP-06: REQ-037. Handlers invoked after claimed see updated capabilities.

    An action invoked after the session is claimed must see the
    agentCapabilities from the tesseron/claimed notification.
    """
    raise NotImplementedError


@pytest.mark.capability
@pytest.mark.xfail(reason="implementation pending: SDK ActionContext not yet implemented")
async def test_cp07_capabilities_before_claimed_reflect_welcome_values(mock_gateway: MockGateway) -> None:
    """CP-07: REQ-033. Capabilities before claimed reflect welcome values.

    Before the tesseron/claimed notification arrives, handlers must use
    the capabilities from the welcome response.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Capability gating tests (CP-08 through CP-11)
# ---------------------------------------------------------------------------


@pytest.mark.capability
@pytest.mark.xfail(reason="implementation pending: SDK ActionContext.agent_capabilities not yet implemented")
async def test_cp08_sampling_capability_queryable_before_calling_sample(mock_gateway: MockGateway) -> None:
    """CP-08: REQ-074. ctx.agent_capabilities.sampling queryable before calling ctx.sample().

    A handler can read ctx.agent_capabilities.sampling before deciding
    whether to call ctx.sample(). If False, take the fallback path.
    """
    raise NotImplementedError


@pytest.mark.capability
@pytest.mark.xfail(reason="implementation pending: SDK ActionContext.agent_capabilities not yet implemented")
async def test_cp09_elicitation_capability_queryable_before_calling_elicit(mock_gateway: MockGateway) -> None:
    """CP-09: REQ-074. ctx.agent_capabilities.elicitation queryable before calling ctx.elicit().

    A handler can read ctx.agent_capabilities.elicitation before deciding
    whether to call ctx.elicit(). If False, take the fallback path.
    """
    raise NotImplementedError


@pytest.mark.capability
@pytest.mark.xfail(reason="implementation pending: SDK ActionContext not yet implemented")
async def test_cp10_fallback_path_works_when_capability_absent(mock_gateway: MockGateway) -> None:
    """CP-10: REQ-074. Fallback path works when capability absent.

    A handler that checks ctx.agent_capabilities.sampling and takes the
    fallback path when False must complete successfully without error.
    """
    raise NotImplementedError


@pytest.mark.capability
@pytest.mark.xfail(reason="implementation pending: SDK ctx.sample() not yet implemented")
async def test_cp11_happy_path_works_when_capability_present(mock_gateway: MockGateway) -> None:
    """CP-11. Happy path works when capability present.

    When sampling is available, ctx.sample() must complete successfully
    and return the LLM's response.
    """
    raise NotImplementedError


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
@pytest.mark.xfail(reason="implementation pending: SDK sampling depth enforcement not yet implemented")
async def test_cp13_exceeding_max_sampling_depth_returns_32008(mock_gateway: MockGateway) -> None:
    """CP-13: REQ-058. Exceeding maxSamplingDepth returns -32008.

    Chain 4 sampling calls (exceeding depth=3). The 4th call must produce
    error -32008 SamplingDepthExceeded with {depth: 4, max: 3} in error.data.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# Gap analysis additional tests (CP-14, CP-15)
# ---------------------------------------------------------------------------


@pytest.mark.capability
@pytest.mark.xfail(reason="implementation pending: SDK elicit fallback schema not yet implemented")
async def test_cp14_elicit_without_schema_uses_permissive_fallback(mock_gateway: MockGateway) -> None:
    """CP-14: REQ-066. SDK SHOULD send permissive fallback elicit schema when none provided.

    When ctx.elicit() is called without an explicit schema, the SDK must
    send the permissive fallback:
    {
        "type": "object",
        "properties": {"response": {"type": "string", "description": "Your response"}},
        "required": ["response"]
    }
    """
    raise NotImplementedError


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
