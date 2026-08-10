"""Tests for opaque refresh-token rotation."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from alembic.script import ScriptDirectory

from orchestwin.identity.sessions import (
    ExpiredRefreshToken,
    RefreshSession,
    RefreshSessionService,
    RefreshTokenReuseDetected,
)
from orchestwin.persistence.migrate import (
    create_alembic_config,
)

TEST_DATABASE_URL = "postgresql+psycopg://user:password@localhost:5432/orchestwin"


class InMemoryRefreshSessionRepository:
    """Deterministic repository double for session behavior tests."""

    def __init__(self) -> None:
        self.sessions: dict[UUID, RefreshSession] = {}

    async def add(
        self,
        session: RefreshSession,
    ) -> RefreshSession:
        self.sessions[session.id] = session
        return session

    async def get_by_digest_for_update(
        self,
        digest: str,
    ) -> RefreshSession | None:
        return next(
            (
                session
                for session in self.sessions.values()
                if session.refresh_token_digest == digest
            ),
            None,
        )

    async def mark_rotated(
        self,
        *,
        session_id: UUID,
        replacement_session_id: UUID,
        rotated_at: datetime,
    ) -> None:
        current = self.sessions[session_id]
        self.sessions[session_id] = replace(
            current,
            rotated_at=rotated_at,
            replaced_by_session_id=(replacement_session_id),
            last_used_at=rotated_at,
        )

    async def revoke_session(
        self,
        *,
        session_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        current = self.sessions[session_id]
        self.sessions[session_id] = replace(
            current,
            revoked_at=revoked_at,
            revocation_reason=reason,
            last_used_at=revoked_at,
        )

    async def revoke_family(
        self,
        *,
        token_family_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> int:
        revoked = 0

        for session_id, session in tuple(self.sessions.items()):
            if session.token_family_id != token_family_id or session.revoked_at is not None:
                continue

            self.sessions[session_id] = replace(
                session,
                revoked_at=revoked_at,
                revocation_reason=reason,
                last_used_at=revoked_at,
            )
            revoked += 1

        return revoked


def test_issue_stores_only_token_digest() -> None:
    """Return the raw token once while persisting only its digest."""
    repository = InMemoryRefreshSessionRepository()
    now = datetime(
        2026,
        8,
        7,
        12,
        0,
        tzinfo=UTC,
    )
    service = RefreshSessionService(
        repository,
        clock=lambda: now,
    )

    issued = asyncio.run(service.issue(user_id=UUID("00000000-0000-4000-8000-000000000001")))

    assert issued.token
    assert len(issued.session.refresh_token_digest) == 64
    assert issued.token != (issued.session.refresh_token_digest)
    assert issued.token not in repr(issued)


def test_rotate_replaces_active_token_in_same_family() -> None:
    """Invalidate the current token and issue one replacement."""
    repository = InMemoryRefreshSessionRepository()
    now = datetime(
        2026,
        8,
        7,
        12,
        0,
        tzinfo=UTC,
    )
    service = RefreshSessionService(
        repository,
        clock=lambda: now,
    )

    original = asyncio.run(service.issue(user_id=UUID("00000000-0000-4000-8000-000000000001")))
    replacement = asyncio.run(service.rotate(original.token))
    stored_original = repository.sessions[original.session.id]

    assert replacement.token != original.token
    assert replacement.session.token_family_id == original.session.token_family_id
    assert stored_original.rotated_at == now
    assert stored_original.replaced_by_session_id == replacement.session.id


def test_reusing_rotated_token_revokes_family() -> None:
    """Detect replay and revoke the complete token family."""
    repository = InMemoryRefreshSessionRepository()
    now = datetime(
        2026,
        8,
        7,
        12,
        0,
        tzinfo=UTC,
    )
    service = RefreshSessionService(
        repository,
        clock=lambda: now,
    )

    original = asyncio.run(service.issue(user_id=UUID("00000000-0000-4000-8000-000000000001")))
    asyncio.run(service.rotate(original.token))

    with pytest.raises(RefreshTokenReuseDetected):
        asyncio.run(service.rotate(original.token))

    family_sessions = [
        session
        for session in repository.sessions.values()
        if session.token_family_id == original.session.token_family_id
    ]

    assert family_sessions
    assert all(session.revoked_at == now for session in family_sessions)
    assert all(session.revocation_reason == "refresh_token_reuse" for session in family_sessions)


def test_expired_token_is_revoked() -> None:
    """Reject and revoke a token after its expiry."""
    repository = InMemoryRefreshSessionRepository()
    current_time = [
        datetime(
            2026,
            8,
            7,
            12,
            0,
            tzinfo=UTC,
        )
    ]
    service = RefreshSessionService(
        repository,
        token_lifetime=timedelta(seconds=1),
        clock=lambda: current_time[0],
    )

    issued = asyncio.run(service.issue(user_id=UUID("00000000-0000-4000-8000-000000000001")))
    current_time[0] += timedelta(seconds=2)

    with pytest.raises(ExpiredRefreshToken):
        asyncio.run(service.rotate(issued.token))

    expired = repository.sessions[issued.session.id]

    assert expired.revoked_at == current_time[0]
    assert expired.revocation_reason == "refresh_token_expired"


def test_session_revision_follows_user_revision() -> None:
    """Keep the session table attached to the user migration."""
    scripts = ScriptDirectory.from_config(create_alembic_config(TEST_DATABASE_URL))
    revision = scripts.get_revision("0003_auth_sessions")

    assert revision is not None
    assert revision.down_revision == ("0002_identity_users")
    assert len(scripts.get_heads()) == 1
