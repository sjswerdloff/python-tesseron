"""Resource declaration, subscription lifecycle for the Tesseron protocol.

Design Contract: DC-007 (ResourceManager)
Spec Reference: §11 (Resources)

Guarantees:
- Resource declaration and read handling.
- Subscription lifecycle with cleanup functions (REQ-068, REQ-072, REQ-073).
- Clean up all subscriptions on transport close (REQ-070, REQ-071).
- Dynamic registration triggers resources/list_changed (REQ-069).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from python_tesseron.types import ResourceManifestEntry

logger = logging.getLogger(__name__)


@dataclass
class ResourceDefinition:
    """Internal representation of a declared resource.

    Attributes:
        name: Resource name.
        reader: Synchronous callable returning the current resource value.
        subscriber: Optional callable receiving an emit function, returning cleanup.
        description: Human-readable description.
        subscribable: Whether the resource supports subscriptions.
        output_schema: Optional JSON Schema for the value.

    """

    name: str
    reader: Callable[[], Any]
    subscriber: Callable[..., Any] | None = None
    description: str = ""
    subscribable: bool = False
    output_schema: dict[str, Any] | None = None

    def to_manifest_entry(self) -> ResourceManifestEntry:
        """Convert to a ResourceManifestEntry for wire serialisation.

        Returns:
            ResourceManifestEntry suitable for hello/list_changed params.

        """
        return ResourceManifestEntry(
            name=self.name,
            description=self.description,
            subscribable=self.subscribable,
            outputSchema=self.output_schema,
        )


@dataclass
class ActiveSubscription:
    """Tracks a live resource subscription.

    Attributes:
        subscription_id: Gateway-assigned subscription identifier.
        resource_name: The subscribed resource's name.
        cleanup_fn: Callable that tears down the subscription.

    """

    subscription_id: str
    resource_name: str
    cleanup_fn: Callable[[], Any]


class ResourceManager:
    """Manages resource declarations and active subscriptions.

    Implements DC-007. Handles resources/read, resources/subscribe,
    resources/unsubscribe, and cleans up on transport close.

    Attributes:
        _resources: Map of resource name to ResourceDefinition.
        _subscriptions: Map of subscriptionId to ActiveSubscription.
        _notify_list_changed: Async callable for resources/list_changed.
        _notify_updated: Async callable to push resources/updated.
        _ready: Whether the session is connected (hello sent).

    """

    def __init__(
        self,
        notify_list_changed: Callable[[], Any] | None = None,
        notify_updated: Callable[[str, Any], Any] | None = None,
    ) -> None:
        """Initialise with empty registries.

        Args:
            notify_list_changed: Async callable for resources/list_changed.
            notify_updated: Async callable accepting (subscriptionId, value).

        """
        self._resources: dict[str, ResourceDefinition] = {}
        self._subscriptions: dict[str, ActiveSubscription] = {}
        self._notify_list_changed = notify_list_changed
        self._notify_updated = notify_updated
        self._ready = False

    def set_ready(self) -> None:
        """Mark the registry as ready (hello sent).

        After calling this, new registrations/removals trigger list_changed.

        """
        self._ready = True

    def register(self, definition: ResourceDefinition) -> None:
        """Register a resource definition.

        Per REQ-069: if already ready (post-hello), triggers resources/list_changed.

        Args:
            definition: The ResourceDefinition to register.

        """
        self._resources[definition.name] = definition
        logger.debug("Registered resource: %s", definition.name)
        if self._ready and self._notify_list_changed is not None:
            import asyncio

            asyncio.ensure_future(self._emit_list_changed())

    def get_manifest_entries(self) -> list[ResourceManifestEntry]:
        """Return all resources as manifest entries.

        Returns:
            List of ResourceManifestEntry objects.

        """
        return [defn.to_manifest_entry() for defn in self._resources.values()]

    async def handle_read(self, name: str) -> Any:
        """Handle a resources/read request.

        Args:
            name: The resource name to read.

        Returns:
            The current resource value.

        Raises:
            KeyError: If no resource with the given name is registered.

        """
        defn = self._resources.get(name)
        if defn is None:
            raise KeyError(f"Resource not found: {name!r}")
        return defn.reader()

    async def handle_subscribe(
        self,
        name: str,
        subscription_id: str,
    ) -> None:
        """Handle a resources/subscribe request.

        Calls the subscriber with an emit function. Stores the cleanup function
        returned by the subscriber.

        Per REQ-068: cleanup called on unsubscribe.
        Per REQ-070: cleanup called on transport close.

        Args:
            name: Resource name to subscribe.
            subscription_id: Gateway-assigned subscription ID.

        Raises:
            KeyError: If no resource with the given name is registered.
            ValueError: If the resource is not subscribable.

        """
        defn = self._resources.get(name)
        if defn is None:
            raise KeyError(f"Resource not found: {name!r}")
        if not defn.subscribable or defn.subscriber is None:
            raise ValueError(f"Resource {name!r} is not subscribable")

        async def emit(value: Any) -> None:
            """Send a resources/updated notification for this subscription.

            Args:
                value: The new resource value.

            """
            if self._notify_updated is not None:
                try:
                    await self._notify_updated(subscription_id, value)
                except Exception:
                    logger.exception("Failed to emit resources/updated for sub %s", subscription_id)

        cleanup_fn = defn.subscriber(emit)
        if cleanup_fn is None:
            cleanup_fn = lambda: None  # noqa: E731

        self._subscriptions[subscription_id] = ActiveSubscription(
            subscription_id=subscription_id,
            resource_name=name,
            cleanup_fn=cleanup_fn,
        )
        logger.debug("Subscribed to %s with id %s", name, subscription_id)

    async def handle_unsubscribe(self, subscription_id: str) -> None:
        """Handle a resources/unsubscribe request.

        Per REQ-072, REQ-073: call cleanup function and remove from map.

        Args:
            subscription_id: The subscription ID to cancel.

        """
        subscription = self._subscriptions.pop(subscription_id, None)
        if subscription is None:
            logger.debug("Unsubscribe for unknown subscription %s; ignored", subscription_id)
            return
        try:
            subscription.cleanup_fn()
            logger.debug("Cleaned up subscription %s", subscription_id)
        except Exception:
            logger.exception("Cleanup failed for subscription %s", subscription_id)

    async def close_all_subscriptions(self) -> None:
        """Call cleanup for all active subscriptions and clear the map.

        Per REQ-070 (cleanup called), REQ-071 (map cleared) on transport close.

        """
        subscriptions = dict(self._subscriptions)
        self._subscriptions.clear()
        for sub_id, subscription in subscriptions.items():
            try:
                subscription.cleanup_fn()
                logger.debug("Closed subscription %s on transport close", sub_id)
            except Exception:
                logger.exception("Cleanup failed for subscription %s on close", sub_id)

    async def _emit_list_changed(self) -> None:
        """Emit a resources/list_changed notification.

        Per REQ-069.

        """
        if self._notify_list_changed is not None:
            try:
                await self._notify_list_changed()
            except Exception:
                logger.exception("Failed to emit resources/list_changed")


def make_resource_decorator(registry: ResourceManager) -> Callable[..., Any]:
    """Create the @tesseron.resource() decorator.

    Args:
        registry: The ResourceManager to register resources into.

    Returns:
        A decorator factory callable.

    """

    def decorator(
        name: str,
        *,
        description: str = "",
        subscribable: bool = False,
        output_schema: dict[str, Any] | None = None,
    ) -> Callable[..., Any]:
        """Register a resource handler.

        Args:
            name: Resource name.
            description: Human-readable description.
            subscribable: Whether the resource supports subscriptions.
            output_schema: Optional JSON Schema for the resource value.

        Returns:
            Decorator that registers the handler function.

        """

        def wrapper(fn: Callable[..., Any]) -> Callable[..., Any]:
            defn = ResourceDefinition(
                name=name,
                reader=fn if not subscribable else _noop_reader,
                subscriber=fn if subscribable else None,
                description=description,
                subscribable=subscribable,
                output_schema=output_schema,
            )
            registry.register(defn)
            return fn

        return wrapper

    return decorator


def _noop_reader() -> None:
    """No-op reader for subscribable-only resources.

    Returns:
        None

    """
    return None
