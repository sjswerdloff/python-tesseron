# Error Model Test Specifications

Source: Spec §13 Error Model

## Error Code Tests

Each error code has a test that triggers the condition and verifies the correct code, message, and data structure.

| Test ID | Error Code | Error Name | Trigger | Verification |
|---------|-----------|------------|---------|--------------|
| ER-01 | -32700 | ParseError | Send malformed JSON on wire | Peer receives -32700 response |
| ER-02 | -32600 | InvalidRequest | Send valid JSON but invalid JSON-RPC (missing jsonrpc field) | Peer receives -32600 response |
| ER-03 | -32601 | MethodNotFound | Send request with unregistered method | Peer receives -32601 response |
| ER-04 | -32602 | InvalidParams | Send request with wrong param shape | Peer receives -32602 response |
| ER-05 | -32603 | InternalError | Handler raises unexpected exception | Peer receives -32603 with exception message |
| ER-06 | -32000 | ProtocolMismatch | Send tesseron/hello with incompatible major version | Peer receives -32000 |
| ER-07 | -32001 | Cancelled | Agent sends actions/cancel during invocation | Handler receives CancelledError |
| ER-08 | -32002 | Timeout | Action exceeds timeout_ms | Agent receives -32002, handler cancellation signal fires |
| ER-09 | -32003 | ActionNotFound | Agent invokes non-existent action | Agent receives -32003 |
| ER-10 | -32004 | InputValidation | Agent sends input failing schema validation | Agent receives -32004 with validation issues in error.data |
| ER-11 | -32005 | HandlerError (exception) | Handler raises ValueError | Agent receives -32005 with ValueError message |
| ER-12 | -32005 | HandlerError (strict output) | Handler returns value not matching output schema (strict_output=True) | Agent receives -32005 with validation issues in error.data |
| ER-13 | -32006 | SamplingNotAvailable | Handler calls ctx.sample() without agent sampling capability | SamplingNotAvailableError raised |
| ER-14 | -32007 | ElicitationNotAvailable | Handler calls ctx.elicit() without agent elicitation capability | ElicitationNotAvailableError raised |
| ER-15 | -32008 | SamplingDepthExceeded | Sampling chain exceeds maxSamplingDepth (3) | SamplingDepthExceededError with {depth, max} data |
| ER-16 | -32009 | Unauthorized | Wrong claim code submitted | Agent receives -32009 |
| ER-17 | -32010 | TransportClosed | Transport closes with pending requests | All pending requests rejected with TransportClosedError |
| ER-18 | -32011 | ResumeFailed | Resume with expired TTL or wrong token | SDK receives -32011, clears credentials, falls back to hello |

## Error Mapping Tests (§13.4)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| ER-19 | TesseronError from handler maps to JSON-RPC error with matching code/message/data | Raise TesseronError(code=-32003, message="x", data={"y": 1}), verify wire format |
| ER-20 | Non-TesseronError from handler maps to -32005 HandlerError | Raise RuntimeError("oops"), verify -32005 with message "oops" |
| ER-21 | Incoming JSON-RPC error constructs TesseronError and rejects pending request | Send error response for pending request, verify TesseronError properties |

## Error Class Tests (§13.3)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| ER-22 | SamplingNotAvailableError is subclass of TesseronError with code -32006 | isinstance check, code check |
| ER-23 | ElicitationNotAvailableError is subclass of TesseronError with code -32007 | isinstance check, code check |
| ER-24 | CancelledError is subclass of TesseronError with code -32001 | isinstance check, code check |
| ER-25 | TimeoutError is subclass of TesseronError with code -32002 | isinstance check, code check |
| ER-26 | TransportClosedError is subclass of TesseronError with code -32010 | isinstance check, code check |

## Confirm vs Elicit Error Asymmetry (§10, §13)

| Test ID | Requirement | Verification |
|---------|-------------|--------------|
| ER-27 | ctx.confirm() returns False when elicitation not available (NOT throw) | Call confirm without capability, verify returns False |
| ER-28 | ctx.elicit() throws ElicitationNotAvailableError when not available | Call elicit without capability, verify exception |
