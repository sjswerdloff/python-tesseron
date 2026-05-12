"""Gateway resume manager tests.

Test IDs: GW-74 through GW-87
Source: Gateway Requirements REQ-132, REQ-133, REQ-134, REQ-135
Design Contract: DC-024 GatewayResumeManager

Tests verify:
- Disconnected claimed sessions are retained as zombies (REQ-132).
- Default TTL of 90 seconds with BVA: at 85s (within), at 90s (boundary),
  at 91s (past boundary) (REQ-132).
- Configurable TTL is respected (REQ-132).
- Constant-time token comparison is used to prevent timing attacks (REQ-133).
- Successful resume returns a rotated resumeToken that differs from the original (REQ-134).
- Old token is rejected after rotation (REQ-134).
- All resume failure conditions from EP {unknown session, bad token, TTL elapsed,
  cross-app, unclaimed zombie} return -32011 ResumeFailed (REQ-135).

All tests are marked xfail until GatewayResumeManager is implemented.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import AsyncMock

import pytest

from python_tesseron.errors import ResumeFailedError
from python_tesseron.gateway.resume import DEFAULT_ZOMBIE_TTL_S, GatewayResumeManager
from python_tesseron.gateway.session import GatewaySessionManager
from python_tesseron.types import AgentIdentity, TesseronCapabilities


def _make_dispatcher() -> Any:
    """Create a mock dispatcher."""
    dispatcher = AsyncMock()
    dispatcher.reject_all_pending = AsyncMock()
    dispatcher.notify = AsyncMock()
    return dispatcher


async def _make_claimed_session(mgr: GatewaySessionManager, app_id: str = "myapp") -> Any:
    """Create and fully claim a session."""
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    params: dict[str, Any] = {
        "protocolVersion": "1.2.0",
        "app": {"id": app_id, "name": app_id, "origin": f"python:{app_id}"},
        "actions": [],
        "resources": [],
        "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    }
    welcome = await mgr.handle_hello(session, params)
    agent = AgentIdentity(id="agent", name="Agent")
    agent_caps = TesseronCapabilities()
    await mgr.handle_claim(session.session_id, welcome["claimCode"], agent_identity=agent, agent_capabilities=agent_caps)
    return session


# ---------------------------------------------------------------------------
# GW-74: Disconnected session retained as zombie (REQ-132)
# ---------------------------------------------------------------------------


async def test_gw74_zombie_retention() -> None:
    """GW-74: Disconnected claimed session retained as zombie.

    Verifies: DC-024 — when a claimed session's transport closes, the session
    is retained in zombie state rather than immediately destroyed, enabling
    subsequent resume.
    REQ-132
    """
    mgr = GatewaySessionManager()
    resume_mgr = GatewayResumeManager()

    session = await _make_claimed_session(mgr)
    session_id = session.session_id
    resume_token = session.resume_token
    assert resume_token is not None

    # Retain as zombie before close
    resume_mgr.retain_as_zombie(session)

    zombie = resume_mgr.get_zombie(session_id)
    assert zombie is not None
    assert zombie.session_id == session_id
    assert zombie.resume_token == resume_token
    assert zombie.was_claimed is True


# ---------------------------------------------------------------------------
# GW-75: Default TTL 90 seconds — resume at 85s succeeds (REQ-132 — BVA within)
# ---------------------------------------------------------------------------


async def test_gw75_default_ttl_within() -> None:
    """GW-75: Resume within default TTL (85s < 90s) succeeds.

    Verifies: DC-024 — resuming at 85 seconds after disconnect is within the
    default 90-second TTL and therefore succeeds (BVA: value below boundary).
    REQ-132
    """
    mgr = GatewaySessionManager()
    resume_mgr = GatewayResumeManager()

    session = await _make_claimed_session(mgr)
    resume_token = session.resume_token
    assert resume_token is not None

    resume_mgr.retain_as_zombie(session)

    # Simulate 85 seconds having passed (within TTL)
    zombie = resume_mgr.get_zombie(session.session_id)
    assert zombie is not None

    now = zombie.disconnected_at + 85  # 85s after disconnect
    result = resume_mgr.validate_and_resume(session.session_id, resume_token, now=now)
    assert result is not None


# ---------------------------------------------------------------------------
# GW-76: Resume at TTL boundary (90s) succeeds (REQ-132 — BVA on boundary)
# ---------------------------------------------------------------------------


async def test_gw76_ttl_boundary() -> None:
    """GW-76: Resume at exactly TTL boundary (90s) succeeds.

    Verifies: DC-024 — resuming at exactly 90 seconds after disconnect is at
    the TTL boundary and succeeds (BVA: on-boundary value is valid).
    REQ-132
    """
    resume_mgr = GatewayResumeManager()
    mgr = GatewaySessionManager()

    session = await _make_claimed_session(mgr)
    resume_token = session.resume_token
    assert resume_token is not None

    resume_mgr.retain_as_zombie(session)
    zombie = resume_mgr.get_zombie(session.session_id)
    assert zombie is not None

    now = zombie.disconnected_at + DEFAULT_ZOMBIE_TTL_S  # Exactly at boundary
    result = resume_mgr.validate_and_resume(session.session_id, resume_token, now=now)
    assert result is not None


# ---------------------------------------------------------------------------
# GW-77: Resume after TTL (91s) fails with -32011 (REQ-132, REQ-135 — BVA past boundary)
# ---------------------------------------------------------------------------


async def test_gw77_ttl_exceeded() -> None:
    """GW-77: Resume after TTL (91s > 90s) returns -32011 ResumeFailed.

    Verifies: DC-024 — resuming at 91 seconds after disconnect exceeds the
    default 90-second TTL and is rejected with -32011 (BVA: boundary+1 fails).
    REQ-132, REQ-135
    """
    resume_mgr = GatewayResumeManager()
    mgr = GatewaySessionManager()

    session = await _make_claimed_session(mgr)
    resume_token = session.resume_token
    assert resume_token is not None

    resume_mgr.retain_as_zombie(session)
    zombie = resume_mgr.get_zombie(session.session_id)
    assert zombie is not None

    now = zombie.disconnected_at + DEFAULT_ZOMBIE_TTL_S + 1  # 1s past boundary
    with pytest.raises(ResumeFailedError) as exc_info:
        resume_mgr.validate_and_resume(session.session_id, resume_token, now=now)

    assert exc_info.value.code == -32011


# ---------------------------------------------------------------------------
# GW-78: Configurable TTL respected (REQ-132)
# ---------------------------------------------------------------------------


async def test_gw78_configurable_ttl() -> None:
    """GW-78: Configurable TTL is respected by the resume manager.

    Verifies: DC-024 — when TTL is configured to 30 seconds, resuming at 35
    seconds after disconnect is rejected with -32011 ResumeFailed.
    REQ-132
    """
    resume_mgr = GatewayResumeManager(zombie_ttl_s=30)
    mgr = GatewaySessionManager()

    session = await _make_claimed_session(mgr)
    resume_token = session.resume_token
    assert resume_token is not None

    resume_mgr.retain_as_zombie(session)
    zombie = resume_mgr.get_zombie(session.session_id)
    assert zombie is not None

    now = zombie.disconnected_at + 35  # 35s after disconnect, TTL=30s
    with pytest.raises(ResumeFailedError) as exc_info:
        resume_mgr.validate_and_resume(session.session_id, resume_token, now=now)

    assert exc_info.value.code == -32011


# ---------------------------------------------------------------------------
# GW-79: Constant-time token comparison (REQ-133)
# ---------------------------------------------------------------------------


async def test_gw79_constant_time_comparison() -> None:
    """GW-79: Resume token comparison uses constant-time algorithm.

    Verifies: DC-024 — the GatewayResumeManager uses hmac.compare_digest or
    equivalent constant-time comparison to prevent timing-based token oracle
    attacks.
    REQ-133
    """
    # Verify that the source code of validate_and_resume uses hmac.compare_digest
    source = inspect.getsource(GatewayResumeManager.validate_and_resume)
    assert "hmac.compare_digest" in source, "validate_and_resume must use hmac.compare_digest for constant-time comparison"


# ---------------------------------------------------------------------------
# GW-80: Successful resume returns rotated token (REQ-134)
# ---------------------------------------------------------------------------


async def test_gw80_token_rotation() -> None:
    """GW-80: Successful resume response includes a rotated resumeToken.

    Verifies: DC-024 — the welcome response on a successful session resume
    contains a new resumeToken, implementing token rotation.
    REQ-134
    """
    resume_mgr = GatewayResumeManager()
    mgr = GatewaySessionManager()

    session = await _make_claimed_session(mgr)
    original_token = session.resume_token
    assert original_token is not None

    resume_mgr.retain_as_zombie(session)

    resume_mgr.validate_and_resume(session.session_id, original_token)
    new_token = resume_mgr.rotate_token(session.session_id)

    assert new_token is not None


# ---------------------------------------------------------------------------
# GW-81: Rotated token differs from original (REQ-134)
# ---------------------------------------------------------------------------


async def test_gw81_rotated_token_differs() -> None:
    """GW-81: Rotated resumeToken differs from the original token.

    Verifies: DC-024 — the rotated resumeToken returned after a successful
    resume is a distinct value from the token that was used to resume.
    REQ-134
    """
    resume_mgr = GatewayResumeManager()
    mgr = GatewaySessionManager()

    session = await _make_claimed_session(mgr)
    original_token = session.resume_token
    assert original_token is not None

    resume_mgr.retain_as_zombie(session)
    resume_mgr.validate_and_resume(session.session_id, original_token)
    new_token = resume_mgr.rotate_token(session.session_id)

    assert new_token != original_token


# ---------------------------------------------------------------------------
# GW-82: Old token rejected after rotation (REQ-134)
# ---------------------------------------------------------------------------


async def test_gw82_old_token_rejected() -> None:
    """GW-82: Original resumeToken is rejected after token rotation.

    Verifies: DC-024 — once a resume has occurred and the token has been
    rotated, re-presenting the original (pre-rotation) token is rejected
    with -32011 ResumeFailed.
    REQ-134
    """
    resume_mgr = GatewayResumeManager()
    mgr = GatewaySessionManager()

    session = await _make_claimed_session(mgr)
    original_token = session.resume_token
    assert original_token is not None

    resume_mgr.retain_as_zombie(session)
    resume_mgr.validate_and_resume(session.session_id, original_token)
    resume_mgr.rotate_token(session.session_id)

    # Old token must now be rejected
    with pytest.raises(ResumeFailedError) as exc_info:
        resume_mgr.validate_and_resume(session.session_id, original_token)

    assert exc_info.value.code == -32011


# ---------------------------------------------------------------------------
# GW-83: Unknown sessionId returns -32011 (REQ-135 — EP: unknown session)
# ---------------------------------------------------------------------------


async def test_gw83_unknown_session_fails() -> None:
    """GW-83: Resume with fabricated/unknown sessionId returns -32011.

    Verifies: DC-024 — presenting a sessionId that does not correspond to any
    known zombie session is rejected with -32011 ResumeFailed.
    REQ-135
    """
    resume_mgr = GatewayResumeManager()

    with pytest.raises(ResumeFailedError) as exc_info:
        resume_mgr.validate_and_resume("fabricated-session-id", "any-token")

    assert exc_info.value.code == -32011


# ---------------------------------------------------------------------------
# GW-84: Bad resumeToken returns -32011 (REQ-135 — EP: bad token)
# ---------------------------------------------------------------------------


async def test_gw84_bad_token_fails() -> None:
    """GW-84: Resume with incorrect resumeToken returns -32011.

    Verifies: DC-024 — presenting a valid sessionId with a wrong resumeToken
    is rejected with -32011 ResumeFailed.
    REQ-135
    """
    resume_mgr = GatewayResumeManager()
    mgr = GatewaySessionManager()

    session = await _make_claimed_session(mgr)
    resume_mgr.retain_as_zombie(session)

    with pytest.raises(ResumeFailedError) as exc_info:
        resume_mgr.validate_and_resume(session.session_id, "wrong-token")

    assert exc_info.value.code == -32011


# ---------------------------------------------------------------------------
# GW-85: TTL elapsed returns -32011 (REQ-135 — EP: TTL elapsed; see GW-77)
# ---------------------------------------------------------------------------


async def test_gw85_ttl_elapsed_fails() -> None:
    """GW-85: Resume after TTL expiry returns -32011 (cross-reference GW-77).

    Verifies: DC-024 — resuming a zombie session after its TTL has elapsed
    is rejected with -32011 ResumeFailed. EP failure condition: TTL elapsed.
    REQ-135
    """
    resume_mgr = GatewayResumeManager(zombie_ttl_s=10)
    mgr = GatewaySessionManager()

    session = await _make_claimed_session(mgr)
    resume_token = session.resume_token
    assert resume_token is not None

    resume_mgr.retain_as_zombie(session)
    zombie = resume_mgr.get_zombie(session.session_id)
    assert zombie is not None

    now = zombie.disconnected_at + 11  # Past TTL
    with pytest.raises(ResumeFailedError) as exc_info:
        resume_mgr.validate_and_resume(session.session_id, resume_token, now=now)

    assert exc_info.value.code == -32011


# ---------------------------------------------------------------------------
# GW-86: Cross-app resume returns -32011 (REQ-135 — EP: cross-app)
# ---------------------------------------------------------------------------


async def test_gw86_cross_app_fails() -> None:
    """GW-86: Cross-app resume attempt returns -32011.

    Verifies: DC-024 — attempting to resume app A's zombie session from app B's
    connection context is rejected with -32011 ResumeFailed.
    REQ-135
    """
    resume_mgr = GatewayResumeManager()
    mgr = GatewaySessionManager()

    session = await _make_claimed_session(mgr, app_id="app_a")
    resume_token = session.resume_token
    assert resume_token is not None

    resume_mgr.retain_as_zombie(session)

    # Try to resume from app_b's context
    with pytest.raises(ResumeFailedError) as exc_info:
        resume_mgr.validate_and_resume(session.session_id, resume_token, requesting_app_id="app_b")

    assert exc_info.value.code == -32011


# ---------------------------------------------------------------------------
# GW-87: Unclaimed zombie resume returns -32011 (REQ-135 — EP: unclaimed zombie)
# ---------------------------------------------------------------------------


async def test_gw87_unclaimed_zombie_fails() -> None:
    """GW-87: Resuming an unclaimed zombie session returns -32011.

    Verifies: DC-024 — a session that disconnected before being claimed cannot
    be resumed; the attempt is rejected with -32011 ResumeFailed.
    REQ-135
    """
    resume_mgr = GatewayResumeManager()
    mgr = GatewaySessionManager()

    # Create session but do NOT claim it
    dispatcher = _make_dispatcher()
    session = mgr.create_session(dispatcher)
    params: dict[str, Any] = {
        "protocolVersion": "1.2.0",
        "app": {"id": "myapp", "name": "App", "origin": "test"},
        "actions": [],
        "resources": [],
        "capabilities": {"streaming": True, "subscriptions": True, "sampling": True, "elicitation": True},
    }
    await mgr.handle_hello(session, params)
    # Do NOT claim — session stays AWAITING_CLAIM

    # Manually inject resume token to simulate having one
    session.resume_token = "some-token"

    resume_mgr.retain_as_zombie(session)

    with pytest.raises(ResumeFailedError) as exc_info:
        resume_mgr.validate_and_resume(session.session_id, "some-token")

    assert exc_info.value.code == -32011
