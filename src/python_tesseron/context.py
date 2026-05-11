"""ActionContext handler context object for Tesseron actions.

Design Contract: DC-016 (ActionContext)
Spec Reference: §8.3 (ActionContext)

Guarantees:
- ctx.signal: cancellation asyncio.Event (REQ-052).
- ctx.agent: agent identity (REQ-034).
- ctx.agent_capabilities: authoritative negotiated capabilities (REQ-037, REQ-074).
- ctx.progress(update): emits actions/progress notification (REQ-051).
- ctx.sample(request): sampling bridge call (REQ-059).
- ctx.confirm(question): yes/no elicitation (REQ-060, REQ-075).
- ctx.elicit(question, schema): structured elicitation (REQ-065).
- ctx.log(entry): structured log notification.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from python_tesseron.cancellation import ProgressEmitter
from python_tesseron.elicitation import ElicitationBridge
from python_tesseron.sampling import SamplingBridge
from python_tesseron.types import AgentIdentity, TesseronCapabilities

logger = logging.getLogger(__name__)


class ActionContext:
    """Context object passed to every action handler.

    Implements DC-016. Provides access to cancellation, agent identity,
    capabilities, progress, sampling, elicitation, and logging.

    Attributes:
        signal: asyncio.Event fired on cancellation or timeout (REQ-052).
        agent: Agent identity (id and name).
        agent_capabilities: Current authoritative negotiated capabilities.
        invocation_id: The invocation ID correlating progress and cancel.

    """

    def __init__(
        self,
        invocation_id: str,
        cancel_event: asyncio.Event,
        agent: AgentIdentity,
        agent_capabilities: TesseronCapabilities,
        progress_emitter: ProgressEmitter,
        sampling_bridge: SamplingBridge,
        elicitation_bridge: ElicitationBridge,
        notify: Any,
        client: dict[str, Any] | None = None,
    ) -> None:
        """Initialise the action context.

        Args:
            invocation_id: Unique invocation identifier.
            cancel_event: asyncio.Event to check/await for cancellation.
            agent: Connected agent identity.
            agent_capabilities: Current negotiated capabilities.
            progress_emitter: ProgressEmitter for ctx.progress().
            sampling_bridge: SamplingBridge for ctx.sample().
            elicitation_bridge: ElicitationBridge for ctx.confirm()/ctx.elicit().
            notify: Dispatcher.notify callable for ctx.log().
            client: Optional client context metadata.

        """
        self.invocation_id = invocation_id
        self.signal = cancel_event
        self.agent = agent
        self.agent_capabilities = agent_capabilities
        self._progress_emitter = progress_emitter
        self._sampling_bridge = sampling_bridge
        self._elicitation_bridge = elicitation_bridge
        self._notify = notify
        self.client = client or {}

    async def progress(
        self,
        message: str | None = None,
        percent: float | None = None,
        data: Any = None,
    ) -> None:
        """Emit an actions/progress notification.

        Per REQ-051, §8.1: fire-and-forget, never raises. After transport close,
        silently dropped (REQ-084).

        Args:
            message: Optional short status message.
            percent: Optional completion percentage (0-100). SHOULD be monotonically
                increasing.
            data: Optional free-form structured data.

        """
        await self._progress_emitter.emit(message=message, percent=percent, data=data)

    async def sample(
        self,
        prompt: str,
        json_schema: dict[str, Any] | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        """Ask the agent's LLM to produce a response.

        Per REQ-059: checks sampling capability. Per REQ-077: raises
        SamplingNotAvailableError if capability absent.

        Args:
            prompt: Prompt to send to the agent's LLM.
            json_schema: Optional JSON Schema to constrain the response.
            max_tokens: Optional max token count.

        Returns:
            Parsed response content (JSON if schema given, string otherwise).

        Raises:
            SamplingNotAvailableError: If sampling capability is absent.

        """
        return await self._sampling_bridge.sample(
            invocation_id=self.invocation_id,
            prompt=prompt,
            json_schema=json_schema,
            max_tokens=max_tokens,
        )

    async def confirm(self, question: str) -> bool:
        """Ask the user a yes/no question.

        Per REQ-060, REQ-075: returns False when elicitation unavailable.
        Safe to call unconditionally.

        Args:
            question: The yes/no question to show the user.

        Returns:
            True if user explicitly accepted, False otherwise.

        """
        return await self._elicitation_bridge.confirm(
            invocation_id=self.invocation_id,
            question=question,
        )

    async def elicit(
        self,
        question: str,
        json_schema: dict[str, Any] | None = None,
    ) -> Any:
        """Ask the user for structured input.

        Per REQ-065: raises ElicitationNotAvailableError when unavailable.
        Unlike confirm(), this raises because structured data has no safe default.

        Args:
            question: The question to show the user.
            json_schema: Optional JSON Schema for the input. Defaults to
                permissive fallback (REQ-066).

        Returns:
            The accepted value (dict), or None if declined/cancelled.

        Raises:
            ElicitationNotAvailableError: If elicitation capability is absent.
            InvalidParamsError: If json_schema violates MCP constraints.

        """
        return await self._elicitation_bridge.elicit(
            invocation_id=self.invocation_id,
            question=question,
            json_schema=json_schema,
        )

    async def log(
        self,
        level: str,
        message: str,
        meta: dict[str, Any] | None = None,
    ) -> None:
        """Emit a structured log notification.

        Per §15.6: the gateway forwards log notifications as MCP sendLoggingMessage.
        Fire-and-forget.

        Args:
            level: Log level string (e.g., "info", "warn", "error").
            message: Log message.
            meta: Optional structured metadata.

        """
        params: dict[str, Any] = {"level": level, "message": message}
        if meta is not None:
            params["meta"] = meta

        try:
            await self._notify("log", params)
        except Exception:
            logger.debug("Log notification silently swallowed")
