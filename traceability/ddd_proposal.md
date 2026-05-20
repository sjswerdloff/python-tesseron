# DDD Proposal for python-tesseron — AI-proposed, awaiting human curation

**Sprint 1: Implicit Spec Recovery**
Generated from code-graph analysis (859 symbols, 1028 calls, 360 imports).

## Proposed Bounded Contexts

| ID | Name | Classification | Modules |
|---|---|---|---|
| BC-PT-001 | AppSDK | Core | actions, cancellation, capabilities, context, elicitation, manifest, resources, resume, sampling, session |
| BC-PT-002 | Gateway | Core | gateway/* (action_router, elicitation_bridge, manifest_watcher, mcp_bridge, resume, sampling_bridge, server, session) |
| BC-PT-003 | Transport | Supporting | transport_uds, transport_ws, transport_ws_client, transport_ws_pyodide |
| BC-PT-004 | Protocol | Generic | dispatcher, errors, types |

## Proposed DC → BC Mapping

Once `bounded_context_id` column is added via migration tool:

| DC | Title | Bounded Context |
|---|---|---|
| DC-001 | JsonRpcDispatcher | BC-PT-004 (Protocol) |
| DC-002 | WebSocketTransport | BC-PT-003 (Transport) |
| DC-003 | UdsTransport | BC-PT-003 (Transport) |
| DC-004 | SessionStateMachine | BC-PT-001 (AppSDK) |
| DC-005 | HandshakeManager | BC-PT-001 (AppSDK) |
| DC-006 | ActionRegistry | BC-PT-001 (AppSDK) |
| DC-007 | ResourceManager | BC-PT-001 (AppSDK) |
| DC-008 | ProgressCancellation | BC-PT-001 (AppSDK) |
| DC-009 | SamplingBridge | BC-PT-001 (AppSDK) |
| DC-010 | ElicitationBridge | BC-PT-001 (AppSDK) |
| DC-011 | CapabilityNegotiation | BC-PT-001 (AppSDK) |
| DC-012 | ErrorModel | BC-PT-004 (Protocol) |
| DC-013 | DiscoveryManifest | BC-PT-001 (AppSDK) |
| DC-014 | SessionResume | BC-PT-001 (AppSDK) |
| DC-015 | TypeDefinitions | BC-PT-004 (Protocol) |
| DC-016 | ActionContext | BC-PT-001 (AppSDK) |
| DC-017 | PyodideWebSocketTransport | BC-PT-003 (Transport) |
| DC-018 | GatewayWebSocketServer | BC-PT-002 (Gateway) |
| DC-019 | GatewaySessionManager | BC-PT-002 (Gateway) |
| DC-020 | GatewayMcpBridge | BC-PT-002 (Gateway) |
| DC-021 | GatewayActionRouter | BC-PT-002 (Gateway) |
| DC-022 | GatewaySamplingBridge | BC-PT-002 (Gateway) |
| DC-023 | GatewayElicitationBridge | BC-PT-002 (Gateway) |
| DC-024 | GatewayResumeManager | BC-PT-002 (Gateway) |
| DC-025 | GatewayManifestWatcher | BC-PT-002 (Gateway) |

## Context Map

| From → To | Pattern | Rationale |
|---|---|---|
| Gateway → Protocol | Customer-Supplier | Gateway consumes Protocol types and dispatcher |
| AppSDK → Protocol | Customer-Supplier | AppSDK consumes Protocol types and dispatcher |
| Gateway → Transport | Customer-Supplier | Gateway uses Transport for WebSocket server connections |
| AppSDK → Transport | Customer-Supplier | AppSDK uses Transport for UDS/WebSocket client connections |
| Gateway ↔ AppSDK | Separate-Ways | No direct code sharing; communicate only via Tesseron wire protocol |

## Key Term Collisions Found (validates the DDD need)

| Term | In AppSDK | In Gateway | Why this matters |
|---|---|---|---|
| session | App-side state machine (handshake→claim→close) | Server-side per-connection tracking | Code has `session.py` AND `gateway/session.py` with different classes |
| invoke | Execute local action handler | Route MCP tool call to remote app | `actions.py:invoke` vs `gateway/action_router.py:invoke` — same name, different semantics |
| resume | Client reconnection with stored credentials | Server-side zombie recovery and replay | `resume.py` AND `gateway/resume.py` with different classes |
| manifest | App's discovery document served locally | Gateway's filesystem watcher for discovery | `manifest.py` vs `gateway/manifest_watcher.py` |

These are exactly the conflations that caused confusion during development (Cyril's gateway/SDK confusion).

## Curation needed

- [ ] Are the four BCs correct? Should any be split or merged?
- [ ] Are the DC → BC assignments right?
- [ ] Domain terms: any missing? Any aliases_to_avoid wrong?
- [ ] Context map: are the relationship patterns correct?
