# Gateway Test Specifications

Source: Gateway Requirements REQ-108 through REQ-147, Design Contracts DC-018 through DC-025

Test ID prefix: GW-

## Systematic Test Design Techniques Applied

| Design Contract | Primary Technique | Secondary Technique | Rationale |
|----------------|-------------------|---------------------|-----------|
| DC-018 WebSocket Server | Equivalence Partitioning | BVA | Subprotocol valid/invalid classes, loopback boundary |
| DC-019 Session Manager | State Transition Testing | Decision Table | Session state machine + capability intersection matrix |
| DC-020 MCP Bridge | Equivalence Partitioning | Cause-Effect Graphing | Tool naming patterns, notification trigger conditions |
| DC-021 Action Router | BVA | State Transition | Timeout boundaries, action invocation lifecycle |
| DC-022 Sampling Bridge | BVA | Decision Table | Depth boundary (3), capability x depth matrix |
| DC-023 Elicitation Bridge | Equivalence Partitioning | Decision Table | Action types, capability x schema validity matrix |
| DC-024 Resume Manager | BVA | State Transition | TTL boundary, zombie session lifecycle |
| DC-025 Manifest Watcher | State Transition | Equivalence Partitioning | Manifest lifecycle, valid/stale/missing classes |

---

## DC-018: GatewayWebSocketServer

### Connection Acceptance (REQ-108)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-01 | Accept inbound WebSocket with tesseron-gateway subprotocol | Connect with correct subprotocol, verify connection accepted and delegated to session manager |
| GW-02 | Accept multiple simultaneous inbound connections | Open 3 connections sequentially, verify all accepted with independent sessions |

### Subprotocol Validation (REQ-109)

EP: {valid subprotocol, no subprotocol, wrong subprotocol}

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-03 | Reject connection without subprotocol | Connect without requesting subprotocol, verify connection rejected |
| GW-04 | Reject connection with wrong subprotocol | Connect with "graphql-ws" subprotocol, verify connection rejected |

### Loopback Enforcement (REQ-138)

EP: {loopback URLs, non-loopback URLs}

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-05 | Accept loopback manifest URL | Manifest with ws://127.0.0.1:PORT or ws://localhost:PORT, verify gateway connects |
| GW-06 | Refuse non-loopback manifest URL | Manifest with ws://192.168.1.100:PORT, verify gateway refuses connection |
| GW-07 | Refuse public hostname manifest URL | Manifest with ws://example.com:PORT, verify gateway refuses connection |

---

## DC-019: GatewaySessionManager

### Session State Machine (REQ-141)

States: DISCONNECTED (S1), HANDSHAKING (S2), AWAITING_CLAIM (S3), CLAIMED (S4), CLOSED (S5)

#### Valid Transitions

| Test ID | From | To | Trigger | Verification |
|---------|------|-----|---------|--------------|
| GW-08 | S1 DISCONNECTED | S2 HANDSHAKING | App opens WebSocket | Session created in HANDSHAKING state |
| GW-09 | S2 HANDSHAKING | S3 AWAITING_CLAIM | Gateway processes hello, returns welcome | Session transitions to AWAITING_CLAIM, welcome contains claimCode |
| GW-10 | S3 AWAITING_CLAIM | S4 CLAIMED | Agent submits correct claim code | Session transitions to CLAIMED, claimed notification sent |
| GW-11 | S3 AWAITING_CLAIM | S5 CLOSED | Transport closes before claim | Session transitions to CLOSED, resources cleaned up |
| GW-12 | S4 CLAIMED | S5 CLOSED | Transport closes | Session transitions to CLOSED, pending rejected, subscriptions cleaned |

#### Invalid Transitions

| Test ID | From | Attempted | Verification |
|---------|------|-----------|--------------|
| GW-13 | S2 HANDSHAKING | S4 CLAIMED | Claim attempt before welcome returns error or is impossible |
| GW-14 | S4 CLAIMED | S3 AWAITING_CLAIM | No mechanism to revert to awaiting claim |
| GW-15 | S5 CLOSED | S4 CLAIMED | Claim on closed session rejected |

### Hello/Welcome Exchange (REQ-113)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-16 | Welcome contains all required fields | Send hello, verify welcome response has sessionId, protocolVersion, capabilities, claimCode, resumeToken |
| GW-17 | sessionId is unique per session | Open two sessions, verify different sessionIds |

### Claim Code Generation (REQ-110, REQ-111, REQ-112)

BVA on format: exactly XXXX-XX, characters from 31-char alphabet (ABCDEFGHJKMNPQRSTUVWXYZ23456789)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-18 | Claim code matches XXXX-XX format | Generate claim code, verify regex ^[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{4}-[ABCDEFGHJKMNPQRSTUVWXYZ23456789]{2}$ |
| GW-19 | Claim code excludes ambiguous characters | Generate 100 claim codes, verify none contain O, 0, 1, I, or L |
| GW-20 | Claim code printed to stderr | Capture stderr during hello, verify claim code appears |
| GW-21 | Successful claim consumes code | Claim with correct code, attempt second claim with same code, verify rejection |
| GW-22 | Wrong claim code rejected with -32009 | Submit incorrect claim code, verify -32009 Unauthorized (REQ-137) |

### Capability Intersection (REQ-114)

Decision table: 4 capabilities (streaming, subscriptions, sampling, elicitation) x 2 sides (app, agent)

| Test ID | App Capabilities | Agent Capabilities | Expected Intersection | Verification |
|---------|-----------------|-------------------|----------------------|--------------|
| GW-23 | all four true | all four true | all four true | Full intersection |
| GW-24 | sampling=false, rest true | all four true | sampling=false, rest true | App limitation respected |
| GW-25 | all four true | sampling=false, elicitation=false | sampling=false, elicitation=false | Agent limitation respected |
| GW-26 | sampling=true only | elicitation=true only | all false | Disjoint capabilities produce empty intersection |

### Claimed Notification (REQ-115)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-27 | App receives claimed notification after claim | After successful claim, verify app receives tesseron/claimed with agent identity, claimedAt, agentCapabilities |

### Protocol Version Validation (REQ-116)

BVA on major version boundary

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-28 | Major version mismatch rejected with -32000 | Send hello with protocolVersion "2.0", verify -32000 ProtocolMismatch and connection closed |
| GW-29 | Minor version mismatch accepted | Send hello with protocolVersion "1.1" (same major, different minor), verify welcome returned |

### Multiple Simultaneous Sessions (REQ-139)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-30 | Separate sessions with independent state | Connect two apps, verify each gets own sessionId, claimCode, claim state |
| GW-31 | Claiming one session does not affect another | Claim session A, verify session B still in AWAITING_CLAIM |

### Transport Close Behavior (REQ-142, REQ-143, REQ-144)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-32 | Pending outbound requests rejected on close | Send request to app, close transport before response, verify TransportClosedError (REQ-142) |
| GW-33 | In-flight invocations cancelled on close | Start long action, close transport, verify cancellation signal fired (REQ-143) |
| GW-34 | Active subscriptions cleaned on close | Subscribe to resource, close transport, verify cleanup function called (REQ-144) |

### Authorization (REQ-136)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-35 | Action invocation on unclaimed session rejected | Send action invoke before claiming, verify -32009 Unauthorized |

---

## DC-020: GatewayMcpBridge

### Tool Registration (REQ-117)

EP: {single action, multiple actions, action with underscores in name}

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-36 | Actions registered as app_id__action_name MCP tools | App declares action "do_thing", verify MCP tool registered as "myapp__do_thing" with double-underscore separator |
| GW-37 | Multiple actions from same app all registered | App declares 3 actions, verify all 3 appear as MCP tools with correct prefix |
| GW-38 | Action name with underscores preserved | App declares "do_complex_thing", verify tool name "myapp__do_complex_thing" -- separator is double underscore, single underscores in action name are preserved |

### Meta-Tools (REQ-118, REQ-119, REQ-120)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-39 | tesseron__claim_session tool exists and accepts code | List MCP tools, verify tesseron__claim_session present; invoke with valid code, verify claim succeeds |
| GW-40 | tesseron__list_actions lists all claimed actions and resources | Claim session with actions and resources, invoke tesseron__list_actions, verify complete listing |
| GW-41 | tesseron__list_pending_claims lists pending claim codes | Create two sessions without claiming, invoke tesseron__list_pending_claims, verify both pending codes listed |

### Resource Exposure (REQ-129)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-42 | Resources exposed with tesseron://app_id/resource_name URI | App declares resource "config", verify MCP resource at tesseron://myapp/config |

### Dynamic Notifications (REQ-130, REQ-131)

Cause-Effect: session events -> notification emissions

| Test ID | Trigger | Expected Notification | Verification |
|---------|---------|----------------------|--------------|
| GW-43 | App session connects | tools/list_changed | Verify notification emitted on connect (REQ-130) |
| GW-44 | App session claimed | tools/list_changed | Verify notification emitted on claim (REQ-130) |
| GW-45 | App session drops | tools/list_changed | Verify notification emitted on drop (REQ-130) |
| GW-46 | App resource added | resources/list_changed | Verify notification emitted (REQ-131) |
| GW-47 | App resource removed | resources/list_changed | Verify notification emitted (REQ-131) |

### Log Forwarding (REQ-128)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-48 | App log forwarded as MCP sendLoggingMessage | App emits log notification, verify MCP receives sendLoggingMessage with logger=app_id |

### Foundation (REQ-145)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-49 | FastMCP used as MCP server | Structural: verify gateway MCP server is instance of FastMCP (or uses FastMCP API) |

---

## DC-021: GatewayActionRouter

### Routing (REQ-140, REQ-121)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-50 | Tool call routed to correct app by app_id prefix | Two apps connected, invoke myapp_a__action, verify routed to app A not app B (REQ-140) |
| GW-51 | actions/invoke forwarded as JSON-RPC request | Invoke tool, verify app receives actions/invoke with correct params (REQ-121) |
| GW-52 | Unknown app_id prefix returns ActionNotFoundError | Invoke "nonexistent_app__action", verify -32003 |

### Progress Forwarding (REQ-122)

EP: {progressToken supplied, progressToken absent}

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-53 | actions/progress forwarded when progressToken supplied | Invoke with progressToken, app sends progress, verify MCP notifications/progress received |
| GW-54 | actions/progress not forwarded when no progressToken | Invoke without progressToken, app sends progress, verify no MCP notification |

### Cancellation (REQ-123)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-55 | actions/cancel sent on agent cancellation | Start action, agent cancels, verify app receives actions/cancel |
| GW-56 | actions/cancel sent on timeout | Start action, wait for timeout, verify app receives actions/cancel |

### Timeout (REQ-124)

BVA on timeout: default 60000ms, custom values

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-57 | Default 60000ms timeout enforced | Invoke action without timeoutMs, action takes >60s, verify -32002 Timeout |
| GW-58 | Custom timeoutMs respected | Invoke with timeoutMs=1000, action takes >1s, verify -32002 after ~1s |
| GW-59 | Action completing before timeout succeeds | Invoke with timeoutMs=5000, action completes in 100ms, verify success (no timeout) |

### Authorization (REQ-136)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-60 | Invocation on unclaimed session rejected | Route tool call to unclaimed session, verify -32009 Unauthorized |

---

## DC-022: GatewaySamplingBridge

### Translation (REQ-125)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-61 | sampling/request translated to MCP sampling/createMessage | App sends sampling/request, verify gateway sends MCP sampling/createMessage with translated params |
| GW-62 | LLM response returned to app | MCP sampling returns response, verify app receives result |

### Depth Tracking (REQ-126)

BVA on maxSamplingDepth=3: test at 1, 3 (boundary), 4 (boundary+1)

| Test ID | Depth | Expected | Verification |
|---------|-------|----------|--------------|
| GW-63 | 1 | Success | Single sampling request succeeds |
| GW-64 | 3 | Success | Sampling at max depth succeeds (boundary) |
| GW-65 | 4 | -32008 | Sampling exceeding max depth fails (boundary+1) |
| GW-66 | 4 | Error data | Verify error includes {depth: 4, max: 3} in data field |

### Capability Gating

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-67 | SamplingNotAvailableError when agent lacks capability | Agent without sampling capability, app sends sampling/request, verify -32006 |

---

## DC-023: GatewayElicitationBridge

### Translation (REQ-127)

EP on action result: {accept, decline, cancel} x {with value, without value}

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-68 | elicitation/request translated to MCP elicitInput | App sends elicitation/request, verify gateway sends MCP elicitInput with question and schema |
| GW-69 | Accept with value returned to app | User accepts with value, verify app receives ElicitationResult action=accept with value |
| GW-70 | Decline returned to app | User declines, verify app receives ElicitationResult action=decline |
| GW-71 | Cancel returned to app | User cancels, verify app receives ElicitationResult action=cancel |

### Capability Gating

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-72 | ElicitationNotAvailableError when agent lacks capability | Agent without elicitation capability, app sends elicitation/request, verify -32007 |

### Schema Validation

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-73 | InvalidParamsError on schema constraint violations | App sends elicitation with invalid schema (e.g., non-object type, combinators), verify -32602 |

---

## DC-024: GatewayResumeManager

### Zombie Retention (REQ-132)

BVA on TTL: default 90s, at boundary, past boundary

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-74 | Disconnected session retained as zombie | Disconnect claimed session, verify session retained (not immediately destroyed) |
| GW-75 | Default TTL is 90 seconds | Disconnect, resume at 85s (within TTL), verify success |
| GW-76 | Resume at TTL boundary succeeds | Disconnect, resume at exactly 90s, verify success |
| GW-77 | Resume after TTL fails | Disconnect, resume at 91s, verify -32011 ResumeFailed (REQ-135) |
| GW-78 | Configurable TTL respected | Set TTL to 30s, disconnect, resume at 35s, verify -32011 |

### Token Validation (REQ-133, REQ-134)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-79 | Constant-time token comparison | Verify implementation uses hmac.compare_digest or equivalent (structural/timing test) |
| GW-80 | Successful resume returns rotated token | Resume successfully, verify new resumeToken in response |
| GW-81 | Rotated token different from original | Compare original and rotated tokens, verify they differ |
| GW-82 | Old token rejected after rotation | Resume with original token after rotation, verify -32011 |

### Resume Failure Conditions (REQ-135)

EP on failure conditions: {unknown session, bad token, TTL elapsed, cross-app, unclaimed zombie}

| Test ID | Failure Condition | Verification |
|---------|------------------|--------------|
| GW-83 | Unknown sessionId | Resume with fabricated sessionId, verify -32011 with appropriate message |
| GW-84 | Bad resumeToken | Resume with wrong token, verify -32011 |
| GW-85 | TTL elapsed | Resume after TTL, verify -32011 (covered by GW-77, cross-referenced) |
| GW-86 | Cross-app resume | App A's session, resume from app B, verify -32011 |
| GW-87 | Unclaimed zombie | Disconnect before claiming, attempt resume, verify -32011 |

---

## DC-025: GatewayManifestWatcher

### Directory Watching (REQ-146)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-88 | Watches ~/.tesseron/instances/ for manifests | Write manifest file to directory, verify watcher detects it |
| GW-89 | Discovered manifest triggers app dial | Write valid manifest with loopback WS URL, verify gateway initiates connection |

### Stale Detection (REQ-147)

EP: {running pid, dead pid}

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-90 | Running pid not flagged stale | Manifest with pid of running process, verify not treated as stale |
| GW-91 | Dead pid flagged stale | Manifest with pid of non-existent process, verify flagged stale |

### Error Handling

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| GW-92 | Missing discovery directory handled | Remove ~/.tesseron/instances/, verify FileNotFoundError or graceful creation |

---

## Cross-Cutting Tests

These tests verify behavior that spans multiple design contracts.

### Multi-App Isolation

| Test ID | Contracts | Verification |
|---------|-----------|--------------|
| GW-93 | DC-019, DC-020, DC-021 | Actions from app A never reach app B -- invoke myapp_a__action, verify app B receives nothing |
| GW-94 | DC-019, DC-024 | Zombie session for app A does not block app B connections |

### Concurrent Operations

| Test ID | Contracts | Verification |
|---------|-----------|--------------|
| GW-95 | DC-019 | Concurrent claim attempts on same session -- only first succeeds, second gets -32009 |
| GW-96 | DC-021 | Concurrent action invocations on same session -- both routed correctly without interference |

### End-to-End Gateway Flow

| Test ID | Contracts | Verification |
|---------|-----------|--------------|
| GW-97 | DC-018 through DC-021 | Full lifecycle: app connects via WS, hello/welcome, agent claims via meta-tool, agent invokes action, app returns result, agent receives result |

---

## Gap Analysis

### Requirements Fully Covered by Test Specs

All 40 gateway requirements (REQ-108 through REQ-147) have at least one test specification.

### Coverage Summary

| Design Contract | Test Count | Requirements Covered |
|----------------|-----------|---------------------|
| DC-018 GatewayWebSocketServer | 7 (GW-01 through GW-07) | REQ-108, REQ-109, REQ-138 |
| DC-019 GatewaySessionManager | 28 (GW-08 through GW-35) | REQ-110-116, REQ-136, REQ-137, REQ-139, REQ-141-144 |
| DC-020 GatewayMcpBridge | 14 (GW-36 through GW-49) | REQ-117-120, REQ-128-131, REQ-145 |
| DC-021 GatewayActionRouter | 11 (GW-50 through GW-60) | REQ-121-124, REQ-136, REQ-140 |
| DC-022 GatewaySamplingBridge | 7 (GW-61 through GW-67) | REQ-125, REQ-126 |
| DC-023 GatewayElicitationBridge | 6 (GW-68 through GW-73) | REQ-127 |
| DC-024 GatewayResumeManager | 14 (GW-74 through GW-87) | REQ-132-135 |
| DC-025 GatewayManifestWatcher | 5 (GW-88 through GW-92) | REQ-146, REQ-147 |
| Cross-cutting | 5 (GW-93 through GW-97) | Spans multiple |
| **Total** | **97** | **40/40 requirements** |

### Techniques Applied Per Test

| Technique | Tests Using It |
|-----------|---------------|
| Equivalence Partitioning | GW-03/04, GW-05/06/07, GW-19, GW-36/37/38, GW-53/54, GW-69/70/71, GW-83-87, GW-90/91 |
| Boundary Value Analysis | GW-18/19, GW-28/29, GW-57/58/59, GW-63-66, GW-75-78 |
| State Transition Testing | GW-08-15, GW-74, GW-88/89 |
| Decision Table | GW-23-26 |
| Cause-Effect Graphing | GW-43-47 |
