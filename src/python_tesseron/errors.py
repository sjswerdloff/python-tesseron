"""Tesseron protocol error hierarchy.

These error classes correspond directly to the error codes defined in the
Tesseron protocol specification §13.

All errors are subclasses of TesseronError, which carries the JSON-RPC
error code, message, and optional structured data payload.
"""

from __future__ import annotations

from typing import Any


class TesseronError(Exception):
    """Base class for all Tesseron protocol errors.

    Maps directly to a JSON-RPC error object:
    ``{ "code": ..., "message": ..., "data": ... }``

    Attributes:
        code: JSON-RPC error code (negative integer).
        message: Human-readable error description.
        data: Optional structured payload (validation issues, depth info, etc.).

    """

    code: int = -32603  # InternalError default
    message: str = "Internal error"
    data: Any | None = None

    def __init__(
        self,
        message: str | None = None,
        *,
        code: int | None = None,
        data: Any | None = None,
    ) -> None:
        """Initialise a TesseronError.

        Args:
            message: Human-readable description. Defaults to the class-level
                ``message`` attribute if omitted.
            code: JSON-RPC error code. Defaults to the class-level ``code``
                attribute if omitted.
            data: Optional structured payload attached to ``error.data``.

        """
        if code is not None:
            self.code = code
        if message is not None:
            self.message = message
        self.data = data
        super().__init__(self.message)

    def __repr__(self) -> str:
        """Return detailed repr for debugging."""
        return f"{type(self).__name__}(code={self.code}, message={self.message!r}, data={self.data!r})"


class ParseError(TesseronError):
    """JSON-RPC message failed to parse.

    Code: -32700
    """

    code = -32700
    message = "Parse error"


class InvalidRequestError(TesseronError):
    """Valid JSON but not a valid JSON-RPC request.

    Code: -32600
    """

    code = -32600
    message = "Invalid request"


class MethodNotFoundError(TesseronError):
    """Method not registered in the dispatcher.

    Code: -32601
    """

    code = -32601
    message = "Method not found"


class InvalidParamsError(TesseronError):
    """Params do not match the method's expected shape.

    Also raised when elicit schema violates MCP constraints.

    Code: -32602
    """

    code = -32602
    message = "Invalid params"


class InternalError(TesseronError):
    """Unhandled exception in the SDK or gateway.

    Code: -32603
    """

    code = -32603
    message = "Internal error"


class ProtocolMismatchError(TesseronError):
    """tesseron/hello sent a protocolVersion the gateway does not accept.

    Raised when the major version in the hello request does not match the
    gateway's supported major version.

    Code: -32000
    """

    code = -32000
    message = "Protocol version mismatch"


class CancelledError(TesseronError):
    """Invocation was cancelled by the agent.

    Code: -32001
    """

    code = -32001
    message = "Cancelled"


class TimeoutError(TesseronError):
    """Invocation exceeded its configured timeout.

    Code: -32002
    """

    code = -32002
    message = "Timeout"


class ActionNotFoundError(TesseronError):
    """Agent called an action that is not registered for this session.

    Code: -32003
    """

    code = -32003
    message = "Action not found"


class InputValidationError(TesseronError):
    """Input failed schema validation.

    The ``data`` field contains an array of validation issues from the
    schema validator.

    Code: -32004
    """

    code = -32004
    message = "Input validation failed"


class HandlerError(TesseronError):
    """Handler threw, or output failed strict validation.

    For strict output validation failures, ``data`` contains an array of
    validation issues.

    Code: -32005
    """

    code = -32005
    message = "Handler error"


class SamplingNotAvailableError(TesseronError):
    """Handler called ctx.sample() but agent did not advertise sampling.

    Code: -32006
    """

    code = -32006
    message = "Sampling not available"


class ElicitationNotAvailableError(TesseronError):
    """Handler called ctx.elicit() but agent did not advertise elicitation.

    Note: ctx.confirm() returns False instead of raising this error.

    Code: -32007
    """

    code = -32007
    message = "Elicitation not available"


class SamplingDepthExceededError(TesseronError):
    """Sampling chain exceeded maxSamplingDepth (3).

    The ``data`` field contains ``{"depth": N, "max": 3}``.

    Code: -32008
    """

    code = -32008
    message = "Sampling depth exceeded"


class UnauthorizedError(TesseronError):
    """Wrong claim code, unclaimed session invoking action, or origin not allowlisted.

    Code: -32009
    """

    code = -32009
    message = "Unauthorized"


class TransportClosedError(TesseronError):
    """Transport closed while a request was pending.

    Raised to reject all pending outbound requests when the transport
    closes before responses are received.

    Code: -32010
    """

    code = -32010
    message = "Transport closed"


class ResumeFailedError(TesseronError):
    """Session resume failed.

    Conditions: unknown session, bad token, TTL elapsed, wrong app, etc.
    On resume failure, the SDK should clear stored credentials and fall
    back to a fresh tesseron/hello.

    Code: -32011
    """

    code = -32011
    message = "Resume failed"
