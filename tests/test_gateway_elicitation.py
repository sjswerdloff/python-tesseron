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

from typing import Any

import pytest

from python_tesseron.errors import ElicitationNotAvailableError, InvalidParamsError
from python_tesseron.gateway.elicitation_bridge import GatewayElicitationBridge
from python_tesseron.types import TesseronCapabilities


def _make_session(elicitation_enabled: bool = True) -> Any:
    """Create a minimal mock session for elicitation tests."""

    class MockSession:
        negotiated_capabilities = TesseronCapabilities(
            streaming=True,
            subscriptions=True,
            sampling=True,
            elicitation=elicitation_enabled,
        )

    return MockSession()


def _make_elicitation_params(
    question: str = "What is your preference?",
    schema: dict[str, Any] | None = None,
    invocation_id: str = "inv_001",
) -> dict[str, Any]:
    """Build elicitation/request params dict."""
    return {
        "invocationId": invocation_id,
        "question": question,
        "schema": schema or {"type": "object", "properties": {"answer": {"type": "string"}}},
    }


# ---------------------------------------------------------------------------
# GW-68: elicitation/request translated to MCP elicitInput (REQ-127)
# ---------------------------------------------------------------------------


async def test_gw68_elicitation_translation() -> None:
    """GW-68: elicitation/request translated to MCP elicitInput.

    Verifies: DC-023 — gateway translates Tesseron elicitation/request to MCP
    elicitInput, forwarding the question and schema parameters.
    REQ-127
    """
    mcp_calls: list[dict[str, Any]] = []

    async def mock_mcp_client(elicit_params: dict[str, Any]) -> dict[str, Any]:
        mcp_calls.append(elicit_params)
        return {"action": "accept", "content": {"answer": "yes"}}

    bridge = GatewayElicitationBridge(mcp_client=mock_mcp_client)
    session = _make_session(elicitation_enabled=True)

    await bridge.handle_elicitation_request(session, _make_elicitation_params())

    assert len(mcp_calls) == 1
    # Verify the question was forwarded
    assert "message" in mcp_calls[0] or "question" in mcp_calls[0] or mcp_calls[0].get("message") is not None


# ---------------------------------------------------------------------------
# GW-69: Accept with value returned to app (REQ-127 — EP: accept)
# ---------------------------------------------------------------------------


async def test_gw69_accept_with_value() -> None:
    """GW-69: Accept result with value returned to app.

    Verifies: DC-023 — when the user accepts an elicitation and provides a
    value, the app receives ElicitationResult with action=accept and the value.
    REQ-127
    """

    async def mock_mcp_client(elicit_params: dict[str, Any]) -> dict[str, Any]:
        return {"action": "accept", "content": {"answer": "yes"}}

    bridge = GatewayElicitationBridge(mcp_client=mock_mcp_client)
    session = _make_session(elicitation_enabled=True)

    result = await bridge.handle_elicitation_request(session, _make_elicitation_params())

    assert result["action"] == "accept"
    assert result.get("value") is not None


# ---------------------------------------------------------------------------
# GW-70: Decline returned to app (REQ-127 — EP: decline)
# ---------------------------------------------------------------------------


async def test_gw70_decline() -> None:
    """GW-70: Decline result returned to app.

    Verifies: DC-023 — when the user declines an elicitation, the app receives
    ElicitationResult with action=decline.
    REQ-127
    """

    async def mock_mcp_client(elicit_params: dict[str, Any]) -> dict[str, Any]:
        return {"action": "decline"}

    bridge = GatewayElicitationBridge(mcp_client=mock_mcp_client)
    session = _make_session(elicitation_enabled=True)

    result = await bridge.handle_elicitation_request(session, _make_elicitation_params())

    assert result["action"] == "decline"


# ---------------------------------------------------------------------------
# GW-71: Cancel returned to app (REQ-127 — EP: cancel)
# ---------------------------------------------------------------------------


async def test_gw71_cancel() -> None:
    """GW-71: Cancel result returned to app.

    Verifies: DC-023 — when the user cancels an elicitation, the app receives
    ElicitationResult with action=cancel.
    REQ-127
    """

    async def mock_mcp_client(elicit_params: dict[str, Any]) -> dict[str, Any]:
        return {"action": "cancel"}

    bridge = GatewayElicitationBridge(mcp_client=mock_mcp_client)
    session = _make_session(elicitation_enabled=True)

    result = await bridge.handle_elicitation_request(session, _make_elicitation_params())

    assert result["action"] == "cancel"


# ---------------------------------------------------------------------------
# GW-72: ElicitationNotAvailableError when agent lacks capability
# ---------------------------------------------------------------------------


async def test_gw72_elicitation_not_available() -> None:
    """GW-72: ElicitationNotAvailableError (-32007) when agent lacks elicitation capability.

    Verifies: DC-023 — if the negotiated capability intersection does not
    include elicitation, an app elicitation/request is rejected with -32007.
    REQ-127
    """
    bridge = GatewayElicitationBridge()
    session = _make_session(elicitation_enabled=False)

    with pytest.raises(ElicitationNotAvailableError) as exc_info:
        await bridge.handle_elicitation_request(session, _make_elicitation_params())

    assert exc_info.value.code == -32007


# ---------------------------------------------------------------------------
# GW-73: InvalidParamsError on schema constraint violations (REQ-127)
# ---------------------------------------------------------------------------


async def test_gw73_invalid_schema() -> None:
    """GW-73: InvalidParamsError (-32602) on elicitation schema constraint violations.

    Verifies: DC-023 — an elicitation/request carrying an invalid schema
    (e.g., non-object root type or forbidden combinators) is rejected with
    -32602 InvalidParams before forwarding to the agent.
    REQ-127
    """
    bridge = GatewayElicitationBridge()
    session = _make_session(elicitation_enabled=True)

    # Schema with non-object root type
    invalid_schema_params = _make_elicitation_params(schema={"type": "string"})

    with pytest.raises(InvalidParamsError) as exc_info:
        await bridge.handle_elicitation_request(session, invalid_schema_params)

    assert exc_info.value.code == -32602
