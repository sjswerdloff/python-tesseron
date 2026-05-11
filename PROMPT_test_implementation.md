# Prompt: Implement pytest Test Suite from V-Model Test Specifications

**Agent:** Sonnet
**Role:** Test implementer for python-tesseron
**Date:** 2026-05-11
**Author:** vivian-1a61bc9a (Lead QE)

## Skills to Load

Before starting, load these skills:

1. `python-development` — Python project structure, uv, ruff, type annotations
2. `test-writing-philosophy` — Contract testing, behavioral mocking, test naming
3. `development-tooling-efficiency` — Token-efficient linting/testing with JSON+jq
4. `linting-efficiency` — Write code that passes linting first try
5. `systematic-test-design` — QE test design techniques (boundary value, state transition, equivalence partitioning)

## Context

python-tesseron is a clean-room Python implementation of the Tesseron protocol — typed action exposure for AI agents over MCP/WebSocket. The implementation uses FastMCP, Pydantic, and asyncio.

This prompt asks you to implement the **test suite only**, before any implementation code exists. The tests define the behavioral contracts that the implementation must satisfy. Tests SHOULD fail initially (no implementation to import yet) — that is correct V-model behavior.

## Input Documents

All input documents are in this repository:

- `SPEC_tesseron_protocol_for_python.md` — The protocol specification (1,546 lines, 18 sections). This is the single source of truth for all behavioral requirements.
- `traceability/requirements.csv` — 102 extracted requirements with RFC 2119 priority mapping (REQ-001 through REQ-102).
- `traceability/state_transition_tests.md` — 20 state transition test specifications (ST-01 through ST-20)
- `traceability/error_model_tests.md` — 28 error model test specifications (ER-01 through ER-28)
- `traceability/wire_format_tests.md` — 35 wire format test specifications (WF-01 through WF-35)
- `traceability/capability_tests.md` — 13 capability negotiation test specifications (CP-01 through CP-13)
- `traceability/gap_analysis.md` — 14 additional tests needed for 97% coverage (SEC-*, API-*, additional WF/ST/CP)
- `traceability/acceptance_to_requirements.csv` — Maps 20 acceptance scenarios to requirement IDs
- `traceability/verified_by.csv` — Requirement-to-test traceability matrix

## Project Setup

Create the project structure using `uv`:

```
python-tesseron/
├── pyproject.toml          # uv project, Python >=3.12
├── src/
│   └── python_tesseron/    # Implementation package (stubs only for now)
│       ├── __init__.py
│       ├── types.py        # Pydantic models for protocol types
│       └── errors.py       # TesseronError hierarchy
├── tests/
│   ├── conftest.py         # Shared fixtures (mock gateway, transport helpers)
│   ├── test_wire_format.py # WF-01 through WF-37
│   ├── test_state_transitions.py  # ST-01 through ST-22
│   ├── test_error_model.py # ER-01 through ER-28
│   ├── test_capabilities.py # CP-01 through CP-15
│   ├── test_security.py    # SEC-01 through SEC-06
│   ├── test_acceptance.py  # AT-01 through AT-20 (acceptance scenarios from spec §18)
│   └── test_api.py         # API-01, API-02 (decorator, elicit schema)
└── traceability/           # Already exists — do not modify
```

### Dependencies

```toml
[project]
name = "python-tesseron"
requires-python = ">=3.12"
dependencies = [
    "fastmcp>=2.0",
    "pydantic>=2.0",
    "websockets>=13.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "ruff>=0.8",
    "mypy>=1.0",
]
```

## Implementation Rules

### What to Write

1. **Stub types and errors first** — Create minimal `src/python_tesseron/types.py` with Pydantic models for protocol messages (HelloParams, WelcomeResult, ActionDefinition, InvocationResult, etc.) and `src/python_tesseron/errors.py` with the TesseronError hierarchy. These are needed for test imports to work. Keep them as close to the spec as possible.

2. **Test files** — One file per test specification document. Each test function:
   - Named `test_<test_id>_<short_description>` (e.g., `test_wf01_request_has_required_fields`)
   - Docstring with the test ID and requirement IDs it verifies (e.g., `"""WF-01: REQ-005. Request must have jsonrpc, id, method, params."""`)
   - Uses pytest markers: `@pytest.mark.state_transition`, `@pytest.mark.error_model`, `@pytest.mark.wire_format`, `@pytest.mark.capability`, `@pytest.mark.security`, `@pytest.mark.acceptance`
   - Uses `pytest.mark.xfail(reason="implementation pending")` for tests that cannot pass without the SDK implementation

3. **Mock gateway fixture** — In conftest.py, create a mock gateway that:
   - Accepts WebSocket connections on loopback
   - Sends/receives JSON-RPC messages
   - Can simulate the full handshake (hello → welcome → claimed)
   - Can send actions/invoke, actions/cancel, resources/read, etc.
   - Tracks sent/received messages for assertion

4. **Transport test helpers** — Helpers for:
   - Creating WebSocket connections to the mock gateway
   - Creating UDS connections
   - Sending raw JSON-RPC envelopes
   - Asserting on JSON-RPC response structure

### What NOT to Write

- Do NOT implement the SDK (Tesseron class, ActionContext, connection logic). Only stubs.
- Do NOT modify anything in `traceability/` — those are the QE source of truth.
- Do NOT consult or reference the TypeScript implementation.
- Do NOT write tests that test internal implementation details. Test behavioral contracts only — inputs, outputs, side effects observable from the wire.

### Test Philosophy (from test-writing-philosophy skill)

- **Test the contract, not the implementation.** Tests verify what the spec says, not how the code does it.
- **Use behavioral mocking.** The mock gateway simulates the wire protocol, not internal SDK classes.
- **Name tests by what they verify.** `test_er10_input_validation_returns_32004` tells you what failed without reading the code.
- **Each test is independent.** No ordering dependencies. Fresh fixtures per test.
- **Async tests use pytest-asyncio.** Mark with `@pytest.mark.asyncio`.

### Code Style (from python-development skill)

- Double quotes, 127 max line length, 4-space indentation
- Google-style docstrings
- Type annotations everywhere
- snake_case for functions/variables, PascalCase for classes
- Imports: stdlib → third-party → first-party → local
- Use ruff for formatting and linting

### FastMCP Integration

The spec states the SDK uses FastMCP for the MCP integration (App ↔ Gateway ↔ Agent). The gateway side translates Tesseron JSON-RPC to MCP. For testing:
- Tests verify the Tesseron JSON-RPC wire format, NOT the MCP side
- The mock gateway simulates the gateway's Tesseron-facing behavior
- FastMCP types may be referenced in stubs where the SDK will bridge to MCP

## Verification

After writing all tests:

1. Run `uv run ruff check src/ tests/` — must pass with zero errors
2. Run `uv run ruff format --check src/ tests/` — must pass
3. Run `uv run pytest --co` — must collect all tests without import errors
4. Run `uv run pytest -x` — tests marked xfail should xfail; any test that CAN pass with just stubs should pass

## Traceability

Every test function MUST reference its test specification ID (ST-xx, ER-xx, WF-xx, CP-xx, SEC-xx, AT-xx, API-xx) and the requirement IDs it verifies in its docstring. This enables automated traceability verification later.

Example:
```python
@pytest.mark.wire_format
@pytest.mark.asyncio
async def test_wf07_response_echoes_request_id(mock_gateway):
    """WF-07: REQ-005. Responding peer must echo exact same request ID."""
    ...
```

## Output

Commit all files to a new branch `vivian/test-implementation` with a clear commit message listing files created and test counts. Push to origin.
