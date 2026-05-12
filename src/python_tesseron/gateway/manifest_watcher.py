"""Gateway manifest watcher.

Design Contract: DC-025 (GatewayManifestWatcher)
Spec Reference: §16.2, §3.3

Watches the discovery directory for instance manifests.

Guarantees:
- Watch ~/.tesseron/instances/ for manifest files (REQ-146).
- Detect stale manifests by checking if pid process is still running (REQ-147).
- Trigger gateway to dial discovered desktop apps (REQ-146).
- Handle missing directory gracefully (REQ-146).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from python_tesseron.types import InstanceManifest

logger = logging.getLogger(__name__)

# Default discovery directory (REQ-146)
DEFAULT_DISCOVERY_DIR = Path.home() / ".tesseron" / "instances"


def is_pid_running(pid: int) -> bool:
    """Check whether a process with the given PID is currently running.

    REQ-147: detect stale manifests by PID liveness check.

    Args:
        pid: Process ID to check.

    Returns:
        True if the process is running, False if not.

    """
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it
        return True
    except OSError:
        return False
    else:
        return True


def is_manifest_stale(manifest: InstanceManifest) -> bool:
    """Determine if a manifest is stale.

    A manifest is stale if its pid field refers to a process that is no
    longer running. If no pid is present, assume not stale.

    REQ-147: stale detection by pid.

    Args:
        manifest: Parsed InstanceManifest.

    Returns:
        True if the manifest is stale (dead pid), False if fresh or no pid.

    """
    if manifest.pid is None:
        return False
    return not is_pid_running(manifest.pid)


def load_manifest(path: Path) -> InstanceManifest | None:
    """Parse an instance manifest file.

    Args:
        path: Path to the JSON manifest file.

    Returns:
        Parsed InstanceManifest, or None if parsing fails.

    """
    try:
        with path.open() as f:
            data = json.load(f)
        return InstanceManifest.model_validate(data)
    except Exception:
        logger.exception("Failed to parse manifest at %s", path)
        return None


class GatewayManifestWatcher:
    """Watches the discovery directory for Tesseron app manifests.

    Design Contract: DC-025 (GatewayManifestWatcher)

    Scans ~/.tesseron/instances/ for manifest files, detects stale
    manifests by PID, and triggers the gateway to dial discovered apps.

    Attributes:
        _directory: Path to the discovery directory.
        _dial_callback: Called with each valid manifest URL to dial.
        _seen_instances: Set of instance IDs already dialled.

    """

    def __init__(
        self,
        directory: Path | None = None,
        dial_callback: Any | None = None,
    ) -> None:
        """Initialise the manifest watcher.

        Args:
            directory: Discovery directory to watch.
                Defaults to ~/.tesseron/instances/.
            dial_callback: Async callable accepting a WebSocket URL string.
                Called when a valid manifest is discovered.

        """
        self._directory = directory if directory is not None else DEFAULT_DISCOVERY_DIR
        self._dial_callback = dial_callback
        self._seen_instances: set[str] = set()

    def set_dial_callback(self, cb: Any) -> None:
        """Set the callback for dialling discovered app URLs.

        Args:
            cb: Async callable accepting a WebSocket URL string.

        """
        self._dial_callback = cb

    def _ensure_directory(self) -> None:
        """Ensure the discovery directory exists.

        Per REQ-146: if directory missing, create it or raise FileNotFoundError.
        We create it to enable graceful start without manual setup.

        Raises:
            FileNotFoundError: If directory cannot be created (permissions, etc.).

        """
        try:
            self._directory.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise FileNotFoundError(f"Discovery directory {self._directory} does not exist and could not be created") from exc

    def scan(self) -> list[InstanceManifest]:
        """Scan the discovery directory for valid, non-stale manifests.

        REQ-146: detect manifest files in directory.
        REQ-147: filter stale manifests.

        Returns:
            List of valid (non-stale) InstanceManifest objects.

        Raises:
            FileNotFoundError: If directory does not exist and cannot be created.

        """
        self._ensure_directory()

        valid_manifests = []
        for path in self._directory.iterdir():
            if not path.suffix == ".json":
                continue
            manifest = load_manifest(path)
            if manifest is None:
                continue
            if is_manifest_stale(manifest):
                logger.debug("Stale manifest at %s (pid=%s)", path, manifest.pid)
                continue
            valid_manifests.append(manifest)

        return valid_manifests

    async def poll(self) -> None:
        """Poll the discovery directory once and dial new discovered apps.

        REQ-146: trigger gateway to dial discovered apps.

        Scans for valid manifests and calls the dial callback for each
        new instance not yet dialled.

        Raises:
            FileNotFoundError: If directory does not exist and cannot be created.

        """
        manifests = self.scan()

        for manifest in manifests:
            if manifest.instance_id in self._seen_instances:
                continue

            transport = manifest.transport
            if transport.kind == "ws":
                url = transport.url
                self._seen_instances.add(manifest.instance_id)
                logger.info(
                    "Discovered new app: instance=%s url=%s",
                    manifest.instance_id,
                    url,
                )
                if self._dial_callback is not None:
                    try:
                        await self._dial_callback(url)
                    except Exception:
                        logger.exception("Error dialling %s", url)
                else:
                    logger.debug("No dial callback configured, skipping %s", url)

    def is_stale(self, manifest: InstanceManifest) -> bool:
        """Check whether a manifest is stale.

        Convenience wrapper for is_manifest_stale.

        REQ-147.

        Args:
            manifest: Manifest to check.

        Returns:
            True if stale (dead pid).

        """
        return is_manifest_stale(manifest)
