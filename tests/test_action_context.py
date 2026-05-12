"""Isolation tests for DC-016 (ActionContext).

Design Contract: DC-016
Module: python_tesseron/context.py

These tests verify DC-016 guarantees against mock dependencies — no dispatcher,
no transport, no real bridges. Each test isolates a specific ActionContext
guarantee.

Guarantees tested:
- ctx.signal fires on timeout or cancel
- ctx.agent returns agent identity
- ctx.agent_capabilities returns authoritative capability set
- ctx.progress emits fire-and-forget notification
- ctx.log emits structured log notification
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from python_tesseron.context import ActionContext
from python_tesseron.types import AgentIdentity, TesseronCapabilities


@pytest.fixture()
def mock_progress_emitter() -> AsyncMock:
    """Mock ProgressEmitter with async emit method."""
    emitter = AsyncMock()
    emitter.emit = AsyncMock()
    return emitter


@pytest.fixture()
def mock_sampling_bridge() -> AsyncMock:
    """Mock SamplingBridge with async sample method."""
    bridge = AsyncMock()
    bridge.sample = AsyncMock(return_value="sample result")
    return bridge


@pytest.fixture()
def mock_elicitation_bridge() -> AsyncMock:
    """Mock ElicitationBridge with confirm and elicit methods."""
    bridge = AsyncMock()
    bridge.confirm = AsyncMock(return_value=True)
    bridge.elicit = AsyncMock(return_value={"name": "value"})
    return bridge


@pytest.fixture()
def mock_notify() -> AsyncMock:
    """Mock notify callable for ctx.log."""
    return AsyncMock()


@pytest.fixture()
def agent() -> AgentIdentity:
    """Test agent identity."""
    return AgentIdentity(id="agent-test-001", name="TestAgent")


@pytest.fixture()
def capabilities() -> TesseronCapabilities:
    """Test capabilities with sampling disabled."""
    return TesseronCapabilities(streaming=True, subscriptions=True, sampling=False, elicitation=True)


@pytest.fixture()
def cancel_event() -> asyncio.Event:
    """Cancellation event for context."""
    return asyncio.Event()


@pytest.fixture()
def ctx(
    cancel_event: asyncio.Event,
    agent: AgentIdentity,
    capabilities: TesseronCapabilities,
    mock_progress_emitter: AsyncMock,
    mock_sampling_bridge: AsyncMock,
    mock_elicitation_bridge: AsyncMock,
    mock_notify: AsyncMock,
) -> ActionContext:
    """ActionContext with all mock dependencies."""
    return ActionContext(
        invocation_id="inv-test-001",
        cancel_event=cancel_event,
        agent=agent,
        agent_capabilities=capabilities,
        progress_emitter=mock_progress_emitter,
        sampling_bridge=mock_sampling_bridge,
        elicitation_bridge=mock_elicitation_bridge,
        notify=mock_notify,
        client={"source": "test"},
    )


# ---------------------------------------------------------------------------
# AC-01 through AC-03: Identity and capability access
# ---------------------------------------------------------------------------


class TestContextIdentity:
    """AC-01 through AC-03: Agent identity and capabilities in isolation."""

    def test_ac01_agent_identity(self, ctx: ActionContext, agent: AgentIdentity) -> None:
        """AC-01: ctx.agent returns the agent identity set at construction.

        Verifies: DC-016 — ctx.agent returns agent identity.
        REQ-034
        """
        assert ctx.agent.id == "agent-test-001"
        assert ctx.agent.name == "TestAgent"
        assert ctx.agent is agent

    def test_ac02_agent_capabilities(self, ctx: ActionContext, capabilities: TesseronCapabilities) -> None:
        """AC-02: ctx.agent_capabilities returns authoritative capability set.

        Verifies: DC-016 — ctx.agent_capabilities returns authoritative set.
        REQ-037
        """
        assert ctx.agent_capabilities.streaming is True
        assert ctx.agent_capabilities.sampling is False
        assert ctx.agent_capabilities.elicitation is True
        assert ctx.agent_capabilities is capabilities

    def test_ac03_invocation_id_and_client(self, ctx: ActionContext) -> None:
        """AC-03: invocation_id and client metadata accessible.

        Verifies: DC-016 — construction state preserved.
        REQ-098
        """
        assert ctx.invocation_id == "inv-test-001"
        assert ctx.client == {"source": "test"}


# ---------------------------------------------------------------------------
# AC-04: Cancellation signal
# ---------------------------------------------------------------------------


class TestContextSignal:
    """AC-04: ctx.signal fires on cancellation."""

    def test_ac04_signal_fires(self, ctx: ActionContext, cancel_event: asyncio.Event) -> None:
        """AC-04: ctx.signal is set when cancel_event is fired.

        Verifies: DC-016 — ctx.signal fires on timeout or cancel.
        REQ-052
        """
        assert not ctx.signal.is_set()
        cancel_event.set()
        assert ctx.signal.is_set()


# ---------------------------------------------------------------------------
# AC-05 through AC-06: Progress emission
# ---------------------------------------------------------------------------


class TestContextProgress:
    """AC-05 through AC-06: ctx.progress with mock emitter."""

    async def test_ac05_progress_emits(self, ctx: ActionContext, mock_progress_emitter: AsyncMock) -> None:
        """AC-05: ctx.progress delegates to ProgressEmitter.emit.

        Verifies: DC-016 — ctx.progress emits fire-and-forget notification.
        REQ-051
        """
        await ctx.progress(message="Working...", percent=50.0, data={"step": 3})
        mock_progress_emitter.emit.assert_called_once_with(
            message="Working...",
            percent=50.0,
            data={"step": 3},
        )

    async def test_ac06_progress_optional_params(self, ctx: ActionContext, mock_progress_emitter: AsyncMock) -> None:
        """AC-06: ctx.progress works with no arguments.

        Verifies: DC-016 — progress params are all optional.
        REQ-051
        """
        await ctx.progress()
        mock_progress_emitter.emit.assert_called_once_with(
            message=None,
            percent=None,
            data=None,
        )


# ---------------------------------------------------------------------------
# AC-07: Log emission
# ---------------------------------------------------------------------------


class TestContextLog:
    """AC-07 through AC-08: ctx.log with mock notify."""

    async def test_ac07_log_emits(self, ctx: ActionContext, mock_notify: AsyncMock) -> None:
        """AC-07: ctx.log calls notify with correct params.

        Verifies: DC-016 — ctx.log emits structured log notification.
        REQ-098
        """
        await ctx.log(level="info", message="test log", meta={"key": "val"})
        mock_notify.assert_called_once_with(
            "log",
            {"level": "info", "message": "test log", "meta": {"key": "val"}},
        )

    async def test_ac08_log_without_meta(self, ctx: ActionContext, mock_notify: AsyncMock) -> None:
        """AC-08: ctx.log without meta omits meta from params.

        Verifies: DC-016 — meta is optional.
        REQ-098
        """
        await ctx.log(level="warn", message="warning")
        mock_notify.assert_called_once_with(
            "log",
            {"level": "warn", "message": "warning"},
        )

    async def test_ac09_log_swallows_exceptions(self, ctx: ActionContext, mock_notify: AsyncMock) -> None:
        """AC-09: ctx.log silently swallows notify failures.

        Verifies: DC-016 — fire-and-forget, never raises.
        REQ-098
        """
        mock_notify.side_effect = ConnectionError("transport closed")
        # Should not raise
        await ctx.log(level="error", message="this should not crash")
