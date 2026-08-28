"""Tests for evidence-gated promotion of exact Sprint 09 JVM profiles."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime

import pytest

from orchestwin.jvm_execution.profile_registry import (
    create_sprint09_jvm_profile_registry,
    evaluate_sprint09_jvm_profile_promotions,
)
from orchestwin.jvm_execution.targets import jvm_scope_for
from orchestwin.jvm_execution.validation_evidence import (
    JvmProfilePromotionStatus,
    JvmProfileValidationEvidence,
    JvmProfileValidationEvidenceCatalog,
    JvmProfileValidationEvidenceKind,
    evaluate_jvm_profile_promotion,
)
from orchestwin.sandbox.container_runtime import ContainerImageReference
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)

from .profile_support import (
    declaration_for,
    runner_for,
    snapshot_for,
    source_revision_reference,
)

_RECORDED_AT = datetime(2026, 8, 28, 14, 0, tzinfo=UTC)
_REQUIRED_KINDS = tuple(
    kind
    for kind in JvmProfileValidationEvidenceKind
    if kind is not JvmProfileValidationEvidenceKind.REPRODUCIBILITY
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _runner_digest(target: ExecutionTarget) -> str:
    return "c" * 64 if target is ExecutionTarget.JVM_SCALA else "d" * 64


def _evidence_catalog(
    target: ExecutionTarget,
    *,
    omit_kind: JvmProfileValidationEvidenceKind | None = None,
    stale: bool = False,
    conflicting_field: str | None = None,
    failed_kind: JvmProfileValidationEvidenceKind | None = None,
    reproducibility_records: int = 2,
    duplicate_reproducibility_artifact: bool = False,
) -> JvmProfileValidationEvidenceCatalog:
    scope = jvm_scope_for(target)
    kinds = [kind for kind in _REQUIRED_KINDS if kind is not omit_kind]
    kinds.extend(
        JvmProfileValidationEvidenceKind.REPRODUCIBILITY for _ in range(reproducibility_records)
    )
    common = {
        "runner_image_digest": _runner_digest(target),
        "runner_build_recipe_hash": _digest(f"recipe:{target.value}"),
        "toolchain_manifest_hash": _digest(f"toolchain:{target.value}"),
        "fixture_bundle_hash": _digest(f"fixtures:{target.value}"),
        "environment_fingerprint": _digest("windows-docker-linux-amd64"),
    }
    records: list[JvmProfileValidationEvidence] = []
    first_reproducibility_hash: str | None = None
    for sequence, kind in enumerate(kinds, start=1):
        identity = dict(common)
        if conflicting_field is not None and sequence == 2:
            identity[conflicting_field] = "f" * 64
        artifact_hash = _digest(f"{scope.profile_id}:{kind.value}:{sequence}")
        if kind is JvmProfileValidationEvidenceKind.REPRODUCIBILITY:
            if first_reproducibility_hash is None:
                first_reproducibility_hash = artifact_hash
            elif duplicate_reproducibility_artifact:
                artifact_hash = first_reproducibility_hash
        records.append(
            JvmProfileValidationEvidence(
                evidence_id=f"evidence.{scope.profile_id}.{sequence}",
                kind=kind,
                profile_id=scope.profile_id,
                profile_version=scope.profile_version,
                baseline_scope_hash="9" * 64 if stale else scope.content_hash,
                artifact_content_hash=artifact_hash,
                reference=f"report:{scope.profile_id}:item-{sequence}",
                recorded_at=_RECORDED_AT,
                passed=kind is not failed_kind,
                **identity,
            )
        )
    return JvmProfileValidationEvidenceCatalog(
        records=tuple(
            sorted(
                records,
                key=lambda record: (
                    record.profile_id,
                    record.profile_version,
                    record.kind.value,
                    record.evidence_id,
                ),
            )
        )
    )


def test_registry_remains_design_only_without_recorded_evidence() -> None:
    registry = create_sprint09_jvm_profile_registry()
    decisions = evaluate_sprint09_jvm_profile_promotions(
        JvmProfileValidationEvidenceCatalog(records=())
    )

    assert all(
        profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        for profile in registry.profiles
    )
    assert {decision.status for decision in decisions} == {JvmProfilePromotionStatus.INCOMPLETE}


def test_missing_evidence_or_duplicate_reproducibility_prevents_promotion() -> None:
    scope = jvm_scope_for(ExecutionTarget.JVM_KOTLIN)

    missing_kind = evaluate_jvm_profile_promotion(
        scope,
        catalog=_evidence_catalog(
            ExecutionTarget.JVM_KOTLIN,
            omit_kind=JvmProfileValidationEvidenceKind.REPAIR_RERUN,
        ),
    )
    duplicate_repetition = evaluate_jvm_profile_promotion(
        scope,
        catalog=_evidence_catalog(
            ExecutionTarget.JVM_KOTLIN,
            duplicate_reproducibility_artifact=True,
        ),
    )

    assert missing_kind.status is JvmProfilePromotionStatus.INCOMPLETE
    assert "profile:REPAIR_RERUN" in missing_kind.missing_requirements
    assert duplicate_repetition.status is JvmProfilePromotionStatus.INCOMPLETE
    assert any(
        item.startswith("profile:REPRODUCIBILITY")
        for item in duplicate_repetition.missing_requirements
    )


@pytest.mark.parametrize(
    "conflicting_field",
    [
        "runner_image_digest",
        "runner_build_recipe_hash",
        "toolchain_manifest_hash",
        "fixture_bundle_hash",
        "environment_fingerprint",
    ],
)
def test_stale_failed_and_conflicting_records_are_distinguished(
    conflicting_field: str,
) -> None:
    scope = jvm_scope_for(ExecutionTarget.JVM_JAVA)

    stale = evaluate_jvm_profile_promotion(
        scope,
        catalog=_evidence_catalog(ExecutionTarget.JVM_JAVA, stale=True),
    )
    failed = evaluate_jvm_profile_promotion(
        scope,
        catalog=_evidence_catalog(
            ExecutionTarget.JVM_JAVA,
            failed_kind=JvmProfileValidationEvidenceKind.FAILURE_MATRIX,
        ),
    )
    conflicting = evaluate_jvm_profile_promotion(
        scope,
        catalog=_evidence_catalog(
            ExecutionTarget.JVM_JAVA,
            conflicting_field=conflicting_field,
        ),
    )

    assert stale.status is JvmProfilePromotionStatus.STALE
    assert failed.status is JvmProfilePromotionStatus.FAILED
    assert conflicting.status is JvmProfilePromotionStatus.CONFLICTING


def test_complete_kotlin_evidence_promotes_exact_scope_validation_and_runner() -> None:
    catalog = _evidence_catalog(ExecutionTarget.JVM_KOTLIN)
    registry = create_sprint09_jvm_profile_registry(evidence_catalog=catalog)
    profile = registry.for_target(ExecutionTarget.JVM_KOTLIN)
    assert profile is not None
    baseline = jvm_scope_for(ExecutionTarget.JVM_KOTLIN)

    assert baseline.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
    assert profile.scope.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D
    assert profile.scope.validation_evidence_refs

    snapshot = snapshot_for(ExecutionTarget.JVM_KOTLIN)
    declaration = declaration_for(ExecutionTarget.JVM_KOTLIN)
    validation = profile.validate(snapshot, declaration)
    contract = profile.create_contract(
        snapshot,
        declaration,
        source_revision=source_revision_reference(),
        runner=runner_for(ExecutionTarget.JVM_KOTLIN),
    )

    assert validation.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D
    assert validation.validation_scope_hash == profile.scope.content_hash
    assert validation.validation_scope_hash != baseline.content_hash
    assert contract.runner.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D
    assert contract.runner.validation_evidence_refs == profile.scope.validation_evidence_refs
    assert contract.execution_plan.target_selection == validation.selection


def test_partial_catalog_promotes_only_the_target_with_complete_evidence() -> None:
    catalog = _evidence_catalog(ExecutionTarget.JVM_KOTLIN)
    registry = create_sprint09_jvm_profile_registry(evidence_catalog=catalog)

    statuses = {
        profile.scope.target: profile.scope.capability_status for profile in registry.profiles
    }
    assert statuses == {
        ExecutionTarget.JVM_JAVA: ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
        ExecutionTarget.JVM_KOTLIN: ExecutionCapabilityStatus.VALIDATED_LEVEL_D,
        ExecutionTarget.JVM_SCALA: ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C,
    }


def test_promoted_profile_rejects_a_runner_not_bound_to_recorded_evidence() -> None:
    catalog = _evidence_catalog(ExecutionTarget.JVM_SCALA)
    registry = create_sprint09_jvm_profile_registry(evidence_catalog=catalog)
    profile = registry.for_target(ExecutionTarget.JVM_SCALA)
    assert profile is not None
    runner = runner_for(ExecutionTarget.JVM_SCALA)
    mismatched = replace(
        runner,
        image=ContainerImageReference("orchestwin/jvm-sbt-runner@sha256:" + "1" * 64),
    )

    with pytest.raises(ValueError, match="runner digest differs"):
        profile.create_contract(
            snapshot_for(ExecutionTarget.JVM_SCALA),
            declaration_for(ExecutionTarget.JVM_SCALA),
            source_revision=source_revision_reference(),
            runner=mismatched,
        )


def test_catalog_requires_canonical_order_and_unique_evidence_ids() -> None:
    catalog = _evidence_catalog(ExecutionTarget.JVM_JAVA)

    with pytest.raises(ValueError, match="canonical order"):
        JvmProfileValidationEvidenceCatalog(records=tuple(reversed(catalog.records)))
    with pytest.raises(ValueError, match="IDs must be unique"):
        JvmProfileValidationEvidenceCatalog(
            records=tuple(
                sorted(
                    (*catalog.records, catalog.records[0]),
                    key=lambda record: (
                        record.profile_id,
                        record.profile_version,
                        record.kind.value,
                        record.evidence_id,
                    ),
                )
            )
        )
