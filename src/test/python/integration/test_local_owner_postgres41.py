from __future__ import annotations

import asyncio
from dataclasses import replace

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from orchestwin.identity.application import (
    AuthenticationStatus,
    GuidanceChoiceResult,
    GuidanceChoiceStatus,
)
from orchestwin.identity.domain import GuidanceMode
from orchestwin.identity.persistence import (
    AuthSessionRecord,
    SqlAlchemyUserRepository,
    UserRecord,
)
from orchestwin.identity.sessions import digest_refresh_token
from orchestwin.persistence import create_database_runtime
from src.test.python.integration.test_guidance_choice_postgres import identity, stored_choices
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]
pytestmark = pytest.mark.integration
LOCAL_EMAIL = "local-owner@example.com"


async def local_owner_rows(db):
    async with db.session_factory() as session:
        rows = await session.execute(
            sa.select(UserRecord.id, UserRecord.email_normalized).where(
                UserRecord.email_normalized == LOCAL_EMAIL
            )
        )
        return [tuple(row) for row in rows.all()]


async def stored_session(db, session_id):
    async with db.session_factory() as session:
        row = (
            await session.execute(
                sa.select(
                    AuthSessionRecord.user_id,
                    AuthSessionRecord.refresh_token_digest,
                    AuthSessionRecord.rotated_at,
                    AuthSessionRecord.revoked_at,
                ).where(AuthSessionRecord.id == session_id)
            )
        ).one()
        return tuple(row)


def test_the_local_owner_is_created_once_and_found_again(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            service = identity(db)
            first = await service.local_owner(email=" Local-Owner@Example.COM ")
            again = await service.local_owner(email=LOCAL_EMAIL)
            rows = await local_owner_rows(db)
            attempts = [
                await service.login(email=LOCAL_EMAIL, password=value)
                for value in (LOCAL_EMAIL, "")
            ]

            assert again == first
            assert (first.email.value, first.is_active, first.guidance_mode) == (
                LOCAL_EMAIL,
                True,
                None,
            )
            assert first.password_hash.startswith("$argon2")
            assert rows == [(first.id, LOCAL_EMAIL)]
            assert [attempt.status for attempt in attempts] == [
                AuthenticationStatus.INVALID_CREDENTIALS
            ] * 2
        finally:
            await db.dispose()

    run(scenario())


def test_a_local_owner_session_is_a_real_refresh_session(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            service = identity(db)
            issued = await service.issue_local_owner_session(email=LOCAL_EMAIL)
            rows = await local_owner_rows(db)
            stored = await stored_session(db, issued.refresh_token.session.id)
            current = await service.current_user(issued.access_token.token)
            rotated = await service.refresh(issued.refresh_token.token)
            replayed = await service.refresh(issued.refresh_token.token)
            again = await service.issue_local_owner_session(email=LOCAL_EMAIL)

            assert rows == [(issued.user.id, LOCAL_EMAIL)]
            assert stored == (
                issued.user.id,
                digest_refresh_token(issued.refresh_token.token),
                None,
                None,
            )
            assert current == issued.user
            assert rotated.status is AuthenticationStatus.AUTHENTICATED
            assert rotated.authenticated is not None
            assert rotated.authenticated.user == issued.user
            assert replayed.status is AuthenticationStatus.REFRESH_TOKEN_REUSE_DETECTED
            assert again.user == issued.user
            assert again.refresh_token.token != issued.refresh_token.token
            assert await local_owner_rows(db) == rows
        finally:
            await db.dispose()

    run(scenario())


def test_the_local_owner_chooses_its_guidance_mode_only_once(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            service = identity(db)
            owner = await service.local_owner(email=LOCAL_EMAIL)
            chosen = await service.choose_guidance_mode(user_id=owner.id, mode="GUIDED")
            again = [
                await service.choose_guidance_mode(user_id=owner.id, mode=mode)
                for mode in ("GUIDED", "EXPERT")
            ]
            found = await service.local_owner(email=LOCAL_EMAIL)
            issued = await service.issue_local_owner_session(email=LOCAL_EMAIL)

            expected = replace(owner, guidance_mode=GuidanceMode.GUIDED)
            assert chosen == GuidanceChoiceResult(
                status=GuidanceChoiceStatus.CHOSEN,
                user=expected,
            )
            assert again == [GuidanceChoiceResult(status=GuidanceChoiceStatus.ALREADY_CHOSEN)] * 2
            assert found == expected
            assert issued.user == expected
            assert await stored_choices(db) == [(owner.id, "GUIDED")]
        finally:
            await db.dispose()

    run(scenario())


def test_two_first_starts_at_the_same_time_create_one_local_owner(database, monkeypatch):
    async def scenario():
        db = create_database_runtime(database)
        try:
            service = identity(db)
            together = asyncio.Barrier(2)
            conflicts = []
            original = SqlAlchemyUserRepository.add

            async def add_together(self, user):
                await together.wait()
                try:
                    return await original(self, user)
                except IntegrityError:
                    conflicts.append(user.email.value)
                    raise

            monkeypatch.setattr(SqlAlchemyUserRepository, "add", add_together)
            owner, issued = await asyncio.wait_for(
                asyncio.gather(
                    service.local_owner(email=LOCAL_EMAIL),
                    service.issue_local_owner_session(email=LOCAL_EMAIL),
                ),
                timeout=30,
            )

            assert conflicts == [LOCAL_EMAIL]
            assert issued.user.id == owner.id
            assert await local_owner_rows(db) == [(owner.id, LOCAL_EMAIL)]
            assert await stored_session(db, issued.refresh_token.session.id) == (
                owner.id,
                digest_refresh_token(issued.refresh_token.token),
                None,
                None,
            )
        finally:
            await db.dispose()

    run(scenario())
