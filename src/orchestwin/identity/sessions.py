"""Opaque refresh-token issuance, rotation, and revocation."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4


class SessionStateConflict(RuntimeError):
    """Raised when a refresh session changes concurrently."""


class RefreshRotationStatus(StrEnum):
    """Stable outcomes of a refresh-token rotation attempt."""

    ROTATED = "rotated"
    INVALID = "invalid"
    EXPIRED = "expired"
    REUSE_DETECTED = "reuse_detected"


@dataclass(frozen=True, slots=True)
class RefreshSession:
    """Persisted server-side state for one opaque refresh token."""

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

    def __post_init__(self) -> None:
        """Protect refresh-session invariants."""
        if len(self.refresh_token_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.refresh_token_digest
        ):
            raise ValueError("refresh-token digest must be a lowercase SHA-256 digest")

        timestamps = (
            self.expires_at,
            self.created_at,
            self.last_used_at,
            self.rotated_at,
            self.revoked_at,
        )

        if any(timestamp is not None and timestamp.tzinfo is None for timestamp in timestamps):
            raise ValueError("refresh-session timestamps must be timezone-aware")

        if self.expires_at <= self.created_at:
            raise ValueError("refresh session must expire after creation")

        if self.last_used_at < self.created_at:
            raise ValueError("last-used timestamp must not precede creation")

        rotation_is_complete = (
            self.rotated_at is not None and self.replaced_by_session_id is not None
        )
        rotation_is_absent = self.rotated_at is None and self.replaced_by_session_id is None

        if not (rotation_is_complete or rotation_is_absent):
            raise ValueError("rotation timestamp and replacement identifier must be set together")

        revocation_is_complete = self.revoked_at is not None and self.revocation_reason is not None
        revocation_is_absent = self.revoked_at is None and self.revocation_reason is None

        if not (revocation_is_complete or revocation_is_absent):
            raise ValueError("revocation timestamp and reason must be set together")


@dataclass(frozen=True, slots=True)
class IssuedRefreshToken:
    """Raw refresh token returned once to the authenticated client."""

    token: str = field(repr=False)
    session: RefreshSession

    def __post_init__(self) -> None:
        """Reject an empty raw token."""
        if not self.token:
            raise ValueError("issued refresh token must not be empty")


@dataclass(frozen=True, slots=True)
class RefreshRotationResult:
    """Typed result that allows revocation mutations to commit."""

    status: RefreshRotationStatus
    issued_token: IssuedRefreshToken | None = None

    def __post_init__(self) -> None:
        """Associate an issued token only with successful rotation."""
        succeeded = self.status is RefreshRotationStatus.ROTATED

        if succeeded != (self.issued_token is not None):
            raise ValueError("only a successful rotation may contain an issued token")

    @property
    def succeeded(self) -> bool:
        """Return whether rotation produced a replacement token."""
        return self.status is RefreshRotationStatus.ROTATED


class RefreshSessionRepository(Protocol):
    """Persistence operations required by refresh-token use cases."""

    async def add(
        self,
        session: RefreshSession,
    ) -> RefreshSession:
        """Persist a refresh session."""

    async def get_by_digest_for_update(
        self,
        digest: str,
    ) -> RefreshSession | None:
        """Lock and return a session by digest."""

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
        """Revoke one active session."""

    async def revoke_family(
        self,
        *,
        token_family_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        """Revoke all active sessions in a token family."""


Clock = Callable[[], datetime]
TokenFactory = Callable[[], str]
UuidFactory = Callable[[], UUID]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def generate_refresh_token() -> str:
    """Generate a URL-safe token from 48 random bytes."""
    return secrets.token_urlsafe(48)


def digest_refresh_token(token: str) -> str:
    """Create the irreversible lookup digest stored by the server."""
    if not token:
        raise ValueError("refresh token must not be empty")

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RefreshSessionService:
    """Issue, rotate, and revoke opaque refresh-token sessions."""

    def __init__(
        self,
        repository: RefreshSessionRepository,
        *,
        token_lifetime: timedelta = timedelta(days=30),
        clock: Clock = utc_now,
        token_factory: TokenFactory = generate_refresh_token,
        uuid_factory: UuidFactory = uuid4,
    ) -> None:
        if token_lifetime <= timedelta(0):
            raise ValueError("token lifetime must be positive")

        self._repository = repository
        self._token_lifetime = token_lifetime
        self._clock = clock
        self._token_factory = token_factory
        self._uuid_factory = uuid_factory

    async def issue(
        self,
        *,
        user_id: UUID,
    ) -> IssuedRefreshToken:
        """Create the first refresh token in a new family."""
        issued_at = self._current_time()

        return await self._create_and_persist(
            user_id=user_id,
            token_family_id=self._uuid_factory(),
            issued_at=issued_at,
        )

    async def rotate(
        self,
        token: str,
    ) -> RefreshRotationResult:
        """Rotate an active token and detect replay."""
        if not token:
            return RefreshRotationResult(status=RefreshRotationStatus.INVALID)

        now = self._current_time()
        current = await self._repository.get_by_digest_for_update(digest_refresh_token(token))

        if current is None:
            return RefreshRotationResult(status=RefreshRotationStatus.INVALID)

        if current.rotated_at is not None or current.revoked_at is not None:
            await self._repository.revoke_family(
                token_family_id=current.token_family_id,
                revoked_at=now,
                reason="refresh_token_reuse",
            )

            return RefreshRotationResult(status=(RefreshRotationStatus.REUSE_DETECTED))

        if current.expires_at <= now:
            await self._repository.revoke_session(
                session_id=current.id,
                revoked_at=now,
                reason="refresh_token_expired",
            )

            return RefreshRotationResult(status=RefreshRotationStatus.EXPIRED)

        replacement = await self._create_and_persist(
            user_id=current.user_id,
            token_family_id=current.token_family_id,
            issued_at=now,
        )

        await self._repository.mark_rotated(
            session_id=current.id,
            replacement_session_id=(replacement.session.id),
            rotated_at=now,
        )

        return RefreshRotationResult(
            status=RefreshRotationStatus.ROTATED,
            issued_token=replacement,
        )

    async def revoke(
        self,
        token: str,
        *,
        reason: str = "logout",
    ) -> bool:
        """Revoke one currently active refresh session."""
        if not token:
            return False

        now = self._current_time()
        current = await self._repository.get_by_digest_for_update(digest_refresh_token(token))

        if current is None or current.rotated_at is not None or current.revoked_at is not None:
            return False

        await self._repository.revoke_session(
            session_id=current.id,
            revoked_at=now,
            reason=reason,
        )

        return True

    def _current_time(self) -> datetime:
        """Return and validate the injected clock value."""
        current = self._clock()

        if current.tzinfo is None:
            raise ValueError("refresh-session clock must be timezone-aware")

        return current

    async def _create_and_persist(
        self,
        *,
        user_id: UUID,
        token_family_id: UUID,
        issued_at: datetime,
    ) -> IssuedRefreshToken:
        """Generate and persist one refresh token."""
        raw_token = self._token_factory()

        if not raw_token:
            raise ValueError("refresh-token factory returned an empty token")

        session = RefreshSession(
            id=self._uuid_factory(),
            user_id=user_id,
            token_family_id=token_family_id,
            refresh_token_digest=(digest_refresh_token(raw_token)),
            expires_at=(issued_at + self._token_lifetime),
            created_at=issued_at,
            last_used_at=issued_at,
        )

        persisted = await self._repository.add(session)

        return IssuedRefreshToken(
            token=raw_token,
            session=persisted,
        )
