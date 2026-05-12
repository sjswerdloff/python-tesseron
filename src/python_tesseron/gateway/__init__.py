"""Tesseron gateway package.

The gateway is the server component that bridges Tesseron apps to MCP agents.

Design Contracts: DC-018 through DC-025.
Spec Reference: §3.2, §5, §6, §7, §8, §9, §14, §15, §16.

Public API:
    GatewayWebSocketServer   — accepts inbound app connections (DC-018).
    GatewaySessionManager    — session state machine and handshake (DC-019).
    GatewayMcpBridge         — FastMCP integration and tool registration (DC-020).
    GatewayActionRouter      — routes MCP tool calls to app sessions (DC-021).
    GatewaySamplingBridge    — translates sampling/request to MCP (DC-022).
    GatewayElicitationBridge — translates elicitation/request to MCP (DC-023).
    GatewayResumeManager     — zombie session TTL and token rotation (DC-024).
    GatewayManifestWatcher   — watches discovery directory (DC-025).
"""

from python_tesseron.gateway.action_router import GatewayActionRouter
from python_tesseron.gateway.elicitation_bridge import GatewayElicitationBridge
from python_tesseron.gateway.manifest_watcher import GatewayManifestWatcher
from python_tesseron.gateway.mcp_bridge import GatewayMcpBridge
from python_tesseron.gateway.resume import GatewayResumeManager
from python_tesseron.gateway.sampling_bridge import GatewaySamplingBridge
from python_tesseron.gateway.server import GatewayWebSocketServer, is_loopback_url
from python_tesseron.gateway.session import (
    GatewaySession,
    GatewaySessionManager,
)

__all__ = [
    "GatewayActionRouter",
    "GatewayElicitationBridge",
    "GatewayManifestWatcher",
    "GatewayMcpBridge",
    "GatewayResumeManager",
    "GatewaySamplingBridge",
    "GatewaySession",
    "GatewaySessionManager",
    "GatewayWebSocketServer",
    "is_loopback_url",
]
