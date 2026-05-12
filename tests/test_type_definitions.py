"""Isolation tests for DC-015 (TypeDefinitions).

Design Contract: DC-015
Module: python_tesseron/types.py

These tests verify DC-015 guarantees in isolation — no dispatcher, no transport.
Each test references only requirements fulfilled by DC-015, producing full
verified_by coverage.

Guarantees tested:
- All wire types modeled as Pydantic BaseModel with ConfigDict(extra=ignore)
- camelCase wire names aliased to snake_case Python names
- JSON-RPC envelope shapes: Request, Notification, SuccessResponse, ErrorResponse
- id may be string, int, or None (REQ-003)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from python_tesseron.types import (
    ActionInvokeParams,
    ActionManifestEntry,
    AgentIdentity,
    JsonRpcErrorObject,
    JsonRpcErrorResponse,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcSuccessResponse,
    TesseronCapabilities,
    WelcomeResult,
)

# ---------------------------------------------------------------------------
# TD-01: Pydantic model validation — valid construction
# ---------------------------------------------------------------------------


class TestPydanticValidation:
    """TD-01 through TD-04: Core Pydantic validation guarantees."""

    def test_td01_request_valid_construction(self) -> None:
        """TD-01: JsonRpcRequest constructs with valid data.

        Verifies: DC-015 — Request envelope shape (method + id).
        REQ-003
        """
        req = JsonRpcRequest(id=1, method="tesseron/hello", params={"key": "value"})
        assert req.jsonrpc == "2.0"
        assert req.id == 1
        assert req.method == "tesseron/hello"
        assert req.params == {"key": "value"}

    def test_td02_request_id_types(self) -> None:
        """TD-02: Request id may be string, int, or None.

        Verifies: DC-015 — id may be string, int, or None per REQ-003.
        REQ-003
        """
        req_int = JsonRpcRequest(id=42, method="test")
        assert req_int.id == 42

        req_str = JsonRpcRequest(id="abc-123", method="test")
        assert req_str.id == "abc-123"

        req_none = JsonRpcRequest(id=None, method="test")
        assert req_none.id is None

    def test_td03_notification_no_id(self) -> None:
        """TD-03: Notification has method but no id field.

        Verifies: DC-015 — Notification envelope shape (method only).
        REQ-098
        """
        notif = JsonRpcNotification(method="actions/progress", params={"percent": 50})
        assert notif.jsonrpc == "2.0"
        assert notif.method == "actions/progress"
        assert not hasattr(notif, "id") or "id" not in notif.model_fields

    def test_td04_envelope_shapes(self) -> None:
        """TD-04: All four envelope shapes construct correctly.

        Verifies: DC-015 — Request, Notification, SuccessResponse, ErrorResponse.
        REQ-098
        """
        request = JsonRpcRequest(id=1, method="test")
        assert request.id == 1 and request.method == "test"

        notification = JsonRpcNotification(method="notify")
        assert notification.method == "notify"

        success = JsonRpcSuccessResponse(id=1, result={"ok": True})
        assert success.id == 1 and success.result == {"ok": True}

        error_obj = JsonRpcErrorObject(code=-32600, message="Invalid")
        error = JsonRpcErrorResponse(id=1, error=error_obj)
        assert error.id == 1 and error.error.code == -32600

    def test_td05_request_missing_required_field(self) -> None:
        """TD-05: Missing required field raises ValidationError.

        Verifies: DC-015 — Pydantic ValidationError on malformed input.
        REQ-098
        """
        with pytest.raises(ValidationError):
            JsonRpcRequest(id=1)  # type: ignore[call-arg]  # missing method

    def test_td06_error_response_missing_error(self) -> None:
        """TD-06: ErrorResponse without error field raises ValidationError.

        Verifies: DC-015 — Pydantic ValidationError on malformed input.
        REQ-098
        """
        with pytest.raises(ValidationError):
            JsonRpcErrorResponse(id=1)  # type: ignore[call-arg]  # missing error


# ---------------------------------------------------------------------------
# TD-07 through TD-10: camelCase aliasing round-trip
# ---------------------------------------------------------------------------


class TestCamelCaseAliasing:
    """TD-07 through TD-10: camelCase wire names aliased to snake_case Python."""

    def test_td07_snake_to_camel_serialization(self) -> None:
        """TD-07: snake_case Python fields serialize to camelCase wire format.

        Verifies: DC-015 — camelCase wire names aliased to snake_case Python names.
        REQ-098
        """
        welcome = WelcomeResult(
            session_id="sess-1",
            protocol_version="1.2.0",
            capabilities=TesseronCapabilities(),
            agent=AgentIdentity(id="agent-1", name="TestAgent"),
            claim_code="ABCD-EF",
            resume_token="tok-123",
        )
        dumped = welcome.model_dump(by_alias=True)
        assert "sessionId" in dumped
        assert "protocolVersion" in dumped
        assert "claimCode" in dumped
        assert "resumeToken" in dumped
        # snake_case keys should NOT appear
        assert "session_id" not in dumped
        assert "protocol_version" not in dumped

    def test_td08_camel_to_snake_parsing(self) -> None:
        """TD-08: camelCase wire dict parses to snake_case Python attributes.

        Verifies: DC-015 — camelCase wire names aliased to snake_case Python names.
        REQ-098
        """
        wire_data = {
            "sessionId": "sess-2",
            "protocolVersion": "1.2.0",
            "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
            "agent": {"id": "agent-2", "name": "Agent2"},
            "claimCode": "WXYZ-12",
            "resumeToken": "tok-456",
        }
        welcome = WelcomeResult.model_validate(wire_data)
        assert welcome.session_id == "sess-2"
        assert welcome.protocol_version == "1.2.0"
        assert welcome.claim_code == "WXYZ-12"
        assert welcome.resume_token == "tok-456"

    def test_td09_action_manifest_aliasing(self) -> None:
        """TD-09: ActionManifestEntry aliases round-trip correctly.

        Verifies: DC-015 — camelCase aliasing on nested types.
        REQ-098
        """
        wire = {
            "name": "do_thing",
            "inputSchema": {"type": "object"},
            "outputSchema": {"type": "string"},
            "timeoutMs": 5000,
            "strictOutput": True,
        }
        entry = ActionManifestEntry.model_validate(wire)
        assert entry.input_schema == {"type": "object"}
        assert entry.timeout_ms == 5000
        assert entry.strict_output is True

        dumped = entry.model_dump(by_alias=True)
        assert "inputSchema" in dumped
        assert "timeoutMs" in dumped
        assert "strictOutput" in dumped

    def test_td10_aliasing_round_trip(self) -> None:
        """TD-10: Parse from camelCase, dump to camelCase, parse again — identical.

        Verifies: DC-015 — camelCase aliasing is lossless round-trip.
        REQ-098
        """
        wire = {
            "invocationId": "inv-1",
            "name": "greet",
            "input": {"who": "world"},
        }
        parsed = ActionInvokeParams.model_validate(wire)
        dumped = parsed.model_dump(by_alias=True)
        reparsed = ActionInvokeParams.model_validate(dumped)
        assert reparsed.invocation_id == parsed.invocation_id
        assert reparsed.name == parsed.name
        assert reparsed.input == parsed.input


# ---------------------------------------------------------------------------
# TD-11 through TD-13: extra=ignore behavior
# ---------------------------------------------------------------------------


class TestExtraIgnore:
    """TD-11 through TD-13: Unknown fields silently ignored."""

    def test_td11_unknown_fields_dropped(self) -> None:
        """TD-11: Unknown fields in wire data are silently ignored.

        Verifies: DC-015 — ConfigDict(extra=ignore).
        REQ-098
        """
        wire = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "test",
            "params": None,
            "futureField": "from-v2",
            "anotherNew": 42,
        }
        req = JsonRpcRequest.model_validate(wire)
        assert req.method == "test"
        assert not hasattr(req, "futureField")
        assert not hasattr(req, "anotherNew")

    def test_td12_extra_ignore_no_error(self) -> None:
        """TD-12: Extra fields do NOT cause ValidationError.

        Verifies: DC-015 — future protocol versions don't break parsing.
        REQ-098
        """
        wire = {
            "streaming": True,
            "subscriptions": True,
            "sampling": False,
            "elicitation": True,
            "newCapability": True,
        }
        caps = TesseronCapabilities.model_validate(wire)
        assert caps.sampling is False
        assert not hasattr(caps, "newCapability")

    def test_td13_extra_ignore_on_nested_models(self) -> None:
        """TD-13: extra=ignore applies to nested models too.

        Verifies: DC-015 — ConfigDict(extra=ignore) on all wire types.
        REQ-098
        """
        wire = {
            "name": "action_a",
            "description": "test",
            "annotations": {
                "readOnly": True,
                "futureAnnotation": "ignored",
            },
        }
        entry = ActionManifestEntry.model_validate(wire)
        assert entry.annotations is not None
        assert entry.annotations.read_only is True
        assert not hasattr(entry.annotations, "futureAnnotation")
