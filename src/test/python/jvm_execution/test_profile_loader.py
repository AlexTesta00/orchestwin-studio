"""Synthetic, test-only evidence checks JVM catalog loading, never real validation."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, replace
from types import TracebackType
from typing import Self

import pytest

from orchestwin.jvm_execution.profile_loader import (
    JvmProfileCatalogLoader,
    LoadedJvmProfileCatalog,
    build_jvm_profile_catalog_loader,
)
from orchestwin.jvm_execution.profile_registry import create_sprint09_jvm_profile_registry
from orchestwin.jvm_execution.validation_evidence import (
    JvmProfilePromotionStatus,
    JvmProfileValidationEvidence,
    JvmProfileValidationEvidenceKind,
)
from orchestwin.jvm_execution.validation_evidence_persistence import (
    canonical_jvm_validation_evidence,
)
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus, ExecutionTarget

from .test_validation_evidence import _evidence_catalog

_IDENTITY_FIELDS = (
    "runner_image_digest",
    "runner_build_recipe_hash",
    "toolchain_manifest_hash",
    "fixture_bundle_hash",
    "environment_fingerprint",
)


class EvidenceHistory:
    def __init__(self, records: tuple[JvmProfileValidationEvidence, ...]) -> None:
        self.records = records
        self.read_count = 0
        self.failure: Exception | None = None

    async def history(self) -> tuple[JvmProfileValidationEvidence, ...]:
        self.read_count += 1
        if self.failure is not None:
            raise self.failure
        return self.records


class ReadOnlyUnitOfWork:
    def __init__(self, evidence: EvidenceHistory) -> None:
        self.evidence = evidence
        self.closed = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.closed = True

    async def commit(self) -> None:
        pytest.fail("Loading JVM profile evidence must never commit a write transaction")


class UnitOfWorkFactory:
    def __init__(self, records: tuple[JvmProfileValidationEvidence, ...]) -> None:
        self.evidence = EvidenceHistory(records)
        self.units: list[ReadOnlyUnitOfWork] = []

    def __call__(self) -> ReadOnlyUnitOfWork:
        unit = ReadOnlyUnitOfWork(self.evidence)
        self.units.append(unit)
        return unit


def _load(records: tuple[JvmProfileValidationEvidence, ...]) -> LoadedJvmProfileCatalog:
    factory = UnitOfWorkFactory(records)
    loaded = asyncio.run(JvmProfileCatalogLoader(unit_of_work_factory=factory).load())
    assert len(factory.units) == 1
    assert factory.evidence.read_count == 1
    assert factory.units[0].closed
    return loaded


def test_empty_catalog_keeps_three_profiles_level_c_with_inspectable_reasons() -> None:
    loaded = _load(())
    assert loaded.catalog.records == ()
    assert loaded.registry.to_snapshot() == create_sprint09_jvm_profile_registry().to_snapshot()
    assert len(loaded.registry.profiles) == len(loaded.promotion_decisions) == 3
    assert all(
        profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        for profile in loaded.registry.profiles
    )
    assert all(
        decision.status is JvmProfilePromotionStatus.INCOMPLETE
        and decision.missing_requirements == ("evidence:any",)
        for decision in loaded.promotion_decisions
    )


@pytest.mark.parametrize(
    "target", [ExecutionTarget.JVM_JAVA, ExecutionTarget.JVM_KOTLIN, ExecutionTarget.JVM_SCALA]
)
def test_complete_synthetic_evidence_promotes_only_its_exact_profile(
    target: ExecutionTarget,
) -> None:
    catalog = _evidence_catalog(target)
    loaded = _load(catalog.records)
    assert loaded.catalog == catalog
    for profile in loaded.registry.profiles:
        scope = profile.scope
        decision = loaded.promotion_for(scope.profile_id, scope.profile_version)
        assert decision is not None
        eligible = scope.target is target
        assert decision.is_eligible == eligible
        assert scope.capability_status is (
            ExecutionCapabilityStatus.VALIDATED_LEVEL_D
            if eligible
            else ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        )
        assert scope.validation_evidence_refs == decision.evidence_refs
        if eligible:
            assert set(decision.evidence_refs) == {record.reference for record in catalog.records}
            for identity_field in _IDENTITY_FIELDS:
                assert getattr(decision, identity_field) == getattr(
                    catalog.records[0], identity_field
                )


def test_complete_synthetic_evidence_promotes_all_three_from_the_same_catalog() -> None:
    records = canonical_jvm_validation_evidence(
        tuple(
            record
            for profile in create_sprint09_jvm_profile_registry().profiles
            for record in _evidence_catalog(profile.scope.target).records
        )
    )
    loaded = _load(records)
    assert loaded.catalog.records == records
    assert len(loaded.promotion_decisions) == 3
    assert all(decision.is_eligible for decision in loaded.promotion_decisions)
    assert all(
        profile.scope.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D
        for profile in loaded.registry.profiles
    )


@pytest.mark.parametrize(
    ("condition", "expected_status"),
    [
        ("partial", JvmProfilePromotionStatus.INCOMPLETE),
        ("stale", JvmProfilePromotionStatus.STALE),
        ("failed", JvmProfilePromotionStatus.FAILED),
        *((field, JvmProfilePromotionStatus.CONFLICTING) for field in _IDENTITY_FIELDS),
        ("missing-repair", JvmProfilePromotionStatus.INCOMPLETE),
        ("missing-reproducibility", JvmProfilePromotionStatus.INCOMPLETE),
        ("duplicate-reproducibility", JvmProfilePromotionStatus.INCOMPLETE),
        ("wrong-version", JvmProfilePromotionStatus.INCOMPLETE),
        ("unknown-profile", JvmProfilePromotionStatus.INCOMPLETE),
    ],
)
def test_ineligible_history_is_kept_and_explained_without_promotion(
    condition: str,
    expected_status: JvmProfilePromotionStatus,
) -> None:
    records = _evidence_catalog(ExecutionTarget.JVM_KOTLIN).records
    if condition == "partial":
        records = records[:1]
    elif condition == "stale":
        records = (replace(records[0], baseline_scope_hash="1" * 64), *records[1:])
    elif condition == "failed":
        records = (replace(records[0], passed=False), *records[1:])
    elif condition in _IDENTITY_FIELDS:
        records = (replace(records[0], **{condition: "1" * 64}), *records[1:])
    elif condition == "missing-repair":
        records = tuple(
            record
            for record in records
            if record.kind is not JvmProfileValidationEvidenceKind.REPAIR_RERUN
        )
    elif condition == "missing-reproducibility":
        records = _evidence_catalog(ExecutionTarget.JVM_KOTLIN, reproducibility_records=1).records
    elif condition == "duplicate-reproducibility":
        records = _evidence_catalog(
            ExecutionTarget.JVM_KOTLIN, duplicate_reproducibility_artifact=True
        ).records
    elif condition == "wrong-version":
        records = tuple(replace(record, profile_version="2.0.0") for record in records)
    elif condition == "unknown-profile":
        records = tuple(replace(record, profile_id="jvm.future") for record in records)
    loaded = _load(records)
    assert loaded.catalog.records == records
    decision = loaded.promotion_for("jvm.kotlin-gradle", "1.0.0")
    assert decision is not None
    assert decision.status is expected_status
    assert decision.missing_requirements or decision.issue_messages
    assert all(getattr(decision, identity_field) is None for identity_field in _IDENTITY_FIELDS)
    assert all(
        profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        for profile in loaded.registry.profiles
    )


@pytest.mark.parametrize(
    ("mutation", "expected_status"),
    [
        ({"passed": False}, JvmProfilePromotionStatus.FAILED),
        ({"baseline_scope_hash": "1" * 64}, JvmProfilePromotionStatus.STALE),
        ({"fixture_bundle_hash": "1" * 64}, JvmProfilePromotionStatus.CONFLICTING),
    ],
)
def test_fresh_load_keeps_later_adverse_evidence_without_mutating_earlier_snapshot(
    mutation: dict[str, object], expected_status: JvmProfilePromotionStatus
) -> None:
    records = _evidence_catalog(ExecutionTarget.JVM_JAVA).records
    factory = UnitOfWorkFactory(records)
    loader = JvmProfileCatalogLoader(unit_of_work_factory=factory)
    first = asyncio.run(loader.load())
    adverse_record = replace(records[0], evidence_id="evidence.later.adverse", **mutation)
    factory.evidence.records = canonical_jvm_validation_evidence((*records, adverse_record))
    second = asyncio.run(loader.load())
    first_decision = first.promotion_for("jvm.java-gradle", "1.0.0")
    second_decision = second.promotion_for("jvm.java-gradle", "1.0.0")
    assert first_decision is not None and first_decision.is_eligible
    assert second_decision is not None and second_decision.status is expected_status
    assert first.catalog.records == records
    assert second.catalog.records == factory.evidence.records
    assert adverse_record in second.catalog.records
    assert factory.evidence.read_count == 2
    assert len(factory.units) == 2
    assert all(unit.closed for unit in factory.units)
    assert first.registry.content_hash != second.registry.content_hash
    with pytest.raises(FrozenInstanceError):
        first.catalog = second.catalog


@pytest.mark.parametrize(
    "failure", [ValueError("corrupt JVM evidence hash"), OSError("database unavailable")]
)
def test_read_failure_propagates_after_previous_success_and_closes_unit(failure: Exception) -> None:
    factory = UnitOfWorkFactory(_evidence_catalog(ExecutionTarget.JVM_JAVA).records)
    loader = JvmProfileCatalogLoader(unit_of_work_factory=factory)
    asyncio.run(loader.load())
    factory.evidence.failure = failure
    with pytest.raises(type(failure), match=str(failure)):
        asyncio.run(loader.load())
    assert factory.evidence.read_count == 2
    assert len(factory.units) == 2
    assert all(unit.closed for unit in factory.units)


def test_cancelled_history_read_closes_unit_without_returning_cached_capability() -> None:
    async def scenario() -> None:
        started = asyncio.Event()

        class BlockingEvidenceHistory(EvidenceHistory):
            async def history(self) -> tuple[JvmProfileValidationEvidence, ...]:
                started.set()
                await asyncio.Future()
                pytest.fail("A cancelled read must not return records")

        factory = UnitOfWorkFactory(())
        factory.evidence = BlockingEvidenceHistory(())
        task = asyncio.create_task(JvmProfileCatalogLoader(unit_of_work_factory=factory).load())
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert len(factory.units) == 1
        assert factory.units[0].closed

    asyncio.run(scenario())


@pytest.mark.parametrize("duplicate", [False, True])
def test_noncanonical_or_duplicate_history_fails_after_unit_closes(duplicate: bool) -> None:
    records = _evidence_catalog(ExecutionTarget.JVM_JAVA).records
    records = (records[0], records[0]) if duplicate else tuple(reversed(records))
    factory = UnitOfWorkFactory(records)
    with pytest.raises(ValueError):
        asyncio.run(JvmProfileCatalogLoader(unit_of_work_factory=factory).load())
    assert len(factory.units) == 1
    assert factory.units[0].closed


def test_diagnostic_lookup_is_exact_and_loaded_result_is_deterministic() -> None:
    records = _evidence_catalog(ExecutionTarget.JVM_SCALA).records
    first, second = _load(records), _load(records)
    assert first.catalog == second.catalog
    assert first.registry.content_hash == second.registry.content_hash
    assert first.promotion_decisions == second.promotion_decisions
    assert first.promotion_for("jvm.scala-sbt", "2.0.0") is None
    assert first.promotion_for("jvm.unknown", "1.0.0") is None


def test_production_builder_does_not_open_database_connections_until_load() -> None:
    def session_factory():
        pytest.fail("Constructing a JVM loader must not open a database connection")

    assert isinstance(build_jvm_profile_catalog_loader(session_factory), JvmProfileCatalogLoader)
