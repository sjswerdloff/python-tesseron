"""Gateway elicitation bridge.

Design Contract: DC-023 (GatewayElicitationBridge)
Spec Reference: §8 (Elicitation)

Translates Tesseron elicitation/request to MCP elicitInput.

Guarantees:
- Translate elicitation/request to MCP elicitInput (REQ-127).
- Return ElicitationResult with action accept/decline/cancel (REQ-127).
- Return -32007 when agent lacks elicitation capability (REQ-127).
- Return -32602 on schema constraint violations (REQ-127).
"""

from __future__ import annotations

import logging
from typing import Any

from python_tesseron.errors import ElicitationNotAvailableError, InvalidParamsError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema validation helpers (REQ-127)
# ---------------------------------------------------------------------------

_FORBIDDEN_KEYWORDS = frozenset({"oneOf", "anyOf", "allOf", "not", "$ref"})


def validate_elicitation_schema(schema: dict[str, Any]) -> None:
    """Validate that an elicitation schema meets MCP constraints.

    Per REQ-127 and MCP elicitInput constraints:
    - Root type must be "object".
    - Forbidden combinators (oneOf, anyOf, allOf, not, $ref) must not appear.

    Args:
        schema: JSON Schema dict to validate.

    Raises:
        InvalidParamsError: If schema is invalid (-32602).

    """
    if schema.get("type") != "object":
        raise InvalidParamsError(f"Elicitation schema root type must be 'object'; got {schema.get('type')!r}")

    for kw in _FORBIDDEN_KEYWORDS:
        if kw in schema:
            raise InvalidParamsError(
                f"Elicitation schema contains forbidden keyword {kw!r}. Forbidden keywords: {sorted(_FORBIDDEN_KEYWORDS)}"
            )


class GatewayElicitationBridge:
    """Translates Tesseron elicitation requests to MCP elicitInput calls.

    Design Contract: DC-023 (GatewayElicitationBridge)

    Validates schemas, checks capability availability, and translates
    between the Tesseron and MCP elicitation formats.

    Attributes:
        _mcp_client: Callable or object to perform MCP elicitInput calls.

    """

    def __init__(self, mcp_client: Any = None) -> None:
        """Initialise the elicitation bridge.

        Args:
            mcp_client: Optional MCP client to perform elicitation calls.
                        If None, a stub must be set before use.

        """
        self._mcp_client = mcp_client

    def set_mcp_client(self, mcp_client: Any) -> None:
        """Set the MCP client for performing elicitation calls.

        Args:
            mcp_client: MCP client with elicitation capability.

        """
        self._mcp_client = mcp_client

    async def handle_elicitation_request(
        self,
        session: Any,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Handle an elicitation/request from an app.

        Validates schema constraints, checks capability, translates to MCP
        elicitInput, and returns the ElicitationResult to the app.

        REQ-127: translate elicitation/request to MCP elicitInput.

        Args:
            session: The GatewaySession that made the request.
            params: Raw params from the elicitation/request JSON-RPC call.

        Returns:
            ElicitationResult dict with 'action' and optional 'value'.

        Raises:
            ElicitationNotAvailableError: If elicitation not in negotiated caps (-32007).
            InvalidParamsError: If schema violates MCP constraints (-32602).

        """
        if params is None:
            params = {}

        from python_tesseron.types import ElicitationRequestParams

        req = ElicitationRequestParams.model_validate(params)

        # REQ-127: validate schema before checking capability
        validate_elicitation_schema(req.json_schema)

        # REQ-127: check elicitation capability
        if not session.negotiated_capabilities.elicitation:
            raise ElicitationNotAvailableError("Agent does not support elicitation")

        # Translate to MCP elicitInput (REQ-127)
        result = await self._do_mcp_elicitation(req.question, req.json_schema)

        return result

    async def _do_mcp_elicitation(
        self,
        question: str,
        schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Perform the actual MCP elicitInput call.

        REQ-127: forward elicitation to agent via MCP.

        Args:
            question: The question to show the user.
            schema: JSON Schema for the requested input.

        Returns:
            ElicitationResult dict with 'action' and optional 'value'.

        """
        if self._mcp_client is None:
            raise ElicitationNotAvailableError("No MCP client configured for elicitation")

        elicit_params: dict[str, Any] = {
            "message": question,
            "requestedSchema": schema,
        }

        if callable(self._mcp_client):
            response = await self._mcp_client(elicit_params)
        else:
            response = await self._mcp_client.elicit_input(elicit_params)

        # Normalize response to ElicitationResult format
        if isinstance(response, dict):
            action = response.get("action", "cancel")
            if action not in ("accept", "decline", "cancel"):
                action = "cancel"
            result: dict[str, Any] = {"action": action}
            if action == "accept" and "content" in response:
                result["value"] = response["content"]
            elif action == "accept" and "value" in response:
                result["value"] = response["value"]
            return result

        return {"action": "cancel"}
