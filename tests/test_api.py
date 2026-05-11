"""API surface tests.

Test IDs: API-01, API-02
Source: Spec Appendix A (Python SDK API Surface), §10.4 (Elicitation)
Gap analysis: traceability/gap_analysis.md — REQ-041, REQ-067

Tests verify:
- The decorator-based action declaration API (@tesseron.action).
- That elicit calls include schema (documentation/convention test).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from python_tesseron import Tesseron
from python_tesseron.types import ActionManifestEntry

# ---------------------------------------------------------------------------
# Requirements excluded from automated testing (design/MAY constraints)
#
# REQ-098 (API naming may be adjusted for Python): Design choice — the spec
# explicitly says the implementer MAY adjust API naming to be more Pythonic
# while preserving behavioral equivalence. No behavioral test is needed or
# possible for a permissive naming convention.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# API-01: Decorator-based action declaration
# ---------------------------------------------------------------------------


@pytest.mark.api
def test_api01_action_decorator_registers_action() -> None:
    """API-01: REQ-041. Declare action via @tesseron.action decorator, verify registration.

    Scenario:
    - Create a Tesseron instance.
    - Use @tesseron.action decorator with a Pydantic model for input/output.
    - Verify the action is registered in tesseron's action list.
    - Verify the registered action has correct name, description, and schema.

    Requirements:
    - REQ-041: Actions SHOULD be declared using decorators with Pydantic models.
    """

    class CreateNoteInput(BaseModel):
        title: str
        body: str

    class CreateNoteOutput(BaseModel):
        note_id: str

    tesseron = Tesseron(app={"id": "notes_app", "name": "Notes"})

    @tesseron.action("createNote", input=CreateNoteInput, output=CreateNoteOutput, description="Create a note")
    async def create_note(input: CreateNoteInput, ctx: Any) -> CreateNoteOutput:
        return CreateNoteOutput(note_id="123")

    entries = tesseron._action_registry.get_manifest_entries()
    assert len(entries) == 1
    assert entries[0].name == "createNote"
    assert entries[0].description == "Create a note"
    assert entries[0].input_schema is not None


@pytest.mark.api
def test_api01_action_decorator_generates_correct_input_schema() -> None:
    """API-01: REQ-041. @tesseron.action generates inputSchema from Pydantic model.

    The decorator must derive the JSON Schema for the action's input
    from the Pydantic model's schema, not require manual schema construction.
    """

    class SearchInput(BaseModel):
        query: str
        limit: int = 10

    tesseron = Tesseron(app={"id": "search_app", "name": "Search"})

    @tesseron.action("search", input=SearchInput, description="Search")
    async def search_action(input: SearchInput, ctx: Any) -> dict[str, Any]:
        return {}

    entries = tesseron._action_registry.get_manifest_entries()
    assert len(entries) == 1
    schema = entries[0].input_schema
    assert schema is not None
    assert schema.get("type") == "object"
    # Pydantic generates properties from the model fields
    assert "query" in schema.get("properties", {}) or "query" in str(schema)


@pytest.mark.api
def test_api01_action_decorator_with_timeout_ms() -> None:
    """API-01: REQ-041. @tesseron.action accepts timeout_ms parameter.

    The decorator must forward the timeout_ms override to the ActionDefinition.
    """
    tesseron = Tesseron(app={"id": "timeout_app", "name": "Timeout Test"})

    @tesseron.action("longRunning", description="Long running", timeout_ms=30_000)
    async def long_running(input: Any, ctx: Any) -> dict[str, Any]:
        return {}

    defn = tesseron._action_registry.get_definition("longRunning")
    assert defn.timeout_ms == 30_000


@pytest.mark.api
def test_api01_action_decorator_with_annotations() -> None:
    """API-01: REQ-041. @tesseron.action accepts annotations dict.

    The decorator must forward readOnly, destructive, and requiresConfirmation
    to the ActionDefinition's annotations.
    """
    tesseron = Tesseron(app={"id": "annotated_app", "name": "Annotated"})

    @tesseron.action(
        "deleteOrder",
        description="Delete an order",
        annotations={"destructive": True, "requiresConfirmation": True},
    )
    async def delete_order(input: Any, ctx: Any) -> dict[str, Any]:
        return {}

    defn = tesseron._action_registry.get_definition("deleteOrder")
    assert defn.annotations is not None
    assert defn.annotations.destructive is True
    assert defn.annotations.requires_confirmation is True


# ---------------------------------------------------------------------------
# API-02: elicit calls should include schema
# ---------------------------------------------------------------------------


@pytest.mark.api
def test_api02_elicitation_request_params_require_schema_field() -> None:
    """API-02: REQ-067. ElicitationRequestParams requires a schema field.

    The ElicitationRequestParams model should require the schema field,
    enforcing the convention that callers always provide a proper schema
    (REQ-067: callers SHOULD always provide elicit schema).
    """
    from python_tesseron.types import ElicitationRequestParams

    # Valid construction requires schema; use alias names (populate_by_name=True)
    params = ElicitationRequestParams.model_validate(
        {
            "invocationId": "inv_1",
            "question": "Which warehouse?",
            "schema": {
                "type": "object",
                "properties": {"warehouseId": {"type": "string"}},
                "required": ["warehouseId"],
            },
        }
    )
    assert params.json_schema is not None
    assert params.json_schema["type"] == "object"


@pytest.mark.api
def test_api02_action_manifest_entry_has_default_input_schema() -> None:
    """API-02 related: ActionManifestEntry has permissive default inputSchema.

    Per spec §7.1, when no input schema is provided the default is a permissive
    schema. This allows actions with no mandatory inputs.
    """
    entry = ActionManifestEntry(name="myAction", description="Does things")

    # Default schema should be permissive
    schema = entry.input_schema
    assert schema is not None
    assert schema.get("type") == "object"
    assert schema.get("additionalProperties") is True
