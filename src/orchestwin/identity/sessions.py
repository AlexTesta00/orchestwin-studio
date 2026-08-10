"""Rotating opaque refresh-token sessions."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4


class RefreshTokenError(ValueError):
    """Base error for invalid refresh-session operations."""


class InvalidRefreshToken(RefreshTokenError):
    """Raised when no session matches a refresh token."""


class ExpiredRefreshToken(RefreshTokenError):
    """Raised when a refresh token has expired."""


class RefreshTokenReuseDetected(RefreshTokenError):
    """Raised when a rotated or revoked token is presented again."""


class SessionStateConflict(RuntimeError):
    """Raised when a session changed concurrently."""


@dataclass(frozen=True, slots=True)
class RefreshSession:
    """Persisted refresh-session state."""

    id: UUID
    user_id: UUID
    token_family_id: UUID
    refresh_token_digest: str = field(repr=False)
    expires_at: datetime
    created_at: datetime
    last_used_at: datetime
    rotated_at: datetime | None = None
    replaced_by_session_id: UUID | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None


@dataclass(frozen=True, slots=True)
class IssuedRefreshToken:
    """One raw token returned to the authenticated client."""

    token: str = field(repr=False)
    session: RefreshSession


class RefreshSessionRepository(Protocol):
    """Persistence operations required by refresh-token rotation."""

    async def add(
        self,
        session: RefreshSession,
    ) -> RefreshSession:
        """Persist a refresh session."""

    async def get_by_digest_for_update(
        self,
        digest: str,
    ) -> RefreshSession | None:
        """Lock and return the session matching a digest."""

    async def mark_rotated(
        self,
        *,
        session_id: UUID,
        replacement_session_id: UUID,
        rotated_at: datetime,
    ) -> None:
        """Mark one active session as rotated."""

    async def revoke_session(
        self,
        *,
        session_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        """Revoke one session."""

    async def revoke_family(
        self,
        *,
        token_family_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> int:
        """Revoke every active session in a token family."""


Clock = Callable[[], datetime]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def generate_refresh_token() -> str:
    """Generate a high-entropy URL-safe refresh token."""
    return secrets.token_urlsafe(48)


def digest_refresh_token(token: str) -> str:
    """Create the irreversible lookup digest stored by the server."""
    if not token:
        raise InvalidRefreshToken("refresh token is required")

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RefreshSessionService:
    """Issue, rotate, and revoke opaque refresh sessions."""

    def __init__(
        self,
        repository: RefreshSessionRepository,
        *,
        token_lifetime: timedelta = timedelta(days=30),
        clock: Clock = utc_now,
    ) -> None:
        if token_lifetime <= timedelta(0):
            raise ValueError("token lifetime must be positive")

        self._repository = repository
        self._token_lifetime = token_lifetime
        self._clock = clock

    async def issue(
        self,
        *,
        user_id: UUID,
    ) -> IssuedRefreshToken:
        """Create the first token in a new family."""
        return await self._create_and_persist(
            user_id=user_id,
            token_family_id=uuid4(),
        )

    async def rotate(
        self,
        token: str,
    ) -> IssuedRefreshToken:
        """Replace one active refresh token with another."""
        now = self._clock()
        digest = digest_refresh_token(token)
        current = await self._repository.get_by_digest_for_update(digest)

        if current is None:
            raise InvalidRefreshToken("refresh token is invalid")

        if current.rotated_at is not None or current.revoked_at is not None:
            await self._repository.revoke_family(
                token_family_id=current.token_family_id,
                revoked_at=now,
                reason="refresh_token_reuse",
            )
            raise RefreshTokenReuseDetected("refresh token reuse detected")

        if current.expires_at <= now:
            await self._repository.revoke_session(
                session_id=current.id,
                revoked_at=now,
                reason="refresh_token_expired",
            )
            raise ExpiredRefreshToken("refresh token has expired")

        replacement = await self._create_and_persist(
            user_id=current.user_id,
            token_family_id=current.token_family_id,
        )

        await self._repository.mark_rotated(
            session_id=current.id,
            replacement_session_id=(replacement.session.id),
            rotated_at=now,
        )

        return replacement

    async def revoke(
        self,
        token: str,
        *,
        reason: str = "logout",
    ) -> bool:
        """Revoke an active refresh session."""
        now = self._clock()
        digest = digest_refresh_token(token)
        current = await self._repository.get_by_digest_for_update(digest)

        if current is None or current.revoked_at is not None:
            return False

        await self._repository.revoke_session(
            session_id=current.id,
            revoked_at=now,
            reason=reason,
        )
        return True

    async def _create_and_persist(
        self,
        *,
        user_id: UUID,
        token_family_id: UUID,
    ) -> IssuedRefreshToken:
        """Generate and persist one refresh token."""
        now = self._clock()
        raw_token = generate_refresh_token()
        session = RefreshSession(
            id=uuid4(),
            user_id=user_id,
            token_family_id=token_family_id,
            refresh_token_digest=(digest_refresh_token(raw_token)),
            expires_at=now + self._token_lifetime,
            created_at=now,
            last_used_at=now,
        )

        persisted = await self._repository.add(session)

        return IssuedRefreshToken(
            token=raw_token,
            session=persisted,
        )
