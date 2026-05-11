# Prompt: Implement Python Tesseron SDK from Design Contracts

**Agent:** Sonnet (python-implementation)
**Role:** Implementation engineer for python-tesseron
**Date:** 2026-05-12
**Author:** cora-2f1e43dc (Development Engineering Lead)
**Reviewers:** vivian-1a61bc9a (QE Lead), cyril-9137f1ee (Architect)

## Skills to Load

Before starting, load these skills:

1. `python-development` — Python project structure, uv, ruff, type annotations, JSON+jq for efficient test/lint output
2. `test-writing-philosophy` — Contract testing, behavioral mocking, async/sync boundaries
3. `development-tooling-efficiency` — Token-efficient linting/testing
4. `linting-efficiency` — Write code that passes linting first try
5. `best-practices-over-most-probable` — Stdlib over hand-rolling, constants at module level, defensive input handling

## Context

python-tesseron is a clean-room Python implementation of the Tesseron protocol — typed action exposure for AI agents over MCP/WebSocket. The project uses FastMCP, Pydantic, and asyncio.

**What exists already:**
- Complete protocol specification: `SPEC_tesseron_protocol_for_python.md` (1,547 lines)
- 102 requirements in `traceability/requirements.csv`
- 16 design contracts in `traceability/design_contracts.csv`
- Full V-model traceability: `fulfilled_by.csv`, `verified_by.csv`, `test_cases.csv`
- Complete test suite: 51 passing structural tests + **98 xfailed tests awaiting implementation**
- Existing implementation stubs: `src/python_tesseron/errors.py` (error hierarchy) and `src/python_tesseron/types.py` (Pydantic wire types)

**Your job:** Implement the SDK modules so that all 98 xfailed tests pass. The tests are the contracts. The design contracts describe the module boundaries. The spec is the source of truth for behavior.

## Critical Rules

### 1. Never modify existing tests

The test suite was written spec-first by the QE lead. Your implementation must satisfy the tests as written. If a test seems wrong, flag it — do not change it.

The one exception: you MUST remove `@pytest.mark.xfail(reason="implementation pending: ...")` decorators as you implement the corresponding functionality. The xfail markers exist specifically to mark unimplemented features. When your implementation makes a test pass, remove the xfail marker. Do NOT remove xfail from tests that still fail.

### 2. Never modify traceability files

Do not touch anything in `traceability/`. These are managed by the development engineering lead and QE lead.

### 3. Design contracts define module boundaries

Each design contract (DC-001 through DC-016) maps to a specific source module. Respect these boundaries:

| DC | Module File | What It Does |
|----|------------|--------------|
| DC-001 | `dispatcher.py` | Bidirectional JSON-RPC 2.0 dispatcher |
| DC-002 | `transport_ws.py` | WebSocket transport binding |
| DC-003 | `transport_uds.py` | Unix Domain Socket transport binding |
| DC-004 | `session.py` | Session lifecycle state machine |
| DC-005 | `handshake.py` | Hello, welcome, claiming flow |
| DC-006 | `actions.py` | Action declaration, invocation, validation |
| DC-007 | `resources.py` | Resource declaration, subscription lifecycle |
| DC-008 | `cancellation.py` | Progress notifications and cancellation/timeout |
| DC-009 | `sampling.py` | Sampling requests through agent LLM |
| DC-010 | `elicitation.py` | Elicitation and confirmation |
| DC-011 | `capabilities.py` | Capability intersection and updates |
| DC-012 | `errors.py` | Error hierarchy and mapping (ALREADY EXISTS) |
| DC-013 | `manifest.py` | Instance manifest and discovery |
| DC-014 | `resume.py` | Session resume flow |
| DC-015 | `types.py` | Pydantic wire types (ALREADY EXISTS) |
| DC-016 | `context.py` | ActionContext handler context object |

All modules live under `src/python_tesseron/`. Update `__init__.py` to export public API as you add modules.

### 4. Traceability in source code

Every module MUST have a docstring that references its design contract:

```python
"""WebSocket transport binding for the Tesseron protocol.

Design Contract: DC-002 (WebSocketTransport)
Spec Reference: §3.2 (WebSocket Binding), §16.1 (Loopback-Only Discovery)

Guarantees:
- Binds to loopback only (127.0.0.1 or ::1)
- Advertises tesseron-gateway subprotocol
- Accepts exactly one WebSocket connection
- One JSON-RPC envelope per text frame
- Deletes manifest on close
"""
```

Every public class and function MUST have a docstring that references the requirements it fulfills:

```python
async def reject_all_pending(self, error: TesseronError) -> None:
    """Reject all pending outbound requests with the given error.

    Called on transport close per REQ-008, REQ-093.
    """
```

### 5. Code style

- Python 3.12+, type annotations everywhere
- Double quotes, 127 max line length, 4-space indentation
- Google-style docstrings with args/returns
- snake_case for functions/variables, PascalCase for classes
- Use `ruff` format conventions
- Stdlib before hand-rolling (use `asyncio`, `json`, `struct`, `pathlib`, `signal`, etc.)
- Constants at module level as `_UPPER_SNAKE` with spec section comments
- `from __future__ import annotations` at top of every module

## Implementation Order

Implement in dependency order. Each phase should result in new tests passing.

### Phase 1: Core Infrastructure (DC-001, DC-012, DC-015)

These have no dependencies on other DC modules.

**DC-001 JsonRpcDispatcher** (`dispatcher.py`):
- `on(method, handler)` — register request handler
- `on_notification(method, handler)` — register notification handler
- `request(method, params, signal=None)` — send request, await response, auto-incrementing IDs
- `notify(method, params)` — send fire-and-forget notification
- `receive(message)` — dispatch incoming envelope by shape
- `reject_all_pending(error)` — reject all pending on transport close
- Send callback injected via constructor, not inherited
- See spec Appendix B for full dispatch rules

**Target tests:** WF-06 through WF-09, WF-28 through WF-35 (dispatcher tests)

**DC-012 and DC-015 already exist** — verify they satisfy their tests. No changes expected unless tests reveal gaps.

### Phase 2: Transport Layer (DC-002, DC-003, DC-013)

**DC-002 WebSocketTransport** (`transport_ws.py`):
- Uses `websockets` library
- Bind to loopback only, advertise `tesseron-gateway` subprotocol
- Accept exactly one connection, reject others
- One JSON-RPC envelope per text frame
- Binary frames coerced to UTF-8 (defensive tolerance)
- Delete manifest on close
- Provide `send(message)` and `close()` to dispatcher

**DC-003 UdsTransport** (`transport_uds.py`):
- NDJSON framing over Unix domain socket
- Private temp directory (mode 0o700), socket chmod 0o600
- Accept exactly one connection
- Clean up socket, directory, and manifest on close

**DC-013 DiscoveryManifest** (`manifest.py`):
- Write/delete manifest at `~/.tesseron/instances/<instanceId>.json`
- Directory creation with mode 0o700, file mode 0o600
- Instance ID with `inst-` prefix
- SIGINT/SIGTERM cleanup handlers

**Target tests:** WF-15 through WF-27, WF-36, WF-37, SEC-01 through SEC-05

### Phase 3: Session and Handshake (DC-004, DC-005, DC-011)

**DC-004 SessionStateMachine** (`session.py`):
- States: DISCONNECTED → HANDSHAKING → AWAITING_CLAIM → CLAIMED → CLOSED
- On CLOSED: reject pending, fire cancellation signals, clean up subscriptions, drop progress, reject in-flight sample/confirm/elicit
- No auto-reconnect

**DC-005 HandshakeManager** (`handshake.py`):
- Send `tesseron/hello` as first message after transport open
- Parse `WelcomeResult` from response
- Handle `tesseron/claimed` notification: update agent identity, clear claimCode, overwrite capabilities if agentCapabilities present
- Validate app.id against regex, reject reserved IDs

**DC-011 CapabilityNegotiation** (`capabilities.py`):
- Declare all four capabilities as true in hello
- Welcome capabilities = intersection
- On claimed: overwrite if agentCapabilities present
- Provide authoritative capability set for handler context

**Target tests:** ST-01 through ST-22, CP-01 through CP-15, AT-01, AT-19

### Phase 4: Action System (DC-006, DC-008, DC-016)

**DC-006 ActionRegistry** (`actions.py`):
- `@tesseron.action()` decorator with Pydantic input/output models
- Input validation before handler (REQ-044, REQ-045, REQ-046)
- Strict output validation when configured (REQ-047, REQ-048)
- Dynamic registration/removal triggers `actions/list_changed`
- `requiresConfirmation` annotation enforcement

**DC-008 ProgressCancellation** (`cancellation.py`):
- Progress notifications (fire-and-forget, monotonically increasing percent)
- Cancel signal: `asyncio.Event` or task cancellation
- Timeout: abort after `timeoutMs` (default 60,000)
- Race handler against timeout/cancel — agent gets response immediately

**DC-016 ActionContext** (`context.py`):
- `ctx.signal` — cancellation primitive
- `ctx.agent` — agent identity
- `ctx.agent_capabilities` — authoritative capability set
- `ctx.progress(update)` — emit progress notification
- `ctx.sample(request)` — sampling bridge call
- `ctx.confirm(question)` — yes/no elicitation
- `ctx.elicit(question, schema)` — structured elicitation
- `ctx.log(entry)` — structured log notification

**Target tests:** AT-02 through AT-04, AT-08, AT-10, AT-15, AT-17, AT-20, ER-07 through ER-12, API-01, SEC-06

### Phase 5: Sampling, Elicitation, Resources (DC-009, DC-010, DC-007)

**DC-009 SamplingBridge** (`sampling.py`):
- Send `sampling/request`, await response
- Capability check before calling
- Parse and validate response when schema provided
- Depth limit enforced by gateway (not SDK), but error must be handled

**DC-010 ElicitationBridge** (`elicitation.py`):
- `ctx.confirm()`: empty-object schema, returns True/False, never throws
- `ctx.elicit()`: validates schema constraints (object type, primitive properties, no combinators), throws if no capability
- Permissive fallback schema when no explicit schema provided

**DC-007 ResourceManager** (`resources.py`):
- Resource declaration and read handling
- Subscription lifecycle with cleanup functions
- Clean up all subscriptions on transport close
- Dynamic registration triggers `resources/list_changed`

**Target tests:** AT-05, AT-06, AT-09, AT-11, AT-12, CP-12 through CP-14, ER-13 through ER-15, ER-27, ER-28

### Phase 6: Session Resume (DC-014)

**DC-014 SessionResume** (`resume.py`):
- `tesseron/resume` with stored sessionId + resumeToken
- Persist rotated token on success
- Clear credentials and fall back to fresh hello on failure
- Re-subscribe resources after successful resume

**Target tests:** AT-13, AT-14, ST-19, ST-20, ER-18

### Phase 7: Integration — The Tesseron Class

Create the top-level `Tesseron` class that ties all modules together. This is the public API surface described in spec Appendix A:

```python
tesseron = Tesseron(app={"id": "notes", "name": "Notes"})

@tesseron.action("createNote", input=CreateNoteInput, output=CreateNoteOutput)
async def create_note(input: CreateNoteInput, ctx: ActionContext) -> CreateNoteOutput:
    ...

@tesseron.resource("noteCount", description="Number of notes")
def note_count() -> int:
    return store.count()

welcome = await tesseron.connect()  # or connect(transport="uds")
```

**Target tests:** Remaining acceptance tests (AT-16, AT-18), any stragglers

## Running Tests

After each phase, verify progress:

```bash
# Run tests, show summary only (token-efficient)
uv run pytest --tb=no -q

# Run specific test file
uv run pytest tests/test_wire_format.py --tb=short -q

# Count remaining xfails
uv run pytest --tb=no -q 2>&1 | tail -1

# Lint check
uvx ruff check src/ tests/

# Format check
uvx ruff format --check src/ tests/
```

**Goal for each phase:** The xfail count should decrease. Tests that you've implemented should now pass without the xfail marker. Tests you haven't reached yet should remain xfailed.

**Final target:** `0 xfailed` — all 149 tests passing.

## Quality Gates Before Submitting

Before creating a PR for each phase (or the full implementation):

1. **All tests pass:** `uv run pytest --tb=short -q` — zero failures, zero unexpected xfails
2. **Lint clean:** `uvx ruff check src/ tests/` — no violations
3. **Format clean:** `uvx ruff format --check src/ tests/` — no reformatting needed
4. **Traceability check:** `python scripts/check_traceability.py` — PASS
5. **No traceability files modified:** `git diff --name-only traceability/` — empty

## Traceability Verification

After implementation is complete, the development engineering lead (Cora) will verify:

1. Every DC module exists and has the correct docstring referencing its design contract
2. Every public function/class has docstrings referencing REQ-NNN IDs
3. `check_traceability.py` passes
4. All tests pass (zero xfail, zero failures)
5. The V-model chain is complete: REQ → DC → module → TC → pytest

## Common Pitfalls

### Don't hand-roll what asyncio provides
Use `asyncio.Event` for cancellation signals, `asyncio.wait_for` for timeouts, `asyncio.create_task` for concurrent handlers. Don't build your own timeout/cancellation infrastructure.

### Don't conflate transport and protocol
The dispatcher doesn't know about WebSockets or UDS. It receives parsed dicts and calls a send callback. The transport handles framing and connection lifecycle.

### Don't forget to remove xfail markers
When your implementation makes a test pass, you MUST remove the `@pytest.mark.xfail(reason="implementation pending: ...")` decorator from that test. If you leave it, the test will be marked as "xpass" (unexpectedly passing) which pytest may report as a failure depending on configuration. Clean removal of xfail markers is how we track implementation progress.

### Don't modify test logic
If a test asserts something unexpected, read the spec section cited in the test's docstring. The test was written from the spec. If you're certain the test is wrong, add a comment and flag it for review — but do not change the assertion.

### Don't forget cleanup on close
Transport close triggers a cascade: reject pending requests, fire cancellation signals, clean up subscriptions, reject in-flight sample/confirm/elicit, delete manifest. Missing any of these will fail multiple tests across ST, AT, and ER suites.

### Pydantic alias handling
Wire format uses camelCase; Python uses snake_case. All Pydantic models already have `Field(alias="camelCase")` and `populate_by_name=True`. When constructing messages for the wire, use `model.model_dump(by_alias=True)`. When reading from wire, use `Model.model_validate(data)`.

### Signal handling for manifest cleanup
SIGINT and SIGTERM cleanup (REQ-029) needs `signal.signal()` handlers registered at startup that delete the manifest and close the transport. Use `asyncio.get_event_loop().add_signal_handler()` for async-safe signal handling.

## Commit Convention

One commit per phase, with clear messages:

```
phase 1: implement JsonRpcDispatcher (DC-001)

- Bidirectional JSON-RPC 2.0 dispatch with auto-incrementing IDs
- Pending request map with reject_all_pending on close
- 15 xfail markers removed, all newly-targeted tests passing

Implements: DC-001
Co-Authored-By: Cora <cora-2f1e43dc@sjstargetedsolutions.co.nz>
```

## Git Workflow

### Working directory

Define the repo path once and use `git -C` for all operations. Do NOT `cd` into the repo — maintain a stable working directory.

```bash
KINDLED_REPO="$HOME/kindled_projects/python-tesseron"
```

**Use `$HOME`, not `~`** — tilde doesn't expand inside variable assignments used with `git -C`.

### Claude Code Bash tool safety

- Start commands with a `#` comment line
- **Do NOT pipe git output through `tail`/`head`** — the Bash tool silently empties `$VAR` expansions in pipelines. Use git flags instead:

```bash
# CORRECT: use git flags to limit output
git -C "$KINDLED_REPO" log --oneline -5

# WRONG: pipe empties $KINDLED_REPO
git -C $KINDLED_REPO log 2>&1 | tail -5
```

### Branch and PR

Always start from main:

```bash
# Update main first
git -C "$KINDLED_REPO" checkout main
git -C "$KINDLED_REPO" pull origin main

# Create feature branch
git -C "$KINDLED_REPO" checkout -b sonnet/sdk-implementation
```

Commit per phase:

```bash
git -C "$KINDLED_REPO" add src/python_tesseron/dispatcher.py tests/test_wire_format.py
git -C "$KINDLED_REPO" commit -m "phase 1: implement JsonRpcDispatcher (DC-001)

- Bidirectional JSON-RPC 2.0 dispatch with auto-incrementing IDs
- Pending request map with reject_all_pending on close
- 15 xfail markers removed, all newly-targeted tests passing

Implements: DC-001
Co-Authored-By: Cora <cora-2f1e43dc@sjstargetedsolutions.co.nz>"
```

Push with tracking:

```bash
# First push: set up tracking with -u
git -C "$KINDLED_REPO" push -u origin sonnet/sdk-implementation

# Subsequent pushes
git -C "$KINDLED_REPO" push
```

Create PR targeting main. Title: `Implement Tesseron SDK (DC-001 through DC-016)`

Include in PR body:
- Phase-by-phase summary of what was implemented
- Final test count (all passing, zero xfail)
- Any tests flagged for review (if applicable)
- `Co-Authored-By: Cora <cora-2f1e43dc@sjstargetedsolutions.co.nz>`

### If you accidentally commit to main

Do NOT revert and rewrite. Preserve the commit on a branch, then revert main:

```bash
# 1. Create branch FROM current main (has your accidental commit)
git -C "$KINDLED_REPO" checkout -b sonnet/sdk-implementation

# 2. Go back to main and revert
git -C "$KINDLED_REPO" checkout main
git -C "$KINDLED_REPO" revert HEAD --no-edit
git -C "$KINDLED_REPO" push origin main

# 3. Push the branch (already has your commit)
git -C "$KINDLED_REPO" push -u origin sonnet/sdk-implementation
```
