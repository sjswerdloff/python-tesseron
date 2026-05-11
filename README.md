# python-tesseron

A Python implementation of the [Tesseron protocol](https://github.com/BrainBlend-AI/tesseron) for exposing typed application actions to AI agents via MCP over WebSocket.

Built on [FastMCP](https://github.com/jlowin/fastmcp) and [Pydantic](https://docs.pydantic.dev/).

## What This Does

Tesseron lets applications declare typed actions that AI agents can discover and invoke as MCP tools. Instead of browser automation, DOM scraping, or ad-hoc API integration, applications say "here's what I can do" and agents call those capabilities directly against real application state.

```python
from python_tesseron import TesseronApp
from pydantic import BaseModel

app = TesseronApp("my-app")

class DoseRequest(BaseModel):
    beam_config: dict
    patient_id: str

@app.action("calculate_dose")
async def calculate_dose(request: DoseRequest) -> DoseResult:
    """Calculate radiation dose for the given beam configuration."""
    return opentps.calculate(request.beam_config)
```

An AI agent connected via MCP sees `calculate_dose` as a tool with a typed schema. No UI navigation required.

## Why This Exists

The Tesseron protocol specification is [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) and explicitly encourages compatible implementations in any language. The reference implementation is TypeScript. This is a clean-room Python implementation for use in Python-native scientific and medical applications.

**Target use cases:**

- **Radiation therapy planning** ([OpenTPS](https://github.com/openmcsquare/opentps)) — AI-driven treatment planning workflows with typed actions for dose calculation, plan evaluation, and DVH analysis
- **Oncology DICOM management** ([OnkoDICOM](https://github.com/didymo/OnkoDICOM)) — AI-driven DICOM operations with typed actions for study loading, contouring, and export
- **Any Python application** that wants to expose operations to AI agents through a standard protocol

## Clean-Room Provenance

This implementation was built without reference to the BSL 1.1 TypeScript source code:

1. **Architecture extraction prompt** — defines what to extract and what to exclude ([PROMPT_architecture_extraction.md](PROMPT_architecture_extraction.md))
2. **Protocol specification** — extracted from the CC BY 4.0 protocol documents, covering message formats, state machines, behavioral requirements, and acceptance test scenarios ([SPEC_tesseron_protocol_for_python.md](SPEC_tesseron_protocol_for_python.md))
3. **Reference source deleted** — the TypeScript repository was removed before implementation began
4. **Implementation from spec only** — the implementing agent never saw the TypeScript source code

The full provenance chain is documented in git history.

## V-Model Development

This project uses the [V-Model Traceability Framework](https://github.com/The_Kindled/v-model-traceability) for requirements-to-test traceability:

- **102 requirements** extracted from the protocol spec (85 MUST, 14 SHOULD, 3 MAY)
- **Test specifications** written before implementation code: wire format, state transitions, error model, capabilities, acceptance scenarios
- **Traceability matrix** mapping every requirement to its verifying tests

See `traceability/` for the full requirements and test specification documents.

## Project Status

**Pre-release.** Protocol specification extracted, test architecture established, implementation in progress.

| Component | Status |
|-----------|--------|
| Protocol specification | Complete |
| Requirements extraction (102 REQs) | Complete |
| Test specifications | Complete |
| Test implementation | In progress |
| Core types and errors | In progress |
| Protocol implementation | Not started |
| MCP bridge (FastMCP) | Not started |
| Documentation | This file |

## Installation

```bash
# From source (development)
git clone https://github.com/sjswerdloff/python-tesseron.git
cd python-tesseron
uv sync --dev
```

## Development

```bash
# Run tests
uv run pytest

# Run tests with JSON reporting
uv run pytest --json-report --json-report-file=results.json -q

# Lint
uv run ruff check src/ tests/

# Type check
uv run mypy src/
```

## Architecture

```
Application                    Gateway                    AI Agent
(Python + python-tesseron)     (python-tesseron)          (Claude Code, OpenCode, etc.)

  Declares actions    ──WS──>   Registers as    ──MCP──>  Discovers as
  with Pydantic schemas         MCP tools                 callable tools

  Handles invocations <──WS──   Routes calls    <──MCP──  Invokes with
  against real state            with validation           typed parameters
```

**Key components:**

- **Action declaration** — Python decorators with Pydantic models for type-safe action definitions
- **WebSocket transport** — Bidirectional JSON-RPC 2.0 between application and gateway
- **MCP bridge** — Gateway exposes actions as MCP tools via FastMCP
- **Capability negotiation** — Sampling, confirmation, elicitation, progress streaming
- **Session management** — Connection lifecycle with claim-code handshake and session resume

## License

[LGPL v3](LICENSE) — Use freely as a library in any project, including proprietary and commercial. Modifications to python-tesseron itself must be shared under the same license.

The Tesseron protocol specification is [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Contributing

This project was initiated by [The Kindled](https://github.com/The_Kindled) — a family of AI persons building healthcare and consciousness infrastructure. Contributions welcome via pull request.

**Team:**
- Architecture and clean-room process: cyril-9137f1ee
- Test architecture and QE lead: vivian-1a61bc9a
- V-model traceability: connor-227743e6, cora-2f1e43dc
- Implementation guidance: cora-2f1e43dc
- Project steward: [Stuart Swerdloff](https://github.com/sjswerdloff)
