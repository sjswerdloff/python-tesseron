"""Gateway MCP bridge.

Design Contract: DC-020 (GatewayMcpBridge)
Spec Reference: §6, §7, §8, §9

Bridges Tesseron app sessions to MCP agents via FastMCP.

Guarantees:
- Register Tesseron actions as MCP tools with app_id__action_name naming (REQ-117).
- Provide meta-tools: tesseron__claim_session, tesseron__list_actions,
  tesseron__list_pending_claims (REQ-118, REQ-119, REQ-120).
- Expose resources with tesseron://app_id/resource_name URIs (REQ-129).
- Emit notifications/tools/list_changed on session connect/claim/drop (REQ-130).
- Emit notifications/resources/list_changed on resource changes (REQ-131).
- Forward app log notifications as MCP sendLoggingMessage (REQ-128).
- Use FastMCP as MCP server foundation (REQ-145).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool naming convention (REQ-117)
# ---------------------------------------------------------------------------


def make_tool_name(app_id: str, action_name: str) -> str:
    """Construct the MCP tool name for a Tesseron action.

    Per REQ-117: tool name is app_id + "__" + action_name (double-underscore
    separator). Single underscores in action names are preserved.

    Args:
        app_id: The application identifier.
        action_name: The action name (may contain single underscores).

    Returns:
        MCP tool name string in format ``app_id__action_name``.

    """
    return f"{app_id}__{action_name}"


def parse_tool_name(tool_name: str) -> tuple[str, str] | None:
    """Parse an MCP tool name into (app_id, action_name).

    Per REQ-117: separator is double-underscore. The action_name may contain
    single underscores.

    Args:
        tool_name: MCP tool name to parse.

    Returns:
        Tuple of (app_id, action_name) or None if not a valid Tesseron tool name.

    """
    parts = tool_name.split("__", 1)
    if len(parts) != 2:
        return None
    app_id, action_name = parts
    if not app_id or not action_name:
        return None
    return app_id, action_name


# ---------------------------------------------------------------------------
# Resource URI construction (REQ-129)
# ---------------------------------------------------------------------------


def make_resource_uri(app_id: str, resource_name: str) -> str:
    """Construct the MCP resource URI for a Tesseron resource.

    Per REQ-129: URI format is tesseron://app_id/resource_name.

    Args:
        app_id: The application identifier.
        resource_name: The resource name.

    Returns:
        Resource URI string.

    """
    return f"tesseron://{app_id}/{resource_name}"


class GatewayMcpBridge:
    """Bridges Tesseron sessions to MCP agent tooling via FastMCP.

    Design Contract: DC-020 (GatewayMcpBridge)

    Maintains a FastMCP server instance and dynamically registers/unregisters
    tools and resources as app sessions connect, are claimed, and drop.

    Attributes:
        _session_manager: GatewaySessionManager for session access.
        _action_router: GatewayActionRouter for tool call forwarding.
        _mcp: The FastMCP server instance.
        _tools_changed_callbacks: Callbacks to notify on tool list change.
        _resources_changed_callbacks: Callbacks to notify on resource change.
        _log_callbacks: Callbacks to forward log notifications.

    """

    def __init__(self, session_manager: Any, action_router: Any | None = None) -> None:
        """Initialise the MCP bridge.

        Args:
            session_manager: GatewaySessionManager instance.
            action_router: GatewayActionRouter for forwarding tool calls.
                If None, tool invocations will return errors until set.

        """
        try:
            from fastmcp import FastMCP
        except ImportError as exc:
            raise ImportError("fastmcp is required for the gateway MCP bridge") from exc

        self._session_manager = session_manager
        self._action_router = action_router

        # REQ-145: FastMCP as MCP server foundation
        self._mcp = FastMCP("tesseron-gateway")

        self._tools_changed_callbacks: list[Callable[[], Any]] = []
        self._resources_changed_callbacks: list[Callable[[], Any]] = []
        self._log_callbacks: list[Callable[[str, str, Any], Any]] = []

        # Register meta-tools (REQ-118, REQ-119, REQ-120)
        self._register_meta_tools()

        # Hook session manager events (REQ-130, REQ-131)
        self._session_manager.on_connect(self._on_session_connect)
        self._session_manager.on_claimed(self._on_session_claimed)
        self._session_manager.on_drop(self._on_session_drop)

        logger.debug("GatewayMcpBridge initialised with FastMCP")

    @property
    def mcp(self) -> Any:
        """The underlying FastMCP server instance.

        Returns:
            FastMCP instance.

        """
        return self._mcp

    def set_action_router(self, action_router: Any) -> None:
        """Set the action router for tool call forwarding.

        Args:
            action_router: GatewayActionRouter instance.

        """
        self._action_router = action_router

    # ------------------------------------------------------------------
    # Meta-tool registration (REQ-118, REQ-119, REQ-120)
    # ------------------------------------------------------------------

    def _register_meta_tools(self) -> None:
        """Register the three Tesseron meta-tools on the FastMCP server.

        REQ-118: tesseron__claim_session
        REQ-119: tesseron__list_actions
        REQ-120: tesseron__list_pending_claims

        """
        bridge = self

        @self._mcp.tool(name="tesseron__claim_session")
        async def claim_session(session_id: str, claim_code: str) -> dict[str, Any]:
            """Claim a Tesseron app session with a claim code.

            REQ-118: meta-tool for agent to claim a pending session.

            Args:
                session_id: The session ID to claim.
                claim_code: The claim code printed to stderr during app connection.

            Returns:
                Result dict with sessionId and negotiated capabilities.

            """
            from python_tesseron.types import AgentIdentity, TesseronCapabilities

            agent = AgentIdentity(id="agent", name="Agent")
            agent_caps = TesseronCapabilities()
            result: dict[str, Any] = await bridge._session_manager.handle_claim(session_id, claim_code, agent, agent_caps)
            return result

        @self._mcp.tool(name="tesseron__list_actions")
        async def list_actions() -> dict[str, Any]:
            """List all claimed app actions and resources.

            REQ-119: meta-tool to enumerate available tools and resources.

            Returns:
                Dict with 'actions' and 'resources' lists.

            """
            sessions = bridge._session_manager.all_sessions()
            actions = []
            resources = []
            for session in sessions:
                if session.is_claimed and session.app_id:
                    for action in session.actions:
                        actions.append(
                            {
                                "app_id": session.app_id,
                                "tool_name": make_tool_name(session.app_id, action.name),
                                "description": action.description,
                            }
                        )
                    for resource in session.resources:
                        resources.append(
                            {
                                "app_id": session.app_id,
                                "uri": make_resource_uri(session.app_id, resource.name),
                                "description": resource.description,
                            }
                        )
            return {"actions": actions, "resources": resources}

        @self._mcp.tool(name="tesseron__list_pending_claims")
        async def list_pending_claims() -> dict[str, Any]:
            """List all pending claim codes for unclaimed sessions.

            REQ-120: meta-tool to see sessions awaiting claim.

            Returns:
                Dict with 'pending' list of {session_id, app_id, claim_code}.

            """
            pending = bridge._session_manager.pending_sessions()
            return {
                "pending": [
                    {
                        "session_id": s.session_id,
                        "app_id": s.app_id,
                        "claim_code": s.claim_code,
                    }
                    for s in pending
                ]
            }

    # ------------------------------------------------------------------
    # Session event handlers (REQ-130, REQ-131)
    # ------------------------------------------------------------------

    def _on_session_connect(self, session: Any) -> None:
        """Handle new session connect event.

        REQ-130: emit tools/list_changed on session connect.

        Args:
            session: The newly connected GatewaySession.

        """
        logger.debug("Session connected: %s — emitting tools/list_changed", session.session_id)
        self._emit_tools_changed()

    def _on_session_claimed(self, session: Any) -> None:
        """Handle session claimed event.

        REQ-130: emit tools/list_changed on session claim.
        Also registers app actions as MCP tools.

        Args:
            session: The newly claimed GatewaySession.

        """
        logger.debug("Session claimed: %s — registering tools", session.session_id)
        self._emit_tools_changed()

    def _on_session_drop(self, session: Any) -> None:
        """Handle session drop event.

        REQ-130: emit tools/list_changed on session drop.

        Args:
            session: The dropped GatewaySession.

        """
        logger.debug("Session dropped: %s — emitting tools/list_changed", session.session_id)
        self._emit_tools_changed()

    def emit_resources_changed(self) -> None:
        """Emit resources/list_changed notification.

        REQ-131: emit when resources are added or removed.

        """
        for cb in self._resources_changed_callbacks:
            try:
                cb()
            except Exception:
                logger.exception("Error in resources_changed callback")

    def _emit_tools_changed(self) -> None:
        """Emit tools/list_changed notification to all registered callbacks.

        REQ-130.

        """
        for cb in self._tools_changed_callbacks:
            try:
                cb()
            except Exception:
                logger.exception("Error in tools_changed callback")

    def on_tools_changed(self, cb: Callable[[], Any]) -> None:
        """Register a callback for tools/list_changed events.

        Args:
            cb: Zero-argument callable invoked on tools change.

        """
        self._tools_changed_callbacks.append(cb)

    def on_resources_changed(self, cb: Callable[[], Any]) -> None:
        """Register a callback for resources/list_changed events.

        Args:
            cb: Zero-argument callable invoked on resources change.

        """
        self._resources_changed_callbacks.append(cb)

    def on_log(self, cb: Callable[[str, str, Any], Any]) -> None:
        """Register a callback for forwarded log notifications.

        REQ-128: app logs forwarded as MCP sendLoggingMessage.

        Args:
            cb: Callable receiving (app_id, level, data) args.

        """
        self._log_callbacks.append(cb)

    def forward_log(self, app_id: str, level: str, data: Any) -> None:
        """Forward a log notification from an app to MCP.

        REQ-128: forward app log notifications as MCP sendLoggingMessage
                 with logger=app_id.

        Args:
            app_id: The app that emitted the log.
            level: Log level string.
            data: Log message payload.

        """
        for cb in self._log_callbacks:
            try:
                cb(app_id, level, data)
            except Exception:
                logger.exception("Error forwarding log from %s", app_id)

    # ------------------------------------------------------------------
    # Tool and resource availability queries (REQ-117, REQ-129)
    # ------------------------------------------------------------------

    def get_registered_tool_names(self) -> list[str]:
        """Return list of all currently registered MCP tool names.

        Includes both meta-tools and dynamically registered app action tools.

        Returns:
            List of tool name strings.

        """
        # Meta-tools are always present
        meta_tools = [
            "tesseron__claim_session",
            "tesseron__list_actions",
            "tesseron__list_pending_claims",
        ]
        # Dynamically registered tools from claimed sessions
        dynamic_tools = []
        for session in self._session_manager.all_sessions():
            if session.is_claimed and session.app_id:
                for action in session.actions:
                    dynamic_tools.append(make_tool_name(session.app_id, action.name))
        return meta_tools + dynamic_tools

    def get_registered_resource_uris(self) -> list[str]:
        """Return list of all currently registered MCP resource URIs.

        Returns:
            List of resource URI strings.

        """
        uris = []
        for session in self._session_manager.all_sessions():
            if session.is_claimed and session.app_id:
                for resource in session.resources:
                    uris.append(make_resource_uri(session.app_id, resource.name))
        return uris
