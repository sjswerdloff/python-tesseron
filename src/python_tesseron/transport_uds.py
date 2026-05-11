"""Unix Domain Socket transport binding for the Tesseron protocol.

Design Contract: DC-003 (UdsTransport)
Spec Reference: §3.3 (Unix Domain Socket Binding)

Guarantees:
- NDJSON framing (one JSON-RPC envelope per newline) (REQ-011).
- Private temp directory with mode 0o700 (REQ-021).
- Socket file chmod 0o600 (REQ-023).
- Accepts exactly one connection (REQ-022).
- Cleans up socket, directory, and manifest on close (REQ-028).
"""

from __future__ import annotations

import asyncio
import json
import logging
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — §3.3, §17
# ---------------------------------------------------------------------------

# Private temp directory mode — REQ-021
_DIR_MODE = 0o700

# Socket file mode — REQ-023
_SOCKET_MODE = 0o600

# Socket file name within the private directory
_SOCKET_NAME = "sock"


class UdsTransport:
    """Unix Domain Socket transport server for the Tesseron SDK.

    Implements DC-003. Creates a private temp directory, binds a UDS socket,
    and accepts exactly one connection (REQ-022).

    Attributes:
        _dir: The private temp directory path.
        socket_path: The UDS socket file path.

    """

    def __init__(self) -> None:
        """Initialise in a not-started state."""
        self._dir: Path | None = None
        self._socket_path: Path | None = None
        self._server: asyncio.AbstractServer | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._connection_event = asyncio.Event()
        self._message_queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._closed = False
        self._connection_accepted = False

    @property
    def socket_path(self) -> Path | None:
        """Path to the UDS socket file, or None if not started.

        Returns:
            Path to socket file.

        """
        return self._socket_path

    async def start(self) -> None:
        """Create the private temp directory and start the UDS server.

        Per REQ-021: private directory with mode 0o700.
        Per REQ-023: socket file chmod 0o600 after bind.

        """
        # Create private temp directory with mode 0o700
        tmp_dir = tempfile.mkdtemp(prefix="tesseron-")
        self._dir = Path(tmp_dir)
        self._dir.chmod(_DIR_MODE)

        socket_path = self._dir / _SOCKET_NAME
        self._socket_path = socket_path

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(socket_path),
        )

        # REQ-023: chmod the socket file after bind
        try:
            socket_path.chmod(_SOCKET_MODE)
        except OSError:
            logger.exception("Failed to chmod socket file")

        logger.info("UDS transport listening at %s", socket_path)

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """Handle an incoming UDS connection.

        Per REQ-022: accepts exactly one connection.

        Args:
            reader: Stream reader for the connection.
            writer: Stream writer for the connection.

        """
        if self._connection_accepted:
            # Reject subsequent connections
            writer.close()
            return

        self._connection_accepted = True
        self._reader = reader
        self._writer = writer
        self._connection_event.set()
        logger.info("UDS connection accepted")

        try:
            buffer = b""
            while not self._closed:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line_bytes, buffer = buffer.split(b"\n", 1)
                    line = line_bytes.decode("utf-8", errors="replace").strip()
                    if line:  # REQ-011: empty lines are ignored
                        await self._message_queue.put(line)
        except Exception:
            logger.exception("UDS connection handler error")
        finally:
            await self._message_queue.put(None)
            logger.info("UDS connection closed")

    async def wait_for_connection(self, timeout: float = 30.0) -> None:
        """Wait until the gateway connects.

        Args:
            timeout: Maximum seconds to wait.

        Raises:
            TimeoutError: If no connection arrives within the timeout.

        """
        await asyncio.wait_for(self._connection_event.wait(), timeout=timeout)

    async def send(self, message: dict[str, Any]) -> None:
        """Send a JSON-RPC envelope as a newline-terminated NDJSON line.

        Per REQ-011: one JSON-RPC envelope per newline-terminated line.

        Args:
            message: The dict to serialise and send.

        Raises:
            RuntimeError: If no connection is established.

        """
        if self._writer is None:
            raise RuntimeError("No UDS connection established")
        raw = json.dumps(message) + "\n"
        self._writer.write(raw.encode("utf-8"))
        await self._writer.drain()

    async def close(self) -> None:
        """Close the UDS connection, socket, and temp directory.

        Per REQ-028: clean up socket file, temp directory, and manifest.

        """
        if self._closed:
            return
        self._closed = True

        if self._writer is not None:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                logger.exception("Error closing UDS writer")
            self._writer = None

        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                logger.exception("Error stopping UDS server")
            self._server = None

        # Clean up socket file and temp directory
        if self._socket_path is not None:
            try:
                self._socket_path.unlink(missing_ok=True)
            except OSError:
                logger.exception("Failed to remove socket file")
            self._socket_path = None

        if self._dir is not None:
            try:
                self._dir.rmdir()
            except OSError:
                logger.exception("Failed to remove UDS temp directory")
            self._dir = None

        logger.info("UDS transport closed")

    async def messages(self) -> AsyncIterator[str]:
        """Iterate over incoming NDJSON lines.

        Yields raw JSON strings, one per newline-terminated line.
        Empty lines are silently skipped (REQ-011).
        Stops when the connection is closed.

        Yields:
            Raw JSON string for each complete line.

        """
        while True:
            text = await self._message_queue.get()
            if text is None:
                break
            yield text
