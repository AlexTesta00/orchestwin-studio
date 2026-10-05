from __future__ import annotations

import asyncio
import importlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import sqlalchemy as sa
from pydantic import SecretStr
from sqlalchemy.exc import DBAPIError, IntegrityError

from orchestwin.api.auth import UserResponse
from orchestwin.identity.application import (
    AuthenticationStatus,
    GuidanceChoiceResult,
    GuidanceChoiceStatus,
    LocalIdentityApplicationService,
)
from orchestwin.identity.domain import GuidanceMode
from orchestwin.identity.passwords import Argon2PasswordService
from orchestwin.identity.persistence import (
    SqlAlchemyIdentityUnitOfWorkFactory,
    SqlAlchemyUserRepository,
    UserGuidanceChoiceRecord,
)
from orchestwin.identity.tokens import AccessTokenSettings, JwtAccessTokenService
from orchestwin.persistence import create_database_runtime
from orchestwin.persistence.migrate import downgrade_database, upgrade_database
from src.test.python.integration.postgres_isolation import (
    assert_reversible_migration,
    catalog_snapshot,
    isolated_postgres_settings,
)
from src.test.python.integration.test_postgresql_project_import import seed_users
from src.test.python.integration.test_proposal_evidence_postgres import database, run

__all__ = ["database"]
pytestmark = pytest.mark.integration
MIGRATION = importlib.import_module(
    "orchestwin.persistence.migrations.versions.0072_guidance_choice"
)
TABLE = "user_guidance_choices"
FUNCTION = "user_guidance_choice_append_only"
CHOICES = UserGuidanceChoiceRecord.__table__
NOW = datetime(2026, 10, 5, 9, tzinfo=UTC)
EMAIL = "owner@example.com"
PASSWORD = "Correct horse battery staple!"
COLUMNS = [
    ("user_id", "uuid", "None", "NO"),
    ("mode", "character varying", "8", "NO"),
    ("chosen_at", "timestamp with time zone", "None", "NO"),
]
PRIMARY_KEY = "pk_user_guidance_choices"
FOREIGN_KEY = "fk_user_guidance_choices_user_id_users"
CHECK = "ck_user_guidance_choice_mode"


def identity(db) -> LocalIdentityApplicationService:
    return LocalIdentityApplicationService(
        unit_of_work_factory=SqlAlchemyIdentityUnitOfWorkFactory(db.session_factory),
        password_service=Argon2PasswordService(),
        access_token_service=JwtAccessTokenService(
            AccessTokenSettings(
                jwt_secret=SecretStr("integration-test-jwt-secret-with-more-than-32-characters"),
                access_token_leeway_seconds=0,
                _env_file=None,
            )
        ),
    )


async def stored_users(db):
    async with db.session_factory() as session:
        return (
            (await session.execute(sa.text("SELECT row_to_json(t)::text FROM users t ORDER BY id")))
            .scalars()
            .all()
        )


async def stored_user(db, user_id):
    async with db.session_factory() as session:
        return await session.scalar(
            sa.text("SELECT row_to_json(t)::text FROM users t WHERE id = :id"), {"id": user_id}
        )


async def stored_choices(db):
    async with db.session_factory() as session:
        rows = await session.execute(
            sa.select(CHOICES.c.user_id, CHOICES.c.mode).order_by(CHOICES.c.user_id)
        )
        return [tuple(row) for row in rows.all()]


def test_isolated_guidance_choice_migration_is_reversible(database):
    assert_reversible_migration(database, MIGRATION)


def test_upgrade_on_an_isolated_schema_adds_only_the_choice_table_and_keeps_every_user(database):
    with isolated_postgres_settings(database, revision=MIGRATION.down_revision) as scoped:
        previous = catalog_snapshot(scoped)

        async def scenario():
            db = create_database_runtime(scoped)
            try:
                await seed_users(db, uuid4(), uuid4())
                before = await stored_users(db)
                await asyncio.to_thread(upgrade_database, scoped, revision=MIGRATION.revision)
                assert await stored_users(db) == before
                assert await stored_choices(db) == []
            finally:
                await db.dispose()

        run(scenario())
        current = catalog_snapshot(scoped)
    assert previous["revision"] == [(MIGRATION.down_revision,)]
    assert current["revision"] == [(MIGRATION.revision,)]
    for name in ("columns", "constraints", "indexes", "triggers"):
        assert [row for row in current[name] if row[0] != TABLE] == previous[name]
    assert [row for row in current["functions"] if row[0] != FUNCTION] == previous["functions"]
    assert [row[0] for row in current["functions"] if row[0] == FUNCTION] == [FUNCTION]
    assert [row[1:5] for row in current["columns"] if row[0] == TABLE] == COLUMNS
    definitions = {row[1]: row[2] for row in current["constraints"] if row[0] == TABLE}
    assert {PRIMARY_KEY, FOREIGN_KEY, CHECK} <= set(definitions)
    assert all(
        name.endswith("_not_null") for name in set(definitions) - {PRIMARY_KEY, FOREIGN_KEY, CHECK}
    )
    assert definitions[PRIMARY_KEY] == "PRIMARY KEY (user_id)"
    assert definitions[FOREIGN_KEY].endswith("ON DELETE RESTRICT")
    assert sorted(row[1] for row in current["indexes"] if row[0] == TABLE) == [PRIMARY_KEY]
    assert [row[1] for row in current["triggers"] if row[0] == TABLE] == [f"{TABLE}_immutable"]


def test_one_known_mode_per_existing_account_is_accepted(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            guided, expert = uuid4(), uuid4()
            await seed_users(db, guided, expert)

            async def insert(**changes):
                async with db.session_factory() as session, session.begin():
                    await session.execute(
                        sa.insert(CHOICES).values(
                            **{"user_id": guided, "mode": "GUIDED", "chosen_at": NOW, **changes}
                        )
                    )

            for mode in ("NOVICE", "guided", "Expert", "", "GUIDED "):
                with pytest.raises(IntegrityError) as rejected:
                    await insert(mode=mode)
                assert rejected.value.orig.diag.constraint_name == CHECK, mode
            for column in ("user_id", "mode", "chosen_at"):
                with pytest.raises(IntegrityError) as rejected:
                    await insert(**{column: None})
                assert rejected.value.orig.sqlstate == "23502"
                assert rejected.value.orig.diag.column_name == column
            with pytest.raises(IntegrityError) as rejected:
                await insert(user_id=uuid4())
            assert rejected.value.orig.diag.constraint_name == FOREIGN_KEY
            await insert()
            await insert(user_id=expert, mode="EXPERT")
            for mode in ("GUIDED", "EXPERT"):
                with pytest.raises(IntegrityError) as rejected:
                    await insert(mode=mode, chosen_at=NOW + timedelta(minutes=1))
                assert rejected.value.orig.diag.constraint_name == PRIMARY_KEY
            assert sorted(await stored_choices(db)) == sorted(
                [(guided, "GUIDED"), (expert, "EXPERT")]
            )
        finally:
            await db.dispose()

    run(scenario())


def test_update_and_delete_of_a_choice_are_refused_by_the_trigger(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            owner = uuid4()
            await seed_users(db, owner)
            async with db.session_factory() as session, session.begin():
                await session.execute(
                    sa.insert(CHOICES).values(user_id=owner, mode="GUIDED", chosen_at=NOW)
                )
            for statement in (
                sa.update(CHOICES).where(CHOICES.c.user_id == owner).values(mode="EXPERT"),
                sa.update(CHOICES)
                .where(CHOICES.c.user_id == owner)
                .values(chosen_at=NOW + timedelta(days=1)),
                sa.delete(CHOICES).where(CHOICES.c.user_id == owner),
            ):
                with pytest.raises(DBAPIError, match="guidance choices are append-only"):
                    async with db.session_factory() as session, session.begin():
                        await session.execute(statement)
            assert await stored_choices(db) == [(owner, "GUIDED")]
        finally:
            await db.dispose()

    run(scenario())


def test_two_concurrent_choices_have_exactly_one_winner(database, monkeypatch):
    async def scenario():
        db = create_database_runtime(database)
        try:
            service = identity(db)
            registered = await service.register(email=EMAIL, password=PASSWORD)
            assert registered.authenticated is not None
            account = registered.authenticated.user
            before = await stored_user(db, account.id)
            together = asyncio.Barrier(2)
            conflicts = []
            original = SqlAlchemyUserRepository.add_guidance_choice

            async def insert_together(self, **choice):
                await together.wait()
                try:
                    await original(self, **choice)
                except IntegrityError:
                    conflicts.append(choice["mode"])
                    raise

            monkeypatch.setattr(SqlAlchemyUserRepository, "add_guidance_choice", insert_together)
            results = await asyncio.wait_for(
                asyncio.gather(
                    service.choose_guidance_mode(user_id=account.id, mode="GUIDED"),
                    service.choose_guidance_mode(user_id=account.id, mode="EXPERT"),
                ),
                timeout=30,
            )
            [won] = [result for result in results if result.status is GuidanceChoiceStatus.CHOSEN]
            [lost] = [result for result in results if result is not won]
            assert lost == GuidanceChoiceResult(status=GuidanceChoiceStatus.ALREADY_CHOSEN)
            chosen = won.user
            assert chosen is not None
            assert chosen.guidance_mode is not None
            assert conflicts == [mode for mode in GuidanceMode if mode is not chosen.guidance_mode]
            assert await stored_choices(db) == [(account.id, chosen.guidance_mode.value)]
            assert await stored_user(db, account.id) == before
            assert await service.current_user(registered.authenticated.access_token.token) == chosen
        finally:
            await db.dispose()

    run(scenario())


def test_registration_choice_sign_in_and_me_through_the_real_service(database):
    async def scenario():
        db = create_database_runtime(database)
        try:
            service = identity(db)
            registered = await service.register(email=EMAIL, password=PASSWORD)
            assert registered.status is AuthenticationStatus.AUTHENTICATED
            assert registered.authenticated is not None
            account = registered.authenticated.user
            token = registered.authenticated.access_token.token
            assert account.guidance_mode is None
            assert await service.current_user(token) == account
            assert UserResponse.from_domain(account).guidance_mode is None

            before = await stored_user(db, account.id)
            started = datetime.now(UTC)
            chosen = await service.choose_guidance_mode(user_id=account.id, mode="EXPERT")
            finished = datetime.now(UTC)
            after = await stored_user(db, account.id)
            again = [
                await service.choose_guidance_mode(user_id=account.id, mode=mode)
                for mode in ("EXPERT", "GUIDED")
            ]
            signed_in = await service.login(email=EMAIL, password=PASSWORD)
            assert signed_in.authenticated is not None
            refreshed = await service.refresh(signed_in.authenticated.refresh_token.token)
            assert refreshed.authenticated is not None
            current = await service.current_user(token)
            async with db.session_factory() as session:
                stored = (await session.execute(sa.select(CHOICES))).all()

            expected = replace(account, guidance_mode=GuidanceMode.EXPERT)
            assert chosen == GuidanceChoiceResult(status=GuidanceChoiceStatus.CHOSEN, user=expected)
            assert again == [GuidanceChoiceResult(status=GuidanceChoiceStatus.ALREADY_CHOSEN)] * 2
            assert after == before
            assert signed_in.authenticated.user == expected
            assert refreshed.authenticated.user == expected
            assert current == expected
            assert UserResponse.from_domain(current).guidance_mode == "EXPERT"
            [(user_id, mode, chosen_at)] = [tuple(row) for row in stored]
            assert (user_id, mode) == (account.id, "EXPERT")
            assert started <= chosen_at <= finished
        finally:
            await db.dispose()

    run(scenario())


def test_downgrade_refuses_a_table_with_choices_and_keeps_them(database):
    with isolated_postgres_settings(database, revision=MIGRATION.revision) as scoped:

        async def scenario():
            db = create_database_runtime(scoped)
            try:
                owner = uuid4()
                await seed_users(db, owner)
                async with db.session_factory() as session, session.begin():
                    await session.execute(
                        sa.insert(CHOICES).values(user_id=owner, mode="EXPERT", chosen_at=NOW)
                    )
                with pytest.raises(
                    RuntimeError, match="guidance choices must be preserved before downgrade"
                ):
                    await asyncio.to_thread(
                        downgrade_database, scoped, revision=MIGRATION.down_revision
                    )
                assert await stored_choices(db) == [(owner, "EXPERT")]
            finally:
                await db.dispose()

        run(scenario())
        snapshot = catalog_snapshot(scoped)
    assert snapshot["revision"] == [(MIGRATION.revision,)]
    assert [row[0] for row in snapshot["functions"] if row[0] == FUNCTION] == [FUNCTION]


def test_downgrade_of_an_empty_choice_table_drops_it_and_keeps_every_user(database):
    with isolated_postgres_settings(database, revision=MIGRATION.revision) as scoped:

        async def scenario():
            db = create_database_runtime(scoped)
            try:
                await seed_users(db, uuid4())
                before = await stored_users(db)
                await asyncio.to_thread(
                    downgrade_database, scoped, revision=MIGRATION.down_revision
                )
                assert await stored_users(db) == before
                async with db.session_factory() as session:
                    assert (
                        await session.scalar(
                            sa.text("SELECT to_regclass('user_guidance_choices') IS NULL")
                        )
                        is True
                    )
            finally:
                await db.dispose()

        run(scenario())
        snapshot = catalog_snapshot(scoped)
    assert snapshot["revision"] == [(MIGRATION.down_revision,)]
    assert not any(row[0] == FUNCTION for row in snapshot["functions"])
    assert not any(row[0] == TABLE for row in snapshot["columns"])
