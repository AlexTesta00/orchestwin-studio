"""Tests for opaque refresh-token rotation."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

from alembic.script import ScriptDirectory

from orchestwin.identity.sessions import (
    RefreshRotationStatus,
    RefreshSession,
    RefreshSessionService,
    digest_refresh_token,
    generate_refresh_token,
)
from orchestwin.persistence.migrate import (
    create_alembic_config,
)

TEST_DATABASE_URL = (
    "postgresql+psycopg://user:database-secret-must-not-leak-8472@localhost:5432/orchestwin"
)
USER_ID = UUID("00000000-0000-4000-8000-000000000001")
TOKEN_FAMILY_ID = UUID("00000000-0000-4000-8000-000000000010")
FIRST_SESSION_ID = UUID("00000000-0000-4000-8000-000000000011")
SECOND_SESSION_ID = UUID("00000000-0000-4000-8000-000000000012")


class InMemoryRefreshSessionRepository:
    """Deterministic repository double for session behavior tests."""

    def __init__(self) -> None:
        self.sessions: dict[
            UUID,
            RefreshSession,
        ] = {}

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
    ) -> None:
        for session_id, session in tuple(self.sessions.items()):
            if session.token_family_id != token_family_id or session.revoked_at is not None:
                continue

            self.sessions[session_id] = replace(
                session,
                revoked_at=revoked_at,
                revocation_reason=reason,
                last_used_at=revoked_at,
            )


class SequenceFactory:
    """Return deterministic values from a finite sequence."""

    def __init__(
        self,
        values: list[object],
    ) -> None:
        self._values: Iterator[object] = iter(values)

    def __call__(self):
        return next(self._values)


def build_service(
    repository: InMemoryRefreshSessionRepository,
    *,
    current_time: list[datetime],
    raw_tokens: list[str] | None = None,
) -> RefreshSessionService:
    """Create a deterministic service for state-transition tests."""
    return RefreshSessionService(
        repository,
        clock=lambda: current_time[0],
        token_factory=SequenceFactory(
            raw_tokens
            or [
                "first-refresh-token",
                "second-refresh-token",
            ]
        ),
        uuid_factory=SequenceFactory(
            [
                TOKEN_FAMILY_ID,
                FIRST_SESSION_ID,
                SECOND_SESSION_ID,
            ]
        ),
    )


def test_generated_refresh_token_has_high_entropy_length() -> None:
    """Generate independent URL-safe tokens from 48 random bytes."""
    first = generate_refresh_token()
    second = generate_refresh_token()

    assert first != second
    assert len(first) >= 64
    assert len(second) >= 64


def test_issue_returns_raw_token_and_stores_only_digest() -> None:
    """Return the raw token once while persisting only its digest."""
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
    service = build_service(
        repository,
        current_time=current_time,
    )

    issued = asyncio.run(service.issue(user_id=USER_ID))

    assert issued.token == "first-refresh-token"
    assert issued.session.id == FIRST_SESSION_ID
    assert issued.session.token_family_id == TOKEN_FAMILY_ID
    assert issued.session.refresh_token_digest == digest_refresh_token("first-refresh-token")
    assert issued.token not in repr(issued)
    assert issued.token not in repr(issued.session)


def test_rotate_replaces_active_token_in_same_family() -> None:
    """Invalidate the current token and issue one successor."""
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
    service = build_service(
        repository,
        current_time=current_time,
    )

    original = asyncio.run(service.issue(user_id=USER_ID))
    result = asyncio.run(service.rotate(original.token))

    assert result.status is (RefreshRotationStatus.ROTATED)
    assert result.succeeded is True
    assert result.issued_token is not None

    replacement = result.issued_token
    stored_original = repository.sessions[original.session.id]

    assert replacement.token == ("second-refresh-token")
    assert replacement.session.token_family_id == original.session.token_family_id
    assert stored_original.rotated_at == (current_time[0])
    assert stored_original.replaced_by_session_id == replacement.session.id


def test_reusing_rotated_token_revokes_family() -> None:
    """Persist family revocation when a rotated token is replayed."""
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
    service = build_service(
        repository,
        current_time=current_time,
    )

    original = asyncio.run(service.issue(user_id=USER_ID))
    asyncio.run(service.rotate(original.token))

    replay_result = asyncio.run(service.rotate(original.token))

    assert replay_result.status is (RefreshRotationStatus.REUSE_DETECTED)
    assert replay_result.issued_token is None

    family_sessions = [
        session
        for session in repository.sessions.values()
        if session.token_family_id == original.session.token_family_id
    ]

    assert family_sessions
    assert all(session.revoked_at == current_time[0] for session in family_sessions)
    assert all(session.revocation_reason == "refresh_token_reuse" for session in family_sessions)


def test_expired_token_is_revoked_and_returns_typed_result() -> None:
    """Persist expiry revocation without raising an expected exception."""
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
        token_factory=SequenceFactory(["expiring-refresh-token"]),
        uuid_factory=SequenceFactory(
            [
                TOKEN_FAMILY_ID,
                FIRST_SESSION_ID,
            ]
        ),
    )

    issued = asyncio.run(service.issue(user_id=USER_ID))
    current_time[0] += timedelta(seconds=2)

    result = asyncio.run(service.rotate(issued.token))
    expired = repository.sessions[issued.session.id]

    assert result.status is (RefreshRotationStatus.EXPIRED)
    assert result.issued_token is None
    assert expired.revoked_at == current_time[0]
    assert expired.revocation_reason == "refresh_token_expired"


def test_invalid_token_returns_typed_result_without_mutation() -> None:
    """Reject an unknown token without creating or revoking sessions."""
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
    service = build_service(
        repository,
        current_time=current_time,
    )

    result = asyncio.run(service.rotate("unknown-refresh-token"))

    assert result.status is (RefreshRotationStatus.INVALID)
    assert result.issued_token is None
    assert repository.sessions == {}


def test_revoke_is_idempotent_for_logout() -> None:
    """Revoke one active token and safely ignore repeated logout."""
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
    service = build_service(
        repository,
        current_time=current_time,
    )
    issued = asyncio.run(service.issue(user_id=USER_ID))

    first_result = asyncio.run(service.revoke(issued.token))
    second_result = asyncio.run(service.revoke(issued.token))
    revoked = repository.sessions[issued.session.id]

    assert first_result is True
    assert second_result is False
    assert revoked.revoked_at == current_time[0]
    assert revoked.revocation_reason == "logout"


def test_session_revision_follows_user_revision() -> None:
    """Keep the session table attached to the user migration."""
    scripts = ScriptDirectory.from_config(create_alembic_config(TEST_DATABASE_URL))
    revision = scripts.get_revision("0003_auth_sessions")

    assert revision is not None
    assert revision.down_revision == ("0002_identity_users")
    assert len(scripts.get_heads()) == 1
