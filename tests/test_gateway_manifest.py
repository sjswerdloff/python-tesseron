"""Gateway manifest watcher tests.

Test IDs: GW-88 through GW-92
Source: Gateway Requirements REQ-146, REQ-147
Design Contract: DC-025 GatewayManifestWatcher

Tests verify:
- Directory watching behaviour (REQ-146): the watcher monitors
  ~/.tesseron/instances/ for manifest files and reacts when they
  appear or disappear.
- Stale detection by pid (REQ-147): a manifest whose recorded pid
  belongs to a dead process is flagged stale; one whose pid belongs
  to a live process is not.
- Missing directory handling: graceful behaviour when the discovery
  directory does not exist.

All tests are marked xfail — the GatewayManifestWatcher implementation
does not yet exist.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from python_tesseron.gateway.manifest_watcher import (
    GatewayManifestWatcher,
    is_manifest_stale,
    is_pid_running,
)
from python_tesseron.types import InstanceManifest, WsTransport

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_manifest(directory: Path, instance_id: str, pid: int | None, url: str = "ws://127.0.0.1:9999/") -> Path:
    """Write a manifest JSON file to the discovery directory."""
    manifest_data: dict[str, Any] = {
        "version": 2,
        "instanceId": instance_id,
        "appName": "Test App",
        "addedAt": int(time.time() * 1000),
        "transport": {"kind": "ws", "url": url},
    }
    if pid is not None:
        manifest_data["pid"] = pid

    path = directory / f"{instance_id}.json"
    with path.open("w") as f:
        json.dump(manifest_data, f)
    return path


# ---------------------------------------------------------------------------
# DC-025: GatewayManifestWatcher — Directory Watching (REQ-146)
# ---------------------------------------------------------------------------


async def test_gw88_watches_directory(tmp_path: Path) -> None:
    """GW-88: Watches ~/.tesseron/instances/ for manifest files.

    Verifies: DC-025 — manifest directory watching.
    REQ-146

    Write a manifest file to the watched directory and verify the watcher
    detects its presence.
    """
    watcher = GatewayManifestWatcher(directory=tmp_path)

    _write_manifest(tmp_path, "inst-001", pid=None)

    manifests = watcher.scan()
    instance_ids = [m.instance_id for m in manifests]

    assert "inst-001" in instance_ids


async def test_gw89_manifest_triggers_dial(tmp_path: Path) -> None:
    """GW-89: Discovered manifest triggers app dial.

    Verifies: DC-025 — valid manifest with loopback WS URL causes the
    gateway to initiate a connection to the advertised endpoint.
    REQ-146

    Write a valid manifest containing a ws://127.0.0.1:PORT WebSocket
    URL to the watched directory and verify the gateway attempts to
    connect to that URL.
    """
    dialled_urls: list[str] = []

    async def mock_dial(url: str) -> None:
        dialled_urls.append(url)

    watcher = GatewayManifestWatcher(directory=tmp_path, dial_callback=mock_dial)

    # Write a manifest with a loopback WS URL and no pid (non-stale)
    _write_manifest(tmp_path, "inst-dial", pid=None, url="ws://127.0.0.1:9999/")

    await watcher.poll()

    assert len(dialled_urls) >= 1
    assert dialled_urls[0] == "ws://127.0.0.1:9999/"


# ---------------------------------------------------------------------------
# DC-025: GatewayManifestWatcher — Stale Detection (REQ-147)
# ---------------------------------------------------------------------------


async def test_gw90_running_pid_not_stale() -> None:
    """GW-90: Running pid not flagged stale.

    Verifies: DC-025 — a manifest whose pid field refers to a currently
    running process is NOT treated as stale.
    REQ-147

    Equivalence class: {running pid}

    Write a manifest with the pid of a known-running process (e.g. the
    current test process) and verify the watcher does not flag it stale.
    """
    running_pid = os.getpid()  # Current test process is definitely running
    manifest = InstanceManifest(
        version=2,
        instanceId="inst-running",
        appName="Test",
        addedAt=int(time.time() * 1000),
        pid=running_pid,
        transport=WsTransport(kind="ws", url="ws://127.0.0.1:9999/"),
    )

    assert is_manifest_stale(manifest) is False


async def test_gw91_dead_pid_stale() -> None:
    """GW-91: Dead pid flagged stale.

    Verifies: DC-025 — a manifest whose pid field refers to a process
    that is no longer running IS flagged stale.
    REQ-147

    Equivalence class: {dead pid}

    Write a manifest with a pid that is known not to exist (e.g. a very
    large pid number that was never assigned) and verify the watcher
    flags the manifest as stale.
    """
    # Use a very large PID that is almost certainly not running
    dead_pid = 2_147_483_647  # Max int32, virtually never a real process
    assert is_pid_running(dead_pid) is False

    manifest = InstanceManifest(
        version=2,
        instanceId="inst-dead",
        appName="Test",
        addedAt=int(time.time() * 1000),
        pid=dead_pid,
        transport=WsTransport(kind="ws", url="ws://127.0.0.1:9999/"),
    )

    assert is_manifest_stale(manifest) is True


# ---------------------------------------------------------------------------
# DC-025: GatewayManifestWatcher — Error Handling
# ---------------------------------------------------------------------------


async def test_gw92_missing_directory(tmp_path: Path) -> None:
    """GW-92: Missing discovery directory handled gracefully.

    Verifies: DC-025 — when ~/.tesseron/instances/ does not exist the
    watcher either raises FileNotFoundError with a clear message or
    creates the directory automatically rather than crashing silently.
    REQ-146

    Remove (or point the watcher at) a non-existent directory and verify
    the watcher responds with FileNotFoundError or creates the directory
    and continues without error.
    """
    non_existent_dir = tmp_path / "does" / "not" / "exist"
    watcher = GatewayManifestWatcher(directory=non_existent_dir)

    # The watcher should either create the directory or raise FileNotFoundError
    try:
        manifests = watcher.scan()
        # If we get here, directory was created — verify it now exists
        assert non_existent_dir.exists()
        assert manifests == []
    except FileNotFoundError:
        # Also acceptable per REQ-146
        pass
