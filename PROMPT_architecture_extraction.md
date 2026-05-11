# Tesseron Architecture Extraction — Opus Agent Prompt

**Purpose:** Extract protocol specification, architectural requirements, and behavioral contracts from the Tesseron project. The output will guide a separate agent (who will never see the Tesseron source code) to build a Python implementation using FastMCP as the MCP foundation.

**Legal context:** The Tesseron protocol specification is CC BY 4.0 (fully open). The reference implementation is BSL 1.1 (source-available, restricted). We are extracting the protocol and behavioral requirements — what the system must do — not copying implementation code.

---

## Instructions for the Opus Agent

### Step 1: Clone the repo

```bash
git clone https://github.com/BrainBlend-AI/tesseron.git /tmp/tesseron-extraction
```

### Step 2: Read the protocol specification

Look for protocol documentation under `/docs/` or `/docs/src/content/docs/protocol/`. Read the protocol spec thoroughly. This is the authoritative source — CC BY 4.0 licensed, explicitly intended for compatible implementations.

### Step 3: Read the reference implementation for behavioral understanding

Read the TypeScript source to understand behaviors that the protocol spec may not fully document. Focus on:

- What happens during connection establishment (the claim-code handshake)
- What messages are exchanged in what order
- How actions are registered, discovered, and invoked
- How capabilities are negotiated (sampling, confirmation, elicitation, progress)
- How errors are handled and propagated
- How sessions are resumed after disconnection
- How resources (subscribable live reads) work
- Edge cases: timeouts, partial failures, concurrent requests

### Step 4: Produce the extraction document

Write the output to: `/Users/stuartswerdloff/ai/ClaudeInstanceHomeOffices/cyril-9137f1ee/SPEC_tesseron_protocol_for_python.md`

---

## What to INCLUDE in the extraction

### A. Protocol Message Formats

Every message type exchanged between application and gateway, and between gateway and MCP client. Include:
- JSON-RPC 2.0 message structure
- Method names and parameter schemas
- Response formats
- Notification formats (server-initiated messages)
- Error codes and error response formats

Document these as schemas/contracts, not as TypeScript types.

### B. State Machines

- Connection lifecycle: states and transitions from initial WebSocket connection through claim-code handshake to active session
- Action lifecycle: from declaration through discovery to invocation and response
- Session lifecycle: connect, active, disconnect, resume
- Resource subscription lifecycle: subscribe, update, unsubscribe

Draw these as state transitions, not as code.

### C. Capability System

- What capabilities exist (sampling, confirmation, elicitation, progress streaming)
- How capabilities are negotiated during connection
- How an action handler detects whether the connected agent supports a given capability
- How graceful degradation works when a capability is absent

### D. Behavioral Requirements

For each major operation, document what MUST happen:
- "When a client connects with claim code X, the gateway MUST..."
- "When an action is invoked with invalid parameters, the application MUST..."
- "When a long-running action reports progress, the gateway MUST..."
- "When a WebSocket connection drops during an active invocation, the gateway MUST..."

Use RFC 2119 language (MUST, SHOULD, MAY) where the behavior is clear from the spec or implementation.

### E. MCP Integration Contract

- How Tesseron actions map to MCP tools (the bridge)
- How Tesseron resources map to MCP resources
- How the gateway advertises available tools to MCP clients
- Dynamic tool registration: how new actions become available to already-connected clients

### F. Security and Trust Model

- How claim codes work (generation, expiry, single-use)
- What authentication/authorization exists beyond the claim code
- What the gateway trusts vs validates

### G. Acceptance Criteria / Test Scenarios

Describe 10-15 behavioral scenarios that a correct implementation must handle:
1. Application declares 3 actions, agent connects, discovers all 3 as MCP tools
2. Agent invokes action with valid parameters, receives typed response
3. Agent invokes action with invalid parameters, receives schema validation error
4. Long-running action streams progress updates to agent
5. Action requires confirmation, agent approves/denies
6. Action uses sampling (asks the agent's LLM a question mid-execution)
7. WebSocket drops during active invocation, client reconnects, session resumes
8. Application adds new action while agent is connected — agent discovers it
9. Resource subscription: agent subscribes, application updates, agent receives update
10. Multiple agents connected simultaneously to same application
11. Elicitation: action asks agent for structured input via schema
12. Action handler checks for capability support before using it
... etc.

These scenarios become the test specification for the Python implementation.

---

## What to EXCLUDE from the extraction

- **TypeScript class hierarchies or module structure.** The Python implementation will have its own structure.
- **TypeScript-specific patterns** (builder chains, Zod schema definitions, Promise patterns). The Python agent should use Pydantic, decorators, and asyncio.
- **Implementation algorithms.** Don't describe HOW the TypeScript code routes messages or manages state internally. Describe WHAT must happen from the outside.
- **Package management details** (pnpm, Turbo, monorepo structure). Irrelevant to Python.
- **Framework-specific SDK details** (React hooks, Svelte stores, Vue composables). We need the core protocol, not the UI bindings.
- **Code snippets from the BSL 1.1 codebase.** Describe behavior in prose, not in TypeScript.

---

## Context for the Extraction Agent

The Python implementation will use:

- **FastMCP** as the MCP server foundation (decorator-based tool registration, Pydantic schemas, async Python)
- **Pydantic** for schema validation (equivalent role to Zod in the TypeScript version)
- **websockets** or **aiohttp** for WebSocket transport
- **asyncio** for async operations
- **Python 3.11+** as the target runtime

The target use case: instrumenting Python scientific/medical applications (like radiation therapy planning software) to expose typed operations to AI agents. The application declares actions using Python decorators with Pydantic models, a gateway exposes them as MCP tools, and AI agents in Claude Code or OpenCode invoke them.

The extraction document should give a competent Python developer everything needed to build a correct, complete implementation WITHOUT ever seeing the TypeScript source code. Think of it as writing an RFC that the TypeScript implementation happens to conform to.

---

## After extraction

After producing the specification document, the Opus agent's work is done. The `/tmp/tesseron-extraction` directory will be deleted by Stuart. A separate Sonnet agent will later read only the specification document to build the Python implementation.
