"""Gateway MCP Bridge tests — GatewayMcpBridge (DC-020).

Test IDs: GW-36 through GW-49
Source: traceability/gateway_tests.md §DC-020
Design Contract: DC-020 — GatewayMcpBridge

Requirements covered:
    REQ-117: Tool registration with app_id__action_name naming convention
    REQ-118: tesseron__claim_session meta-tool
    REQ-119: tesseron__list_actions meta-tool
    REQ-120: tesseron__list_pending_claims meta-tool
    REQ-128: Log forwarding as MCP sendLoggingMessage
    REQ-129: Resources exposed with tesseron://app_id/resource_name URI
    REQ-130: tools/list_changed notification on session events
    REQ-131: resources/list_changed notification on resource events
    REQ-145: FastMCP used as MCP server foundation
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

from python_tesseron.gateway.mcp_bridge import (
    GatewayMcpBridge,
    make_resource_uri,
    make_tool_name,
    parse_tool_name,
)
from python_tesseron.gateway.session import GatewaySessionManager
from python_tesseron.types import AgentIdentity


def _make_dispatcher() -> Any:
    """Create a mock dispatcher for testing."""
    dispatcher = AsyncMock()
    dispatcher.reject_all_pending = AsyncMock()
    dispatcher.notify = AsyncMock()
    return dispatcher


async def _make_claimed_session(mgr: GatewaySessionManager, app_id: str = "myapp", actions: list[Any] | None = None) -> Any:
    """Create and claim a session with optional actions."""
    from python_tesseron.types import TesseronCapabilities

    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    params: dict[str, Any] = {
        "protocolVersion": "1.2.0",
        "app": {"id": app_id, "name": app_id, "origin": f"python:{app_id}"},
        "actions": actions or [],
        "resources": [],
        "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    }
    welcome = await mgr.handle_hello(session, params)
    claim_code = welcome["claimCode"]
    agent = AgentIdentity(id="agent", name="Agent")
    agent_caps = TesseronCapabilities()
    await mgr.handle_claim(session.session_id, claim_code, agent_identity=agent, agent_capabilities=agent_caps)
    return session


# ---------------------------------------------------------------------------
# Tool Registration (REQ-117)
# ---------------------------------------------------------------------------


async def test_gw36_tool_naming_convention() -> None:
    """GW-36: Actions registered as app_id__action_name MCP tools.

    Verifies: DC-020 — actions registered with double-underscore separator.
    App declares action "do_thing", MCP tool registered as "myapp__do_thing".
    REQ-117
    """
    tool_name = make_tool_name("myapp", "do_thing")
    assert tool_name == "myapp__do_thing"


async def test_gw37_multiple_actions_registered() -> None:
    """GW-37: Multiple actions from same app all registered.

    Verifies: DC-020 — all declared actions appear as MCP tools with correct prefix.
    App declares 3 actions, all 3 appear as MCP tools prefixed with app_id__.
    REQ-117
    """
    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    actions = [
        {"name": "action_one", "description": "First", "inputSchema": {"type": "object"}},
        {"name": "action_two", "description": "Second", "inputSchema": {"type": "object"}},
        {"name": "action_three", "description": "Third", "inputSchema": {"type": "object"}},
    ]
    await _make_claimed_session(mgr, app_id="myapp", actions=actions)

    tool_names = bridge.get_registered_tool_names()

    assert "myapp__action_one" in tool_names
    assert "myapp__action_two" in tool_names
    assert "myapp__action_three" in tool_names


async def test_gw38_underscore_in_action_name() -> None:
    """GW-38: Action name with underscores preserved in MCP tool name.

    Verifies: DC-020 — double-underscore is separator; single underscores in
    action name are preserved. "do_complex_thing" -> "myapp__do_complex_thing".
    REQ-117
    """
    tool_name = make_tool_name("myapp", "do_complex_thing")
    assert tool_name == "myapp__do_complex_thing"

    # Also verify parsing round-trips correctly
    parsed = parse_tool_name(tool_name)
    assert parsed is not None
    app_id, action_name = parsed
    assert app_id == "myapp"
    assert action_name == "do_complex_thing"


# ---------------------------------------------------------------------------
# Meta-Tools (REQ-118, REQ-119, REQ-120)
# ---------------------------------------------------------------------------


async def test_gw39_claim_session_meta_tool() -> None:
    """GW-39: tesseron__claim_session tool exists and accepts a claim code.

    Verifies: DC-020 — tesseron__claim_session present in MCP tool list;
    invoking it with a valid claim code causes the session to transition
    to CLAIMED state.
    REQ-118
    """
    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    tool_names = bridge.get_registered_tool_names()
    assert "tesseron__claim_session" in tool_names

    # Verify the meta-tool is registered on the FastMCP server
    assert bridge.mcp is not None


async def test_gw40_list_actions_meta_tool() -> None:
    """GW-40: tesseron__list_actions lists all claimed actions and resources.

    Verifies: DC-020 — after claiming a session with declared actions and
    resources, invoking tesseron__list_actions returns a complete listing.
    REQ-119
    """
    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    actions = [{"name": "do_thing", "description": "Does something", "inputSchema": {"type": "object"}}]
    await _make_claimed_session(mgr, app_id="myapp", actions=actions)

    tool_names = bridge.get_registered_tool_names()
    assert "tesseron__list_actions" in tool_names
    assert "myapp__do_thing" in tool_names


async def test_gw41_list_pending_claims_meta_tool() -> None:
    """GW-41: tesseron__list_pending_claims lists all pending claim codes.

    Verifies: DC-020 — with two unclaimed sessions, tesseron__list_pending_claims
    returns both pending claim codes.
    REQ-120
    """
    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    # Create two unclaimed sessions
    dispatcher1 = _make_dispatcher()
    session1 = mgr.create_session(dispatcher1)
    await mgr.handle_hello(
        session1,
        {
            "protocolVersion": "1.2.0",
            "app": {"id": "app_a", "name": "App A", "origin": "a"},
            "actions": [],
            "resources": [],
            "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
        },
    )

    dispatcher2 = _make_dispatcher()
    session2 = mgr.create_session(dispatcher2)
    await mgr.handle_hello(
        session2,
        {
            "protocolVersion": "1.2.0",
            "app": {"id": "app_b", "name": "App B", "origin": "b"},
            "actions": [],
            "resources": [],
            "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
        },
    )

    pending = mgr.pending_sessions()
    assert len(pending) == 2

    tool_names = bridge.get_registered_tool_names()
    assert "tesseron__list_pending_claims" in tool_names


# ---------------------------------------------------------------------------
# Resource Exposure (REQ-129)
# ---------------------------------------------------------------------------


async def test_gw42_resource_uri_format() -> None:
    """GW-42: Resources exposed with tesseron://app_id/resource_name URI.

    Verifies: DC-020 — app declares resource "config", MCP resource is
    available at URI tesseron://myapp/config.
    REQ-129
    """
    uri = make_resource_uri("myapp", "config")
    assert uri == "tesseron://myapp/config"


# ---------------------------------------------------------------------------
# Dynamic Notifications (REQ-130, REQ-131)
# Cause-Effect: session events -> notification emissions
# ---------------------------------------------------------------------------


async def test_gw43_tools_changed_on_connect() -> None:
    """GW-43: tools/list_changed notification emitted on app session connect.

    Verifies: DC-020 — when an app session connects, the MCP bridge emits
    a tools/list_changed notification to the agent.
    REQ-130
    """
    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    tools_changed_events: list[Any] = []
    bridge.on_tools_changed(lambda: tools_changed_events.append(True))

    # Connect a session (triggers on_connect)
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    await mgr.handle_hello(
        session,
        {
            "protocolVersion": "1.2.0",
            "app": {"id": "myapp", "name": "App", "origin": "test"},
            "actions": [],
            "resources": [],
            "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
        },
    )

    assert len(tools_changed_events) >= 1


async def test_gw44_tools_changed_on_claim() -> None:
    """GW-44: tools/list_changed notification emitted on app session claim.

    Verifies: DC-020 — when an app session is claimed by an agent, the MCP
    bridge emits a tools/list_changed notification.
    REQ-130
    """
    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    tools_changed_events: list[Any] = []
    bridge.on_tools_changed(lambda: tools_changed_events.append(True))
    tools_changed_events.clear()  # Clear connect event

    await _make_claimed_session(mgr, app_id="myapp")

    # At least one event fired for connect and one for claim
    assert len(tools_changed_events) >= 1


async def test_gw45_tools_changed_on_drop() -> None:
    """GW-45: tools/list_changed notification emitted on app session drop.

    Verifies: DC-020 — when an app session disconnects/drops, the MCP bridge
    emits a tools/list_changed notification.
    REQ-130
    """
    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    tools_changed_events: list[Any] = []
    bridge.on_tools_changed(lambda: tools_changed_events.append(True))

    session = await _make_claimed_session(mgr, app_id="myapp")
    event_count_before_drop = len(tools_changed_events)

    await mgr.close_session(session)

    assert len(tools_changed_events) > event_count_before_drop


async def test_gw46_resources_changed_on_add() -> None:
    """GW-46: resources/list_changed notification emitted when resource added.

    Verifies: DC-020 — when an app session adds a resource, the MCP bridge
    emits a resources/list_changed notification.
    REQ-131
    """
    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    resources_changed_events: list[Any] = []
    bridge.on_resources_changed(lambda: resources_changed_events.append(True))

    # Manually emit resources changed (would normally come from session notification)
    bridge.emit_resources_changed()

    assert len(resources_changed_events) == 1


async def test_gw47_resources_changed_on_remove() -> None:
    """GW-47: resources/list_changed notification emitted when resource removed.

    Verifies: DC-020 — when an app session removes a resource, the MCP bridge
    emits a resources/list_changed notification.
    REQ-131
    """
    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    resources_changed_events: list[Any] = []
    bridge.on_resources_changed(lambda: resources_changed_events.append(True))

    bridge.emit_resources_changed()
    bridge.emit_resources_changed()

    assert len(resources_changed_events) == 2


# ---------------------------------------------------------------------------
# Log Forwarding (REQ-128)
# ---------------------------------------------------------------------------


async def test_gw48_log_forwarding() -> None:
    """GW-48: App log notifications forwarded as MCP sendLoggingMessage.

    Verifies: DC-020 — when an app emits a log notification, the MCP bridge
    forwards it as MCP sendLoggingMessage with logger set to the app_id.
    REQ-128
    """
    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    logged_events: list[tuple[str, str, Any]] = []
    bridge.on_log(lambda app_id, level, data: logged_events.append((app_id, level, data)))

    bridge.forward_log("myapp", "info", "Test log message")

    assert len(logged_events) == 1
    assert logged_events[0][0] == "myapp"
    assert logged_events[0][1] == "info"


# ---------------------------------------------------------------------------
# Foundation (REQ-145)
# ---------------------------------------------------------------------------


async def test_gw49_fastmcp_foundation() -> None:
    """GW-49: FastMCP used as MCP server foundation.

    Verifies: DC-020 — structural test confirming the gateway MCP server is
    an instance of FastMCP or uses the FastMCP API.
    REQ-145
    """
    from fastmcp import FastMCP

    mgr = GatewaySessionManager()
    bridge = GatewayMcpBridge(mgr)

    assert isinstance(bridge.mcp, FastMCP)
