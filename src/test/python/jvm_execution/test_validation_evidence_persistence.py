"""Strict JVM evidence storage, conflict isolation, and explicit transactions."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from orchestwin.jvm_execution.validation_evidence import (
    JvmProfileValidationEvidence,
    JvmProfileValidationEvidenceCatalog,
    JvmProfileValidationEvidenceKind,
)
from orchestwin.jvm_execution.validation_evidence_persistence import (
    JVM_PROFILE_VALIDATION_EVIDENCE,
    JvmValidationEvidenceAppendStatus,
    SqlAlchemyJvmValidationEvidenceRepository,
    SqlAlchemyJvmValidationEvidenceUnitOfWork,
    canonical_jvm_validation_evidence,
    jvm_validation_evidence_from_record,
    jvm_validation_evidence_to_record,
)

HASH_FIELDS = (
    "baseline_scope_hash",
    "runner_image_digest",
    "runner_build_recipe_hash",
    "toolchain_manifest_hash",
    "fixture_bundle_hash",
    "environment_fingerprint",
    "artifact_content_hash",
)


def evidence_fixture(**changes: object) -> JvmProfileValidationEvidence:
    """Synthetic storage data, never evidence from a JVM execution."""
    return replace(
        JvmProfileValidationEvidence(
            evidence_id="test.storage.contract",
            kind=JvmProfileValidationEvidenceKind.CONTRACT_TESTS,
            profile_id="jvm.java",
            profile_version="1.0.0",
            baseline_scope_hash="a" * 64,
            runner_image_digest="b" * 64,
            runner_build_recipe_hash="c" * 64,
            toolchain_manifest_hash="d" * 64,
            fixture_bundle_hash="e" * 64,
            environment_fingerprint="f" * 64,
            artifact_content_hash="1" * 64,
            reference="test:storage/artifact-1",
            recorded_at=datetime(2026, 9, 13, 14, 30, tzinfo=timezone(timedelta(hours=2))),
            passed=True,
        ),
        **changes,
    )


@pytest.mark.parametrize(
    "offset",
    [
        timedelta(),
        timedelta(hours=5, minutes=45),
        timedelta(hours=-3, minutes=-30),
        timedelta(seconds=1, microseconds=123456),
    ],
)
@pytest.mark.parametrize("passed", [True, False])
def test_round_trip_preserves_snapshot_hash_and_original_offset(offset, passed) -> None:
    evidence = evidence_fixture(
        recorded_at=datetime(2026, 9, 13, 14, 30, tzinfo=timezone(offset)), passed=passed
    )
    row = jvm_validation_evidence_to_record(evidence)

    assert row["recorded_at"].tzinfo is UTC
    assert row["recorded_at"] == evidence.recorded_at
    restored = jvm_validation_evidence_from_record(row)
    assert restored.to_snapshot() == evidence.to_snapshot()
    assert restored.content_hash == evidence.content_hash


@pytest.mark.parametrize("field", (*HASH_FIELDS, "content_hash"))
def test_every_digest_projection_is_verified(field: str) -> None:
    row = jvm_validation_evidence_to_record(evidence_fixture())
    row[field] = "9" * 64
    with pytest.raises(ValueError, match="inconsistent"):
        jvm_validation_evidence_from_record(row)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("evidence_id", "test.other"),
        ("kind", "RUNNER_IMAGE"),
        ("profile_id", "jvm.kotlin"),
        ("profile_version", "2.0.0"),
        ("reference", "test:other"),
        ("passed", 1),
        ("passed", False),
        ("recorded_at", datetime(2026, 9, 13)),
        ("recorded_at", datetime(2026, 9, 12, tzinfo=UTC)),
    ],
)
def test_non_digest_projections_are_verified_without_coercion(field, value) -> None:
    row = jvm_validation_evidence_to_record(evidence_fixture())
    row[field] = value
    with pytest.raises(ValueError):
        jvm_validation_evidence_from_record(row)


@pytest.mark.parametrize("field", HASH_FIELDS)
def test_invalid_digest_in_snapshot_is_rejected(field: str) -> None:
    row = jvm_validation_evidence_to_record(evidence_fixture())
    row["evidence_snapshot"][field] = "not-a-digest"
    with pytest.raises(ValueError):
        jvm_validation_evidence_from_record(row)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("profile_version", 1),
        ("passed", "false"),
        ("passed", 1),
        ("kind", "UNKNOWN"),
        ("reference", "not-a-uri"),
        ("evidence_id", "test:invalid"),
        ("recorded_at", "2026-09-13T14:30:00"),
        ("recorded_at", "2026-09-13 14:30:00+02:00"),
        ("recorded_at", "2026-09-13T14:30:00.000000+02:00"),
    ],
)
def test_snapshot_types_and_timestamp_representation_are_strict(field, value) -> None:
    row = jvm_validation_evidence_to_record(evidence_fixture())
    row["evidence_snapshot"][field] = value
    with pytest.raises(ValueError):
        jvm_validation_evidence_from_record(row)


@pytest.mark.parametrize("scope", ["columns", "snapshot"])
@pytest.mark.parametrize("damage", ["extra", "missing", "not-object"])
def test_storage_schema_is_exact(scope: str, damage: str) -> None:
    row = jvm_validation_evidence_to_record(evidence_fixture())
    target = row if scope == "columns" else row["evidence_snapshot"]
    if damage == "extra":
        target["unverified"] = True
    elif damage == "missing":
        del target["toolchain_manifest_hash"]
    elif scope == "snapshot":
        row["evidence_snapshot"] = []
    else:
        row = []
    with pytest.raises(ValueError):
        jvm_validation_evidence_from_record(row)


def test_catalog_order_preserves_failed_stale_and_conflicting_evidence() -> None:
    records = (
        evidence_fixture(evidence_id="test.z", profile_id="jvm.scala"),
        evidence_fixture(evidence_id="test.b", passed=False),
        evidence_fixture(evidence_id="test.a", baseline_scope_hash="9" * 64),
        evidence_fixture(evidence_id="test.c", runner_build_recipe_hash="9" * 64),
        evidence_fixture(evidence_id="test.v", profile_version="2.0.0"),
        evidence_fixture(evidence_id="test.d", kind=JvmProfileValidationEvidenceKind.RUN_REPORT),
    )
    ordered = canonical_jvm_validation_evidence(records)
    assert tuple(item.evidence_id for item in ordered) == (
        "test.a",
        "test.b",
        "test.c",
        "test.d",
        "test.v",
        "test.z",
    )
    assert JvmProfileValidationEvidenceCatalog(ordered).records == ordered
    assert set(ordered) == set(records)
    with pytest.raises(ValueError, match="unique"):
        canonical_jvm_validation_evidence((records[0], replace(records[0], passed=False)))


class MappingResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def one_or_none(self):
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None

    def __iter__(self):
        return iter(self.rows)


class Session:
    """A savepoint-sensitive double; real SQL races belong in PostgreSQL tests."""

    def __init__(self, reads=(), *, insert_error=None):
        self.reads = list(reads)
        self.insert_error = insert_error
        self.events = []
        self.in_savepoint = False

    async def execute(self, statement):
        if statement.is_select:
            assert not self.in_savepoint
            self.events.append("read")
            return MappingResult(self.reads.pop(0))
        assert statement.is_insert and self.in_savepoint
        self.events.append("insert")
        if self.insert_error is not None:
            raise self.insert_error
        return None

    def begin_nested(self):
        session = self

        class Savepoint:
            async def __aenter__(self):
                session.events.append("savepoint")
                session.in_savepoint = True

            async def __aexit__(self, exc_type, exc_value, traceback):
                session.in_savepoint = False
                session.events.append("savepoint_rollback" if exc_type else "savepoint_release")

        return Savepoint()

    async def commit(self):
        self.events.append("commit")

    async def rollback(self):
        self.events.append("rollback")

    async def close(self):
        self.events.append("close")


def integrity_error(*, sqlstate="23505", constraint="pk_jvm_profile_validation_evidence"):
    original = Exception("test-only database constraint failure")
    original.sqlstate = sqlstate
    original.diag = SimpleNamespace(constraint_name=constraint)
    return IntegrityError("INSERT", {}, original)


@pytest.mark.parametrize("conflicting", [False, True])
@pytest.mark.parametrize("racing", [False, True])
def test_existing_id_is_idempotent_or_conflicting_and_race_preserves_transaction(
    conflicting: bool, racing: bool
) -> None:
    candidate = evidence_fixture()
    stored = replace(candidate, passed=False) if conflicting else candidate
    row = jvm_validation_evidence_to_record(stored)
    session = Session(
        [[], [row]] if racing else [[row]], insert_error=integrity_error() if racing else None
    )
    result = asyncio.run(SqlAlchemyJvmValidationEvidenceRepository(session).append(candidate))
    assert result is (
        JvmValidationEvidenceAppendStatus.EVIDENCE_CONFLICT
        if conflicting
        else JvmValidationEvidenceAppendStatus.ALREADY_PRESENT
    )
    assert session.events == (
        ["read", "savepoint", "insert", "savepoint_rollback", "read"] if racing else ["read"]
    )
    assert "rollback" not in session.events


@pytest.mark.parametrize(
    ("sqlstate", "constraint"),
    [
        ("23514", "ck_jvm_profile_validation_evidence_digests"),
        ("23505", "unrelated_unique_constraint"),
        (None, None),
    ],
)
def test_unrelated_integrity_errors_propagate_without_becoming_idempotency(
    sqlstate, constraint
) -> None:
    error = integrity_error(sqlstate=sqlstate, constraint=constraint)
    session = Session(
        [[], [jvm_validation_evidence_to_record(evidence_fixture())]], insert_error=error
    )
    with pytest.raises(IntegrityError) as caught:
        asyncio.run(SqlAlchemyJvmValidationEvidenceRepository(session).append(evidence_fixture()))
    assert caught.value is error
    assert session.events[-1] == "savepoint_rollback"
    assert len(session.reads) == 1


def test_duplicate_without_visible_matching_id_preserves_original_error() -> None:
    error = integrity_error()
    session = Session([[], []], insert_error=error)
    with pytest.raises(IntegrityError) as caught:
        asyncio.run(SqlAlchemyJvmValidationEvidenceRepository(session).append(evidence_fixture()))
    assert caught.value is error


def test_repository_append_and_history_verify_and_canonicalize_all_rows() -> None:
    first = evidence_fixture(evidence_id="test.a", passed=False)
    second = evidence_fixture(evidence_id="test.b")
    session = Session(
        [[], [jvm_validation_evidence_to_record(second), jvm_validation_evidence_to_record(first)]]
    )

    async def scenario():
        repository = SqlAlchemyJvmValidationEvidenceRepository(session)
        assert await repository.append(first) is JvmValidationEvidenceAppendStatus.APPENDED
        assert await repository.history() == (first, second)

    asyncio.run(scenario())
    assert session.events == ["read", "savepoint", "insert", "savepoint_release", "read"]
    corrupted = deepcopy(jvm_validation_evidence_to_record(first))
    corrupted["content_hash"] = "9" * 64
    with pytest.raises(ValueError):
        asyncio.run(SqlAlchemyJvmValidationEvidenceRepository(Session([[corrupted]])).history())


@pytest.mark.parametrize("commit", [False, True])
def test_unit_of_work_has_explicit_commit_and_always_closes(commit: bool) -> None:
    session = Session()
    unit = SqlAlchemyJvmValidationEvidenceUnitOfWork(lambda: session)

    async def scenario():
        with pytest.raises(RuntimeError, match="not open"):
            await unit.commit()
        async with unit as opened:
            assert opened is unit
            if commit:
                await unit.commit()
        with pytest.raises(RuntimeError, match="not open"):
            await unit.rollback()

    asyncio.run(scenario())
    assert session.events == (["commit"] if commit else []) + ["rollback", "close"]


def test_unit_of_work_rolls_back_and_closes_on_exception() -> None:
    session = Session()

    async def scenario():
        async with SqlAlchemyJvmValidationEvidenceUnitOfWork(lambda: session):
            raise LookupError("test-only failure")

    with pytest.raises(LookupError):
        asyncio.run(scenario())
    assert session.events == ["rollback", "close"]


def test_metadata_primary_key_matches_the_conflict_constraint() -> None:
    assert JVM_PROFILE_VALIDATION_EVIDENCE.primary_key.name == "pk_jvm_profile_validation_evidence"
