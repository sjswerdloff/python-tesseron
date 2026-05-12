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

import pytest

# ---------------------------------------------------------------------------
# GW-61: sampling/request translated to MCP sampling/createMessage (REQ-125)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw61_sampling_translation() -> None:
    """GW-61: sampling/request translated to MCP sampling/createMessage.

    Verifies: DC-022 — gateway translates Tesseron sampling/request to MCP
    sampling/createMessage with translated params.
    REQ-125
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-62: LLM response returned to app (REQ-125)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw62_sampling_response() -> None:
    """GW-62: LLM response returned to app after MCP sampling.

    Verifies: DC-022 — gateway returns MCP sampling response back to the app
    that originated the sampling/request.
    REQ-125
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-63: Sampling depth 1 succeeds (REQ-126 — BVA lower bound)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw63_depth_1_succeeds() -> None:
    """GW-63: Single sampling request (depth 1) succeeds.

    Verifies: DC-022 — sampling at depth 1 is below maxSamplingDepth=3 and
    completes successfully.
    REQ-126
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-64: Sampling depth 3 succeeds at boundary (REQ-126 — BVA at boundary)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw64_depth_3_boundary() -> None:
    """GW-64: Sampling at max depth (depth=3) succeeds at boundary.

    Verifies: DC-022 — sampling at exactly maxSamplingDepth=3 is permitted
    (on-boundary value succeeds).
    REQ-126
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-65: Sampling depth 4 fails at boundary+1 (REQ-126 — BVA past boundary)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw65_depth_4_fails() -> None:
    """GW-65: Sampling exceeding max depth (depth=4) returns -32008.

    Verifies: DC-022 — sampling at depth 4 when maxSamplingDepth=3 is
    rejected with error code -32008 (boundary+1 value fails).
    REQ-126
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-66: Depth-exceeded error includes data field (REQ-126)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw66_depth_exceeded_error_data() -> None:
    """GW-66: Depth-exceeded error response includes {depth, max} in data.

    Verifies: DC-022 — when sampling is rejected for exceeding maxSamplingDepth,
    the JSON-RPC error response data field contains {depth: 4, max: 3}.
    REQ-126
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-67: SamplingNotAvailableError when agent lacks capability
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw67_sampling_not_available() -> None:
    """GW-67: SamplingNotAvailableError (-32006) when agent lacks sampling capability.

    Verifies: DC-022 — if the negotiated capability intersection does not
    include sampling, an app sampling/request is rejected with -32006.
    REQ-125
    """
    pytest.fail("Not implemented")
