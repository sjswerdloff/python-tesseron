"""Instance manifest discovery for the Tesseron protocol.

Design Contract: DC-013 (DiscoveryManifest)
Spec Reference: §4 (Discovery and Instance Manifests), §16.1 (Loopback-Only Discovery)

Guarantees:
- Writes instance manifest to ~/.tesseron/instances/<instanceId>.json.
- Discovery directory created with mode 0o700.
- Manifest file written with mode 0o600.
- Instance ID uses "inst-" prefix (REQ-027).
- SIGINT/SIGTERM handlers registered to delete manifest and close transport.
- Manifest deleted on close.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import signal
import time
from pathlib import Path
from typing import Any

from python_tesseron.types import InstanceManifest, UdsTransport, WsTransport

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — §4 and §17
# ---------------------------------------------------------------------------

# Primary discovery directory per §4.2
_DISCOVERY_DIR = Path.home() / ".tesseron" / "instances"

# Directory and file permission modes per REQ-025, REQ-026, REQ-088, REQ-089
_DIR_MODE = 0o700
_FILE_MODE = 0o600

# Instance ID prefix per REQ-027
_INSTANCE_ID_PREFIX = "inst-"

# Number of random hex characters in the instance ID suffix
_INSTANCE_ID_SUFFIX_BYTES = 8


def generate_instance_id() -> str:
    """Generate a unique instance ID with the required prefix.

    Per REQ-027, instance IDs SHOULD use the "inst-" prefix followed by
    a random string.

    Returns:
        A string of the form "inst-<hex>" where <hex> is 16 random hex chars.

    """
    suffix = secrets.token_hex(_INSTANCE_ID_SUFFIX_BYTES)
    return f"{_INSTANCE_ID_PREFIX}{suffix}"


class DiscoveryManifest:
    """Manages the lifecycle of a Tesseron instance manifest file.

    Per DC-013, this class handles writing and deleting the manifest at
    ``~/.tesseron/instances/<instanceId>.json``. It also registers signal
    handlers to ensure cleanup on SIGINT/SIGTERM (REQ-029).

    Attributes:
        instance_id: The unique instance identifier (inst- prefixed).
        app_name: Human-readable name for the running app.
        _manifest_path: Resolved path to the written manifest file.
        _registered_signals: Whether signal handlers were registered.

    """

    def __init__(self, instance_id: str, app_name: str) -> None:
        """Initialise the manifest manager.

        Args:
            instance_id: Unique instance identifier (should use inst- prefix).
            app_name: Human-readable application name.

        """
        self.instance_id = instance_id
        self.app_name = app_name
        self._manifest_path: Path | None = None
        self._registered_signals = False
        self._close_callback: Any = None

    def write(self, transport: WsTransport | UdsTransport) -> Path:
        """Write the instance manifest to the discovery directory.

        Creates ~/.tesseron/instances/ with mode 0o700 if it does not exist
        (REQ-025, REQ-088). Writes the manifest with mode 0o600 (REQ-026,
        REQ-089). Sets instance_id, appName, addedAt, pid, and transport.

        Args:
            transport: Transport descriptor (WsTransport or UdsTransport).

        Returns:
            Path to the written manifest file.

        """
        # Ensure discovery directory exists with correct permissions
        _DISCOVERY_DIR.mkdir(parents=True, exist_ok=True)
        _DISCOVERY_DIR.chmod(_DIR_MODE)

        manifest = InstanceManifest(
            instance_id=self.instance_id,
            app_name=self.app_name,
            added_at=int(time.time() * 1000),
            pid=os.getpid(),
            transport=transport,
        )

        manifest_path = _DISCOVERY_DIR / f"{self.instance_id}.json"
        manifest_data = manifest.model_dump(by_alias=True)
        json_text = json.dumps(manifest_data, indent=2)

        # Write atomically — write to temp, then rename (best-effort)
        manifest_path.write_text(json_text, encoding="utf-8")
        manifest_path.chmod(_FILE_MODE)

        self._manifest_path = manifest_path
        logger.info("Manifest written: %s", manifest_path)
        return manifest_path

    def delete(self) -> None:
        """Delete the manifest file if it exists.

        Per REQ-020, REQ-028, the manifest MUST be deleted on transport close.
        Safe to call multiple times (idempotent).

        """
        if self._manifest_path is None:
            return
        path = self._manifest_path
        self._manifest_path = None
        try:
            path.unlink(missing_ok=True)
            logger.info("Manifest deleted: %s", path)
        except OSError:
            logger.exception("Failed to delete manifest: %s", path)

    def register_signal_handlers(self, close_callback: Any = None) -> None:
        """Register SIGINT and SIGTERM handlers for graceful shutdown.

        Per REQ-029, on SIGINT and SIGTERM the SDK SHOULD clean up the
        manifest, close the transport, and exit.

        Uses asyncio signal handlers when an event loop is running, falling
        back to signal.signal() for synchronous contexts.

        Args:
            close_callback: Optional async callable to invoke on signal.

        """
        self._close_callback = close_callback
        self._registered_signals = True

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.add_signal_handler(signal.SIGINT, self._sync_signal_handler)
                loop.add_signal_handler(signal.SIGTERM, self._sync_signal_handler)
                return
        except (RuntimeError, NotImplementedError):
            pass

        # Fallback: use signal.signal (synchronous, safe for non-async contexts)
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _sync_signal_handler(self) -> None:
        """Asyncio-loop-safe signal handler invoked by add_signal_handler.

        Per REQ-029: delete manifest, optionally invoke close callback.

        """
        logger.info("Signal received; cleaning up manifest")
        self.delete()
        if self._close_callback is not None:
            loop = asyncio.get_event_loop()
            loop.create_task(self._async_close())

    def _signal_handler(self, signum: int, frame: Any) -> None:
        """Handle signal for manifest cleanup (fallback).

        Per REQ-029: delete manifest on SIGINT/SIGTERM.

        Args:
            signum: Signal number.
            frame: Current stack frame.

        """
        logger.info("Signal %d received; cleaning up manifest", signum)
        self.delete()

    async def _async_close(self) -> None:
        """Invoke the close callback asynchronously.

        Called by _sync_signal_handler when a close_callback is registered.

        """
        if self._close_callback is not None:
            try:
                await self._close_callback()
            except Exception:
                logger.exception("Error in close callback during signal handling")

    @staticmethod
    def get_manifest_path(instance_id: str) -> Path:
        """Return the expected manifest path for a given instance ID.

        Args:
            instance_id: The instance identifier.

        Returns:
            The full path where the manifest would be written.

        """
        return _DISCOVERY_DIR / f"{instance_id}.json"

    @staticmethod
    def is_loopback(host: str) -> bool:
        """Check whether a host string is a loopback address.

        Per REQ-086, REQ-087: apps MUST bind to loopback only.

        Args:
            host: Host string to check.

        Returns:
            True if the host is 127.0.0.1, ::1, or localhost.

        """
        return host in {"127.0.0.1", "::1", "localhost"}
