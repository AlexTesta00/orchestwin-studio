"""Durable catalog loading must keep capability and diagnostics consistent."""

from __future__ import annotations

import asyncio
from dataclasses import FrozenInstanceError, replace
from types import TracebackType
from typing import Self

import pytest

from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus, ExecutionTarget
from orchestwin.web_execution.profile_loader import (
    WebProfileCatalogLoader,
    build_web_profile_catalog_loader,
)
from orchestwin.web_execution.profile_registry import create_sprint08_web_profile_registry
from orchestwin.web_execution.validation_evidence import (
    WebProfilePromotionStatus,
    WebProfileValidationEvidence,
    WebProfileValidationEvidenceKind,
)
from orchestwin.web_execution.validation_evidence_persistence import (
    canonical_web_validation_evidence,
)
from src.test.python.web_execution.test_validation_evidence import evidence_catalog


class EvidenceHistory:
    def __init__(self, records: tuple[WebProfileValidationEvidence, ...]) -> None:
        self.records = records
        self.read_count = 0
        self.failure: Exception | None = None

    async def history(self) -> tuple[WebProfileValidationEvidence, ...]:
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
        pytest.fail("Loading profile evidence must never commit a write transaction")


class UnitOfWorkFactory:
    def __init__(self, records: tuple[WebProfileValidationEvidence, ...]) -> None:
        self.evidence = EvidenceHistory(records)
        self.units: list[ReadOnlyUnitOfWork] = []

    def __call__(self) -> ReadOnlyUnitOfWork:
        unit = ReadOnlyUnitOfWork(self.evidence)
        self.units.append(unit)
        return unit


def _load(records: tuple[WebProfileValidationEvidence, ...]):
    factory = UnitOfWorkFactory(records)
    loaded = asyncio.run(WebProfileCatalogLoader(unit_of_work_factory=factory).load())
    assert len(factory.units) == 1
    assert factory.evidence.read_count == 1
    assert factory.units[0].closed
    return loaded


def test_empty_catalog_keeps_all_profiles_level_c_with_inspectable_reasons() -> None:
    loaded = _load(())
    assert loaded.catalog.records == ()
    assert loaded.registry.to_snapshot() == create_sprint08_web_profile_registry().to_snapshot()
    assert len(loaded.promotion_decisions) == 5
    assert all(
        decision.status is WebProfilePromotionStatus.INCOMPLETE
        and decision.missing_requirements == ("evidence:any",)
        for decision in loaded.promotion_decisions
    )


@pytest.mark.parametrize(
    "target",
    [
        ExecutionTarget.WEB_STATIC,
        ExecutionTarget.WEB_VUE,
        ExecutionTarget.WEB_NODE_EXPRESS,
        ExecutionTarget.WEB_PHP,
        ExecutionTarget.WEB_VUE_NODE,
    ],
)
def test_complete_evidence_promotes_only_its_exact_profile(target: ExecutionTarget) -> None:
    catalog = evidence_catalog(target)
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
            assert (
                decision.execution_runner_image_digest
                == catalog.records[0].execution_runner_image_digest
            )
            assert (
                decision.browser_runner_image_digest
                == catalog.records[0].browser_runner_image_digest
            )


def test_complete_evidence_for_all_profiles_promotes_all_from_the_same_catalog() -> None:
    records = canonical_web_validation_evidence(
        tuple(
            record
            for profile in create_sprint08_web_profile_registry().profiles
            for record in evidence_catalog(profile.scope.target).records
        )
    )
    loaded = _load(records)
    assert loaded.catalog.records == records
    assert len(loaded.promotion_decisions) == 5
    assert all(decision.is_eligible for decision in loaded.promotion_decisions)
    assert all(
        profile.scope.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D
        for profile in loaded.registry.profiles
    )


@pytest.mark.parametrize(
    ("condition", "expected_status"),
    [
        ("partial", WebProfilePromotionStatus.INCOMPLETE),
        ("stale", WebProfilePromotionStatus.STALE),
        ("failed", WebProfilePromotionStatus.FAILED),
        ("execution-conflict", WebProfilePromotionStatus.CONFLICTING),
        ("browser-conflict", WebProfilePromotionStatus.CONFLICTING),
        ("missing-browser", WebProfilePromotionStatus.INCOMPLETE),
        ("missing-browser-runner", WebProfilePromotionStatus.INCOMPLETE),
        ("wrong-version", WebProfilePromotionStatus.INCOMPLETE),
        ("unknown-profile", WebProfilePromotionStatus.INCOMPLETE),
        ("missing-variant", WebProfilePromotionStatus.INCOMPLETE),
    ],
)
def test_ineligible_records_are_kept_and_explained_without_promotion(
    condition: str,
    expected_status: WebProfilePromotionStatus,
) -> None:
    records = evidence_catalog(ExecutionTarget.WEB_VUE).records
    if condition == "partial":
        records = records[:1]
    elif condition == "stale":
        records = (replace(records[0], baseline_scope_hash="1" * 64), *records[1:])
    elif condition == "failed":
        records = (replace(records[0], passed=False), *records[1:])
    elif condition == "execution-conflict":
        records = (replace(records[0], execution_runner_image_digest="1" * 64), *records[1:])
    elif condition == "browser-conflict":
        records = (replace(records[0], browser_runner_image_digest="1" * 64), *records[1:])
    elif condition == "missing-browser":
        records = tuple(
            record
            for record in records
            if record.kind is not WebProfileValidationEvidenceKind.BROWSER_EVIDENCE
        )
    elif condition == "wrong-version":
        records = tuple(replace(record, profile_version="2.0.0") for record in records)
    elif condition == "unknown-profile":
        records = tuple(replace(record, profile_id="web.future") for record in records)
    elif condition == "missing-browser-runner":
        records = tuple(replace(record, browser_runner_image_digest=None) for record in records)
    elif condition == "missing-variant":
        configuration = next(
            record.language_configuration
            for record in records
            if record.language_configuration is not None
        )
        records = tuple(
            record for record in records if record.language_configuration != configuration
        )
    loaded = _load(records)
    assert loaded.catalog.records == records
    decision = loaded.promotion_for("web.vue", "1.0.0")
    assert decision is not None
    assert decision.status is expected_status
    assert decision.missing_requirements or decision.issue_messages
    assert all(
        profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        for profile in loaded.registry.profiles
    )


def test_fresh_load_observes_new_failure_without_mutating_an_earlier_snapshot() -> None:
    records = evidence_catalog(ExecutionTarget.WEB_STATIC).records
    factory = UnitOfWorkFactory(records)
    loader = WebProfileCatalogLoader(unit_of_work_factory=factory)
    first = asyncio.run(loader.load())
    failure = replace(records[0], evidence_id="evidence.later.failed", passed=False)
    factory.evidence.records = canonical_web_validation_evidence((*records, failure))
    second = asyncio.run(loader.load())
    assert first.promotion_for("web.static", "1.0.0").is_eligible
    assert second.promotion_for("web.static", "1.0.0").status is WebProfilePromotionStatus.FAILED
    assert first.catalog.records == records
    assert factory.evidence.read_count == 2
    assert len(factory.units) == 2
    assert all(unit.closed for unit in factory.units)
    assert first.registry.content_hash != second.registry.content_hash
    with pytest.raises(FrozenInstanceError):
        first.catalog = second.catalog


@pytest.mark.parametrize(
    "failure", [ValueError("corrupt evidence hash"), OSError("database unavailable")]
)
def test_load_failure_is_propagated_even_after_a_previous_success(failure: Exception) -> None:
    factory = UnitOfWorkFactory(evidence_catalog(ExecutionTarget.WEB_STATIC).records)
    loader = WebProfileCatalogLoader(unit_of_work_factory=factory)
    asyncio.run(loader.load())
    factory.evidence.failure = failure
    with pytest.raises(type(failure), match=str(failure)):
        asyncio.run(loader.load())
    assert all(unit.closed for unit in factory.units)


@pytest.mark.parametrize("duplicate", [False, True])
def test_noncanonical_or_duplicate_history_cannot_form_a_catalog(duplicate: bool) -> None:
    records = evidence_catalog(ExecutionTarget.WEB_STATIC).records
    records = (records[0], records[0]) if duplicate else tuple(reversed(records))
    factory = UnitOfWorkFactory(records)
    with pytest.raises(ValueError):
        asyncio.run(WebProfileCatalogLoader(unit_of_work_factory=factory).load())
    assert factory.units[0].closed


def test_diagnostic_lookup_is_exact_and_loaded_result_is_deterministic() -> None:
    records = evidence_catalog(ExecutionTarget.WEB_STATIC).records
    first, second = _load(records), _load(records)
    assert first.catalog == second.catalog
    assert first.registry.content_hash == second.registry.content_hash
    assert first.promotion_decisions == second.promotion_decisions
    assert first.promotion_for("web.static", "2.0.0") is None
    assert first.promotion_for("web.unknown", "1.0.0") is None


def test_production_builder_does_not_open_database_connections_until_load() -> None:
    def session_factory():
        pytest.fail("Constructing a loader must not open a database connection")

    assert isinstance(build_web_profile_catalog_loader(session_factory), WebProfileCatalogLoader)
