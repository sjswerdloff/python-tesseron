# State Transition Test Specifications — Session Lifecycle

Source: Spec §14 Session Lifecycle State Machine

## States

| State | ID |
|-------|-----|
| DISCONNECTED | S1 |
| HANDSHAKING | S2 |
| AWAITING_CLAIM | S3 |
| CLAIMED | S4 |
| CLOSED | S5 |

## Valid Transitions

| From | To | Trigger | Test ID |
|------|-----|---------|---------|
| S1 DISCONNECTED | S2 HANDSHAKING | App opens transport | ST-01 |
| S2 HANDSHAKING | S3 AWAITING_CLAIM | Gateway returns welcome | ST-02 |
| S3 AWAITING_CLAIM | S4 CLAIMED | Agent claims session | ST-03 |
| S3 AWAITING_CLAIM | S5 CLOSED | Transport closes / timeout | ST-04 |
| S4 CLAIMED | S5 CLOSED | Transport closes | ST-05 |

## Invalid Transitions (SHALL NOT occur — test that they are rejected or impossible)

| From | Attempted To | Test ID | Expected Behavior |
|------|-------------|---------|-------------------|
| S1 DISCONNECTED | S3 AWAITING_CLAIM | ST-06 | Cannot reach AWAITING_CLAIM without HANDSHAKING |
| S1 DISCONNECTED | S4 CLAIMED | ST-07 | Cannot claim without handshake |
| S2 HANDSHAKING | S4 CLAIMED | ST-08 | Cannot claim before welcome received |
| S4 CLAIMED | S3 AWAITING_CLAIM | ST-09 | Cannot go back to awaiting claim |
| S5 CLOSED | S4 CLAIMED | ST-10 | Closed sessions cannot be reclaimed |
| S5 CLOSED | S2 HANDSHAKING | ST-11 | New connect() yields NEW session (§14.4) |

## Close Behavior Tests (§14.3 — five MUST requirements on close)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| ST-12 | ALL pending outbound requests MUST be rejected with TransportClosedError | Send request, close transport before response, verify rejection |
| ST-13 | ALL in-flight invocations MUST have cancellation signals fired | Start long action, close transport, verify signal |
| ST-14 | ALL active subscriptions MUST have cleanup functions called | Subscribe to resource, close transport, verify cleanup |
| ST-15 | progress() calls after close MUST be silently dropped | Close transport, call progress(), verify no error and no delivery |
| ST-16 | sample()/confirm()/elicit() in flight MUST reject with TransportClosedError | Start sampling, close transport, verify TransportClosedError |

## Reconnection Tests (§14.4)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| ST-17 | connect() after disconnect yields NEW sessionId and NEW claimCode | Disconnect, reconnect, verify different IDs |
| ST-18 | SDK MUST NOT auto-reconnect silently | Close transport, verify no automatic reconnection attempt |
| ST-19 | Resume within TTL preserves claimed status (§6) | Connect, claim, disconnect, resume within 90s, verify claimed |
| ST-20 | Resume after TTL fails with -32011 ResumeFailed | Connect, claim, disconnect, wait > TTL, attempt resume, verify error |
