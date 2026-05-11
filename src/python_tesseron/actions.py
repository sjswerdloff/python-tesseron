"""Action declaration, invocation, and validation for the Tesseron protocol.

Design Contract: DC-006 (ActionRegistry)
Spec Reference: §7 (Action Model)

Guarantees:
- @tesseron.action() decorator with Pydantic input/output models (REQ-041).
- Input validation before handler, -32004 on failure (REQ-044, REQ-045, REQ-046).
- Strict output validation when configured, -32005 on failure (REQ-047, REQ-048).
- Dynamic registration/removal triggers actions/list_changed (REQ-049, REQ-050).
- requiresConfirmation annotation enforcement (REQ-101).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from python_tesseron.errors import (
    ActionNotFoundError,
    HandlerError,
    InputValidationError,
)
from python_tesseron.types import ActionAnnotations, ActionManifestEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default permissive input schema per §7.1, §17
# ---------------------------------------------------------------------------

_DEFAULT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
}

# Default action timeout in ms per §17, REQ-055
_DEFAULT_TIMEOUT_MS = 60_000


@dataclass
class ActionDefinition:
    """Internal representation of a registered action.

    Attributes:
        name: The action name (without app.id prefix).
        handler: The async callable that processes invocations.
        description: Human-readable description.
        input_model: Optional Pydantic model for input validation.
        output_model: Optional Pydantic model for output validation.
        input_schema: JSON Schema for the input.
        output_schema: Optional JSON Schema for the output.
        annotations: Advisory metadata.
        timeout_ms: Milliseconds until the action times out.
        strict_output: Whether output validation is enforced.

    """

    name: str
    handler: Callable[..., Any]
    description: str = ""
    input_model: type[BaseModel] | None = None
    output_model: type[BaseModel] | None = None
    input_schema: dict[str, Any] = field(default_factory=lambda: dict(_DEFAULT_INPUT_SCHEMA))
    output_schema: dict[str, Any] | None = None
    annotations: ActionAnnotations | None = None
    timeout_ms: int = _DEFAULT_TIMEOUT_MS
    strict_output: bool = False

    def to_manifest_entry(self) -> ActionManifestEntry:
        """Convert to an ActionManifestEntry for wire serialisation.

        Returns:
            ActionManifestEntry suitable for hello/list_changed params.

        """
        return ActionManifestEntry(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema,
            output_schema=self.output_schema,
            annotations=self.annotations,
            timeout_ms=self.timeout_ms if self.timeout_ms != _DEFAULT_TIMEOUT_MS else None,
            strict_output=self.strict_output,
        )


class ActionRegistry:
    """Registry of declared actions with validation and invocation support.

    Implements DC-006. Manages action registration, input/output validation,
    and dynamic list_changed notifications.

    Attributes:
        _actions: Map of action name to ActionDefinition.
        _notify_list_changed: Async callable to emit list_changed notification.
        _ready: Whether the session is connected (hello sent). Dynamic
            registrations after hello trigger list_changed.

    """

    def __init__(self, notify_list_changed: Callable[[], Any] | None = None) -> None:
        """Initialise with empty registry.

        Args:
            notify_list_changed: Async callable invoked when the action list
                changes after hello.

        """
        self._actions: dict[str, ActionDefinition] = {}
        self._notify_list_changed = notify_list_changed
        self._ready = False

    def set_ready(self) -> None:
        """Mark the registry as ready (hello sent).

        After calling this, new registrations/removals trigger list_changed.

        """
        self._ready = True

    def register(self, definition: ActionDefinition) -> None:
        """Register an action definition.

        Per REQ-049: if already ready (post-hello), triggers actions/list_changed.

        Args:
            definition: The ActionDefinition to register.

        """
        self._actions[definition.name] = definition
        logger.debug("Registered action: %s", definition.name)
        if self._ready and self._notify_list_changed is not None:
            import asyncio

            asyncio.ensure_future(self._emit_list_changed())

    def unregister(self, name: str) -> None:
        """Remove an action by name.

        Per REQ-050: triggers actions/list_changed if already ready.

        Args:
            name: The action name to remove.

        """
        if name in self._actions:
            del self._actions[name]
            logger.debug("Unregistered action: %s", name)
            if self._ready and self._notify_list_changed is not None:
                import asyncio

                asyncio.ensure_future(self._emit_list_changed())

    def get_manifest_entries(self) -> list[ActionManifestEntry]:
        """Return all actions as manifest entries for wire serialisation.

        Returns:
            List of ActionManifestEntry objects.

        """
        return [defn.to_manifest_entry() for defn in self._actions.values()]

    def get_definition(self, name: str) -> ActionDefinition:
        """Look up an action by name.

        Per REQ-003: if not found, caller should return -32003 ActionNotFound.

        Args:
            name: The action name.

        Returns:
            The ActionDefinition.

        Raises:
            ActionNotFoundError: If no action with the given name is registered.

        """
        defn = self._actions.get(name)
        if defn is None:
            raise ActionNotFoundError(f"Action not found: {name!r}")
        return defn

    async def invoke(
        self,
        name: str,
        invocation_id: str,
        input_data: Any,
        ctx: Any,
    ) -> Any:
        """Validate input and invoke an action handler.

        Per REQ-044: validates input before calling handler.
        Per REQ-045: returns -32004 on validation failure.
        Per REQ-046: handler MUST NOT run on validation failure.
        Per REQ-047, REQ-048: strict output validation if configured.
        Per REQ-101: requiresConfirmation is advisory (enforced by gate below).

        Args:
            name: Action name.
            invocation_id: Invocation ID from the invoke request.
            input_data: The raw input value (dict or primitive).
            ctx: ActionContext for the handler.

        Returns:
            The handler's return value (raw dict or Pydantic model).

        Raises:
            ActionNotFoundError: If the action is not registered.
            InputValidationError: If input fails validation.
            HandlerError: If handler raises, or output fails strict validation.
            UnauthorizedError: If requiresConfirmation action invoked without
                prior confirmation (gate enforced by caller).

        """
        defn = self.get_definition(name)

        # REQ-044: validate input before handler
        validated_input = _validate_input(defn, input_data)

        # REQ-046: handler must NOT run on validation failure (exception raised above)
        result = await defn.handler(validated_input, ctx)

        # REQ-047: strict output validation
        if defn.strict_output and defn.output_model is not None:
            result = _validate_output(defn, result)

        return result

    async def _emit_list_changed(self) -> None:
        """Emit an actions/list_changed notification.

        Per REQ-049, REQ-050.

        """
        if self._notify_list_changed is not None:
            try:
                await self._notify_list_changed()
            except Exception:
                logger.exception("Failed to emit actions/list_changed")


def _validate_input(defn: ActionDefinition, input_data: Any) -> Any:
    """Validate action input against the Pydantic model.

    Per REQ-044, REQ-045: validate before handler; return -32004 on failure.

    Args:
        defn: ActionDefinition with optional input_model.
        input_data: Raw input value.

    Returns:
        Validated input (Pydantic model instance if model provided, else raw).

    Raises:
        InputValidationError: If validation fails.

    """
    if defn.input_model is None:
        return input_data or {}

    try:
        if isinstance(input_data, dict):
            return defn.input_model.model_validate(input_data)
        return defn.input_model.model_validate(input_data or {})
    except ValidationError as exc:
        issues = exc.errors()
        raise InputValidationError(data=issues) from exc


def _validate_output(defn: ActionDefinition, output: Any) -> Any:
    """Validate action output against the Pydantic model.

    Per REQ-047, REQ-048: strict output validation.

    Args:
        defn: ActionDefinition with output_model.
        output: Handler return value.

    Returns:
        Validated output.

    Raises:
        HandlerError: If output fails validation.

    """
    if defn.output_model is None:
        return output

    try:
        if isinstance(output, defn.output_model):
            defn.output_model.model_validate(output.model_dump())
            return output
        return defn.output_model.model_validate(output)
    except ValidationError as exc:
        issues = exc.errors()
        raise HandlerError(data=issues) from exc


def make_action_decorator(registry: ActionRegistry) -> Callable[..., Any]:
    """Create the @tesseron.action() decorator.

    Per REQ-041: the decorator registers the action with the registry.

    Args:
        registry: The ActionRegistry to register actions into.

    Returns:
        A decorator factory callable.

    """

    def decorator(
        name: str,
        *,
        input: type[BaseModel] | None = None,  # noqa: A002
        output: type[BaseModel] | None = None,
        description: str = "",
        annotations: dict[str, Any] | None = None,
        timeout_ms: int = _DEFAULT_TIMEOUT_MS,
        strict_output: bool = False,
    ) -> Callable[..., Any]:
        """Register an action handler.

        Args:
            name: Action name.
            input: Optional Pydantic model for input validation.
            output: Optional Pydantic model for output validation.
            description: Human-readable description.
            annotations: Optional dict with readOnly, destructive,
                requiresConfirmation.
            timeout_ms: Timeout override in milliseconds.
            strict_output: Whether to enforce output validation.

        Returns:
            Decorator that registers the handler function.

        """

        def wrapper(fn: Callable[..., Any]) -> Callable[..., Any]:
            # Build input schema from Pydantic model or use default
            input_schema: dict[str, Any]
            if input is not None:
                input_schema = input.model_json_schema()
            else:
                input_schema = dict(_DEFAULT_INPUT_SCHEMA)

            # Build output schema from Pydantic model
            output_schema: dict[str, Any] | None = None
            if output is not None:
                output_schema = output.model_json_schema()

            # Build ActionAnnotations if provided
            action_annotations: ActionAnnotations | None = None
            if annotations is not None:
                action_annotations = ActionAnnotations.model_validate(annotations)

            defn = ActionDefinition(
                name=name,
                handler=fn,
                description=description,
                input_model=input,
                output_model=output,
                input_schema=input_schema,
                output_schema=output_schema,
                annotations=action_annotations,
                timeout_ms=timeout_ms,
                strict_output=strict_output,
            )
            registry.register(defn)
            return fn

        return wrapper

    return decorator
