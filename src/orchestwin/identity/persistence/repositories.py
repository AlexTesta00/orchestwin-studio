"""SQLAlchemy implementations of identity repository ports."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.identity.domain import (
    NormalizedEmail,
    UserAccount,
)
from orchestwin.identity.persistence.models import (
    AuthSessionRecord,
    UserRecord,
)
from orchestwin.identity.sessions import (
    RefreshSession,
    SessionStateConflict,
)


def user_record_to_domain(record: UserRecord) -> UserAccount:
    """Translate a user record into an immutable domain value."""
    return UserAccount(
        id=record.id,
        email=NormalizedEmail(record.email_normalized),
        password_hash=record.password_hash,
        is_active=record.is_active,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def session_record_to_domain(
    record: AuthSessionRecord,
) -> RefreshSession:
    """Translate a session record into an immutable domain value."""
    return RefreshSession(
        id=record.id,
        user_id=record.user_id,
        token_family_id=record.token_family_id,
        refresh_token_digest=(record.refresh_token_digest),
        expires_at=record.expires_at,
        rotated_at=record.rotated_at,
        replaced_by_session_id=(record.replaced_by_session_id),
        revoked_at=record.revoked_at,
        revocation_reason=record.revocation_reason,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
    )


class SqlAlchemyUserRepository:
    """SQLAlchemy user repository bound to one transaction session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: UserAccount) -> UserAccount:
        """Add a new account to the current transaction."""
        record = UserRecord(
            id=user.id,
            email_normalized=user.email.value,
            password_hash=user.password_hash,
            is_active=user.is_active,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

        self._session.add(record)
        await self._session.flush()

        return user_record_to_domain(record)

    async def get_by_id(
        self,
        user_id: UUID,
    ) -> UserAccount | None:
        """Return an account by identifier."""
        record = await self._session.scalar(select(UserRecord).where(UserRecord.id == user_id))

        if record is None:
            return None

        return user_record_to_domain(record)

    async def get_by_email(
        self,
        email: NormalizedEmail,
    ) -> UserAccount | None:
        """Return an account by normalized email."""
        record = await self._session.scalar(
            select(UserRecord).where(UserRecord.email_normalized == email.value)
        )

        if record is None:
            return None

        return user_record_to_domain(record)


class SqlAlchemyRefreshSessionRepository:
    """SQLAlchemy refresh-session repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self,
        session: RefreshSession,
    ) -> RefreshSession:
        """Add a refresh session to the transaction."""
        record = AuthSessionRecord(
            id=session.id,
            user_id=session.user_id,
            token_family_id=session.token_family_id,
            refresh_token_digest=(session.refresh_token_digest),
            expires_at=session.expires_at,
            rotated_at=session.rotated_at,
            replaced_by_session_id=(session.replaced_by_session_id),
            revoked_at=session.revoked_at,
            revocation_reason=(session.revocation_reason),
            created_at=session.created_at,
            last_used_at=session.last_used_at,
        )

        self._session.add(record)
        await self._session.flush()

        return session_record_to_domain(record)

    async def get_by_digest_for_update(
        self,
        digest: str,
    ) -> RefreshSession | None:
        """Lock and return one session by token digest."""
        record = await self._session.scalar(
            select(AuthSessionRecord)
            .where(AuthSessionRecord.refresh_token_digest == digest)
            .with_for_update()
        )

        if record is None:
            return None

        return session_record_to_domain(record)

    async def mark_rotated(
        self,
        *,
        session_id: UUID,
        replacement_session_id: UUID,
        rotated_at: datetime,
    ) -> None:
        """Atomically rotate an active session."""
        result = await self._session.execute(
            update(AuthSessionRecord)
            .where(
                AuthSessionRecord.id == session_id,
                AuthSessionRecord.rotated_at.is_(None),
                AuthSessionRecord.revoked_at.is_(None),
            )
            .values(
                rotated_at=rotated_at,
                replaced_by_session_id=(replacement_session_id),
                last_used_at=rotated_at,
            )
        )

        if result.rowcount != 1:
            raise SessionStateConflict("refresh session changed concurrently")

    async def revoke_session(
        self,
        *,
        session_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        """Revoke one active session."""
        await self._session.execute(
            update(AuthSessionRecord)
            .where(
                AuthSessionRecord.id == session_id,
                AuthSessionRecord.revoked_at.is_(None),
            )
            .values(
                revoked_at=revoked_at,
                revocation_reason=reason,
                last_used_at=revoked_at,
            )
        )

    async def revoke_family(
        self,
        *,
        token_family_id: UUID,
        revoked_at: datetime,
        reason: str,
    ) -> int:
        """Revoke every active session in one token family."""
        result = await self._session.execute(
            update(AuthSessionRecord)
            .where(
                AuthSessionRecord.token_family_id == token_family_id,
                AuthSessionRecord.revoked_at.is_(None),
            )
            .values(
                revoked_at=revoked_at,
                revocation_reason=reason,
                last_used_at=revoked_at,
            )
        )

        return result.rowcount or 0
