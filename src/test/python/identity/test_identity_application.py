"""Tests for local identity application use cases."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from typing import Any
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError

from orchestwin.identity.application import (
    AuthenticatedSession,
    AuthenticationStatus,
    GuidanceChoiceResult,
    GuidanceChoiceStatus,
    LocalIdentityApplicationService,
)
from orchestwin.identity.domain import (
    GuidanceMode,
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
        self.choices: list[tuple[UUID, GuidanceMode, datetime]] = []

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

    async def add_guidance_choice(
        self,
        *,
        user_id: UUID,
        mode: GuidanceMode,
        chosen_at: datetime,
    ) -> None:
        if any(chosen == user_id for chosen, _, _ in self.choices):
            raise IntegrityError(
                "INSERT INTO user_guidance_choices",
                {},
                Exception("duplicate key value violates unique constraint"),
            )

        self.choices.append((user_id, mode, chosen_at))
        self.users[user_id] = replace(
            self.users[user_id],
            guidance_mode=mode,
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
        exits: list[type[BaseException] | None] | None = None,
    ) -> None:
        self.users = users
        self.refresh_sessions = sessions
        self.exits = exits

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
        if self.exits is not None:
            self.exits.append(exception_type)

        return None


def build_service(
    exits: list[type[BaseException] | None] | None = None,
) -> tuple[
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
            exits,
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
            password="Correct horse battery staple!",
        )
    )

    assert result.status is (AuthenticationStatus.AUTHENTICATED)
    assert result.authenticated is not None
    assert result.authenticated.user.id == USER_ID
    assert result.authenticated.user.email.value == "owner@example.com"
    assert result.authenticated.user.password_hash != "Correct horse battery staple!"
    assert users.users
    assert sessions.sessions


def test_duplicate_registration_is_rejected() -> None:
    """Return a stable conflict for an existing normalized email."""
    service, _, _ = build_service()

    first = asyncio.run(
        service.register(
            email="owner@example.com",
            password="Correct horse battery staple!",
        )
    )
    second = asyncio.run(
        service.register(
            email="OWNER@example.com",
            password="Another correct horse battery!",
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
            password="Correct horse battery staple!",
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
            password="Correct horse battery staple!",
        )
    )
    assert registration.authenticated is not None

    resolved = asyncio.run(service.current_user(registration.authenticated.access_token.token))
    invalid = asyncio.run(service.current_user("invalid-token"))

    assert resolved is not None
    assert resolved.id == USER_ID
    assert invalid is None


EMAIL = "owner@example.com"
PASSWORD = "Correct horse battery staple!"
MISSING_USER_ID = UUID("00000000-0000-4000-8000-000000000099")


def register(service: LocalIdentityApplicationService) -> AuthenticatedSession:
    result = asyncio.run(service.register(email=EMAIL, password=PASSWORD))
    assert result.authenticated is not None
    return result.authenticated


def seen_modes(
    service: LocalIdentityApplicationService,
    access_token: str,
) -> list[GuidanceMode | None]:
    current = asyncio.run(service.current_user(access_token))
    login = asyncio.run(service.login(email=EMAIL, password=PASSWORD))
    assert current is not None
    assert login.authenticated is not None
    refresh = asyncio.run(service.refresh(login.authenticated.refresh_token.token))
    assert refresh.authenticated is not None
    return [
        current.guidance_mode,
        login.authenticated.user.guidance_mode,
        refresh.authenticated.user.guidance_mode,
    ]


@pytest.mark.parametrize(
    ("mode", "other"),
    [
        (GuidanceMode.GUIDED, GuidanceMode.EXPERT),
        (GuidanceMode.EXPERT, GuidanceMode.GUIDED),
    ],
)
def test_each_account_chooses_its_guidance_mode_once(
    mode: GuidanceMode,
    other: GuidanceMode,
) -> None:
    service, users, _ = build_service()
    registered = register(service)
    before = seen_modes(service, registered.access_token.token)

    chosen = asyncio.run(service.choose_guidance_mode(user_id=USER_ID, mode=mode.value))
    again = [
        asyncio.run(service.choose_guidance_mode(user_id=USER_ID, mode=value))
        for value in (mode.value, other.value)
    ]

    assert registered.user.guidance_mode is None
    assert before == [None, None, None]
    assert chosen == GuidanceChoiceResult(
        status=GuidanceChoiceStatus.CHOSEN,
        user=replace(registered.user, guidance_mode=mode),
    )
    assert again == [GuidanceChoiceResult(status=GuidanceChoiceStatus.ALREADY_CHOSEN)] * 2
    assert seen_modes(service, registered.access_token.token) == [mode, mode, mode]
    assert [(user_id, value) for user_id, value, _ in users.choices] == [(USER_ID, mode)]
    assert users.choices[0][2].tzinfo is UTC
    assert users.users[USER_ID] == replace(registered.user, guidance_mode=mode)


@pytest.mark.parametrize("mode", ["", "guided", "Expert", " GUIDED", "GUIDED ", "NOVICE"])
def test_an_unknown_guidance_mode_is_invalid_before_any_transaction(mode: str) -> None:
    exits: list[type[BaseException] | None] = []
    service, users, _ = build_service(exits)
    register(service)
    exits.clear()

    result = asyncio.run(service.choose_guidance_mode(user_id=USER_ID, mode=mode))

    assert result == GuidanceChoiceResult(status=GuidanceChoiceStatus.INVALID)
    assert exits == []
    assert users.choices == []
    assert users.users[USER_ID].guidance_mode is None


def test_a_missing_or_inactive_account_cannot_choose() -> None:
    service, users, _ = build_service()
    register(service)

    missing = asyncio.run(service.choose_guidance_mode(user_id=MISSING_USER_ID, mode="GUIDED"))
    users.users[USER_ID] = replace(users.users[USER_ID], is_active=False)
    inactive = asyncio.run(service.choose_guidance_mode(user_id=USER_ID, mode="EXPERT"))

    assert missing == GuidanceChoiceResult(status=GuidanceChoiceStatus.USER_UNAVAILABLE)
    assert inactive == GuidanceChoiceResult(status=GuidanceChoiceStatus.USER_UNAVAILABLE)
    assert users.choices == []
    assert users.users[USER_ID].guidance_mode is None


def test_a_choice_lost_to_a_concurrent_request_is_already_chosen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exits: list[type[BaseException] | None] = []
    service, users, _ = build_service(exits)
    registered = register(service)
    exits.clear()
    original = users.add_guidance_choice

    async def concurrent_winner(**choice: Any) -> None:
        await original(user_id=USER_ID, mode=GuidanceMode.EXPERT, chosen_at=NOW)
        await original(**choice)

    monkeypatch.setattr(users, "add_guidance_choice", concurrent_winner)

    result = asyncio.run(service.choose_guidance_mode(user_id=USER_ID, mode="GUIDED"))
    current = asyncio.run(service.current_user(registered.access_token.token))

    assert result == GuidanceChoiceResult(status=GuidanceChoiceStatus.ALREADY_CHOSEN)
    assert exits[0] is IntegrityError
    assert [mode for _, mode, _ in users.choices] == [GuidanceMode.EXPERT]
    assert current is not None
    assert current.guidance_mode is GuidanceMode.EXPERT


def test_a_guidance_choice_result_carries_the_account_only_when_chosen() -> None:
    user = UserAccount(
        id=USER_ID,
        email=NormalizedEmail(EMAIL),
        password_hash="$argon2id$hidden",
        is_active=True,
        created_at=NOW,
        updated_at=NOW,
        guidance_mode=GuidanceMode.GUIDED,
    )
    refused = (
        GuidanceChoiceStatus.ALREADY_CHOSEN,
        GuidanceChoiceStatus.INVALID,
        GuidanceChoiceStatus.USER_UNAVAILABLE,
    )

    assert [status.value for status in GuidanceChoiceStatus] == [
        "guidance_mode_chosen",
        "guidance_mode_already_chosen",
        "invalid_guidance_mode",
        "user_unavailable",
    ]
    assert GuidanceChoiceResult(status=GuidanceChoiceStatus.CHOSEN, user=user).user == user
    with pytest.raises(ValueError, match="only a chosen guidance mode"):
        GuidanceChoiceResult(status=GuidanceChoiceStatus.CHOSEN)
    for status in refused:
        assert GuidanceChoiceResult(status=status).user is None
        with pytest.raises(ValueError, match="only a chosen guidance mode"):
            GuidanceChoiceResult(status=status, user=user)
