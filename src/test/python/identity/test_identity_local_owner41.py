from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import replace

import pytest
from sqlalchemy.exc import IntegrityError

from orchestwin.identity.application import (
    AuthenticationStatus,
    LocalIdentityApplicationService,
    LocalOwnerUnavailable,
)
from orchestwin.identity.domain import NormalizedEmail, UserAccount, create_user_account
from orchestwin.identity.passwords import Argon2PasswordService
from src.test.python.identity.test_identity_application import (
    EMAIL,
    PASSWORD,
    USER_ID,
    build_service,
    register,
)

LOCAL_EMAIL = "local-owner@example.com"


def count_additions(users, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    added: list[str] = []
    original = users.add

    async def counted(user: UserAccount) -> UserAccount:
        added.append(user.email.value)
        return await original(user)

    monkeypatch.setattr(users, "add", counted)
    return added


def test_the_local_owner_is_created_once_and_found_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exits: list[type[BaseException] | None] = []
    service, users, sessions = build_service(exits)
    added = count_additions(users, monkeypatch)

    first = asyncio.run(service.local_owner(email=" Local-Owner@Example.COM "))
    again = asyncio.run(service.local_owner(email=LOCAL_EMAIL))

    assert added == [LOCAL_EMAIL]
    assert first.id == again.id == USER_ID
    assert again == first
    assert first.email.value == LOCAL_EMAIL
    assert first.is_active is True
    assert first.guidance_mode is None
    assert list(users.users) == [USER_ID]
    assert sessions.sessions == {}
    assert exits == [None, None]


def test_the_password_of_the_local_owner_is_random_and_never_shown(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    service, _, _ = build_service()
    generated: list[tuple[int, str]] = []
    original = secrets.token_urlsafe

    def recorded(size: int) -> str:
        token = original(size)
        generated.append((size, token))
        return token

    monkeypatch.setattr(secrets, "token_urlsafe", recorded)
    with caplog.at_level(logging.DEBUG):
        owner = asyncio.run(service.local_owner(email=LOCAL_EMAIL))
    attempts = [
        asyncio.run(service.login(email=LOCAL_EMAIL, password=value)) for value in (LOCAL_EMAIL, "")
    ]
    passwords = Argon2PasswordService()

    assert [size for size, _ in generated] == [48]
    random_password = LocalIdentityApplicationService.LOCAL_OWNER_PASSWORD_PREFIX + generated[0][1]
    assert passwords.verify(random_password, owner.password_hash).valid is True
    assert passwords.verify(LOCAL_EMAIL, owner.password_hash).valid is False
    assert passwords.verify("", owner.password_hash).valid is False
    assert generated[0][1] not in caplog.text
    assert [attempt.status for attempt in attempts] == [
        AuthenticationStatus.INVALID_CREDENTIALS
    ] * 2


def test_a_random_token_without_symbols_still_meets_the_password_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, _, _ = build_service()
    monkeypatch.setattr(secrets, "token_urlsafe", lambda size: "a" * 64)

    owner = asyncio.run(service.local_owner(email=LOCAL_EMAIL))

    assert owner.password_hash.startswith("$argon2")


def test_a_registered_account_named_in_the_configuration_is_kept_as_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, users, _ = build_service()
    registered = register(service)
    added = count_additions(users, monkeypatch)

    owner = asyncio.run(service.local_owner(email=EMAIL))
    signed_in = asyncio.run(service.login(email=EMAIL, password=PASSWORD))

    assert added == []
    assert owner == registered.user
    assert signed_in.status is AuthenticationStatus.AUTHENTICATED


def test_an_inactive_local_owner_is_unavailable() -> None:
    exits: list[type[BaseException] | None] = []
    service, users, sessions = build_service(exits)
    owner = asyncio.run(service.local_owner(email=LOCAL_EMAIL))
    users.users[owner.id] = replace(owner, is_active=False)
    exits.clear()

    with pytest.raises(LocalOwnerUnavailable):
        asyncio.run(service.local_owner(email=LOCAL_EMAIL))
    with pytest.raises(LocalOwnerUnavailable):
        asyncio.run(service.issue_local_owner_session(email=LOCAL_EMAIL))

    assert issubclass(LocalOwnerUnavailable, RuntimeError)
    assert exits == [LocalOwnerUnavailable, LocalOwnerUnavailable]
    assert sessions.sessions == {}


def test_a_local_owner_session_carries_a_working_token_and_refresh_token() -> None:
    exits: list[type[BaseException] | None] = []
    service, users, sessions = build_service(exits)

    issued = asyncio.run(service.issue_local_owner_session(email=LOCAL_EMAIL))
    units = list(exits)
    current = asyncio.run(service.current_user(issued.access_token.token))
    rotated = asyncio.run(service.refresh(issued.refresh_token.token))

    assert units == [None]
    assert issued.user.email.value == LOCAL_EMAIL
    assert list(users.users) == [issued.user.id]
    assert issued.refresh_token.token
    assert issued.refresh_token.session.user_id == issued.user.id
    assert issued.refresh_token.session.id in sessions.sessions
    assert current == issued.user
    assert rotated.status is AuthenticationStatus.AUTHENTICATED
    assert rotated.authenticated is not None
    assert rotated.authenticated.user == issued.user


@pytest.mark.parametrize("with_session", [False, True])
def test_a_creation_lost_to_a_concurrent_request_reads_the_account_again(
    monkeypatch: pytest.MonkeyPatch,
    with_session: bool,
) -> None:
    exits: list[type[BaseException] | None] = []
    service, users, sessions = build_service(exits)
    original = users.add
    winner = create_user_account(
        email=NormalizedEmail(LOCAL_EMAIL),
        password_hash="$argon2id$concurrent-winner",
    )

    async def concurrent_winner(user: UserAccount) -> UserAccount:
        await original(winner)
        raise IntegrityError(
            "INSERT INTO users",
            {},
            Exception("duplicate key value violates unique constraint"),
        )

    monkeypatch.setattr(users, "add", concurrent_winner)

    if with_session:
        issued = asyncio.run(service.issue_local_owner_session(email=LOCAL_EMAIL))
        owner = issued.user
        assert issued.refresh_token.session.id in sessions.sessions
    else:
        owner = asyncio.run(service.local_owner(email=LOCAL_EMAIL))

    assert exits == [IntegrityError, None]
    assert owner.password_hash == "$argon2id$concurrent-winner"
    assert owner.id == USER_ID
