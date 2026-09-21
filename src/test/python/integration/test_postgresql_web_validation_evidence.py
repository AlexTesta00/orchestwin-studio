"""PostgreSQL preserves Web validation observations without granting capability."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError

from orchestwin.persistence import create_database_runtime, load_database_settings
from orchestwin.persistence.database import DatabaseRuntime
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
)
from orchestwin.web_execution.validation_evidence import (
    WebProfileValidationEvidence,
    WebProfileValidationEvidenceCatalog,
    WebProfileValidationEvidenceKind,
)
from orchestwin.web_execution.validation_evidence_persistence import (
    WEB_PROFILE_VALIDATION_EVIDENCE,
    SqlAlchemyWebValidationEvidenceRepository,
    SqlAlchemyWebValidationEvidenceUnitOfWork,
    WebValidationEvidenceAppendStatus,
    web_validation_evidence_to_record,
)

pytestmark = pytest.mark.integration


def _evidence(evidence_id: str, **changes: object) -> WebProfileValidationEvidence:
    """Synthetic test data only; random IDs isolate append-only test histories."""
    return replace(
        WebProfileValidationEvidence(
            evidence_id=evidence_id,
            kind=WebProfileValidationEvidenceKind.CONTRACT_TESTS,
            profile_id="web.static",
            profile_version="1.0.0",
            baseline_scope_hash="a" * 64,
            language_configuration=None,
            execution_runner_image_digest="b" * 64,
            browser_runner_image_digest="c" * 64,
            artifact_content_hash="d" * 64,
            reference="test.integration.web-validation.artifact",
            recorded_at=datetime(2026, 9, 12, 14, 30, tzinfo=timezone(timedelta(hours=2))),
            passed=True,
        ),
        **changes,
    )


def _prefix() -> str:
    return f"test.integration.web-validation.{uuid4().hex}"


def _run(scenario: Callable[[DatabaseRuntime], Awaitable[None]]) -> None:
    async def isolated_runtime() -> None:
        runtime = create_database_runtime(load_database_settings(env_file=None))
        try:
            await scenario(runtime)
        finally:
            await runtime.dispose()

    asyncio.run(isolated_runtime(), loop_factory=asyncio.SelectorEventLoop)


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize(
    "offset",
    [timedelta(hours=2), timedelta(hours=18), timedelta(seconds=30, microseconds=123456)],
)
def test_append_reload_and_new_runtime_preserve_exact_snapshot_and_timestamp(
    configured: bool,
    offset: timedelta,
) -> None:
    evidence = _evidence(
        f"{_prefix()}.original",
        recorded_at=datetime(2026, 9, 12, 14, 30, tzinfo=timezone(offset)),
    )
    if configured:
        evidence = replace(
            evidence,
            kind=WebProfileValidationEvidenceKind.VALID_FIXTURE_RUN,
            language_configuration=WebLanguageConfiguration(
                frontend=WebImplementationLanguage.STATIC_ASSETS, backend=None
            ),
        )

    async def append(runtime: DatabaseRuntime) -> None:
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=evidence.evidence_id) is None
            assert (
                await unit.evidence.append(evidence) is WebValidationEvidenceAppendStatus.APPENDED
            )
            await unit.commit()
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=evidence.evidence_id) == evidence

    async def reload(runtime: DatabaseRuntime) -> None:
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            restored = await unit.evidence.get(evidence_id=evidence.evidence_id)
            assert restored is not None
            assert restored.to_snapshot() == evidence.to_snapshot()
            assert restored.content_hash == evidence.content_hash
            assert restored.recorded_at.isoformat() == evidence.recorded_at.isoformat()
            assert evidence in await unit.evidence.history()

    _run(append)
    # Dispose the first engine and recreate sessions, connections and event loop.
    _run(reload)


def test_idempotency_and_id_conflict_leave_transaction_usable() -> None:
    prefix = _prefix()
    original = _evidence(f"{prefix}.original")
    following = _evidence(f"{prefix}.following")

    async def scenario(runtime: DatabaseRuntime) -> None:
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert (
                await unit.evidence.append(original) is WebValidationEvidenceAppendStatus.APPENDED
            )
            await unit.commit()
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert (
                await unit.evidence.append(original)
                is WebValidationEvidenceAppendStatus.ALREADY_PRESENT
            )
            assert (
                await unit.evidence.append(replace(original, passed=False))
                is WebValidationEvidenceAppendStatus.EVIDENCE_CONFLICT
            )
            assert (
                await unit.evidence.append(following) is WebValidationEvidenceAppendStatus.APPENDED
            )
            await unit.commit()
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=original.evidence_id) == original
            assert await unit.evidence.get(evidence_id=following.evidence_id) == following

    _run(scenario)


@pytest.mark.parametrize("exit_mode", ["uncommitted", "rollback", "exception"])
def test_uncommitted_or_rolled_back_evidence_does_not_survive(exit_mode: str) -> None:
    evidence = _evidence(f"{_prefix()}.rollback")

    class AbortObservation(Exception):
        pass

    async def scenario(runtime: DatabaseRuntime) -> None:
        try:
            async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
                assert (
                    await unit.evidence.append(evidence)
                    is WebValidationEvidenceAppendStatus.APPENDED
                )
                if exit_mode == "rollback":
                    await unit.rollback()
                elif exit_mode == "exception":
                    raise AbortObservation
        except AbortObservation:
            assert exit_mode == "exception"
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=evidence.evidence_id) is None

    _run(scenario)


def test_history_is_canonical_and_retains_failed_stale_and_conflicting_observations() -> None:
    prefix = _prefix()
    records = (
        _evidence(f"{prefix}.z", profile_id="web.vue"),
        _evidence(f"{prefix}.v2", profile_version="2.0.0"),
        _evidence(f"{prefix}.c", execution_runner_image_digest="f" * 64),
        _evidence(f"{prefix}.b", passed=False),
        _evidence(f"{prefix}.a", baseline_scope_hash="f" * 64),
        _evidence(
            f"{prefix}.browser-ts",
            kind=WebProfileValidationEvidenceKind.BROWSER_EVIDENCE,
            language_configuration=WebLanguageConfiguration(
                frontend=WebImplementationLanguage.TYPESCRIPT, backend=None
            ),
        ),
        _evidence(
            f"{prefix}.browser-js",
            kind=WebProfileValidationEvidenceKind.BROWSER_EVIDENCE,
            language_configuration=WebLanguageConfiguration(
                frontend=WebImplementationLanguage.JAVASCRIPT, backend=None
            ),
        ),
    )
    expected = (records[6], records[5], records[4], records[3], records[2], records[1], records[0])

    async def scenario(runtime: DatabaseRuntime) -> None:
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            for record in records:
                assert (
                    await unit.evidence.append(record) is WebValidationEvidenceAppendStatus.APPENDED
                )
            await unit.commit()
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            history = tuple(
                record
                for record in await unit.evidence.history()
                if record.evidence_id.startswith(f"{prefix}.")
            )
            assert history == expected
            assert WebProfileValidationEvidenceCatalog(history).records == expected
            assert {record.content_hash for record in history} == {
                record.content_hash for record in records
            }

    _run(scenario)


@pytest.mark.parametrize("conflicting", [False, True])
def test_concurrent_append_uses_savepoint_and_preserves_both_sessions(
    monkeypatch: pytest.MonkeyPatch, conflicting: bool
) -> None:
    prefix = _prefix()
    first = _evidence(f"{prefix}.shared")
    second = replace(first, passed=False) if conflicting else first
    original_get = SqlAlchemyWebValidationEvidenceRepository.get

    async def scenario(runtime: DatabaseRuntime) -> None:
        both_read_absent = asyncio.Event()
        absent_reads = 0

        async def synchronized_get(
            self: SqlAlchemyWebValidationEvidenceRepository, *, evidence_id: str
        ) -> WebProfileValidationEvidence | None:
            nonlocal absent_reads
            observed = await original_get(self, evidence_id=evidence_id)
            if evidence_id == first.evidence_id and observed is None:
                absent_reads += 1
                if absent_reads == 2:
                    both_read_absent.set()
                await asyncio.wait_for(both_read_absent.wait(), timeout=10)
            return observed

        monkeypatch.setattr(SqlAlchemyWebValidationEvidenceRepository, "get", synchronized_get)

        async def append(
            candidate: WebProfileValidationEvidence, suffix: str
        ) -> WebValidationEvidenceAppendStatus:
            async with runtime.session_factory() as session:
                repository = SqlAlchemyWebValidationEvidenceRepository(session)
                status = await repository.append(candidate)
                assert await session.scalar(sa.select(sa.literal(1))) == 1
                assert (
                    await repository.append(_evidence(f"{prefix}.{suffix}"))
                    is WebValidationEvidenceAppendStatus.APPENDED
                )
                # Each worker commits independently, releasing a waiting unique-key insert.
                await session.commit()
                return status

        statuses = await asyncio.wait_for(
            asyncio.gather(append(first, "worker1"), append(second, "worker2")), timeout=20
        )
        assert absent_reads == 2
        expected_loser = (
            WebValidationEvidenceAppendStatus.EVIDENCE_CONFLICT
            if conflicting
            else WebValidationEvidenceAppendStatus.ALREADY_PRESENT
        )
        assert statuses.count(WebValidationEvidenceAppendStatus.APPENDED) == 1
        assert statuses.count(expected_loser) == 1
        winner = first if statuses[0] is WebValidationEvidenceAppendStatus.APPENDED else second
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=first.evidence_id) == winner
            for suffix in ("worker1", "worker2"):
                assert await unit.evidence.get(evidence_id=f"{prefix}.{suffix}") is not None

    _run(scenario)


@pytest.mark.parametrize("operation", ["UPDATE", "DELETE", "TRUNCATE"])
def test_sql_mutation_of_append_only_evidence_is_rejected(operation: str) -> None:
    evidence = _evidence(f"{_prefix()}.immutable")
    table = WEB_PROFILE_VALIDATION_EVIDENCE
    statements = {
        "UPDATE": sa.update(table)
        .where(table.c.evidence_id == evidence.evidence_id)
        .values(passed=False),
        "DELETE": sa.delete(table).where(table.c.evidence_id == evidence.evidence_id),
        "TRUNCATE": sa.text("TRUNCATE TABLE web_profile_validation_evidence"),
    }

    async def scenario(runtime: DatabaseRuntime) -> None:
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert (
                await unit.evidence.append(evidence) is WebValidationEvidenceAppendStatus.APPENDED
            )
            await unit.commit()
        async with runtime.session_factory() as session:
            try:
                with pytest.raises(DBAPIError, match=r"append.only|immutable"):
                    await session.execute(statements[operation])
            finally:
                # Even a regression allowing TRUNCATE must never commit the mutation.
                await session.rollback()
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=evidence.evidence_id) == evidence

    _run(scenario)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("baseline_scope_hash", "not-a-digest"),
        ("execution_runner_image_digest", "B" * 64),
        ("browser_runner_image_digest", "short"),
        ("artifact_content_hash", "g" * 64),
        ("content_hash", "bad"),
        ("reference", "../unsafe path"),
        ("language_configuration", {"frontend": "STATIC_ASSETS", "backend": None}),
        ("language_configuration", []),
        ("kind", "VALID_FIXTURE_RUN"),
    ],
)
def test_sql_insert_rejects_invalid_digest_reference_and_configuration(
    field: str, invalid: object
) -> None:
    evidence = _evidence(f"{_prefix()}.invalid")
    values = web_validation_evidence_to_record(evidence)
    values[field] = invalid
    if field != "content_hash":
        # Keep projections consistent so domain constraints must reject the value.
        values["evidence_snapshot"][field] = invalid

    async def scenario(runtime: DatabaseRuntime) -> None:
        async with runtime.session_factory() as session:
            try:
                with pytest.raises(IntegrityError):
                    await session.execute(sa.insert(WEB_PROFILE_VALIDATION_EVIDENCE).values(values))
            finally:
                await session.rollback()
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=evidence.evidence_id) is None

    _run(scenario)


@pytest.mark.parametrize(
    "configuration",
    [
        {"frontend": "STATIC_ASSETS"},
        {"frontend": 1, "backend": None},
        {"frontend": None, "backend": None},
        {"frontend": "UNKNOWN", "backend": None},
        {"frontend": "STATIC_ASSETS", "backend": None, "hidden": True},
    ],
)
def test_sql_insert_requires_exact_and_supported_language_configuration(
    configuration: dict[str, object],
) -> None:
    evidence = _evidence(
        f"{_prefix()}.invalid-configuration",
        kind=WebProfileValidationEvidenceKind.VALID_FIXTURE_RUN,
        language_configuration=WebLanguageConfiguration(
            frontend=WebImplementationLanguage.STATIC_ASSETS, backend=None
        ),
    )
    values = web_validation_evidence_to_record(evidence)
    values["language_configuration"] = configuration
    values["evidence_snapshot"]["language_configuration"] = configuration

    async def scenario(runtime: DatabaseRuntime) -> None:
        async with runtime.session_factory() as session:
            try:
                with pytest.raises(IntegrityError):
                    await session.execute(sa.insert(WEB_PROFILE_VALIDATION_EVIDENCE).values(values))
            finally:
                await session.rollback()

    _run(scenario)


@pytest.mark.parametrize(
    ("field", "invalid"),
    [
        ("content_hash", "e" * 64),
        ("recorded_at", datetime(2026, 9, 1, tzinfo=UTC)),
    ],
)
def test_sql_record_with_tampered_identity_fails_closed_on_get_and_history(
    field: str,
    invalid: object,
) -> None:
    evidence = _evidence(f"{_prefix()}.corrupt")
    values = web_validation_evidence_to_record(evidence)
    values[field] = invalid

    async def scenario(runtime: DatabaseRuntime) -> None:
        async with runtime.session_factory() as session:
            try:
                await session.execute(sa.insert(WEB_PROFILE_VALIDATION_EVIDENCE).values(values))
                repository = SqlAlchemyWebValidationEvidenceRepository(session)
                with pytest.raises(ValueError, match=field):
                    await repository.get(evidence_id=evidence.evidence_id)
                with pytest.raises(ValueError, match=field):
                    await repository.history()
            finally:
                # Corruption is tested inside a rollback-only transaction.
                await session.rollback()
        async with SqlAlchemyWebValidationEvidenceUnitOfWork(runtime.session_factory) as unit:
            assert await unit.evidence.get(evidence_id=evidence.evidence_id) is None

    _run(scenario)
