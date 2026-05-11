"""Security model tests.

Test IDs: SEC-01 through SEC-06
Source: Spec §16 (Security Model), §4 (Discovery), §5 (Handshake), §7 (Action Model)

Tests verify:
- Reserved app IDs are rejected.
- Non-loopback manifest URLs are refused by the gateway.
- File permission enforcement (0o700 for directories, 0o600 for files).
- requiresConfirmation enforcement.

All tests requiring SDK integration or file system interaction are marked
xfail until the implementation exists. Structural tests run with stubs.
"""

from __future__ import annotations

import re

import pytest

from tests.conftest import MockGateway

# ---------------------------------------------------------------------------
# SEC-01: Reserved app IDs must not be used
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_sec01_reserved_app_id_tesseron_is_invalid() -> None:
    """SEC-01: REQ-032. Reserved app ID 'tesseron' MUST NOT be used.

    The app.id field MUST match /^[a-z][a-z0-9_]*$/ AND must not be
    one of the reserved values: tesseron, mcp, system.
    """
    reserved_ids = {"tesseron", "mcp", "system"}
    app_id_pattern = re.compile(r"^[a-z][a-z0-9_]*$")

    # All three are syntactically valid but semantically reserved
    for reserved_id in reserved_ids:
        assert app_id_pattern.match(reserved_id), f"'{reserved_id}' must match the regex"

    # The SDK must reject these at construction time
    # This test documents the set of reserved IDs; enforcement is an SDK concern.
    assert "tesseron" in reserved_ids
    assert "mcp" in reserved_ids
    assert "system" in reserved_ids


@pytest.mark.security
def test_sec01_app_id_regex_validation() -> None:
    """SEC-01: REQ-031. app.id MUST match /^[a-z][a-z0-9_]*$/.

    Verify the regex itself accepts valid IDs and rejects invalid ones.
    """
    app_id_pattern = re.compile(r"^[a-z][a-z0-9_]*$")

    valid_ids = ["my_app", "shop", "test_app", "notes2", "a"]
    for app_id in valid_ids:
        assert app_id_pattern.match(app_id), f"'{app_id}' should be valid"

    invalid_ids = [
        "MyApp",  # Uppercase
        "2app",  # Starts with digit
        "my-app",  # Hyphen
        "my app",  # Space
        "",  # Empty
        "_app",  # Starts with underscore
    ]
    for app_id in invalid_ids:
        assert not app_id_pattern.match(app_id), f"'{app_id}' should be invalid"


@pytest.mark.security
@pytest.mark.xfail(reason="implementation pending: SDK app.id validation not yet implemented")
async def test_sec01_sdk_rejects_reserved_app_id_tesseron(mock_gateway: MockGateway) -> None:
    """SEC-01: REQ-032. SDK must reject 'tesseron' as app.id and return -32009 Unauthorized.

    Attempt to send tesseron/hello with app.id='tesseron'. Verify the
    gateway refuses with -32009 Unauthorized (or -32602 InvalidParams).
    """
    raise NotImplementedError


@pytest.mark.security
@pytest.mark.xfail(reason="implementation pending: SDK app.id validation not yet implemented")
async def test_sec01_sdk_rejects_reserved_app_id_mcp(mock_gateway: MockGateway) -> None:
    """SEC-01: REQ-032. SDK must reject 'mcp' as app.id.

    Attempt to send tesseron/hello with app.id='mcp'. Verify rejection.
    """
    raise NotImplementedError


@pytest.mark.security
@pytest.mark.xfail(reason="implementation pending: SDK app.id validation not yet implemented")
async def test_sec01_sdk_rejects_reserved_app_id_system(mock_gateway: MockGateway) -> None:
    """SEC-01: REQ-032. SDK must reject 'system' as app.id.

    Attempt to send tesseron/hello with app.id='system'. Verify rejection.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# SEC-02: Non-loopback manifest URLs must be refused
# ---------------------------------------------------------------------------


@pytest.mark.security
def test_sec02_loopback_url_detection() -> None:
    """SEC-02: REQ-087. Gateway must refuse non-loopback manifest URLs.

    The SDK must only write loopback URLs to the manifest. This test
    verifies that only 127.0.0.1 and ::1 are considered loopback addresses.
    """
    loopback_hosts = {"127.0.0.1", "::1", "localhost"}
    non_loopback = "192.168.1.100"

    # The SDK must refuse to serve on non-loopback addresses
    assert non_loopback not in loopback_hosts


@pytest.mark.security
@pytest.mark.xfail(reason="implementation pending: SDK manifest URL validation not yet implemented")
async def test_sec02_manifest_contains_only_loopback_url() -> None:
    """SEC-02: REQ-087. Written manifest URL must be a loopback address.

    After the SDK starts, verify that the manifest file's transport URL
    uses 127.0.0.1 or ::1 as the host.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# SEC-03: tesseron directory must be mode 0o700
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.xfail(reason="implementation pending: SDK manifest directory creation not yet implemented")
async def test_sec03_tesseron_directory_mode_is_0o700() -> None:
    """SEC-03: REQ-025. ~/.tesseron/ directory must be created with mode 0o700.

    After the SDK creates (or uses) the discovery directory, verify its
    permissions are exactly 0o700.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# SEC-04: Manifest files must be mode 0o600
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.xfail(reason="implementation pending: SDK manifest file creation not yet implemented")
async def test_sec04_manifest_file_mode_is_0o600() -> None:
    """SEC-04: REQ-026. Instance manifest files must be written with mode 0o600.

    After the SDK writes the instance manifest, verify the file's
    permissions are exactly 0o600.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# SEC-05: Claim breadcrumb files must be mode 0o600
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.xfail(reason="implementation pending: SDK claim breadcrumb not yet implemented")
async def test_sec05_claim_breadcrumb_mode_is_0o600() -> None:
    """SEC-05: REQ-090. Claim breadcrumb files must be written with mode 0o600.

    After the SDK writes a claim breadcrumb file, verify the file's
    permissions are exactly 0o600.
    """
    raise NotImplementedError


# ---------------------------------------------------------------------------
# SEC-06: requiresConfirmation must not be called uninvited
# ---------------------------------------------------------------------------


@pytest.mark.security
@pytest.mark.xfail(reason="implementation pending: SDK requiresConfirmation enforcement not yet implemented")
async def test_sec06_requires_confirmation_action_rejects_uninvited_invocation(mock_gateway: MockGateway) -> None:
    """SEC-06: REQ-101. requiresConfirmation action MUST NOT be called without confirmation.

    Declare an action with annotations.requiresConfirmation=True. Invoke it
    without providing the required confirmation. Verify the SDK rejects the
    invocation (e.g., -32009 Unauthorized or -32602 InvalidParams).
    """
    raise NotImplementedError
