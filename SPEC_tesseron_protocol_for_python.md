# Tesseron Protocol Specification for Python Implementation

**Version:** 1.2.0 (protocol version on the wire)
**License:** This specification is derived from the Tesseron protocol documentation, licensed CC BY 4.0.
**Attribution:** Tesseron (Kenny Vaneetvelde), https://github.com/BrainBlend-AI/tesseron
**Purpose:** Complete specification for implementing a Python Tesseron SDK using FastMCP, Pydantic, and asyncio. The implementer MUST NOT consult the TypeScript reference implementation.
**Date:** 2026-05-11

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Wire Format (JSON-RPC 2.0)](#2-wire-format-json-rpc-20)
3. [Transport Bindings](#3-transport-bindings)
4. [Discovery and Instance Manifests](#4-discovery-and-instance-manifests)
5. [Handshake and Claiming](#5-handshake-and-claiming)
6. [Session Resume](#6-session-resume)
7. [Action Model](#7-action-model)
8. [Progress and Cancellation](#8-progress-and-cancellation)
9. [Sampling](#9-sampling)
10. [Elicitation](#10-elicitation)
11. [Resources](#11-resources)
12. [Capability Negotiation](#12-capability-negotiation)
13. [Error Model](#13-error-model)
14. [Session Lifecycle State Machine](#14-session-lifecycle-state-machine)
15. [MCP Integration Contract](#15-mcp-integration-contract)
16. [Security Model](#16-security-model)
17. [Protocol Constants](#17-protocol-constants)
18. [Acceptance Test Scenarios](#18-acceptance-test-scenarios)

---

## 1. Architecture Overview

Tesseron connects three processes:

```
YOUR APP <---> MCP GATEWAY <---> AGENT (Claude Code, etc.)
  (Python)    (JSON-RPC/WS)    (MCP stdio)
```

**Your App** (the Python process this SDK implements):
- Hosts a local endpoint (WebSocket on loopback, or Unix domain socket)
- Declares typed actions (operations the agent can invoke) and resources (state the agent can read)
- Writes a discovery manifest to `~/.tesseron/instances/`
- Waits for the gateway to dial in

**The MCP Gateway** (`@tesseron/mcp`, a Node.js process):
- Watches `~/.tesseron/instances/` for app manifests
- Dials each discovered app via the binding advertised in its manifest
- Runs an MCP stdio server that the agent connects to
- Translates between Tesseron JSON-RPC and MCP
- Manages claim codes, session state, sampling/elicitation bridging

**The Agent** (Claude Code, Cursor, etc.):
- Sees Tesseron actions as standard MCP tools
- Sees Tesseron resources as standard MCP resources
- Never knows about Tesseron directly -- the gateway abstracts everything

### Two Protocols, Two Hops

| Hop | Protocol | Transport |
|-----|----------|-----------|
| App <-> Gateway | Tesseron JSON-RPC 2.0 | WebSocket or Unix domain socket |
| Gateway <-> Agent | Model Context Protocol (MCP) | stdio |

The gateway is the ONLY component that speaks both dialects. The Python SDK speaks only Tesseron JSON-RPC.

### Who Connects to Whom

**Apps bind. The gateway dials.**

The app creates a local server (WS or UDS), writes a manifest, and waits. The gateway discovers the manifest, connects as a client, and the app accepts exactly one inbound connection. The gateway never binds a port of its own.

---

## 2. Wire Format (JSON-RPC 2.0)

Tesseron speaks JSON-RPC 2.0. One JSON object per WebSocket text frame (or per newline-terminated line over UDS). No batching, no binary, no compression.

### 2.1 Envelope Shapes

Every message on the wire is exactly one of four shapes:

#### Request (expects a response)

```json
{
  "jsonrpc": "2.0",
  "id": 42,
  "method": "actions/invoke",
  "params": { ... }
}
```

#### Notification (fire-and-forget, no response)

```json
{
  "jsonrpc": "2.0",
  "method": "actions/progress",
  "params": { "invocationId": "inv_1", "percent": 40 }
}
```

Notifications have NO `id` field. They MUST NOT receive a response.

#### Success Response

```json
{
  "jsonrpc": "2.0",
  "id": 42,
  "result": { ... }
}
```

#### Error Response

```json
{
  "jsonrpc": "2.0",
  "id": 42,
  "error": { "code": -32004, "message": "Invalid input", "data": [...] }
}
```

### 2.2 ID Rules

- `id` MAY be a string, number, or `null`.
- The SDK SHOULD use monotonically incrementing integers.
- The peer that issues a request assigns the `id`. The responding peer MUST echo the exact same `id`.
- The SDK MUST maintain a map of pending outbound requests keyed by `id`. On response, look up the `id`, resolve or reject, and remove the entry.
- On transport close, ALL pending requests MUST be rejected with a `TransportClosedError`.

### 2.3 Method Surface

#### App -> Gateway (you send)

| Method | Kind | Purpose |
|--------|------|---------|
| `tesseron/hello` | request | Register app, actions, resources, capabilities. MUST be the first message. |
| `tesseron/resume` | request | Rejoin a previously-claimed session (alternative first message). |
| `actions/progress` | notification | Streaming update during an invocation. |
| `actions/list_changed` | notification | App registered/removed an action after hello. |
| `resources/updated` | notification | Push a new value to a subscriber. |
| `resources/list_changed` | notification | App registered/removed a resource after hello. |
| `sampling/request` | request | Ask the agent to run an LLM step. |
| `elicitation/request` | request | Ask the user for confirmation or structured input. |
| `log` | notification | Structured log forwarded to MCP logging. |

Plus: the **response** for any `actions/invoke`, `resources/read`, `resources/subscribe`, `resources/unsubscribe` the gateway sent you.

#### Gateway -> App (you handle)

| Method | Kind | Purpose |
|--------|------|---------|
| `actions/invoke` | request | Agent called an action. Respond with `result` or `error`. |
| `actions/cancel` | notification | Agent cancelled an in-flight invocation. |
| `resources/read` | request | Agent requested current resource value. |
| `resources/subscribe` | request | Agent subscribed to future updates. |
| `resources/unsubscribe` | request | Agent unsubscribed. |

And the **response** to your `tesseron/hello` or `tesseron/resume`.

---

## 3. Transport Bindings

### 3.1 Binding-Neutral Contract

Every transport binding MUST provide:

1. **Reliable, ordered delivery.** No best-effort, no reordering, no gaps.
2. **One JSON-RPC envelope per logical message.** No batching, no visible fragmentation.
3. **Symmetric duplex.** Either side can send at any time.
4. **Single connection per session.** `tesseron/hello` opens; close terminates the session.
5. **Same-process / same-user threat model.** The binding is local IPC.

### 3.2 WebSocket Binding

The default transport for Tesseron.

**Framing:**
- One JSON-RPC envelope per WebSocket text frame.
- `json.dumps()` on send, `json.loads()` on receive.
- No fragmentation, no batching, no compression.
- Binary frames SHOULD be coerced to UTF-8 text and parsed (defensive tolerance).

**Subprotocol:**
- The gateway sends `Sec-WebSocket-Protocol: tesseron-gateway` on its upgrade request.
- The app MUST advertise this subprotocol in its handshake response.
- The app MUST reject upgrade requests that do not carry the `tesseron-gateway` subprotocol.

**Binding rules:**
- The app MUST bind to loopback only (`127.0.0.1` or `::1`).
- The app MUST accept exactly one upgrade that carries `tesseron-gateway`; reject all others.
- The app writes `~/.tesseron/instances/<instanceId>.json` with `{ "kind": "ws", "url": "ws://127.0.0.1:<port>/" }`.
- The app deletes its manifest on close.

### 3.3 Unix Domain Socket (UDS) Binding

Lower-overhead local IPC. Linux and macOS only.

**Framing:**
- NDJSON: one JSON-RPC envelope per `\n`-terminated line.
- `json.dumps(msg) + '\n'` on send.
- Buffer inbound bytes and split on `\n` on receive. Empty lines are ignored.
- No batching, no fragmentation, no compression.

**Access control:**
- The app MUST create a private directory (mode `0o700`) under the system temp directory.
- The app MUST bind a socket inside that directory.
- The app SHOULD `chmod 0o600` the socket file after `bind()`.
- These permissions gate same-UID access; cross-UID isolation is the OS's job.

**Binding rules:**
- Accept exactly one connection; reject subsequent connect attempts.
- Write `~/.tesseron/instances/<instanceId>.json` with `{ "kind": "uds", "path": "/tmp/tesseron-xxx/sock" }`.
- Delete the manifest, socket file, and temp directory on close.

### 3.4 No Application-Level Heartbeat

The protocol relies on the underlying binding's keep-alive mechanism and per-action timeouts (default 60,000 ms) to detect dead peers.

---

## 4. Discovery and Instance Manifests

### 4.1 Manifest Format (v2)

Every running app writes a JSON file to `~/.tesseron/instances/<instanceId>.json`:

```json
{
  "version": 2,
  "instanceId": "inst-abc123",
  "appName": "my_python_app",
  "addedAt": 1714145210123,
  "pid": 12345,
  "transport": { "kind": "ws", "url": "ws://127.0.0.1:64872/" }
}
```

Or for UDS:

```json
{
  "version": 2,
  "instanceId": "inst-abc123",
  "appName": "my_python_app",
  "addedAt": 1714145210123,
  "pid": 12345,
  "transport": { "kind": "uds", "path": "/tmp/tesseron-Xy7/sock" }
}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | integer | yes | MUST be `2`. |
| `instanceId` | string | yes | Unique ID for this running instance. Generate a random string. |
| `appName` | string | yes | Human-readable name for logging. |
| `addedAt` | integer | yes | Unix epoch milliseconds when manifest was written. |
| `pid` | integer | no | Process ID of the SDK process. When present, the gateway can detect stale manifests. |
| `transport` | object | yes | Discriminated union: `{ "kind": "ws", "url": "..." }` or `{ "kind": "uds", "path": "..." }`. |

### 4.2 Discovery Directory

- Primary: `~/.tesseron/instances/`
- Legacy (v1 compat): `~/.tesseron/tabs/`
- The directories MUST be created with mode `0o700` if they do not exist.
- Manifest files MUST be written with mode `0o600`.

### 4.3 Instance ID Generation

The `instanceId` SHOULD be a random string prefixed with `inst-`. Example: `inst-a1b2c3d4-e5f6`.

### 4.4 Cleanup

The app MUST delete its manifest file on graceful shutdown. On `SIGINT` and `SIGTERM`, the app SHOULD clean up the manifest, close the transport, and exit.

---

## 5. Handshake and Claiming

### 5.1 Connection Flow

1. App opens transport binding (binds WS server or UDS socket).
2. App writes instance manifest.
3. Gateway discovers manifest, dials the app.
4. App accepts the connection.
5. App sends `tesseron/hello` as the FIRST message.
6. Gateway responds with `welcome` (including a claim code).
7. Gateway prints the claim code to its stderr.
8. The user reads the code and tells their agent: "Claim Tesseron session AB3X-7K".
9. The agent calls the built-in `tesseron__claim_session` MCP tool.
10. Gateway marks the session as claimed, emits `notifications/tools/list_changed`.
11. From this point, the agent can invoke the app's actions.

### 5.2 The `tesseron/hello` Request

Sent by the app immediately after the connection is established.

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tesseron/hello",
  "params": {
    "protocolVersion": "1.2.0",
    "app": {
      "id": "my_app",
      "name": "My Application",
      "description": "Does useful things",
      "origin": "http://localhost:8000",
      "version": "1.0.0"
    },
    "actions": [
      {
        "name": "doSomething",
        "description": "Performs the operation",
        "inputSchema": { "type": "object", "properties": { "param1": { "type": "string" } }, "required": ["param1"] },
        "outputSchema": { "type": "object", "properties": { "result": { "type": "string" } } },
        "annotations": { "readOnly": false },
        "timeoutMs": 60000
      }
    ],
    "resources": [
      {
        "name": "currentState",
        "description": "The current application state",
        "subscribable": true
      }
    ],
    "capabilities": {
      "streaming": true,
      "subscriptions": true,
      "sampling": true,
      "elicitation": true
    }
  }
}
```

**HelloParams fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `protocolVersion` | string | yes | MUST be `"1.2.0"`. |
| `app` | AppMetadata | yes | App identity. |
| `actions` | ActionManifestEntry[] | yes | List of declared actions (may be empty). |
| `resources` | ResourceManifestEntry[] | yes | List of declared resources (may be empty). |
| `capabilities` | TesseronCapabilities | yes | What the app can do. |

**AppMetadata:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | string | yes | MUST match `/^[a-z][a-z0-9_]*$/`. Becomes the MCP tool name prefix. |
| `name` | string | yes | Human-readable name. |
| `description` | string | no | Short description for the agent. |
| `origin` | string | yes | Informational origin identifier. For Python apps, use something like `"python:<app_id>"`. |
| `version` | string | no | App version string. Informational. |
| `iconUrl` | string | no | Absolute URL of an icon. |

**Reserved app IDs:** `tesseron`, `mcp`, `system` -- these MUST NOT be used.

**ActionManifestEntry:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Action name. |
| `description` | string | yes | Human-readable description shown to the agent. |
| `inputSchema` | JSON Schema | yes | JSON Schema for the action's input. |
| `outputSchema` | JSON Schema | no | JSON Schema for the action's output. Informational unless strict. |
| `annotations` | ActionAnnotations | no | Metadata: `readOnly`, `destructive`, `requiresConfirmation`. |
| `timeoutMs` | integer | no | Override the default 60,000 ms timeout. |

**ResourceManifestEntry:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | yes | Resource name. |
| `description` | string | yes | Human-readable description. |
| `subscribable` | boolean | yes | Whether the resource supports subscriptions. |
| `outputSchema` | JSON Schema | no | JSON Schema for the resource value. |

**TesseronCapabilities:**

| Field | Type | Description |
|-------|------|-------------|
| `streaming` | boolean | App can send/receive progress and log notifications. |
| `subscriptions` | boolean | App honours `resources/subscribe`. |
| `sampling` | boolean | App can issue `sampling/request`. |
| `elicitation` | boolean | App can issue `elicitation/request`. |

The SDK SHOULD declare all four as `true` -- the actual availability depends on the agent's capabilities, which come back in the `welcome`.

### 5.3 The `welcome` Response

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "sessionId": "s_a1b2c3de1234567",
    "protocolVersion": "1.2.0",
    "capabilities": {
      "streaming": true,
      "subscriptions": true,
      "sampling": false,
      "elicitation": true
    },
    "agent": { "id": "pending", "name": "Awaiting agent" },
    "claimCode": "AB3X-7K",
    "resumeToken": "Xk9f3nN9kOeGqR7mWpLc2v"
  }
}
```

**WelcomeResult fields:**

| Field | Type | Description |
|-------|------|-------------|
| `sessionId` | string | Opaque session identifier. Log it; use it for resume. |
| `protocolVersion` | string | Gateway's protocol version. |
| `capabilities` | TesseronCapabilities | **Intersection** of app and agent capabilities. This is what handlers MUST trust. |
| `agent` | AgentIdentity | `{ "id": "pending", "name": "Awaiting agent" }` until claimed. |
| `claimCode` | string (optional) | 6-character human-friendly code, format `XXXX-XX`. Present on `hello`, absent on `resume`. |
| `resumeToken` | string (optional) | Token for session resume. Stash it for later reconnection. |

### 5.4 Claim Code

- Format: `XXXX-XX` where characters are drawn from `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (31 characters, excluding visually confusing `0`, `1`, `I`, `L`, `O`).
- Generated using CSPRNG with rejection sampling for uniform distribution.
- Approximately 1.5 billion possible combinations.
- Single-use: a claimed code is consumed and cannot be reused.
- The code is NEVER sent on the wire from gateway to agent. The user carries it out-of-band.

### 5.5 The `tesseron/claimed` Notification

After a session is claimed, the gateway sends a notification to the app:

```json
{
  "jsonrpc": "2.0",
  "method": "tesseron/claimed",
  "params": {
    "agent": { "id": "claude-code", "name": "Claude Code" },
    "claimedAt": 1714145210123,
    "agentCapabilities": {
      "streaming": true,
      "subscriptions": true,
      "sampling": false,
      "elicitation": true
    }
  }
}
```

On receiving this notification, the SDK MUST:
1. Update the cached `WelcomeResult` with the new `agent` identity.
2. Clear the `claimCode` from the cached welcome (it has been consumed).
3. If `agentCapabilities` is present, overwrite `capabilities` in the cached welcome. This is the authoritative capability set that handlers MUST use for `ctx.agentCapabilities`.
4. Fire any registered welcome-change listeners.

### 5.6 Protocol Version Mismatch

The gateway parses `protocolVersion` as `major.minor`:

- **Different major** -> hard reject with error code `-32000 ProtocolMismatch`, WebSocket closed.
- **Different minor** -> accepted with a warning. New fields may be silently dropped.
- **Exact match** -> silent.

---

## 6. Session Resume

Session resume allows an app to rejoin a previously-claimed session after a transport drop, avoiding the need for a new claim code.

### 6.1 Resume Flow

1. On a fresh `tesseron/hello`, the gateway returns a `resumeToken` in the welcome. The app MUST stash this alongside `sessionId`.
2. When the transport drops, the gateway retains the session as a "zombie" for a configurable TTL (default: 90 seconds).
3. On reconnect, the app sends `tesseron/resume` with `{ sessionId, resumeToken }` instead of `tesseron/hello`.
4. If the token matches (constant-time comparison) and the zombie is within TTL, the gateway reattaches the session and rotates the token.
5. The app MUST persist the NEW `resumeToken` from the resume response.

### 6.2 The `tesseron/resume` Request

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tesseron/resume",
  "params": {
    "protocolVersion": "1.2.0",
    "sessionId": "s_a1b2c3de1234567",
    "resumeToken": "Xk9f3nN9kOeGqR7mWpLc2v",
    "app": { "id": "my_app", "name": "My App", "origin": "python:my_app" },
    "actions": [ ... ],
    "resources": [ ... ],
    "capabilities": { "streaming": true, "subscriptions": true, "sampling": true, "elicitation": true }
  }
}
```

`ResumeParams` carries the same `app`, `actions`, `resources`, `capabilities` as `HelloParams` because the app may have changed since the previous connection. The gateway replaces the stored manifest.

### 6.3 Resume Response

Same shape as `WelcomeResult`, but:
- `sessionId` matches the request.
- `resumeToken` is rotated (one-shot). The app MUST overwrite the stored token.
- `claimCode` is ABSENT -- the session is already claimed.
- `agent` carries the real agent identity (not `"pending"`).

### 6.4 Resume Failure

All failures surface as error code `-32011 ResumeFailed`:

| Condition | Message |
|-----------|---------|
| Unknown `sessionId` | `No resumable session "<id>"` |
| Cross-app resume (different `app.id`) | `Session "<id>" is owned by app "<other>"` |
| Unclaimed zombie | `<id> was never claimed` |
| TTL elapsed (zombie evicted) | `No resumable session "<id>"` |
| Wrong `resumeToken` | `Invalid resumeToken for session "<id>"` |

On resume failure, the SDK SHOULD clear the stored credentials and fall back to a fresh `tesseron/hello`.

### 6.5 What Resume Does NOT Do

- Does NOT replay in-flight actions. Cancelled on the gateway; the agent sees an error and can retry.
- Does NOT resurrect resource subscriptions. The SDK MUST re-subscribe after resume.
- Does NOT persist across a gateway restart. Zombies live in gateway process memory.

---

## 7. Action Model

### 7.1 Declaration

In the Python SDK, actions SHOULD be declared using decorators with Pydantic models:

```python
from pydantic import BaseModel

class AddItemInput(BaseModel):
    sku: str
    quantity: int

class AddItemOutput(BaseModel):
    cart_id: str
    item_id: str

@tesseron.action("addItem", input=AddItemInput, output=AddItemOutput)
async def add_item(input: AddItemInput, ctx: ActionContext) -> AddItemOutput:
    item = await cart.add(input.sku, input.quantity)
    return AddItemOutput(cart_id=cart.id, item_id=item.id)
```

Each action produces an `ActionDefinition` containing:

| Property | Type | Required | Default |
|----------|------|----------|---------|
| `name` | string | yes | -- |
| `description` | string | recommended | `""` |
| `inputSchema` | JSON Schema | recommended | Permissive `{ "type": "object", "additionalProperties": true }` |
| `outputSchema` | JSON Schema | optional | None |
| `annotations` | ActionAnnotations | optional | `{}` |
| `timeoutMs` | integer | optional | `60000` |
| `strictOutput` | boolean | optional | `false` |
| `handler` | callable | yes | -- |

### 7.2 Naming and MCP Tool List

The gateway registers every action as an MCP tool named `<app.id>__<action.name>`.

For `app.id = "shop"` and `action.name = "searchProducts"`, the agent sees `shop__searchProducts`.

The double-underscore `__` is the fixed separator. Multiple apps can coexist: `shop__addItem` and `admin__banUser` never collide.

### 7.3 Invocation Wire Format

**Request from gateway to app:**

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "method": "actions/invoke",
  "params": {
    "name": "addItem",
    "invocationId": "inv_abc123",
    "input": { "sku": "SKU-1", "quantity": 2 },
    "client": { "route": "/cart" }
  }
}
```

**ActionInvokeParams:**

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | The action name (without the `app.id__` prefix). |
| `invocationId` | string | Unique ID for this invocation. Used to correlate progress/cancel. |
| `input` | any | The arguments the agent passed. |
| `client` | object (optional) | `{ "route": "..." }` -- contextual metadata. |

**Success response:**

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "result": { "invocationId": "inv_abc123", "output": { "cartId": "c_1", "itemId": "i_42" } }
}
```

The result MUST contain `invocationId` and `output` fields.

**Error response:**

```json
{
  "jsonrpc": "2.0",
  "id": 7,
  "error": { "code": -32005, "message": "Cart is locked", "data": { "cartId": "c_1" } }
}
```

### 7.4 Validation

**Input validation:**
- The SDK MUST validate input against the action's Pydantic model (or JSON Schema) BEFORE invoking the handler.
- On validation failure, the SDK MUST return error code `-32004 InputValidation` with validation issues in `error.data`. The handler MUST NOT run.

**Output validation:**
- By default, output is NOT validated -- passed through as-is.
- If the action is configured with `strict_output=True`, the SDK MUST validate the return value against the output schema. On failure, return error code `-32005 HandlerError` with issues in `error.data`.

### 7.5 Annotations

| Field | Type | Meaning |
|-------|------|---------|
| `readOnly` | boolean | The action does not mutate state. Agent may parallelise or cache. |
| `destructive` | boolean | The action mutates persistent state. Agent SHOULD surface a confirmation UI. |
| `requiresConfirmation` | boolean | The action MUST NOT be called without explicit user confirmation. |

Annotations are advisory. They ride along with the MCP tool descriptor; honouring them is the agent's job.

### 7.6 Dynamic Action Registration

Actions registered AFTER the initial `tesseron/hello` MUST trigger an `actions/list_changed` notification:

```json
{
  "jsonrpc": "2.0",
  "method": "actions/list_changed",
  "params": {
    "actions": [ ... full updated action manifest ... ]
  }
}
```

The gateway forwards this as MCP `notifications/tools/list_changed` so the agent refreshes its tool list.

Similarly, removing an action MUST trigger the same notification with the updated list.

---

## 8. Progress and Cancellation

### 8.1 Progress Notifications

During an action invocation, the handler can emit progress updates via `ctx.progress()`:

```json
{
  "jsonrpc": "2.0",
  "method": "actions/progress",
  "params": {
    "invocationId": "inv_abc",
    "message": "500/2000",
    "percent": 27,
    "data": { "etaMs": 14000 }
  }
}
```

**ActionProgressParams:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `invocationId` | string | yes | Correlates to the active invocation. |
| `message` | string | no | Short status line shown to the user. |
| `percent` | number | no | Completion percentage (0-100). SHOULD increase monotonically. |
| `data` | any | no | Free-form structured data. |

All three payload fields are optional. Send any combination.

Progress is a fire-and-forget notification -- it never fails visibly.

**Guidelines:**
- Cap progress updates at approximately 2 per second.
- Do not use progress for final results (use the response), data the next handler needs, or error surfacing.

### 8.2 Cancellation

The gateway sends a cancellation notification:

```json
{
  "jsonrpc": "2.0",
  "method": "actions/cancel",
  "params": { "invocationId": "inv_abc" }
}
```

On receiving `actions/cancel`:
1. The SDK MUST fire the cancellation signal for the corresponding invocation (in Python, cancel the `asyncio.Task` or set an `asyncio.Event`).
2. The handler SHOULD check for cancellation and clean up.
3. The SDK MUST return error code `-32001 Cancelled`.

Cancellation also fires when the action's timeout expires:
1. The SDK MUST abort the invocation after `timeoutMs` milliseconds (default: 60,000).
2. The SDK MUST return error code `-32002 Timeout`.

**The wire is freed at the deadline regardless of the handler.** If the handler is stuck in a non-cancellable operation, the SDK MUST race the handler against the timeout/cancel signal. The agent receives its error response immediately; the orphaned handler may continue running but the agent is not held hostage.

### 8.3 ActionContext

Every handler receives `(input, ctx)` where `ctx` provides:

| Field/Method | Type | Description |
|-------------|------|-------------|
| `ctx.signal` | Cancellation primitive | Fires on timeout or cancel. In Python, use `asyncio.Event` or similar. |
| `ctx.agent` | `{ id: str, name: str }` | Identity of the calling agent. |
| `ctx.agent_capabilities` | AgentCapabilities | What the agent supports (sampling, elicitation, subscriptions). |
| `ctx.client` | `{ origin: str, route: str | None }` | Origin/route metadata. |
| `ctx.progress(update)` | callable | Emit a progress notification. |
| `ctx.sample(request)` | async callable | Re-enter the agent's LLM. |
| `ctx.confirm(request)` | async callable | Ask the user yes/no. |
| `ctx.elicit(request)` | async callable | Ask the user for structured input. |
| `ctx.log(entry)` | callable | Emit a structured log. |

---

## 9. Sampling

### 9.1 Purpose

Sampling lets an action handler ask the agent's LLM to produce a response mid-handler. The LLM is the agent's -- not your own -- so sampling does not require an API key from your side.

### 9.2 Wire Format

**Request (app -> gateway):**

```json
{
  "jsonrpc": "2.0",
  "id": 9,
  "method": "sampling/request",
  "params": {
    "invocationId": "inv_abc",
    "prompt": "Classify the sentiment of this comment: ...",
    "schema": { "type": "object", "properties": { "sentiment": { "enum": ["positive", "neutral", "negative"] } } },
    "maxTokens": 80
  }
}
```

**SamplingRequestParams:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `invocationId` | string | yes | The current invocation context. |
| `prompt` | string | yes | Prompt sent to the agent's LLM. |
| `schema` | JSON Schema | no | JSON Schema to constrain the response. |
| `maxTokens` | integer | no | Maximum tokens (default 1024 on the bridge). |

**Response (gateway -> app):**

```json
{
  "jsonrpc": "2.0",
  "id": 9,
  "result": { "content": "{ \"sentiment\": \"positive\", \"confidence\": 0.82 }" }
}
```

The `content` field contains the LLM's response. When a `schema` was provided, the SDK SHOULD:
1. Parse `content` as JSON (if it is a string).
2. Validate against the provided Pydantic model or JSON Schema.
3. Return the validated, typed value.
4. If parsing or validation fails, raise a `HandlerError`.

### 9.3 Depth Limit

The gateway enforces `maxSamplingDepth = 3`. Recursive sampling (handler invoked via sampling that itself calls sampling) increments a counter. Exceeding the limit results in error `-32008 SamplingDepthExceeded`.

### 9.4 Capability Gate

Before calling `ctx.sample()`, the SDK SHOULD check `ctx.agent_capabilities.sampling`:

- If `False`, the handler can either fall back to a non-sampling path, or call `ctx.sample()` unconditionally and let it throw `SamplingNotAvailableError` (code `-32006`).

---

## 10. Elicitation

### 10.1 Two Verbs

Elicitation is sampling's human sibling. Instead of the LLM generating the value, the user is prompted.

**`ctx.confirm(question)`** -- yes/no safety gates:
- Returns `True` only on explicit accept.
- Decline, cancel, and missing elicitation capability all collapse to `False`.
- Safe to call unconditionally -- no need to check `ctx.agent_capabilities.elicitation`.
- Under the hood, sends an elicit request with an empty-properties schema: `{ "type": "object", "properties": {}, "required": [] }`.

**`ctx.elicit(question, schema)`** -- structured content:
- Returns the validated value on accept, `None` on decline or cancel.
- Throws `ElicitationNotAvailableError` (code `-32007`) when the agent does not support elicitation.
- Unlike `confirm`, structured data has no safe default, so the handler MUST branch explicitly or catch the error.

### 10.2 Wire Format

**Request (app -> gateway):**

```json
{
  "jsonrpc": "2.0",
  "id": 11,
  "method": "elicitation/request",
  "params": {
    "invocationId": "inv_abc",
    "question": "Which warehouse should I check?",
    "schema": {
      "type": "object",
      "properties": { "warehouseId": { "type": "string" } },
      "required": ["warehouseId"]
    }
  }
}
```

**ElicitationRequestParams:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `invocationId` | string | yes | The current invocation context. |
| `question` | string | yes | Question shown to the user. |
| `schema` | JSON Schema | yes | Schema for the requested input. |

**Response (accept):**

```json
{
  "jsonrpc": "2.0",
  "id": 11,
  "result": { "action": "accept", "value": { "warehouseId": "WH-7" } }
}
```

**Response (decline/cancel):**

```json
{
  "jsonrpc": "2.0",
  "id": 11,
  "result": { "action": "decline" }
}
```

**ElicitationResult:**

| Field | Type | Description |
|-------|------|-------------|
| `action` | `"accept"` / `"decline"` / `"cancel"` | The user's response. |
| `value` | any (optional) | Present only when `action == "accept"`. |

### 10.3 Schema Constraints

MCP elicit constrains the `requestedSchema`:
- Top level MUST be `{ "type": "object" }`.
- Each property MUST be a primitive type (`string`, `number`, `integer`, `boolean`).
- No `oneOf` / `anyOf` / `allOf` / `not` at the top level.

The SDK MUST validate the schema before sending and return `-32602 InvalidParams` if it violates these constraints.

### 10.4 Confirm Schema

For `ctx.confirm()`, the SDK MUST send:

```json
{ "type": "object", "properties": {}, "required": [] }
```

This renders as a pure Accept/Decline prompt with no input field.

### 10.5 Permissive Fallback Schema

When `ctx.elicit()` is called without an explicit `jsonSchema`, the SDK SHOULD send:

```json
{
  "type": "object",
  "properties": { "response": { "type": "string", "description": "Your response" } },
  "required": ["response"]
}
```

This renders as a single text input. For good UX, callers SHOULD always provide a proper schema.

---

## 11. Resources

### 11.1 Declaration

A resource is a named piece of app state the agent can read and optionally subscribe to.

```python
@tesseron.resource("currentRoute")
def current_route():
    return get_current_route()

@tesseron.resource("currentRoute", subscribable=True)
def current_route_subscriber(emit):
    def on_change():
        emit(get_current_route())
    register_route_listener(on_change)
    return lambda: unregister_route_listener(on_change)
```

### 11.2 URI Convention

Resources are exposed to the agent with URI `tesseron://<app_id>/<resource_name>`.

For `app.id = "shop"` and `resource = "currentRoute"`, the URI is `tesseron://shop/currentRoute`.

### 11.3 Wire Format

**Read (gateway -> app, request):**

```json
{
  "jsonrpc": "2.0",
  "id": 14,
  "method": "resources/read",
  "params": { "name": "currentRoute" }
}
```

**Response:**

```json
{
  "jsonrpc": "2.0",
  "id": 14,
  "result": { "value": "/checkout" }
}
```

**Subscribe (gateway -> app, request):**

```json
{
  "jsonrpc": "2.0",
  "id": 15,
  "method": "resources/subscribe",
  "params": { "name": "currentRoute", "subscriptionId": "sub_1" }
}
```

Response is empty acknowledgment.

**Update (app -> gateway, notification):**

```json
{
  "jsonrpc": "2.0",
  "method": "resources/updated",
  "params": { "subscriptionId": "sub_1", "value": "/cart" }
}
```

**Unsubscribe (gateway -> app, request):**

```json
{
  "jsonrpc": "2.0",
  "id": 16,
  "method": "resources/unsubscribe",
  "params": { "subscriptionId": "sub_1" }
}
```

The SDK MUST call the cleanup function returned by the `.subscribe()` handler.

### 11.4 Dynamic Resource Registration

Resources registered or removed after `tesseron/hello` MUST trigger a `resources/list_changed` notification:

```json
{
  "jsonrpc": "2.0",
  "method": "resources/list_changed",
  "params": { "resources": [ ... full updated resource manifest ... ] }
}
```

### 11.5 Subscription Cleanup

On transport close:
- ALL active subscriptions MUST have their cleanup functions called.
- The subscription map MUST be cleared.

On `resources/unsubscribe`:
- The specific subscription's cleanup function MUST be called.
- The subscription MUST be removed from the map.

---

## 12. Capability Negotiation

### 12.1 Bidirectional

Both sides declare capabilities during the handshake:
- The **app** declares what it can do in `tesseron/hello` params.
- The **gateway** returns the **intersection** in `welcome.capabilities`.

The intersection is what the handler MUST trust.

### 12.2 Capabilities

| Capability | Meaning |
|------------|---------|
| `streaming` | `actions/progress` notifications are allowed. |
| `subscriptions` | Agent will call `resources/subscribe`. |
| `sampling` | `ctx.sample()` is available. |
| `elicitation` | `ctx.confirm()` and `ctx.elicit()` are available. |

### 12.3 Capability Updates via `tesseron/claimed`

When a session is claimed, the gateway MAY send updated `agentCapabilities` in the `tesseron/claimed` notification. These are the authoritative values -- they MUST overwrite the capabilities from the welcome, because the welcome-time capabilities were computed before the MCP client's capabilities were known.

### 12.4 Graceful Degradation

| Capability | Behavior when absent |
|------------|---------------------|
| `sampling` | `ctx.sample()` throws `SamplingNotAvailableError`. Check `ctx.agent_capabilities.sampling` first for graceful fallback. |
| `elicitation` | `ctx.confirm()` returns `False` (safe default). `ctx.elicit()` throws `ElicitationNotAvailableError`. |
| `subscriptions` | `resources/subscribe` is never called; `.subscribe()` handlers never fire. |
| `streaming` | Progress notifications are silently dropped by the gateway. |

---

## 13. Error Model

### 13.1 Error Codes

| Code | Name | Raised when |
|------|------|-------------|
| `-32700` | `ParseError` | JSON-RPC message failed to parse. |
| `-32600` | `InvalidRequest` | Valid JSON but not a valid JSON-RPC request. |
| `-32601` | `MethodNotFound` | Method not registered. |
| `-32602` | `InvalidParams` | Params do not match the method's expected shape. Also raised when elicit schema violates MCP constraints. |
| `-32603` | `InternalError` | Unhandled exception in the SDK or gateway. |
| `-32000` | `ProtocolMismatch` | `tesseron/hello` sent a `protocolVersion` the gateway does not accept (major version mismatch). |
| `-32001` | `Cancelled` | Invocation was cancelled by the agent. |
| `-32002` | `Timeout` | Invocation exceeded its timeout. |
| `-32003` | `ActionNotFound` | Agent called an action that is not registered for this session. |
| `-32004` | `InputValidation` | Input failed schema validation. Issues in `error.data`. |
| `-32005` | `HandlerError` | Handler threw, or output failed strict validation. |
| `-32006` | `SamplingNotAvailable` | Handler called `ctx.sample()` but agent did not advertise sampling. |
| `-32007` | `ElicitationNotAvailable` | Handler called `ctx.elicit()` but agent did not advertise elicitation. (`ctx.confirm()` returns `False` instead of throwing.) |
| `-32008` | `SamplingDepthExceeded` | Sampling chain exceeded `maxSamplingDepth` (3). |
| `-32009` | `Unauthorized` | Wrong claim code, unclaimed session invoking action, or origin not allowlisted. |
| `-32010` | `TransportClosed` | Transport closed while a request was pending. |
| `-32011` | `ResumeFailed` | Session resume failed (unknown session, bad token, TTL elapsed, etc.). |

### 13.2 Error Data

The `error.data` field carries structured payloads:

- **`-32004 InputValidation`**: Array of validation issues from the schema validator.
- **`-32005 HandlerError`** (with strict output): Array of validation issues.
- **`-32008 SamplingDepthExceeded`**: `{ "depth": N, "max": 3 }`.

### 13.3 Error Classes

The SDK MUST provide typed error classes:

```python
class TesseronError(Exception):
    code: int
    message: str
    data: Any | None

class SamplingNotAvailableError(TesseronError): ...
class ElicitationNotAvailableError(TesseronError): ...
class SamplingDepthExceededError(TesseronError): ...
class CancelledError(TesseronError): ...
class TimeoutError(TesseronError): ...
class TransportClosedError(TesseronError): ...
```

### 13.4 Error Mapping

- When a handler throws a `TesseronError`, the SDK MUST map it to a JSON-RPC error response with the corresponding `code`, `message`, and `data`.
- When a handler throws any other exception, the SDK MUST map it to `-32005 HandlerError` with the exception's message.
- When an incoming JSON-RPC error response is received for a pending request, the SDK MUST construct a `TesseronError` with the error's `code`, `message`, and `data`, and reject the pending request with it.

---

## 14. Session Lifecycle State Machine

```
                                    ws open
    DISCONNECTED ──────────────> HANDSHAKING
                                    │
                               welcome received
                                    │
                                    v
                              AWAITING CLAIM
                               /          \
                         claim ok      timeout / ws close
                             │              │
                             v              v
                          CLAIMED ───────> CLOSED
                                  ws close
```

### 14.1 States

| State | Description |
|-------|-------------|
| `DISCONNECTED` | No transport connection. No tools visible for this app. |
| `HANDSHAKING` | Transport open, `tesseron/hello` in flight. |
| `AWAITING_CLAIM` | `welcome` received with `claimCode`. Actions registered but NOT exposed as MCP tools. |
| `CLAIMED` | Agent submitted a matching claim. Tool list published. Actions can be invoked. |
| `CLOSED` | Transport closed. Session forgotten by the gateway. |

### 14.2 Transitions

| Transition | Trigger | Side Effects |
|------------|---------|--------------|
| DISCONNECTED -> HANDSHAKING | App opens transport | `tesseron/hello` sent |
| HANDSHAKING -> AWAITING_CLAIM | Gateway returns `welcome` | Claim code generated and printed to stderr |
| AWAITING_CLAIM -> CLAIMED | Agent calls `tesseron__claim_session` | `notifications/tools/list_changed` fires; `tesseron/claimed` notification sent to app |
| AWAITING_CLAIM -> CLOSED | Transport closes or agent never claims | Claim code invalidated |
| CLAIMED -> CLOSED | Transport closes | All in-flight invocations aborted; subscriptions dropped; `tools/list_changed` fires |

### 14.3 Behavior on Close

When the transport closes:
1. ALL pending outbound requests MUST be rejected with `TransportClosedError`.
2. ALL in-flight invocations MUST have their cancellation signals fired.
3. ALL active subscriptions MUST have their cleanup functions called.
4. The `progress()` calls after close are silently dropped.
5. Any `sample()`, `confirm()`, or `elicit()` in flight MUST reject with `TransportClosedError`.

### 14.4 Reconnection

After a disconnect, calling `connect()` again yields a NEW `sessionId` and NEW `claimCode` (unless resuming). The agent MUST re-claim. The SDK MUST NOT auto-reconnect silently.

---

## 15. MCP Integration Contract

### 15.1 Tool Naming

Every Tesseron action is exposed as an MCP tool named `<app_id>__<action_name>`.

The gateway also provides built-in meta-tools:

| Tool | Description |
|------|-------------|
| `tesseron__claim_session` | Always present. Input: `{ "code": "AB3X-7K" }`. |
| `tesseron__list_actions` | Lists all claimed sessions' actions and resources. |
| `tesseron__invoke_action` | Fallback dispatcher: `{ "app_id": "...", "action": "...", "args": {...} }`. |
| `tesseron__read_resource` | Read a resource: `{ "app_id": "...", "name": "..." }`. |
| `tesseron__list_pending_claims` | Lists all pending claim codes the gateway can redeem. |

### 15.2 Resource URIs

Every Tesseron resource is exposed as an MCP resource with URI `tesseron://<app_id>/<resource_name>`.

### 15.3 Dynamic Registration

When a session connects, claims, or drops, the gateway emits:
- `notifications/tools/list_changed` -- agent refreshes its tool list.
- `notifications/resources/list_changed` -- agent refreshes its resource list.

### 15.4 Sampling Bridge

The gateway bridges `sampling/request` (Tesseron) to `sampling/createMessage` (MCP):
- The SDK sends a `sampling/request` over the Tesseron channel.
- The gateway translates it to an MCP `sampling/createMessage` call.
- The agent's LLM generates a response.
- The gateway returns the response to the SDK.

### 15.5 Elicitation Bridge

The gateway bridges `elicitation/request` (Tesseron) to MCP's `elicitInput`:
- The SDK sends an `elicitation/request` over the Tesseron channel.
- The gateway translates it to an MCP `elicitInput` call with the `requestedSchema`.
- The user responds through the agent UI.
- The gateway returns `{ "action": "accept"/"decline"/"cancel", "value": ... }`.

### 15.6 Logging Bridge

The SDK sends `log` notifications, which the gateway forwards as MCP `sendLoggingMessage` with `logger: <app_id>`.

### 15.7 Progress Bridge

The SDK sends `actions/progress` notifications, which the gateway forwards as MCP `notifications/progress` (when the agent supplied a `progressToken`).

---

## 16. Security Model

### 16.1 Loopback-Only Discovery

- Apps MUST bind to loopback only (`127.0.0.1` or `::1` for WS, private temp dir for UDS).
- The gateway MUST refuse non-loopback URLs from manifests.
- The gateway binds no ports of its own.
- Every hop is on the local machine.

### 16.2 Claim Code Gate

Even from a local connection, the session is inert until claimed:
1. The claim code is a 6-character CSPRNG-generated string.
2. It is displayed out-of-band (stderr, app UI).
3. The user carries it to the agent manually.
4. A wrong code results in `-32009 Unauthorized`.
5. Codes are single-use.

### 16.3 File Permissions

- `~/.tesseron/` directory: mode `0o700`.
- Instance manifests: mode `0o600`.
- Claim breadcrumb files: mode `0o600`.

### 16.4 Multi-App Coexistence

Multiple apps can connect simultaneously. Each has its own:
- `app.id` (namespace for tool names)
- Claim code
- Session
- Origin

Tool routing: `tools/call shop__addItem` routes to the session with `app.id == "shop"`.

### 16.5 What Tesseron Does NOT Defend Against

- Malicious code running in your app's process.
- Malicious MCP clients on the same machine (they'd still need the claim code).
- Prompt injection via attacker-controlled descriptions.
- Exfiltration via resources (anything exposed is readable by the claimed agent).

---

## 17. Protocol Constants

| Name | Value |
|------|-------|
| Protocol version | `"1.2.0"` |
| JSON-RPC version | `"2.0"` |
| Discovery directory (v2) | `~/.tesseron/instances/` |
| Discovery directory (v1, compat) | `~/.tesseron/tabs/` |
| Manifest version | `2` |
| WebSocket subprotocol | `tesseron-gateway` |
| UDS framing | NDJSON (one JSON-RPC message per `\n`) |
| Default action timeout | `60000` ms |
| Max sampling depth | `3` |
| Tool name pattern | `<app_id>__<action_name>` |
| Tool name separator | `__` (double underscore) |
| Resource URI pattern | `tesseron:///<app_id>/<resource_name>` |
| `app.id` regex | `/^[a-z][a-z0-9_]*$/` |
| Reserved app IDs | `tesseron`, `mcp`, `system` |
| Claim code alphabet | `ABCDEFGHJKMNPQRSTUVWXYZ23456789` (31 chars) |
| Claim code format | `XXXX-XX` (6 chars with dash after 4th) |
| Default resume TTL | `90000` ms |
| Default max zombies | `100` |
| Confirm schema | `{ "type": "object", "properties": {}, "required": [] }` |
| Permissive elicit fallback | `{ "type": "object", "properties": { "response": { "type": "string", "description": "Your response" } }, "required": ["response"] }` |
| Permissive input schema | `{ "type": "object", "additionalProperties": true }` |

---

## 18. Acceptance Test Scenarios

The following scenarios describe behavioral requirements a correct implementation MUST satisfy. Each scenario is a testable contract.

### Scenario 1: Basic Action Discovery

**Given:** An app declares 3 actions (searchProducts, addItem, removeItem) and connects.
**When:** The agent connects and claims the session.
**Then:** The agent discovers 3 MCP tools: `shop__searchProducts`, `shop__addItem`, `shop__removeItem`, each with the correct input schemas and descriptions.

### Scenario 2: Action Invocation with Valid Input

**Given:** An app declares an action `addItem` with input schema `{ sku: string, quantity: int }`.
**When:** The agent invokes `shop__addItem` with `{ "sku": "ABC", "quantity": 2 }`.
**Then:** The handler receives the validated input, executes, and the agent receives the typed response.

### Scenario 3: Input Validation Failure

**Given:** An app declares an action with input schema `{ query: string }`.
**When:** The agent invokes with `{ "query": 42 }` (wrong type).
**Then:** The handler DOES NOT run. The agent receives error `-32004 InputValidation` with validation issues in `error.data`.

### Scenario 4: Long-Running Action with Progress

**Given:** An app declares a long-running action.
**When:** The handler emits 3 progress updates (`10%`, `50%`, `90%`) before completing.
**Then:** The agent receives all 3 progress notifications with increasing `percent` values, followed by the final result.

### Scenario 5: Action Confirmation (ctx.confirm)

**Given:** An app declares an action that calls `ctx.confirm("Delete 5 items? Cannot be undone.")`.
**When (a):** The user accepts.
**Then:** `ctx.confirm()` returns `True`, handler proceeds.
**When (b):** The user declines.
**Then:** `ctx.confirm()` returns `False`, handler handles gracefully.
**When (c):** The agent does not support elicitation.
**Then:** `ctx.confirm()` returns `False` (safe default). No error thrown.

### Scenario 6: Sampling (ctx.sample)

**Given:** An app declares an action that calls `ctx.sample(prompt="Classify...", schema=SentimentSchema)`.
**When:** The agent supports sampling and the LLM returns valid JSON matching the schema.
**Then:** `ctx.sample()` returns the validated, typed value.
**When:** The agent does NOT support sampling.
**Then:** `ctx.sample()` throws `SamplingNotAvailableError` (code `-32006`).

### Scenario 7: Transport Drop During Active Invocation

**Given:** An action handler is running.
**When:** The WebSocket connection drops.
**Then:**
- The handler's cancellation signal fires.
- All pending outbound requests are rejected with `TransportClosedError`.
- Active subscriptions are cleaned up.
- The agent sees the tool call end abruptly.

### Scenario 8: Dynamic Action Registration

**Given:** An app connects with 2 actions.
**When:** The app registers a 3rd action after the session is claimed.
**Then:** An `actions/list_changed` notification is sent with all 3 actions. The gateway emits `notifications/tools/list_changed`. The agent discovers the new tool.

### Scenario 9: Resource Subscription

**Given:** An app declares a subscribable resource `currentState`.
**When:** The agent subscribes, and the app's state changes twice.
**Then:** The agent receives 2 `resources/updated` notifications with the new values.
**When:** The agent unsubscribes.
**Then:** The cleanup function is called. No further updates are sent.

### Scenario 10: Multiple Apps Simultaneously

**Given:** App A (`app.id = "shop"`) and App B (`app.id = "admin"`) both connect and get claimed.
**When:** The agent calls `shop__addItem`.
**Then:** The invocation routes to App A's handler, not App B's.
**When:** The agent calls `admin__banUser`.
**Then:** The invocation routes to App B's handler.

### Scenario 11: Elicitation (ctx.elicit)

**Given:** An app declares an action that calls `ctx.elicit(question="Which warehouse?", schema=WarehouseSchema)`.
**When:** The user fills in the form and accepts.
**Then:** `ctx.elicit()` returns the validated value.
**When:** The user declines.
**Then:** `ctx.elicit()` returns `None`.
**When:** The agent does NOT support elicitation.
**Then:** `ctx.elicit()` throws `ElicitationNotAvailableError` (code `-32007`).

### Scenario 12: Capability Gating

**Given:** An action handler checks `ctx.agent_capabilities.sampling` before calling `ctx.sample()`.
**When:** The agent does not support sampling.
**Then:** The handler takes the fallback path. No error is thrown.
**When:** The agent supports sampling.
**Then:** The handler uses `ctx.sample()` successfully.

### Scenario 13: Session Resume

**Given:** An app has a claimed session with a stored `sessionId` and `resumeToken`.
**When:** The transport drops and the app reconnects within the 90-second TTL.
**Then:** `tesseron/resume` succeeds. The session retains its claimed status. No new claim code is needed. A new `resumeToken` is returned (rotated).

### Scenario 14: Resume Failure and Fallback

**Given:** An app has stored resume credentials.
**When:** The resume fails (TTL elapsed, wrong token, etc.).
**Then:** The SDK receives error `-32011 ResumeFailed`. The app clears stored credentials and falls back to a fresh `tesseron/hello` with a new claim code.

### Scenario 15: Action Timeout

**Given:** An action is declared with `timeout_ms=5000`.
**When:** The handler takes 6 seconds to complete.
**Then:** After 5 seconds, the cancellation signal fires. The agent receives error `-32002 Timeout`. The handler may continue running orphaned but the agent is not blocked.

### Scenario 16: Handler Error Propagation

**Given:** An action handler raises `ValueError("Cart is locked")`.
**Then:** The agent receives error `-32005 HandlerError` with message "Cart is locked".
**Given:** A handler raises `TesseronError(code=-32003, message="Order not found", data={"orderId": "x"})`.
**Then:** The agent receives exactly that error code, message, and data.

### Scenario 17: Strict Output Validation

**Given:** An action is declared with `strict_output=True` and an output schema.
**When:** The handler returns a value that does not match the output schema.
**Then:** The agent receives error `-32005 HandlerError` with validation issues in `error.data`.

### Scenario 18: Structured Logging

**Given:** An action handler calls `ctx.log(level="info", message="imported CSV", meta={"rows": 1200})`.
**Then:** The gateway forwards this as an MCP `sendLoggingMessage` with `logger: "<app_id>"`.

### Scenario 19: Claimed Notification Updates Capabilities

**Given:** An app connects and receives `welcome.capabilities.sampling = false`.
**When:** The session is claimed and the gateway sends `tesseron/claimed` with `agentCapabilities.sampling = true`.
**Then:** Subsequent handler invocations see `ctx.agent_capabilities.sampling = True`.

### Scenario 20: Concurrent Invocations

**Given:** Two actions are declared.
**When:** The agent invokes both simultaneously (two `actions/invoke` with different `invocationId` values).
**Then:** Both handlers run concurrently. Each has its own cancellation signal. Each returns its own result independently.

---

## Appendix A: Python SDK API Surface (Recommended)

This appendix describes the recommended public API for the Python SDK. The implementer MAY adjust naming conventions to be more Pythonic while preserving behavioral equivalence.

```python
from tesseron import Tesseron, ActionContext
from pydantic import BaseModel

# Initialize
tesseron = Tesseron(app={"id": "notes", "name": "Notes"})

# Declare actions via decorator
class CreateNoteInput(BaseModel):
    title: str
    body: str = ""

class CreateNoteOutput(BaseModel):
    id: str
    title: str

@tesseron.action(
    "createNote",
    input=CreateNoteInput,
    output=CreateNoteOutput,
    description="Create a new note",
    annotations={"destructive": False},
    timeout_ms=30000,
)
async def create_note(input: CreateNoteInput, ctx: ActionContext) -> CreateNoteOutput:
    note = await store.create(title=input.title, body=input.body)
    ctx.progress(message="saved", percent=100)
    return CreateNoteOutput(id=note.id, title=note.title)

# Declare resources
@tesseron.resource("noteCount", description="Number of notes")
def note_count() -> int:
    return store.count()

@tesseron.resource("noteCount", subscribable=True)
def note_count_subscriber(emit):
    def on_change():
        emit(store.count())
    store.on("change", on_change)
    return lambda: store.off("change", on_change)

# Connect
async def main():
    welcome = await tesseron.connect()  # or connect(transport="uds")
    print(f"Claim code: {welcome.claim_code}")

    # Or with resume:
    saved = load_resume_credentials()
    if saved:
        try:
            welcome = await tesseron.connect(resume=saved)
        except TesseronError as e:
            if e.code == -32011:  # ResumeFailed
                clear_resume_credentials()
                welcome = await tesseron.connect()
            else:
                raise

    save_resume_credentials(welcome.session_id, welcome.resume_token)

# Disconnect
async def shutdown():
    await tesseron.disconnect()
```

## Appendix B: JSON-RPC Dispatcher (Implementation Guidance)

The SDK MUST implement a bidirectional JSON-RPC dispatcher with these capabilities:

1. **`on(method, handler)`** -- register a handler for incoming requests on `method`. The handler receives `params` and returns a result (or raises an error).

2. **`on_notification(method, handler)`** -- register a handler for incoming notifications on `method`. The handler receives `params` and returns nothing.

3. **`request(method, params, signal=None)`** -- send a request and await the response. Assigns an auto-incrementing `id`. Returns the `result` on success, raises `TesseronError` on error. Supports cancellation via `signal`. On transport close, all pending requests MUST be rejected.

4. **`notify(method, params)`** -- send a fire-and-forget notification (no `id`, no response expected).

5. **`receive(message)`** -- given a parsed JSON-RPC envelope, dispatch to the appropriate handler or resolve a pending request.

6. **`reject_all_pending(error)`** -- reject all pending outbound requests with the given error. Called on transport close.

**Dispatch rules for `receive(message)`:**

- If `message` has `method` and `id`: it is a request. Look up the handler, call it, send a success or error response.
- If `message` has `method` but no `id`: it is a notification. Look up the notification handler, call it. No response.
- If `message` has `id` and (`result` or `error`) but no `method`: it is a response. Look up the pending request by `id`, resolve or reject it.
- If `message` does not have `jsonrpc: "2.0"`: ignore it.

**Error handling in request handlers:**
- If no handler is registered for the method: send `-32601 MethodNotFound`.
- If the handler raises a `TesseronError`: send an error response with its `code`, `message`, and `data`.
- If the handler raises any other exception: send `-32603 InternalError` with the exception's message.
- If `send()` fails (transport error): close the transport so the peer sees a close and rejects its own pending requests.

## Appendix C: Provenance

This specification was extracted from the Tesseron protocol documentation (CC BY 4.0) at https://github.com/BrainBlend-AI/tesseron, commit hash recorded in the python-tesseron repository. The extraction was performed by reading the protocol specification pages under `docs/src/content/docs/protocol/` and the SDK porting guide under `docs/src/content/docs/sdk/porting.md`. Behavioral details not fully documented in the spec were inferred from reading the reference implementation source code, but NO code was copied. All behavioral requirements are expressed as prose specifications using RFC 2119 language.

The reference implementation is licensed BSL 1.1. This specification describes the protocol (what the system must do), not the implementation (how the TypeScript code does it). The Python implementation will be built from this specification alone, without access to the TypeScript source.
