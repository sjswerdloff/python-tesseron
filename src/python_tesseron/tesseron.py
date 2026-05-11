"""Top-level Tesseron class — the public SDK entry point.

Design Contract: DC-001 through DC-016 (integrated)
Spec Reference: Appendix A (Python SDK API Surface)

This module provides the Tesseron class that integrates all modules:
dispatcher, transport, session, handshake, capabilities, actions, resources,
cancellation, sampling, elicitation, and resume.

Usage::

    tesseron = Tesseron(app={"id": "notes", "name": "Notes"})

    @tesseron.action("createNote", input=CreateNoteInput, output=CreateNoteOutput)
    async def create_note(input: CreateNoteInput, ctx: ActionContext) -> CreateNoteOutput:
        ...

    welcome = await tesseron.connect()
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from pydantic import BaseModel

from python_tesseron.actions import ActionRegistry, make_action_decorator
from python_tesseron.cancellation import InvocationController, ProgressEmitter
from python_tesseron.capabilities import CapabilityNegotiation
from python_tesseron.context import ActionContext
from python_tesseron.dispatcher import JsonRpcDispatcher
from python_tesseron.elicitation import ElicitationBridge
from python_tesseron.errors import (
    ActionNotFoundError,
    HandlerError,
    InternalError,
    TesseronError,
    TransportClosedError,
)
from python_tesseron.handshake import HandshakeManager, validate_app_id
from python_tesseron.manifest import DiscoveryManifest, generate_instance_id
from python_tesseron.resources import ResourceManager, make_resource_decorator
from python_tesseron.resume import ResumeCredentials, SessionResumeManager
from python_tesseron.sampling import SamplingBridge
from python_tesseron.session import SessionStateMachine
from python_tesseron.transport_uds import UdsTransport
from python_tesseron.transport_ws import WebSocketTransport
from python_tesseron.transport_ws_client import WebSocketClientTransport
from python_tesseron.types import (
    ActionCancelParams,
    ActionInvokeParams,
    AppMetadata,
    InvocationResult,
    ResourceReadParams,
    ResourceReadResult,
    ResourceSubscribeParams,
    ResourceUnsubscribeParams,
    ResourceUpdatedParams,
    WelcomeResult,
)
from python_tesseron.types import (
    UdsTransport as UdsTransportType,
)
from python_tesseron.types import (
    WsTransport as WsTransportType,
)

logger = logging.getLogger(__name__)

# Reserved app IDs per REQ-032
_RESERVED_APP_IDS = frozenset({"tesseron", "mcp", "system"})


class Tesseron:
    """Top-level SDK class for the Tesseron protocol.

    Integrates all modules: dispatcher, transport, session state machine,
    handshake, capabilities, action registry, resource manager, cancellation,
    sampling, elicitation, and resume.

    Usage::

        tesseron = Tesseron(app={"id": "notes", "name": "Notes"})

        @tesseron.action("createNote", input=CreateNoteInput)
        async def create_note(input: CreateNoteInput, ctx: ActionContext) -> dict:
            ...

        welcome = await tesseron.connect()

    Attributes:
        action: Decorator factory for registering actions (REQ-041).
        resource: Decorator factory for registering resources.

    """

    def __init__(
        self,
        app: dict[str, Any] | AppMetadata,
        *,
        origin: str | None = None,
    ) -> None:
        """Initialise the Tesseron SDK.

        Per REQ-031: validates app.id against regex.
        Per REQ-032: rejects reserved app IDs.

        Args:
            app: App metadata dict or AppMetadata instance. Must include at
                minimum ``id`` and ``name``. ``origin`` defaults to
                ``"python:<id>"`` if not provided.
            origin: Informational origin identifier. Defaults to
                ``"python:<app.id>"``.

        Raises:
            InvalidParamsError: If app.id does not match the pattern.
            UnauthorizedError: If app.id is a reserved value.

        """
        if isinstance(app, dict):
            # Build AppMetadata from dict, supplying default origin
            app_dict = dict(app)
            if "origin" not in app_dict:
                app_dict["origin"] = origin or f"python:{app_dict.get('id', 'unknown')}"
            self._app_meta = AppMetadata.model_validate(app_dict)
        else:
            self._app_meta = app

        # Validate app ID early
        validate_app_id(self._app_meta.id)

        # Core infrastructure
        self._session = SessionStateMachine()
        self._capabilities = CapabilityNegotiation()
        self._handshake = HandshakeManager(self._app_meta, self._session, self._capabilities)
        self._resume_manager = SessionResumeManager(self._session, self._capabilities)

        # Action and resource registries
        self._action_registry = ActionRegistry(notify_list_changed=self._send_action_list_changed)
        self._resource_manager = ResourceManager(
            notify_list_changed=self._send_resource_list_changed,
            notify_updated=self._send_resource_updated,
        )

        # Public API decorators
        self.action = make_action_decorator(self._action_registry)
        self.resource = make_resource_decorator(self._resource_manager)

        # Transport and dispatcher (set on connect)
        self._transport: WebSocketTransport | UdsTransport | WebSocketClientTransport | None = None
        self._dispatcher: JsonRpcDispatcher | None = None
        self._manifest: DiscoveryManifest | None = None
        self._instance_id: str = generate_instance_id()

        # Active invocations map: invocation_id -> InvocationController
        self._invocations: dict[str, InvocationController] = {}

        # Message receive loop task
        self._receive_task: asyncio.Task[None] | None = None

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    async def connect(
        self,
        transport: Literal["ws", "uds"] = "ws",
        resume: ResumeCredentials | dict[str, str] | None = None,
        connection_timeout: float = 30.0,
    ) -> WelcomeResult:
        """Open transport, send hello (or resume), and return WelcomeResult.

        Per REQ-009: hello is the FIRST message. Per REQ-085: no auto-reconnect.
        Per REQ-027: instance ID uses inst- prefix.

        Args:
            transport: Transport type ("ws" or "uds").
            resume: Optional credentials for session resume (REQ-038).
            connection_timeout: Seconds to wait for gateway to connect.

        Returns:
            WelcomeResult with sessionId, capabilities, and claimCode.

        Raises:
            TesseronError: If the handshake fails (e.g., -32000 ProtocolMismatch).

        """
        # Transition state machine
        self._session.to_handshaking()

        # Start transport
        transport_descriptor: WsTransportType | UdsTransportType
        if transport == "ws":
            ws_transport = WebSocketTransport()
            await ws_transport.start()
            self._transport = ws_transport
            transport_descriptor = WsTransportType(url=ws_transport.url)
        else:
            uds_transport = UdsTransport()
            await uds_transport.start()
            self._transport = uds_transport
            transport_descriptor = UdsTransportType(path=str(uds_transport.socket_path))

        # Write instance manifest
        self._manifest = DiscoveryManifest(
            instance_id=self._instance_id,
            app_name=self._app_meta.name,
        )
        self._manifest.write(transport_descriptor)

        # Set up dispatcher with transport's send callback
        self._dispatcher = JsonRpcDispatcher(send=self._transport.send)

        # Register inbound handlers
        self._register_handlers()

        # Start message receive loop
        self._receive_task = asyncio.create_task(self._receive_loop())

        # Wait for gateway to connect
        await self._transport.wait_for_connection(timeout=connection_timeout)

        # Mark registries as ready (hello about to be sent)
        self._action_registry.set_ready()
        self._resource_manager.set_ready()

        # Load resume credentials if provided
        if resume is not None:
            if isinstance(resume, dict):
                creds = ResumeCredentials.from_dict(resume)
            else:
                creds = resume
            self._resume_manager.store_credentials(
                session_id=creds.session_id,
                resume_token=creds.resume_token,
            )

        # Try resume first, fall back to hello
        welcome: WelcomeResult | None = None
        if self._resume_manager.has_credentials:
            welcome = await self._resume_manager.attempt_resume(
                dispatcher=self._dispatcher,
                app_meta=self._app_meta,
                actions=self._action_registry.get_manifest_entries(),
                resources=self._resource_manager.get_manifest_entries(),
            )

        if welcome is None:
            # Fresh hello (REQ-009)
            hello_params = self._handshake.build_hello_params(
                actions=self._action_registry.get_manifest_entries(),
                resources=self._resource_manager.get_manifest_entries(),
            )
            result = await self._dispatcher.request("tesseron/hello", hello_params)
            welcome = self._handshake.process_welcome(result)

            # Store resume credentials for future reconnect
            if welcome.session_id and welcome.resume_token:
                self._resume_manager.store_credentials(
                    session_id=welcome.session_id,
                    resume_token=welcome.resume_token,
                )

        return welcome

    async def connect_as_client(
        self,
        gateway_url: str,
        resume: ResumeCredentials | dict[str, str] | None = None,
        connection_timeout: float = 10.0,
    ) -> WelcomeResult:
        """Connect as a WebSocket CLIENT to an existing gateway server.

        Used in tests where MockGateway acts as the WS server. Does NOT
        start a local WS server or write a manifest — it connects outbound.

        Per REQ-009: hello is the FIRST message sent after connection.

        Args:
            gateway_url: The ws:// URL of the gateway to connect to.
            resume: Optional credentials for session resume (REQ-038).
            connection_timeout: Seconds to wait for connection.

        Returns:
            WelcomeResult with sessionId, capabilities, and claimCode.

        Raises:
            TesseronError: If the handshake fails.

        """
        # Transition state machine
        self._session.to_handshaking()

        # Connect as client
        client_transport = WebSocketClientTransport(gateway_url)
        await client_transport.start()
        self._transport = client_transport

        # Set up dispatcher with transport's send callback
        self._dispatcher = JsonRpcDispatcher(send=client_transport.send)

        # Register inbound handlers
        self._register_handlers()

        # Start message receive loop
        self._receive_task = asyncio.create_task(self._receive_loop())

        # Mark registries as ready
        self._action_registry.set_ready()
        self._resource_manager.set_ready()

        # Load resume credentials if provided
        if resume is not None:
            if isinstance(resume, dict):
                creds = ResumeCredentials.from_dict(resume)
            else:
                creds = resume
            self._resume_manager.store_credentials(
                session_id=creds.session_id,
                resume_token=creds.resume_token,
            )

        # Try resume first, fall back to hello
        welcome: WelcomeResult | None = None
        if self._resume_manager.has_credentials:
            welcome = await self._resume_manager.attempt_resume(
                dispatcher=self._dispatcher,
                app_meta=self._app_meta,
                actions=self._action_registry.get_manifest_entries(),
                resources=self._resource_manager.get_manifest_entries(),
            )

        if welcome is None:
            # Fresh hello (REQ-009)
            hello_params = self._handshake.build_hello_params(
                actions=self._action_registry.get_manifest_entries(),
                resources=self._resource_manager.get_manifest_entries(),
            )
            result = await self._dispatcher.request("tesseron/hello", hello_params)
            welcome = self._handshake.process_welcome(result)

            # Store resume credentials for future reconnect
            if welcome.session_id and welcome.resume_token:
                self._resume_manager.store_credentials(
                    session_id=welcome.session_id,
                    resume_token=welcome.resume_token,
                )

        return welcome

    async def disconnect(self) -> None:
        """Close the transport and perform cleanup.

        Per §14.3: rejects pending requests, fires cancel signals, cleans up
        subscriptions. Per REQ-028: deletes manifest.

        """
        self._session.to_closed()

        # Cancel all in-flight invocations
        for controller in list(self._invocations.values()):
            controller.cancel()
        self._invocations.clear()

        # Close all subscriptions
        await self._resource_manager.close_all_subscriptions()

        # Reject pending requests
        if self._dispatcher is not None:
            await self._dispatcher.reject_all_pending(TransportClosedError())

        # Stop receive loop
        if self._receive_task is not None:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        # Close transport
        if self._transport is not None:
            await self._transport.close()
            self._transport = None

        # Delete manifest
        if self._manifest is not None:
            self._manifest.delete()
            self._manifest = None

    # ------------------------------------------------------------------
    # Message receive loop
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        """Read messages from the transport and dispatch to the dispatcher.

        Runs as a background task while the session is active.

        """
        if self._transport is None or self._dispatcher is None:
            return

        async for raw_text in self._transport.messages():
            parsed = JsonRpcDispatcher.parse_message(raw_text)
            if parsed is None:
                logger.debug("Failed to parse incoming message; skipping")
                continue
            try:
                await self._dispatcher.receive(parsed)
            except Exception:
                logger.exception("Dispatcher error processing message")

        # Transport closed — perform close cascade
        if not self._session.state == "CLOSED":
            await self._on_transport_closed()

    async def _on_transport_closed(self) -> None:
        """Perform the close cascade on unexpected transport close.

        Per §14.3: reject pending, fire cancellations, clean up subscriptions.

        """
        logger.info("Transport closed unexpectedly; performing close cascade")
        self._session.to_closed()

        for controller in list(self._invocations.values()):
            controller.cancel()
        self._invocations.clear()

        await self._resource_manager.close_all_subscriptions()

        if self._dispatcher is not None:
            await self._dispatcher.reject_all_pending(TransportClosedError())

        if self._manifest is not None:
            self._manifest.delete()
            self._manifest = None

    # ------------------------------------------------------------------
    # Handler registration
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        """Register all inbound method handlers on the dispatcher.

        Called once after the dispatcher is created.

        """
        if self._dispatcher is None:
            return

        self._dispatcher.on("actions/invoke", self._handle_invoke)
        self._dispatcher.on("resources/read", self._handle_resource_read)
        self._dispatcher.on("resources/subscribe", self._handle_resource_subscribe)
        self._dispatcher.on("resources/unsubscribe", self._handle_resource_unsubscribe)
        self._dispatcher.on_notification("actions/cancel", self._handle_cancel)
        self._dispatcher.on_notification("tesseron/claimed", self._handle_claimed)

    # ------------------------------------------------------------------
    # Inbound handlers
    # ------------------------------------------------------------------

    async def _handle_invoke(self, params: dict[str, Any] | None) -> Any:
        """Handle an actions/invoke request from the gateway.

        Per REQ-042, REQ-043: result must contain invocationId and output.
        Per REQ-044, REQ-045, REQ-046: input validated before handler.
        Per REQ-057: race handler against timeout and cancel.

        Args:
            params: Raw ActionInvokeParams dict.

        Returns:
            InvocationResult dict with invocationId and output.

        Raises:
            TesseronError: On validation, handler, or timeout errors.

        """
        invoke_params = ActionInvokeParams.model_validate(params or {})

        # Look up action
        action_defn = self._action_registry.get_definition(invoke_params.name)

        # Create invocation controller
        controller = InvocationController(
            invocation_id=invoke_params.invocation_id,
            timeout_ms=action_defn.timeout_ms,
        )
        self._invocations[invoke_params.invocation_id] = controller

        # Build context
        capabilities = self._capabilities.current
        progress_emitter = ProgressEmitter(
            invocation_id=invoke_params.invocation_id,
            notify=self._dispatcher.notify if self._dispatcher else _noop_notify,
        )
        sampling_bridge = SamplingBridge(
            dispatcher=self._dispatcher,
            capabilities=capabilities,
        )
        elicitation_bridge = ElicitationBridge(
            dispatcher=self._dispatcher,
            capabilities=capabilities,
        )
        ctx = ActionContext(
            invocation_id=invoke_params.invocation_id,
            cancel_event=controller.cancel_event,
            agent=self._handshake.agent,
            agent_capabilities=capabilities,
            progress_emitter=progress_emitter,
            sampling_bridge=sampling_bridge,
            elicitation_bridge=elicitation_bridge,
            notify=self._dispatcher.notify if self._dispatcher else _noop_notify,
            client=invoke_params.client,
        )

        # Use a Future to collect the result
        result_future: asyncio.Future[Any] = asyncio.get_event_loop().create_future()

        async def send_result(output: Any) -> None:
            if not result_future.done():
                result_future.set_result(output)

        async def send_error(exc: Exception) -> None:
            if isinstance(exc, TesseronError):
                err = exc
            else:
                err = HandlerError(str(exc))
            if not result_future.done():
                result_future.set_exception(err)

        async def run() -> None:
            try:
                from python_tesseron.actions import _validate_input, _validate_output

                validated_input = _validate_input(action_defn, invoke_params.input)
                result = await action_defn.handler(validated_input, ctx)
                if action_defn.strict_output and action_defn.output_model is not None:
                    result = _validate_output(action_defn, result)
                if isinstance(result, BaseModel):
                    output = result.model_dump(by_alias=True)
                else:
                    output = result
                await send_result(output)
            except TesseronError:
                raise
            except Exception as exc:
                raise HandlerError(str(exc)) from exc

        await controller.run_handler(
            coro=run(),
            send_error=send_error,
            send_result=send_result,
        )

        # Remove from active invocations
        self._invocations.pop(invoke_params.invocation_id, None)
        progress_emitter.mark_closed()

        # Re-raise any error from the future
        if result_future.done():
            exc = result_future.exception()
            if exc is not None:
                raise exc
            output = result_future.result()
        else:
            raise InternalError("Invocation completed without setting result")

        inv_result = InvocationResult(
            invocation_id=invoke_params.invocation_id,
            output=output,
        )
        return inv_result.model_dump(by_alias=True)

    async def _handle_cancel(self, params: dict[str, Any] | None) -> None:
        """Handle an actions/cancel notification.

        Per REQ-052: fire the cancellation signal for the invocation.
        Per REQ-054: the invocation handler will return -32001 Cancelled.

        Args:
            params: ActionCancelParams dict.

        """
        cancel_params = ActionCancelParams.model_validate(params or {})
        controller = self._invocations.get(cancel_params.invocation_id)
        if controller is not None:
            controller.cancel()
            logger.debug("Cancel fired for invocation %s", cancel_params.invocation_id)
        else:
            logger.debug("Cancel for unknown invocation %s; ignored", cancel_params.invocation_id)

    async def _handle_resource_read(self, params: dict[str, Any] | None) -> dict[str, Any]:
        """Handle a resources/read request.

        Args:
            params: ResourceReadParams dict.

        Returns:
            ResourceReadResult dict with value field.

        Raises:
            TesseronError: If resource not found.

        """
        read_params = ResourceReadParams.model_validate(params or {})
        try:
            value = await self._resource_manager.handle_read(read_params.name)
        except KeyError as exc:
            raise ActionNotFoundError(str(exc)) from exc

        result = ResourceReadResult(value=value)
        return result.model_dump()

    async def _handle_resource_subscribe(self, params: dict[str, Any] | None) -> dict[str, Any]:
        """Handle a resources/subscribe request.

        Args:
            params: ResourceSubscribeParams dict.

        Returns:
            Empty acknowledgment dict.

        Raises:
            TesseronError: If resource not found or not subscribable.

        """
        sub_params = ResourceSubscribeParams.model_validate(params or {})
        try:
            await self._resource_manager.handle_subscribe(
                name=sub_params.name,
                subscription_id=sub_params.subscription_id,
            )
        except (KeyError, ValueError) as exc:
            raise ActionNotFoundError(str(exc)) from exc
        return {}

    async def _handle_resource_unsubscribe(self, params: dict[str, Any] | None) -> dict[str, Any]:
        """Handle a resources/unsubscribe request.

        Args:
            params: ResourceUnsubscribeParams dict.

        Returns:
            Empty acknowledgment dict.

        """
        unsub_params = ResourceUnsubscribeParams.model_validate(params or {})
        await self._resource_manager.handle_unsubscribe(unsub_params.subscription_id)
        return {}

    async def _handle_claimed(self, params: dict[str, Any] | None) -> None:
        """Handle the tesseron/claimed notification.

        Per REQ-034, REQ-035, REQ-036, REQ-037.

        Args:
            params: ClaimedParams dict.

        """
        self._handshake.process_claimed(params or {})

    # ------------------------------------------------------------------
    # Outbound notifications
    # ------------------------------------------------------------------

    async def _send_action_list_changed(self) -> None:
        """Send an actions/list_changed notification.

        Per REQ-049, REQ-050.

        """
        if self._dispatcher is None:
            return
        entries = self._action_registry.get_manifest_entries()
        params = {"actions": [e.model_dump(by_alias=True) for e in entries]}
        try:
            await self._dispatcher.notify("actions/list_changed", params)
        except Exception:
            logger.exception("Failed to send actions/list_changed")

    async def _send_resource_list_changed(self) -> None:
        """Send a resources/list_changed notification.

        Per REQ-069.

        """
        if self._dispatcher is None:
            return
        entries = self._resource_manager.get_manifest_entries()
        params = {"resources": [e.model_dump(by_alias=True) for e in entries]}
        try:
            await self._dispatcher.notify("resources/list_changed", params)
        except Exception:
            logger.exception("Failed to send resources/list_changed")

    async def _send_resource_updated(self, subscription_id: str, value: Any) -> None:
        """Send a resources/updated notification.

        Args:
            subscription_id: The subscription ID.
            value: The new resource value.

        """
        if self._dispatcher is None:
            return
        updated = ResourceUpdatedParams(subscription_id=subscription_id, value=value)
        try:
            await self._dispatcher.notify("resources/updated", updated.model_dump(by_alias=True))
        except Exception:
            logger.exception("Failed to send resources/updated for sub %s", subscription_id)


async def _noop_notify(method: str, params: dict[str, Any] | None = None) -> None:
    """No-op notify callback for when dispatcher is not available.

    Args:
        method: Notification method (unused).
        params: Notification params (unused).

    """
