"""Tests for local identity application use cases."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

from pydantic import SecretStr

from orchestwin.identity.application import (
    AuthenticationStatus,
    LocalIdentityApplicationService,
)
from orchestwin.identity.domain import (
    NormalizedEmail,
    UserAccount,
)
from orchestwin.identity.passwords import (
    Argon2PasswordService,
)
from orchestwin.identity.sessions import (
    RefreshSession,
)
from orchestwin.identity.tokens import (
    AccessTokenSettings,
    JwtAccessTokenService,
)

USER_ID = UUID("00000000-0000-4000-8000-000000000001")
TOKEN_ID = UUID("00000000-0000-4000-8000-000000000002")
NOW = datetime.now(UTC)


class InMemoryUserRepository:
    """In-memory user repository for application tests."""

    def __init__(self) -> None:
        self.users: dict[
            UUID,
            UserAccount,
        ] = {}

    async def add(
        self,
        user: UserAccount,
    ) -> UserAccount:
        persisted = replace(
            user,
            id=USER_ID,
        )
        self.users[persisted.id] = persisted
        return persisted

    async def get_by_id(
        self,
        user_id: UUID,
    ) -> UserAccount | None:
        return self.users.get(user_id)

    async def get_by_email(
        self,
        email: NormalizedEmail,
    ) -> UserAccount | None:
        return next(
            (user for user in self.users.values() if user.email == email),
            None,
        )

    async def update_password_hash(
        self,
        *,
        user_id: UUID,
        password_hash: str,
    ) -> None:
        self.users[user_id] = replace(
            self.users[user_id],
            password_hash=password_hash,
        )


class InMemoryRefreshRepository:
    """In-memory refresh-session repository."""

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
        self.sessions[session_id] = replace(
            self.sessions[session_id],
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
        self.sessions[session_id] = replace(
            self.sessions[session_id],
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
            if session.token_family_id == token_family_id and session.revoked_at is None:
                self.sessions[session_id] = replace(
                    session,
                    revoked_at=revoked_at,
                    revocation_reason=reason,
                    last_used_at=revoked_at,
                )


class InMemoryIdentityUnitOfWork:
    """Reusable in-memory unit of work."""

    def __init__(
        self,
        users: InMemoryUserRepository,
        sessions: InMemoryRefreshRepository,
    ) -> None:
        self.users = users
        self.refresh_sessions = sessions

    async def __aenter__(
        self,
    ) -> InMemoryIdentityUnitOfWork:
        return self

    async def __aexit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def build_service() -> tuple[
    LocalIdentityApplicationService,
    InMemoryUserRepository,
    InMemoryRefreshRepository,
]:
    """Create an identity service with in-memory adapters."""
    users = InMemoryUserRepository()
    sessions = InMemoryRefreshRepository()
    password_service = Argon2PasswordService()
    token_service = JwtAccessTokenService(
        AccessTokenSettings(
            jwt_secret=SecretStr("identity-test-secret-with-more-than-32-characters"),
            access_token_leeway_seconds=0,
            _env_file=None,
        ),
        uuid_factory=lambda: TOKEN_ID,
    )

    service = LocalIdentityApplicationService(
        unit_of_work_factory=lambda: InMemoryIdentityUnitOfWork(
            users,
            sessions,
        ),
        password_service=password_service,
        access_token_service=token_service,
    )

    return service, users, sessions


def test_register_hashes_password_and_issues_session() -> None:
    """Create a normalized user and both token types."""
    service, users, sessions = build_service()

    result = asyncio.run(
        service.register(
            email=" Owner@Example.COM ",
            password="correct horse battery staple",
        )
    )

    assert result.status is (AuthenticationStatus.AUTHENTICATED)
    assert result.authenticated is not None
    assert result.authenticated.user.id == USER_ID
    assert result.authenticated.user.email.value == "owner@example.com"
    assert result.authenticated.user.password_hash != "correct horse battery staple"
    assert users.users
    assert sessions.sessions


def test_duplicate_registration_is_rejected() -> None:
    """Return a stable conflict for an existing normalized email."""
    service, _, _ = build_service()

    first = asyncio.run(
        service.register(
            email="owner@example.com",
            password="correct horse battery staple",
        )
    )
    second = asyncio.run(
        service.register(
            email="OWNER@example.com",
            password="another correct horse battery",
        )
    )

    assert first.status is (AuthenticationStatus.AUTHENTICATED)
    assert second.status is (AuthenticationStatus.EMAIL_ALREADY_REGISTERED)


def test_login_returns_one_generic_invalid_result() -> None:
    """Do not distinguish unknown email from wrong password."""
    service, _, _ = build_service()

    unknown = asyncio.run(
        service.login(
            email="missing@example.com",
            password="incorrect horse battery staple",
        )
    )

    asyncio.run(
        service.register(
            email="owner@example.com",
            password="correct horse battery staple",
        )
    )
    wrong_password = asyncio.run(
        service.login(
            email="owner@example.com",
            password="incorrect horse battery staple",
        )
    )

    assert unknown.status is (AuthenticationStatus.INVALID_CREDENTIALS)
    assert wrong_password.status is (AuthenticationStatus.INVALID_CREDENTIALS)


def test_current_user_requires_valid_access_token() -> None:
    """Resolve only active users from verified access tokens."""
    service, _, _ = build_service()
    registration = asyncio.run(
        service.register(
            email="owner@example.com",
            password="correct horse battery staple",
        )
    )
    assert registration.authenticated is not None

    resolved = asyncio.run(service.current_user(registration.authenticated.access_token.token))
    invalid = asyncio.run(service.current_user("invalid-token"))

    assert resolved is not None
    assert resolved.id == USER_ID
    assert invalid is None
