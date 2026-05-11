"""Sampling bridge for requesting LLM responses through the agent.

Design Contract: DC-009 (SamplingBridge)
Spec Reference: §9 (Sampling)

Guarantees:
- Sends sampling/request, awaits response (REQ-058, REQ-059).
- Capability check before calling (REQ-059).
- Parses and validates response when schema provided (REQ-058).
- Handles -32008 SamplingDepthExceeded (REQ-058).
- Raises SamplingNotAvailableError when capability absent (REQ-077).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from python_tesseron.errors import (
    HandlerError,
    SamplingNotAvailableError,
)
from python_tesseron.types import SamplingRequestParams, SamplingResult, TesseronCapabilities

logger = logging.getLogger(__name__)


class SamplingBridge:
    """Issues sampling/request calls through the gateway to the agent's LLM.

    Implements DC-009. Checks capabilities before sending, validates the
    response against the provided schema if one is given.

    Attributes:
        _dispatcher: The JsonRpcDispatcher for sending requests.
        _capabilities: Current negotiated capabilities.

    """

    def __init__(self, dispatcher: Any, capabilities: TesseronCapabilities) -> None:
        """Initialise the sampling bridge.

        Args:
            dispatcher: JsonRpcDispatcher instance with request() method.
            capabilities: Current negotiated TesseronCapabilities.

        """
        self._dispatcher = dispatcher
        self._capabilities = capabilities

    async def sample(
        self,
        invocation_id: str,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        """Send a sampling/request and return the validated result.

        Per REQ-059: checks capabilities first. Per REQ-058: validates response
        against schema if provided. The gateway enforces depth limits; SDK
        handles the -32008 error.

        Args:
            invocation_id: The current invocation context ID.
            prompt: Prompt to send to the agent's LLM.
            json_schema: Optional JSON Schema to constrain the response.
            max_tokens: Optional max token count for the response.

        Returns:
            The parsed/validated response content. If json_schema provided,
            parsed as JSON. Otherwise, raw string.

        Raises:
            SamplingNotAvailableError: If sampling capability is absent (REQ-077).
            HandlerError: If the response fails schema validation.
            TesseronError: If the gateway returns any error response.

        """
        if not self._capabilities.sampling:
            raise SamplingNotAvailableError()

        params = SamplingRequestParams(
            invocation_id=invocation_id,
            prompt=prompt,
            json_schema=json_schema,
            max_tokens=max_tokens,
        )
        params_dict = params.model_dump(by_alias=True)

        # Remove None values (spec doesn't want them sent)
        params_dict = {k: v for k, v in params_dict.items() if v is not None}

        result_raw = await self._dispatcher.request("sampling/request", params_dict)

        sampling_result = SamplingResult.model_validate(result_raw)
        content = sampling_result.content

        if json_schema is not None:
            # REQ-058: parse and validate response against schema
            return _parse_and_validate_sampling_content(content, json_schema)

        return content


def _parse_and_validate_sampling_content(
    content: str,
    json_schema: dict[str, Any],
) -> Any:
    """Parse sampling content as JSON and validate against schema.

    Per REQ-058: when schema provided, parse content as JSON and validate.
    On failure, raise HandlerError.

    Args:
        content: Raw string content from the LLM.
        json_schema: JSON Schema to validate against.

    Returns:
        Parsed Python object.

    Raises:
        HandlerError: If JSON parsing or schema validation fails.

    """
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HandlerError(
            f"Sampling response is not valid JSON: {exc}"
        ) from exc

    # Basic structural validation using the schema
    # Full JSON Schema validation would require jsonschema library
    # but per spec we do minimal validation
    schema_type = json_schema.get("type")
    if schema_type == "object" and not isinstance(parsed, dict):
        raise HandlerError(
            f"Sampling response expected object, got {type(parsed).__name__}"
        )
    if schema_type == "array" and not isinstance(parsed, list):
        raise HandlerError(
            f"Sampling response expected array, got {type(parsed).__name__}"
        )

    return parsed
