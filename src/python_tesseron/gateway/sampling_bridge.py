"""Gateway sampling bridge.

Design Contract: DC-022 (GatewaySamplingBridge)
Spec Reference: §9 (Sampling)

Translates Tesseron sampling/request to MCP sampling/createMessage.

Guarantees:
- Translate sampling/request to MCP sampling/createMessage (REQ-125).
- Track sampling depth across recursive invocations (REQ-126).
- Return -32008 SamplingDepthExceeded with {depth, max} when depth > 3 (REQ-126).
- Return -32006 when agent lacks sampling capability (REQ-125).
"""

from __future__ import annotations

import logging
from typing import Any

from python_tesseron.errors import SamplingDepthExceededError, SamplingNotAvailableError

logger = logging.getLogger(__name__)

# Maximum sampling depth (REQ-126)
MAX_SAMPLING_DEPTH = 3


class GatewaySamplingBridge:
    """Translates Tesseron sampling requests to MCP sampling calls.

    Design Contract: DC-022 (GatewaySamplingBridge)

    Tracks per-invocation sampling depth to enforce the maximum recursion
    limit and translates between the Tesseron and MCP sampling formats.

    Attributes:
        _mcp_client: Callable or object to perform MCP sampling/createMessage.
        _depth_map: Maps invocation_id to current sampling depth.

    """

    def __init__(self, mcp_client: Any = None) -> None:
        """Initialise the sampling bridge.

        Args:
            mcp_client: Optional MCP client to perform sampling calls.
                        If None, a stub must be set before use.

        """
        self._mcp_client = mcp_client
        self._depth_map: dict[str, int] = {}

    def set_mcp_client(self, mcp_client: Any) -> None:
        """Set the MCP client for performing sampling calls.

        Args:
            mcp_client: MCP client with sampling capability.

        """
        self._mcp_client = mcp_client

    def get_depth(self, invocation_id: str) -> int:
        """Get the current sampling depth for an invocation.

        Args:
            invocation_id: The action invocation context.

        Returns:
            Current depth (0 if not tracked).

        """
        return self._depth_map.get(invocation_id, 0)

    def increment_depth(self, invocation_id: str) -> int:
        """Increment and return the sampling depth for an invocation.

        REQ-126: track depth across recursive invocations.

        Args:
            invocation_id: The action invocation context.

        Returns:
            New depth after increment.

        """
        current = self._depth_map.get(invocation_id, 0) + 1
        self._depth_map[invocation_id] = current
        return current

    def decrement_depth(self, invocation_id: str) -> None:
        """Decrement the sampling depth for an invocation.

        Called after a sampling request completes.

        Args:
            invocation_id: The action invocation context.

        """
        current = self._depth_map.get(invocation_id, 0)
        if current <= 1:
            self._depth_map.pop(invocation_id, None)
        else:
            self._depth_map[invocation_id] = current - 1

    def clear_depth(self, invocation_id: str) -> None:
        """Clear depth tracking for an invocation.

        Called when an invocation completes or is cancelled.

        Args:
            invocation_id: The action invocation context to clear.

        """
        self._depth_map.pop(invocation_id, None)

    async def handle_sampling_request(
        self,
        session: Any,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Handle a sampling/request from an app.

        Translates to MCP sampling/createMessage and returns the result.

        REQ-125: translate sampling/request to MCP sampling/createMessage.
        REQ-126: enforce max sampling depth.

        Args:
            session: The GatewaySession that made the request.
            params: Raw params from the sampling/request JSON-RPC call.

        Returns:
            SamplingResult dict with 'content' field.

        Raises:
            SamplingNotAvailableError: If sampling not in negotiated capabilities (-32006).
            SamplingDepthExceededError: If depth exceeds MAX_SAMPLING_DEPTH (-32008).

        """
        if params is None:
            params = {}

        from python_tesseron.types import SamplingRequestParams

        req = SamplingRequestParams.model_validate(params)

        # REQ-125: check sampling capability
        if not session.negotiated_capabilities.sampling:
            raise SamplingNotAvailableError("Agent does not support sampling")

        # REQ-126: check and enforce depth limit
        invocation_id = req.invocation_id
        new_depth = self.increment_depth(invocation_id)

        try:
            if new_depth > MAX_SAMPLING_DEPTH:
                raise SamplingDepthExceededError(
                    f"Sampling depth {new_depth} exceeds maximum {MAX_SAMPLING_DEPTH}",
                    data={"depth": new_depth, "max": MAX_SAMPLING_DEPTH},
                )

            # Translate to MCP sampling/createMessage (REQ-125)
            result = await self._do_mcp_sampling(req.prompt, req.json_schema, req.max_tokens)
        finally:
            self.decrement_depth(invocation_id)

        return {"content": result}

    async def _do_mcp_sampling(
        self,
        prompt: str,
        json_schema: dict[str, Any] | None,
        max_tokens: int | None,
    ) -> str:
        """Perform the actual MCP sampling/createMessage call.

        REQ-125: forward prompt to agent's LLM via MCP.

        Args:
            prompt: The prompt to send to the LLM.
            json_schema: Optional JSON Schema to constrain the response.
            max_tokens: Optional maximum token count.

        Returns:
            The LLM's response content string.

        """
        if self._mcp_client is None:
            raise SamplingNotAvailableError("No MCP client configured for sampling")

        # Build MCP sampling/createMessage params
        messages = [
            {
                "role": "user",
                "content": {"type": "text", "text": prompt},
            }
        ]

        sampling_params: dict[str, Any] = {"messages": messages}
        if max_tokens is not None:
            sampling_params["maxTokens"] = max_tokens

        # Call MCP client
        if callable(self._mcp_client):
            response = await self._mcp_client(sampling_params)
        else:
            response = await self._mcp_client.create_message(sampling_params)

        # Extract content
        if isinstance(response, dict):
            content = response.get("content", "")
            if isinstance(content, dict):
                return str(content.get("text", ""))
            return str(content)
        return str(response)
