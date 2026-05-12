"""Gateway elicitation bridge tests.

Test IDs: GW-68 through GW-73
Source: Gateway Requirements REQ-127
Design Contract: DC-023 GatewayElicitationBridge

Tests verify:
- Tesseron elicitation/request is translated to MCP elicitInput (REQ-127).
- All three action result types from EP {accept, decline, cancel} are returned
  correctly to the app (REQ-127).
- ElicitationNotAvailableError (-32007) when agent lacks elicitation capability.
- InvalidParamsError (-32602) on schema constraint violations.

All tests are marked xfail until GatewayElicitationBridge is implemented.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# GW-68: elicitation/request translated to MCP elicitInput (REQ-127)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw68_elicitation_translation() -> None:
    """GW-68: elicitation/request translated to MCP elicitInput.

    Verifies: DC-023 — gateway translates Tesseron elicitation/request to MCP
    elicitInput, forwarding the question and schema parameters.
    REQ-127
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-69: Accept with value returned to app (REQ-127 — EP: accept)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw69_accept_with_value() -> None:
    """GW-69: Accept result with value returned to app.

    Verifies: DC-023 — when the user accepts an elicitation and provides a
    value, the app receives ElicitationResult with action=accept and the value.
    REQ-127
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-70: Decline returned to app (REQ-127 — EP: decline)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw70_decline() -> None:
    """GW-70: Decline result returned to app.

    Verifies: DC-023 — when the user declines an elicitation, the app receives
    ElicitationResult with action=decline.
    REQ-127
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-71: Cancel returned to app (REQ-127 — EP: cancel)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw71_cancel() -> None:
    """GW-71: Cancel result returned to app.

    Verifies: DC-023 — when the user cancels an elicitation, the app receives
    ElicitationResult with action=cancel.
    REQ-127
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-72: ElicitationNotAvailableError when agent lacks capability
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw72_elicitation_not_available() -> None:
    """GW-72: ElicitationNotAvailableError (-32007) when agent lacks elicitation capability.

    Verifies: DC-023 — if the negotiated capability intersection does not
    include elicitation, an app elicitation/request is rejected with -32007.
    REQ-127
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# GW-73: InvalidParamsError on schema constraint violations (REQ-127)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw73_invalid_schema() -> None:
    """GW-73: InvalidParamsError (-32602) on elicitation schema constraint violations.

    Verifies: DC-023 — an elicitation/request carrying an invalid schema
    (e.g., non-object root type or forbidden combinators) is rejected with
    -32602 InvalidParams before forwarding to the agent.
    REQ-127
    """
    pytest.fail("Not implemented")
