# Gap Analysis — Requirements Without Test Coverage

Generated: 2026-05-11
Total requirements: 102
Covered by tests: 84 (82%)
Uncovered: 18

## Not Testable in Code (3)

| REQ | Title | Rationale |
|-----|-------|-----------|
| REQ-001 | Implementer must not consult TypeScript impl | Process discipline — enforced by clean-room workflow, not code tests |
| REQ-091 | Acceptance tests must all be satisfied | Meta-requirement — satisfied when all AT-01 through AT-20 pass |
| REQ-098 | API naming may be adjusted for Python | Design choice (MAY) — no behavioral test needed |

## Need Additional Tests — Critical (5)

| REQ | Title | Proposed Test |
|-----|-------|---------------|
| REQ-032 | Reserved app IDs must not be used | SEC-01: Attempt hello with app.id="tesseron", verify rejection. Repeat for "mcp", "system" |
| REQ-087 | Gateway must refuse non-loopback manifest URLs | SEC-02: Write manifest with non-loopback URL, verify gateway refuses connection |
| REQ-088 | tesseron directory must be mode 0o700 | SEC-03: Verify ~/.tesseron/ directory permissions after SDK creates it |
| REQ-089 | Instance manifests must be mode 0o600 | SEC-04: Verify manifest file permissions after SDK writes it |
| REQ-090 | Claim breadcrumb files must be mode 0o600 | SEC-05: Verify breadcrumb file permissions |
| REQ-101 | requiresConfirmation must not be called uninvited | SEC-06: Declare action with requiresConfirmation, invoke without confirmation, verify rejection |

## Need Additional Tests — High (7)

| REQ | Title | Proposed Test |
|-----|-------|---------------|
| REQ-015 | WS binary frames should be coerced to UTF-8 | WF-36: Send binary frame with valid JSON, verify parsed correctly |
| REQ-027 | Instance ID should use inst- prefix | WF-37: Generate instanceId, verify inst- prefix |
| REQ-029 | App should clean up on SIGINT and SIGTERM | ST-21: Send SIGINT, verify manifest deleted and transport closed |
| REQ-041 | Actions should use decorator with Pydantic models | API-01: Declare action via @tesseron.action decorator, verify registration |
| REQ-053 | Handler should check for cancellation | ST-22: Start long action, cancel, verify handler's cancellation check path |
| REQ-066 | SDK should send permissive fallback elicit schema | CP-14: Call ctx.elicit() without schema, verify fallback schema sent |
| REQ-100 | SDK should declare all capabilities as true | CP-15: Inspect hello params, verify all four capabilities declared true |

## Need Additional Tests — Medium (1)

| REQ | Title | Proposed Test |
|-----|-------|---------------|
| REQ-067 | Callers should always provide elicit schema | API-02: Lint/documentation test — verify elicit examples include schema |

## Not Practical to Test (1)

| REQ | Title | Rationale |
|-----|-------|-----------|
| REQ-014 | Transport must use local IPC threat model | Architecture constraint — verified by REQ-018/086 (loopback binding) |

## Summary

Adding the 14 proposed tests (SEC-01 through SEC-06, WF-36-37, ST-21-22, API-01-02, CP-14-15) would bring coverage to 99/102 (97%). The 3 untestable requirements are process/meta/design constraints.
