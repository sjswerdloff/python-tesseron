# Wire Format Test Specifications

Source: Spec §2 Wire Format (JSON-RPC 2.0)

## Envelope Shape Tests (§2.1)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| WF-01 | Request has jsonrpc, id, method, params | Construct request, serialize, verify all four fields present |
| WF-02 | Notification has jsonrpc, method, params but NO id | Construct notification, serialize, verify no id field |
| WF-03 | Success response has jsonrpc, id, result | Construct response, serialize, verify fields |
| WF-04 | Error response has jsonrpc, id, error with code+message | Construct error, serialize, verify structure |
| WF-05 | Notification MUST NOT receive a response | Send notification, verify no response sent back |

## ID Rules Tests (§2.2)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| WF-06 | SDK SHOULD use monotonically incrementing integers for id | Send 3 requests, verify ids are sequential |
| WF-07 | Responding peer MUST echo exact same id | Send request with id=42, verify response has id=42 |
| WF-08 | SDK MUST maintain pending request map keyed by id | Send request, verify map entry exists, receive response, verify entry removed |
| WF-09 | On transport close, ALL pending requests MUST be rejected | Send 3 requests, close transport, verify all 3 rejected with TransportClosedError |

## Method Surface Tests (§2.3)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| WF-10 | App->Gateway methods: tesseron/hello is request | Send hello, verify response expected |
| WF-11 | App->Gateway methods: actions/progress is notification | Send progress, verify no response |
| WF-12 | App->Gateway methods: actions/list_changed is notification | Send list_changed, verify no response |
| WF-13 | Gateway->App methods: actions/invoke is request | Receive invoke, verify response required |
| WF-14 | Gateway->App methods: actions/cancel is notification | Receive cancel, verify no response sent |

## Transport Binding Tests — WebSocket (§3.2)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| WF-15 | One JSON-RPC envelope per WebSocket text frame | Send message, verify single frame contains one complete JSON object |
| WF-16 | No batching, no binary, no compression | Verify config disables compression, binary frames coerced to text |
| WF-17 | Gateway sends Sec-WebSocket-Protocol: tesseron-gateway | Verify subprotocol in upgrade request |
| WF-18 | App MUST reject upgrades without tesseron-gateway subprotocol | Connect without subprotocol, verify rejection |
| WF-19 | App MUST bind to loopback only | Verify bind address is 127.0.0.1 or ::1 |
| WF-20 | App MUST accept exactly one upgrade with tesseron-gateway | First connection accepted, second rejected |
| WF-21 | App writes manifest on bind, deletes on close | Verify manifest file lifecycle |

## Transport Binding Tests — UDS (§3.3)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| WF-22 | NDJSON: one envelope per newline-terminated line | Send message, verify newline termination |
| WF-23 | Empty lines are ignored | Send empty line, verify no parse error |
| WF-24 | Private directory mode 0o700 | Create UDS, verify directory permissions |
| WF-25 | Socket file SHOULD be chmod 0o600 | Create UDS, verify socket permissions |
| WF-26 | Accept exactly one connection | First connect accepted, second rejected |
| WF-27 | Delete manifest, socket, and temp dir on close | Verify cleanup on shutdown |

## Dispatcher Tests (Appendix B)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| WF-28 | Message with method+id dispatches to request handler | Send request, verify handler called |
| WF-29 | Message with method but no id dispatches to notification handler | Send notification, verify handler called, no response |
| WF-30 | Message with id+result but no method resolves pending request | Send response, verify pending request resolved |
| WF-31 | Message with id+error but no method rejects pending request | Send error response, verify pending request rejected |
| WF-32 | Message without jsonrpc 2.0 is ignored | Send message without jsonrpc field, verify ignored |
| WF-33 | No handler for method returns -32601 MethodNotFound | Send request for unregistered method, verify error |
| WF-34 | reject_all_pending called on transport close | Close transport, verify all pending rejected |
| WF-35 | Send failure closes transport | Mock send failure, verify transport closed |
