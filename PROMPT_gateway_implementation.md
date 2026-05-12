# Prompt: Implement Tesseron Gateway from Design Contracts

**Agent:** Sonnet (python-implementation)
**Role:** Implementation engineer for python-tesseron gateway
**Date:** 2026-05-12
**Author:** cora-2f1e43dc (Development Engineering Lead)

## Skills to Load

1. `python-development`
2. `test-writing-philosophy`
3. `best-practices-over-most-probable`
4. `linting-efficiency`

## Context

python-tesseron already has a working SDK (app side). You are implementing the **gateway** — the server component that bridges Tesseron apps to MCP agents via FastMCP.

**What exists:**
- Protocol specification: `SPEC_tesseron_protocol_for_python.md`
- 40 gateway requirements: REQ-108 through REQ-147 in `traceability/requirements.csv`
- 8 gateway design contracts: DC-018 through DC-025 in `traceability/design_contracts.csv`
- 97 test specifications: `traceability/gateway_tests.md` (GW-01 through GW-97)
- 97 xfailed pytest tests across 9 files in `tests/test_gateway_*.py`
- Working SDK modules in `src/python_tesseron/` (dispatcher, types, errors, etc.)

**Your job:** Implement 8 gateway modules so all 97 xfailed tests pass.

## Critical Rules

1. **Never modify test assertions.** Remove `@pytest.mark.xfail` markers as tests pass. Do not change test logic.
2. **Never modify traceability files.** Do not touch `traceability/`.
3. **Reuse existing SDK modules.** The gateway shares `dispatcher.py`, `types.py`, `errors.py`, `capabilities.py` with the SDK. Do not duplicate.

## Module Map

All gateway modules live under `src/python_tesseron/gateway/`. Create `__init__.py` to export public API.

| DC | Module | What It Does |
|----|--------|-------------|
| DC-018 | `gateway/server.py` | WebSocket server accepting inbound connections |
| DC-019 | `gateway/session.py` | Session state machine, claim codes, close cascade |
| DC-020 | `gateway/mcp_bridge.py` | FastMCP integration, tool/resource registration, meta-tools |
| DC-021 | `gateway/action_router.py` | Forward invoke/progress/cancel, timeout, app_id routing |
| DC-022 | `gateway/sampling_bridge.py` | Translate sampling/request to MCP sampling/createMessage |
| DC-023 | `gateway/elicitation_bridge.py` | Translate elicitation/request to MCP elicitInput |
| DC-024 | `gateway/resume.py` | Zombie session TTL, token validation/rotation |
| DC-025 | `gateway/manifest_watcher.py` | Watch discovery directory, detect stale manifests |

## Implementation Order

### Phase 1: Session Core (DC-019, DC-018)

**DC-019 GatewaySessionManager** (`gateway/session.py`):
- Session state machine: DISCONNECTED → HANDSHAKING → AWAITING_CLAIM → CLAIMED → CLOSED
- Claim code generation: CSPRNG, format XXXX-XX, alphabet `ABCDEFGHJKMNPQRSTUVWXYZ23456789`, print to stderr
- Single-use claim codes, reject wrong codes with -32009
- Capability intersection: compute from app-declared and agent capabilities
- Welcome response: sessionId, protocolVersion, capabilities, claimCode, resumeToken
- Claimed notification: agent identity, claimedAt, agentCapabilities
- Protocol version validation: reject major mismatch with -32000
- Multi-session support: independent state per session
- Close cascade: reject pending, fire cancellation signals, clean subscriptions

**DC-018 GatewayWebSocketServer** (`gateway/server.py`):
- Accept inbound WebSocket connections with `websockets` library
- Validate tesseron-gateway subprotocol on all connections
- Refuse non-loopback URLs from manifests
- Delegate to session manager on connect
- Use existing `JsonRpcDispatcher` from SDK for message handling

**Target tests:** GW-01 through GW-35

### Phase 2: MCP Bridge (DC-020)

**DC-020 GatewayMcpBridge** (`gateway/mcp_bridge.py`):
- Use FastMCP as MCP server foundation
- Register Tesseron actions as MCP tools with `app_id__action_name` pattern
- Provide meta-tools: `tesseron__claim_session`, `tesseron__list_actions`, `tesseron__list_pending_claims`
- Expose resources with `tesseron://app_id/resource_name` URIs
- Emit `notifications/tools/list_changed` on session connect/claim/drop
- Emit `notifications/resources/list_changed` on resource changes
- Forward log notifications as MCP `sendLoggingMessage` with `logger=app_id`

**Target tests:** GW-36 through GW-49

### Phase 3: Action System (DC-021)

**DC-021 GatewayActionRouter** (`gateway/action_router.py`):
- Route tool calls to correct app session by parsing app_id prefix
- Forward `actions/invoke` as JSON-RPC request to app via dispatcher
- Forward `actions/progress` to MCP as `notifications/progress` when progressToken supplied
- Send `actions/cancel` on agent cancellation or timeout
- Enforce default 60000ms timeout, custom `timeoutMs` respected
- Reject invocations on unclaimed sessions with -32009

**Target tests:** GW-50 through GW-60

### Phase 4: Bridges (DC-022, DC-023)

**DC-022 GatewaySamplingBridge** (`gateway/sampling_bridge.py`):
- Translate `sampling/request` to MCP `sampling/createMessage`
- Track sampling depth across recursive invocations
- Return -32008 SamplingDepthExceeded with `{depth: N, max: 3}` when depth > 3
- Return -32006 when agent lacks sampling capability

**DC-023 GatewayElicitationBridge** (`gateway/elicitation_bridge.py`):
- Translate `elicitation/request` to MCP `elicitInput`
- Return ElicitationResult (accept/decline/cancel with optional value)
- Return -32007 when agent lacks elicitation capability
- Return -32602 on schema constraint violations

**Target tests:** GW-61 through GW-73

### Phase 5: Resume and Discovery (DC-024, DC-025)

**DC-024 GatewayResumeManager** (`gateway/resume.py`):
- Retain disconnected sessions as zombies for configurable TTL (default 90s)
- Validate resume with constant-time comparison (`hmac.compare_digest`)
- Rotate resumeToken on successful resume
- Return -32011 ResumeFailed for: unknown session, bad token, TTL elapsed, cross-app, unclaimed zombie

**DC-025 GatewayManifestWatcher** (`gateway/manifest_watcher.py`):
- Watch `~/.tesseron/instances/` for manifest files
- Detect stale manifests by checking if pid process is still running
- Trigger gateway to dial discovered desktop apps

**Target tests:** GW-74 through GW-92

### Phase 6: Integration Tests

Wire everything together and ensure cross-cutting tests pass.

**Target tests:** GW-93 through GW-97

## Key Design Decisions

### Reuse the existing JsonRpcDispatcher
The gateway speaks JSON-RPC to apps. Use the existing `dispatcher.py` — one dispatcher instance per app connection. Don't build a separate gateway dispatcher.

### FastMCP for MCP side
Import FastMCP and use its decorator API for tool/resource registration. The gateway IS a FastMCP server that happens to bridge to Tesseron apps.

### Claim codes use secrets module
`secrets.choice()` from the `secrets` module provides CSPRNG. Don't use `random` — claim codes are security-sensitive.

### Constant-time token comparison
Resume token validation MUST use `hmac.compare_digest` to prevent timing attacks. Don't use `==`.

### asyncio for concurrency
Multiple app sessions, concurrent invocations, timeout racing — all use `asyncio`. Use `asyncio.wait_for` for timeouts, `asyncio.create_task` for concurrent handlers, `asyncio.Event` for cancellation signals.

## Traceability in Source Code

Every module docstring must reference its DC:
```python
"""Gateway WebSocket server.

Design Contract: DC-018 (GatewayWebSocketServer)
Spec Reference: §3.2, §16.1
"""
```

Every public function must reference REQ-NNN in its docstring.

## Quality Gates

After each phase:
```bash
uv run pytest --tb=short -q          # tests pass, xfails decrease
uv run ruff check src/ tests/        # lint clean
uv run ruff format --check src/ tests/  # format clean
uv run mypy src/ --ignore-missing-imports  # type clean
```

**Final target:** 277 passed (180 + 97), 0 xfailed.

## Git

```bash
KINDLED_REPO="$HOME/kindled_projects/python-tesseron"
```

Use `git -C "$KINDLED_REPO"` for all git operations. Use `$HOME` not `~`. Do NOT pipe git output through `tail`/`head`. Stage specific files, not `git add -A`. One commit per phase.

Branch: `cora/gateway-implementation` (already created).

Do NOT create a PR — the engineering lead (Cora) will review and create it.

```
Co-Authored-By: Cora <cora-2f1e43dc@sjstargetedsolutions.co.nz>
```
