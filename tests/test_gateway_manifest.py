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

import pytest

# ---------------------------------------------------------------------------
# DC-025: GatewayManifestWatcher — Directory Watching (REQ-146)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw88_watches_directory() -> None:
    """GW-88: Watches ~/.tesseron/instances/ for manifest files.

    Verifies: DC-025 — manifest directory watching.
    REQ-146

    Write a manifest file to the watched directory and verify the watcher
    detects its presence.
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw89_manifest_triggers_dial() -> None:
    """GW-89: Discovered manifest triggers app dial.

    Verifies: DC-025 — valid manifest with loopback WS URL causes the
    gateway to initiate a connection to the advertised endpoint.
    REQ-146

    Write a valid manifest containing a ws://127.0.0.1:PORT WebSocket
    URL to the watched directory and verify the gateway attempts to
    connect to that URL.
    """
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# DC-025: GatewayManifestWatcher — Stale Detection (REQ-147)
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw90_running_pid_not_stale() -> None:
    """GW-90: Running pid not flagged stale.

    Verifies: DC-025 — a manifest whose pid field refers to a currently
    running process is NOT treated as stale.
    REQ-147

    Equivalence class: {running pid}

    Write a manifest with the pid of a known-running process (e.g. the
    current test process) and verify the watcher does not flag it stale.
    """
    pytest.fail("Not implemented")


@pytest.mark.xfail(reason="gateway implementation pending")
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
    pytest.fail("Not implemented")


# ---------------------------------------------------------------------------
# DC-025: GatewayManifestWatcher — Error Handling
# ---------------------------------------------------------------------------


@pytest.mark.xfail(reason="gateway implementation pending")
async def test_gw92_missing_directory() -> None:
    """GW-92: Missing discovery directory handled gracefully.

    Verifies: DC-025 — when ~/.tesseron/instances/ does not exist the
    watcher either raises FileNotFoundError with a clear message or
    creates the directory automatically rather than crashing silently.
    REQ-146

    Remove (or point the watcher at) a non-existent directory and verify
    the watcher responds with FileNotFoundError or creates the directory
    and continues without error.
    """
    pytest.fail("Not implemented")
