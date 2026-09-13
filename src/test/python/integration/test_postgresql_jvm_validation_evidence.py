"""Real PostgreSQL checks for synthetic JVM evidence in disposable test schemas.

These records exercise persistence and promotion rules only. They are never
runner observations or evidence for a production Level D claim.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from orchestwin.jvm_execution.profile_loader import build_jvm_profile_catalog_loader
from orchestwin.jvm_execution.validation_evidence import (
    JvmProfilePromotionStatus,
    JvmProfileValidationEvidence,
)
from orchestwin.jvm_execution.validation_evidence_persistence import (
    JVM_PROFILE_VALIDATION_EVIDENCE,
    JvmValidationEvidenceAppendStatus,
    SqlAlchemyJvmValidationEvidenceRepository,
    SqlAlchemyJvmValidationEvidenceUnitOfWork,
    canonical_jvm_validation_evidence,
    jvm_validation_evidence_to_record,
)
from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.database import DatabaseRuntime
from orchestwin.persistence.migrate import downgrade_database, upgrade_database
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus, ExecutionTarget
from orchestwin.web_execution.validation_evidence_persistence import (
    WEB_PROFILE_VALIDATION_EVIDENCE,
    web_validation_evidence_from_record,
    web_validation_evidence_to_record,
)
from src.test.python.integration.test_postgresql_web_validation_evidence import _evidence
from src.test.python.jvm_execution.test_validation_evidence import _evidence_catalog

pytestmark = pytest.mark.integration

_TARGETS = (ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN, ExecutionTarget.JVM_SCALA)


def _record(**changes: object) -> JvmProfileValidationEvidence:
    return replace(
        _evidence_catalog(ExecutionTarget.JVM_JAVA).records[0],
        evidence_id=f"test.integration.jvm.{uuid4().hex}",
        **changes,
    )


def _run(scenario: Callable[[DatabaseRuntime], Awaitable[None]]) -> None:
    async def execute() -> None:
        runtime = create_database_runtime(load_database_settings(env_file=None))
        try:
            await scenario(runtime)
        finally:
            await runtime.dispose()

    asyncio.run(execute(), loop_factory=asyncio.SelectorEventLoop)


def test_publication_rolls_back_all_new_records_when_stored_history_conflicts(
    monkeypatch, tmp_path
):
    from orchestwin.jvm_execution import validation_harvest
    from orchestwin.jvm_execution.validation_evidence import JvmProfileValidationEvidenceCatalog

    records = canonical_jvm_validation_evidence(
        tuple(record for target in _TARGETS for record in _evidence_catalog(target).records)
    )
    catalog = JvmProfileValidationEvidenceCatalog(records)
    monkeypatch.setattr(validation_harvest, "load_publication", lambda *args, **kwargs: catalog)
    conflict = replace(
        records[0], evidence_id="test.jvm.publication.conflict", environment_fingerprint="f" * 64
    )

    async def scenario(runtime):
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            await unit.evidence.append(conflict)
            await unit.commit()
        with pytest.raises(ValueError, match="STORED_CATALOG_INELIGIBLE"):
            await validation_harvest.publish_catalog(
                runtime.session_factory, root=tmp_path, expected_package_hash="a" * 64
            )
        loaded = await build_jvm_profile_catalog_loader(runtime.session_factory).load()
        assert loaded.catalog.records == (conflict,)

    _run(scenario)


def test_publication_is_atomic_and_identical_retry_is_idempotent(monkeypatch, tmp_path):
    from orchestwin.jvm_execution import validation_harvest
    from orchestwin.jvm_execution.validation_evidence import JvmProfileValidationEvidenceCatalog

    records = canonical_jvm_validation_evidence(
        tuple(record for target in _TARGETS for record in _evidence_catalog(target).records)
    )
    catalog = JvmProfileValidationEvidenceCatalog(records)
    monkeypatch.setattr(validation_harvest, "load_publication", lambda *args, **kwargs: catalog)

    async def scenario(runtime):
        first = await validation_harvest.publish_catalog(
            runtime.session_factory, root=tmp_path, expected_package_hash="a" * 64
        )
        repeated = await validation_harvest.publish_catalog(
            runtime.session_factory, root=tmp_path, expected_package_hash="a" * 64
        )
        assert first == repeated and first["database_published"] is True
        loaded = await build_jvm_profile_catalog_loader(runtime.session_factory).load()
        assert loaded.catalog.records == records and len(records) == 51
        assert all(decision.is_eligible for decision in loaded.promotion_decisions)

    _run(scenario)


def test_three_profile_catalog_is_fresh_and_survives_an_engine_restart() -> None:
    records = canonical_jvm_validation_evidence(
        tuple(record for target in _TARGETS for record in _evidence_catalog(target).records)
    )
    snapshots: dict[str, object] = {}

    async def store(runtime: DatabaseRuntime) -> None:
        loader = build_jvm_profile_catalog_loader(runtime.session_factory)
        empty = await loader.load()
        assert empty.catalog.records == ()
        assert len(empty.registry.profiles) == 3
        assert all(
            profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
            for profile in empty.registry.profiles
        )
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            for record in reversed(records):
                assert (
                    await unit.evidence.append(record) is JvmValidationEvidenceAppendStatus.APPENDED
                )
            await unit.commit()
        loaded = await loader.load()
        assert empty.catalog.records == ()
        assert loaded.catalog.records == records
        assert len(loaded.promotion_decisions) == 3
        assert all(decision.is_eligible for decision in loaded.promotion_decisions)
        assert all(
            profile.scope.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D
            for profile in loaded.registry.profiles
        )
        snapshots["registry"] = loaded.registry.to_snapshot()
        snapshots["decisions"] = loaded.promotion_decisions

    async def reload(runtime: DatabaseRuntime) -> None:
        loaded = await build_jvm_profile_catalog_loader(runtime.session_factory).load()
        assert loaded.catalog.records == records
        assert loaded.registry.to_snapshot() == snapshots["registry"]
        assert loaded.promotion_decisions == snapshots["decisions"]

    _run(store)
    _run(reload)


def test_conflicting_history_is_retained_and_blocks_only_the_affected_profile() -> None:
    records = canonical_jvm_validation_evidence(
        tuple(record for target in _TARGETS for record in _evidence_catalog(target).records)
    )
    conflicting = replace(
        records[0], evidence_id="test.jvm.environment.conflict", environment_fingerprint="f" * 64
    )

    async def scenario(runtime: DatabaseRuntime) -> None:
        loader = build_jvm_profile_catalog_loader(runtime.session_factory)
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            for record in records:
                await unit.evidence.append(record)
            await unit.commit()
        assert all(d.is_eligible for d in (await loader.load()).promotion_decisions)
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            await unit.evidence.append(conflicting)
            await unit.commit()
        loaded = await loader.load()
        assert len(loaded.catalog.records) == len(records) + 1
        assert conflicting in loaded.catalog.records
        for profile in loaded.registry.profiles:
            decision = loaded.promotion_for(profile.scope.profile_id, profile.scope.profile_version)
            assert decision is not None
            if profile.scope.profile_id == conflicting.profile_id:
                assert decision.status is JvmProfilePromotionStatus.CONFLICTING
                assert (
                    profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
                )
            else:
                assert decision.is_eligible

    _run(scenario)


@pytest.mark.parametrize(
    "offset", [timedelta(hours=18), timedelta(seconds=30, microseconds=123456)]
)
def test_original_timestamp_and_hash_survive_postgresql_normalization(offset: timedelta) -> None:
    record = _record(recorded_at=datetime(2026, 9, 13, 14, 30, tzinfo=timezone(offset)))

    async def store(runtime: DatabaseRuntime) -> None:
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.append(record) is JvmValidationEvidenceAppendStatus.APPENDED
            await unit.commit()

    async def reload(runtime: DatabaseRuntime) -> None:
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            restored = await unit.evidence.get(evidence_id=record.evidence_id)
            assert restored is not None
            assert restored.to_snapshot() == record.to_snapshot()
            assert restored.content_hash == record.content_hash
            assert restored.recorded_at.isoformat() == record.recorded_at.isoformat()

    _run(store)
    _run(reload)


def test_idempotency_conflict_and_rollback_do_not_damage_the_transaction() -> None:
    original, following, rolled_back = _record(), _record(), _record()

    async def scenario(runtime: DatabaseRuntime) -> None:
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            await unit.evidence.append(rolled_back)
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=rolled_back.evidence_id) is None
            assert (
                await unit.evidence.append(original) is JvmValidationEvidenceAppendStatus.APPENDED
            )
            await unit.commit()
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert (
                await unit.evidence.append(original)
                is JvmValidationEvidenceAppendStatus.ALREADY_PRESENT
            )
            assert (
                await unit.evidence.append(replace(original, passed=False))
                is JvmValidationEvidenceAppendStatus.EVIDENCE_CONFLICT
            )
            assert (
                await unit.evidence.append(following) is JvmValidationEvidenceAppendStatus.APPENDED
            )
            await unit.commit()
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=original.evidence_id) == original
            assert await unit.evidence.get(evidence_id=following.evidence_id) == following

    _run(scenario)


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_duplicate_insert_recovers_only_the_losing_savepoint(
    monkeypatch: pytest.MonkeyPatch, conflicting: bool
) -> None:
    first = _record()
    second = replace(first, passed=False) if conflicting else first
    original_get = SqlAlchemyJvmValidationEvidenceRepository.get

    async def scenario(runtime: DatabaseRuntime) -> None:
        ready = asyncio.Event()
        absent_reads = 0

        async def synchronized_get(self, *, evidence_id: str):
            nonlocal absent_reads
            value = await original_get(self, evidence_id=evidence_id)
            if evidence_id == first.evidence_id and value is None:
                absent_reads += 1
                if absent_reads == 2:
                    ready.set()
                await asyncio.wait_for(ready.wait(), timeout=10)
            return value

        monkeypatch.setattr(SqlAlchemyJvmValidationEvidenceRepository, "get", synchronized_get)

        async def append(candidate):
            async with runtime.session_factory() as session:
                repository = SqlAlchemyJvmValidationEvidenceRepository(session)
                status = await repository.append(candidate)
                assert await session.scalar(sa.select(sa.literal(1))) == 1
                following = _record()
                assert (
                    await repository.append(following) is JvmValidationEvidenceAppendStatus.APPENDED
                )
                await session.commit()
                return status, following

        results = await asyncio.wait_for(asyncio.gather(append(first), append(second)), timeout=20)
        assert absent_reads == 2
        loser = (
            JvmValidationEvidenceAppendStatus.EVIDENCE_CONFLICT
            if conflicting
            else JvmValidationEvidenceAppendStatus.ALREADY_PRESENT
        )
        assert {status for status, _ in results} == {
            JvmValidationEvidenceAppendStatus.APPENDED,
            loser,
        }
        winner = first if results[0][0] is JvmValidationEvidenceAppendStatus.APPENDED else second
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=first.evidence_id) == winner
            for _, following in results:
                assert await unit.evidence.get(evidence_id=following.evidence_id) == following

    _run(scenario)


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_migration_protects_evidence_from_sql_mutation(operation: str) -> None:
    record = _record()
    table = JVM_PROFILE_VALIDATION_EVIDENCE
    statements = {
        "UPDATE": sa.update(table)
        .where(table.c.evidence_id == record.evidence_id)
        .values(passed=False),
        "DELETE": sa.delete(table).where(table.c.evidence_id == record.evidence_id),
        "TRUNCATE": sa.text("TRUNCATE TABLE jvm_profile_validation_evidence"),
    }

    async def scenario(runtime: DatabaseRuntime) -> None:
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            await unit.evidence.append(record)
            await unit.commit()
        async with runtime.session_factory() as session:
            with pytest.raises(DBAPIError, match="immutable"):
                await session.execute(statements[operation])
            await session.rollback()
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=record.evidence_id) == record

    _run(scenario)


@pytest.mark.parametrize("corruption", ["numeric-boolean", "extra-key", "unknown-kind", "bad-hash"])
def test_database_rejects_invalid_shapes_and_projection_mismatches(corruption: str) -> None:
    values = jvm_validation_evidence_to_record(_record())
    if corruption == "numeric-boolean":
        values["evidence_snapshot"]["passed"] = 1
    elif corruption == "extra-key":
        values["evidence_snapshot"]["invented"] = True
    elif corruption == "unknown-kind":
        values["kind"] = values["evidence_snapshot"]["kind"] = "FAKE_OBSERVATION"
    else:
        values["runner_build_recipe_hash"] = values["evidence_snapshot"][
            "runner_build_recipe_hash"
        ] = "g" * 64

    async def scenario(runtime: DatabaseRuntime) -> None:
        async with runtime.session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(sa.insert(JVM_PROFILE_VALIDATION_EVIDENCE).values(values))
            await session.rollback()

    _run(scenario)


def test_corrupted_content_hash_fails_closed_on_repository_and_catalog_reads() -> None:
    record = _record()
    values = {**jvm_validation_evidence_to_record(record), "content_hash": "f" * 64}

    async def scenario(runtime: DatabaseRuntime) -> None:
        async with runtime.session_factory() as session:
            # SQL validates shape; the application verifies the cryptographic binding.
            await session.execute(sa.insert(JVM_PROFILE_VALIDATION_EVIDENCE).values(values))
            await session.commit()
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            with pytest.raises(ValueError, match="content_hash"):
                await unit.evidence.get(evidence_id=record.evidence_id)
        with pytest.raises(ValueError, match="content_hash"):
            await build_jvm_profile_catalog_loader(runtime.session_factory).load()

    _run(scenario)


def test_migration_round_trip_preserves_existing_web_evidence() -> None:
    settings = load_database_settings(env_file=None)
    engine = sa.create_engine(settings.sqlalchemy_url, poolclass=sa.pool.NullPool)
    web_record = _evidence(f"test.integration.jvm-migration.{uuid4().hex}")
    try:
        with engine.begin() as connection:
            connection.execute(
                sa.insert(WEB_PROFILE_VALIDATION_EVIDENCE).values(
                    web_validation_evidence_to_record(web_record)
                )
            )
        downgrade_database(settings, revision="0035_web_governed_operations")
        with engine.connect() as connection:
            assert not sa.inspect(connection).has_table("jvm_profile_validation_evidence")
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == (
                "0035_web_governed_operations"
            )
        upgrade_database(settings)
        with engine.connect() as connection:
            assert connection.scalar(sa.text("SELECT version_num FROM alembic_version")) == (
                "0037_jvm_governed_operations"
            )
            assert (
                connection.scalar(
                    sa.select(sa.func.count()).select_from(JVM_PROFILE_VALIDATION_EVIDENCE)
                )
                == 0
            )
            restored = (
                connection.execute(sa.select(WEB_PROFILE_VALIDATION_EVIDENCE)).mappings().one()
            )
            assert web_validation_evidence_from_record(restored).to_snapshot() == (
                web_record.to_snapshot()
            )
    finally:
        engine.dispose()
