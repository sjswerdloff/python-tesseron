"""Gateway sampling bridge tests.

Test IDs: GW-61 through GW-67
Source: Gateway Requirements REQ-125, REQ-126
Design Contract: DC-022 GatewaySamplingBridge

Tests verify:
- Tesseron sampling/request is translated to MCP sampling/createMessage (REQ-125).
- LLM responses are returned to the app (REQ-125).
- Depth tracking with BVA at maxSamplingDepth=3: depths 1, 3 (boundary), 4 (boundary+1) (REQ-126).
- Depth-exceeded error includes {depth, max} in the data field (REQ-126).
- SamplingNotAvailableError (-32006) when agent lacks the sampling capability.

All tests are marked xfail until GatewaySamplingBridge is implemented.
"""

from __future__ import annotations

from typing import Any

import pytest

from python_tesseron.errors import SamplingDepthExceededError, SamplingNotAvailableError
from python_tesseron.gateway.sampling_bridge import (
    MAX_SAMPLING_DEPTH,
    GatewaySamplingBridge,
)
from python_tesseron.types import TesseronCapabilities


def _make_session(sampling_enabled: bool = True) -> Any:
    """Create a minimal mock session for sampling tests."""

    class MockSession:
        negotiated_capabilities = TesseronCapabilities(
            streaming=True,
            subscriptions=True,
            sampling=sampling_enabled,
            elicitation=True,
        )

    return MockSession()


def _make_sampling_params(
    invocation_id: str = "inv_001",
    prompt: str = "Say hello",
    schema: dict[str, Any] | None = None,
    max_tokens: int | None = None,
) -> dict[str, Any]:
    """Build sampling/request params dict."""
    params: dict[str, Any] = {
        "invocationId": invocation_id,
        "prompt": prompt,
    }
    if schema is not None:
        params["schema"] = schema
    if max_tokens is not None:
        params["maxTokens"] = max_tokens
    return params


# ---------------------------------------------------------------------------
# GW-61: sampling/request translated to MCP sampling/createMessage (REQ-125)
# ---------------------------------------------------------------------------


async def test_gw61_sampling_translation() -> None:
    """GW-61: sampling/request translated to MCP sampling/createMessage.

    Verifies: DC-022 — gateway translates Tesseron sampling/request to MCP
    sampling/createMessage with translated params.
    REQ-125
    """
    mcp_calls: list[dict[str, Any]] = []

    async def mock_mcp_client(sampling_params: dict[str, Any]) -> dict[str, Any]:
        mcp_calls.append(sampling_params)
        return {"content": "Hello from LLM"}

    bridge = GatewaySamplingBridge(mcp_client=mock_mcp_client)
    session = _make_session(sampling_enabled=True)

    await bridge.handle_sampling_request(session, _make_sampling_params())

    assert len(mcp_calls) == 1
    # Verify messages were constructed for MCP
    assert "messages" in mcp_calls[0]


# ---------------------------------------------------------------------------
# GW-62: LLM response returned to app (REQ-125)
# ---------------------------------------------------------------------------


async def test_gw62_sampling_response() -> None:
    """GW-62: LLM response returned to app after MCP sampling.

    Verifies: DC-022 — gateway returns MCP sampling response back to the app
    that originated the sampling/request.
    REQ-125
    """

    async def mock_mcp_client(sampling_params: dict[str, Any]) -> dict[str, Any]:
        return {"content": "Hello world"}

    bridge = GatewaySamplingBridge(mcp_client=mock_mcp_client)
    session = _make_session(sampling_enabled=True)

    result = await bridge.handle_sampling_request(session, _make_sampling_params())

    assert "content" in result
    assert result["content"] == "Hello world"


# ---------------------------------------------------------------------------
# GW-63: Sampling depth 1 succeeds (REQ-126 — BVA lower bound)
# ---------------------------------------------------------------------------


async def test_gw63_depth_1_succeeds() -> None:
    """GW-63: Single sampling request (depth 1) succeeds.

    Verifies: DC-022 — sampling at depth 1 is below maxSamplingDepth=3 and
    completes successfully.
    REQ-126
    """

    async def mock_mcp_client(sampling_params: dict[str, Any]) -> dict[str, Any]:
        return {"content": "depth 1 response"}

    bridge = GatewaySamplingBridge(mcp_client=mock_mcp_client)
    session = _make_session(sampling_enabled=True)

    result = await bridge.handle_sampling_request(session, _make_sampling_params())

    assert result["content"] == "depth 1 response"


# ---------------------------------------------------------------------------
# GW-64: Sampling depth 3 succeeds at boundary (REQ-126 — BVA at boundary)
# ---------------------------------------------------------------------------


async def test_gw64_depth_3_boundary() -> None:
    """GW-64: Sampling at max depth (depth=3) succeeds at boundary.

    Verifies: DC-022 — sampling at exactly maxSamplingDepth=3 is permitted
    (on-boundary value succeeds).
    REQ-126
    """
    call_count = 0

    async def mock_mcp_client(sampling_params: dict[str, Any]) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        return {"content": f"response {call_count}"}

    bridge = GatewaySamplingBridge(mcp_client=mock_mcp_client)
    session = _make_session(sampling_enabled=True)

    inv_id = "inv_depth_test"
    # Manually set depth to 2 so the next call brings it to 3 (boundary)
    bridge._depth_map[inv_id] = 2

    result = await bridge.handle_sampling_request(session, _make_sampling_params(invocation_id=inv_id))

    assert "content" in result
    assert MAX_SAMPLING_DEPTH == 3


# ---------------------------------------------------------------------------
# GW-65: Sampling depth 4 fails at boundary+1 (REQ-126 — BVA past boundary)
# ---------------------------------------------------------------------------


async def test_gw65_depth_4_fails() -> None:
    """GW-65: Sampling exceeding max depth (depth=4) returns -32008.

    Verifies: DC-022 — sampling at depth 4 when maxSamplingDepth=3 is
    rejected with error code -32008 (boundary+1 value fails).
    REQ-126
    """
    bridge = GatewaySamplingBridge()
    session = _make_session(sampling_enabled=True)

    inv_id = "inv_depth_test"
    # Set depth to 3 so next call brings it to 4 (past boundary)
    bridge._depth_map[inv_id] = 3

    with pytest.raises(SamplingDepthExceededError) as exc_info:
        await bridge.handle_sampling_request(session, _make_sampling_params(invocation_id=inv_id))

    assert exc_info.value.code == -32008


# ---------------------------------------------------------------------------
# GW-66: Depth-exceeded error includes data field (REQ-126)
# ---------------------------------------------------------------------------


async def test_gw66_depth_exceeded_error_data() -> None:
    """GW-66: Depth-exceeded error response includes {depth, max} in data.

    Verifies: DC-022 — when sampling is rejected for exceeding maxSamplingDepth,
    the JSON-RPC error response data field contains {depth: 4, max: 3}.
    REQ-126
    """
    bridge = GatewaySamplingBridge()
    session = _make_session(sampling_enabled=True)

    inv_id = "inv_depth_test"
    bridge._depth_map[inv_id] = 3  # Will become 4 on next call

    with pytest.raises(SamplingDepthExceededError) as exc_info:
        await bridge.handle_sampling_request(session, _make_sampling_params(invocation_id=inv_id))

    err = exc_info.value
    assert err.data is not None
    assert err.data["depth"] == 4
    assert err.data["max"] == 3


# ---------------------------------------------------------------------------
# GW-67: SamplingNotAvailableError when agent lacks capability
# ---------------------------------------------------------------------------


async def test_gw67_sampling_not_available() -> None:
    """GW-67: SamplingNotAvailableError (-32006) when agent lacks sampling capability.

    Verifies: DC-022 — if the negotiated capability intersection does not
    include sampling, an app sampling/request is rejected with -32006.
    REQ-125
    """
    bridge = GatewaySamplingBridge()
    session = _make_session(sampling_enabled=False)

    with pytest.raises(SamplingNotAvailableError) as exc_info:
        await bridge.handle_sampling_request(session, _make_sampling_params())

    assert exc_info.value.code == -32006
