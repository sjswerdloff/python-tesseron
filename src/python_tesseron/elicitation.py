"""Elicitation and confirmation for the Tesseron protocol.

Design Contract: DC-010 (ElicitationBridge)
Spec Reference: §10 (Elicitation)

Guarantees:
- ctx.confirm(): empty-object schema, returns True/False, never throws (REQ-060, REQ-075).
- ctx.elicit(): validates schema constraints, throws if no capability (REQ-065).
- Permissive fallback schema when no explicit schema provided (REQ-066).
- Schema constraints: object type, primitive properties, no combinators (REQ-061, REQ-062, REQ-063, REQ-064).
"""

from __future__ import annotations

import logging
from typing import Any

from python_tesseron.errors import ElicitationNotAvailableError, InvalidParamsError
from python_tesseron.types import ElicitationRequestParams, ElicitationResult, TesseronCapabilities

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema constants — §10.4, §10.5, §17
# ---------------------------------------------------------------------------

# Confirm schema: empty-object, renders as Accept/Decline prompt — §10.4
_CONFIRM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
    "required": [],
}

# Permissive fallback schema for elicit without explicit schema — §10.5
_PERMISSIVE_ELICIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "response": {
            "type": "string",
            "description": "Your response",
        }
    },
    "required": ["response"],
}

# Primitive types allowed in elicitation schema properties — §10.3, REQ-062
_ALLOWED_PRIMITIVE_TYPES = frozenset({"string", "number", "integer", "boolean"})

# Combinator keywords forbidden at the top level — §10.3, REQ-063
_FORBIDDEN_COMBINATORS = frozenset({"oneOf", "anyOf", "allOf", "not"})


class ElicitationBridge:
    """Sends elicitation/request calls through the gateway to the user.

    Implements DC-010. Validates elicitation schemas before sending. Handles
    the confirm/elicit asymmetry per §12.4:
    - confirm() returns False (not raises) when capability absent.
    - elicit() raises ElicitationNotAvailableError when capability absent.

    Attributes:
        _dispatcher: JsonRpcDispatcher with request() method.
        _capabilities: Current negotiated TesseronCapabilities.

    """

    def __init__(self, dispatcher: Any, capabilities: TesseronCapabilities) -> None:
        """Initialise the elicitation bridge.

        Args:
            dispatcher: JsonRpcDispatcher instance.
            capabilities: Current negotiated TesseronCapabilities.

        """
        self._dispatcher = dispatcher
        self._capabilities = capabilities

    async def confirm(
        self,
        invocation_id: str,
        question: str,
    ) -> bool:
        """Ask the user a yes/no question.

        Per REQ-060, §10.1: sends an elicit request with empty-object schema.
        Per REQ-075: returns False (not raises) when capability absent.
        Returns True only on explicit "accept". Decline, cancel, and missing
        capability all collapse to False.

        Args:
            invocation_id: The current invocation context ID.
            question: The yes/no question to show the user.

        Returns:
            True if user explicitly accepted, False otherwise.

        """
        if not self._capabilities.elicitation:
            return False

        try:
            result = await self._send_elicit(
                invocation_id=invocation_id,
                question=question,
                schema=_CONFIRM_SCHEMA,
            )
        except Exception:
            # Graceful degradation: confirm() never throws
            logger.exception("Elicitation confirm() failed; returning False")
            return False

        return result.action == "accept"

    async def elicit(
        self,
        invocation_id: str,
        question: str,
        json_schema: dict[str, Any] | None = None,
    ) -> Any:
        """Ask the user for structured input.

        Per REQ-065: raises ElicitationNotAvailableError when capability absent.
        Per REQ-064: validates schema constraints before sending.
        Per REQ-066: uses permissive fallback schema when json_schema is None.
        Returns the validated value on accept, None on decline/cancel.

        Args:
            invocation_id: The current invocation context ID.
            question: The question to show the user.
            json_schema: Optional JSON Schema for the requested input.
                Must be an object schema with primitive-only properties
                and no combinators. Defaults to permissive fallback.

        Returns:
            The accepted value (dict), or None if declined/cancelled.

        Raises:
            ElicitationNotAvailableError: If elicitation capability is absent.
            InvalidParamsError: If json_schema violates MCP elicitation constraints.

        """
        if not self._capabilities.elicitation:
            raise ElicitationNotAvailableError()

        effective_schema = json_schema if json_schema is not None else _PERMISSIVE_ELICIT_SCHEMA

        # REQ-064: validate schema before sending
        validate_elicitation_schema(effective_schema)

        result = await self._send_elicit(
            invocation_id=invocation_id,
            question=question,
            schema=effective_schema,
        )

        if result.action == "accept":
            return result.value
        return None

    async def _send_elicit(
        self,
        invocation_id: str,
        question: str,
        schema: dict[str, Any],
    ) -> ElicitationResult:
        """Send the elicitation/request and await the response.

        Args:
            invocation_id: Invocation context ID.
            question: Question to show the user.
            schema: Validated schema for the request.

        Returns:
            Parsed ElicitationResult.

        """
        params = ElicitationRequestParams(
            invocation_id=invocation_id,
            question=question,
            json_schema=schema,
        )
        params_dict = params.model_dump(by_alias=True)

        result_raw = await self._dispatcher.request("elicitation/request", params_dict)
        return ElicitationResult.model_validate(result_raw)


def validate_elicitation_schema(schema: dict[str, Any]) -> None:
    """Validate an elicitation schema against MCP constraints.

    Per §10.3, REQ-061, REQ-062, REQ-063, REQ-064:
    - Top level MUST be { "type": "object" }.
    - Each property MUST be a primitive type (string, number, integer, boolean).
    - No oneOf/anyOf/allOf/not at the top level.

    Args:
        schema: The JSON Schema dict to validate.

    Raises:
        InvalidParamsError: If the schema violates MCP elicitation constraints.

    """
    # REQ-061: top level must be object type
    if schema.get("type") != "object":
        raise InvalidParamsError(
            "Elicitation schema top level must be {\"type\": \"object\"}. "
            f"Got type={schema.get('type')!r}"
        )

    # REQ-063: no combinators at top level
    for combinator in _FORBIDDEN_COMBINATORS:
        if combinator in schema:
            raise InvalidParamsError(
                f"Elicitation schema must not use combinator {combinator!r} at the top level."
            )

    # REQ-062: each property must be a primitive type
    properties = schema.get("properties", {})
    for prop_name, prop_schema in properties.items():
        prop_type = prop_schema.get("type")
        if prop_type not in _ALLOWED_PRIMITIVE_TYPES:
            raise InvalidParamsError(
                f"Elicitation schema property {prop_name!r} has type {prop_type!r}. "
                f"Only primitive types are allowed: {sorted(_ALLOWED_PRIMITIVE_TYPES)}"
            )
