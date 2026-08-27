"""Tests for evidence-gated promotion of exact Sprint 08 Web profiles."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import pytest

from orchestwin.sandbox.archive_policy import (
    SourceArchiveEntryDisposition,
    SourceArchiveEntryKind,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionTarget,
)
from orchestwin.sandbox.source_inventory import (
    SourceInventoryClassification,
    SourceInventoryEntry,
    SourceTreeInventory,
)
from orchestwin.web_execution.detection import (
    create_web_detection_snapshot,
    detect_web_project,
)
from orchestwin.web_execution.lockfiles import validate_web_dependency_locks
from orchestwin.web_execution.profile_contracts import WebProfileRunnerSet
from orchestwin.web_execution.profile_registry import (
    create_sprint08_web_profile_registry,
    evaluate_sprint08_web_profile_promotions,
)
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    web_scope_for,
)
from orchestwin.web_execution.validation_evidence import (
    WebProfilePromotionStatus,
    WebProfileValidationEvidence,
    WebProfileValidationEvidenceCatalog,
    WebProfileValidationEvidenceKind,
    evaluate_web_profile_promotion,
)

RECORDED_AT = datetime(2026, 8, 27, 16, 0, tzinfo=UTC)
EXECUTION_RUNNER_DIGEST = "d" * 64
BROWSER_RUNNER_DIGEST = "e" * 64


def snapshot(files: dict[str, str]):
    entries = tuple(
        SourceInventoryEntry(
            normalized_path=path,
            kind=SourceArchiveEntryKind.FILE,
            classification=SourceInventoryClassification.SOURCE,
            size_bytes=len(content.encode("utf-8")),
            sha256_digest=hashlib.sha256(content.encode("utf-8")).hexdigest(),
            disposition=SourceArchiveEntryDisposition.INCLUDE,
            disposition_reason=None,
        )
        for path, content in sorted(files.items())
    )
    inventory = SourceTreeInventory(archive_sha256="a" * 64, entries=entries)
    return create_web_detection_snapshot(inventory, text_content_by_path=files)


def evidence_catalog(
    target: ExecutionTarget,
    *,
    omit_configuration: WebLanguageConfiguration | None = None,
    stale: bool = False,
    conflicting_runner: bool = False,
) -> WebProfileValidationEvidenceCatalog:
    scope = web_scope_for(target)
    profile_kinds = (
        WebProfileValidationEvidenceKind.CI_VERIFICATION,
        WebProfileValidationEvidenceKind.CONTRACT_TESTS,
        WebProfileValidationEvidenceKind.ENVIRONMENT_MANIFEST,
        WebProfileValidationEvidenceKind.KNOWN_LIMITATIONS,
        WebProfileValidationEvidenceKind.REPRODUCIBILITY,
        WebProfileValidationEvidenceKind.RUNNER_BUILD,
    )
    records: list[WebProfileValidationEvidence] = []
    sequence = 1

    def append(
        kind: WebProfileValidationEvidenceKind,
        configuration: WebLanguageConfiguration | None,
    ) -> None:
        nonlocal sequence
        runner_digest = EXECUTION_RUNNER_DIGEST
        if conflicting_runner and sequence == 2:
            runner_digest = "f" * 64
        identifier = f"evidence.{scope.profile_id.replace('-', '.')}.{sequence}"
        reference = f"report:{scope.profile_id.replace('-', '.')}:item-{sequence}"
        records.append(
            WebProfileValidationEvidence(
                evidence_id=identifier,
                kind=kind,
                profile_id=scope.profile_id,
                profile_version=scope.profile_version,
                baseline_scope_hash=("9" * 64 if stale else scope.content_hash),
                language_configuration=configuration,
                execution_runner_image_digest=runner_digest,
                browser_runner_image_digest=(
                    BROWSER_RUNNER_DIGEST if scope.requires_browser_evidence else None
                ),
                artifact_content_hash=hashlib.sha256(identifier.encode("utf-8")).hexdigest(),
                reference=reference,
                recorded_at=RECORDED_AT,
                passed=True,
            )
        )
        sequence += 1

    for kind in profile_kinds:
        append(kind, None)
    for configuration in scope.language_configurations:
        if configuration == omit_configuration:
            continue
        append(WebProfileValidationEvidenceKind.VALID_FIXTURE_RUN, configuration)
        append(WebProfileValidationEvidenceKind.FAILURE_REPAIR_RERUN, configuration)
        if scope.requires_browser_evidence:
            append(WebProfileValidationEvidenceKind.BROWSER_EVIDENCE, configuration)

    return WebProfileValidationEvidenceCatalog(
        records=tuple(
            sorted(
                records,
                key=lambda record: (
                    record.profile_id,
                    record.profile_version,
                    record.kind.value,
                    ""
                    if record.language_configuration is None
                    else str(record.language_configuration.to_snapshot()),
                    record.evidence_id,
                ),
            )
        )
    )


def test_registry_remains_design_only_without_recorded_evidence() -> None:
    registry = create_sprint08_web_profile_registry()
    decisions = evaluate_sprint08_web_profile_promotions(
        WebProfileValidationEvidenceCatalog(records=())
    )

    assert all(
        profile.scope.capability_status is ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
        for profile in registry.profiles
    )
    assert {decision.status for decision in decisions} == {WebProfilePromotionStatus.INCOMPLETE}


def test_stale_scope_hash_prevents_promotion() -> None:
    scope = web_scope_for(ExecutionTarget.WEB_STATIC)

    decision = evaluate_web_profile_promotion(
        scope,
        catalog=evidence_catalog(ExecutionTarget.WEB_STATIC, stale=True),
    )

    assert decision.status is WebProfilePromotionStatus.STALE
    assert decision.evidence_refs == ()


def test_every_language_configuration_requires_fixture_and_repair_evidence() -> None:
    scope = web_scope_for(ExecutionTarget.WEB_VUE)
    typescript = WebLanguageConfiguration(
        frontend=WebImplementationLanguage.TYPESCRIPT,
        backend=None,
    )

    decision = evaluate_web_profile_promotion(
        scope,
        catalog=evidence_catalog(
            ExecutionTarget.WEB_VUE,
            omit_configuration=typescript,
        ),
    )

    assert decision.status is WebProfilePromotionStatus.INCOMPLETE
    assert any("TYPESCRIPT+NONE" in item for item in decision.missing_requirements)


def test_conflicting_runner_identity_prevents_promotion() -> None:
    scope = web_scope_for(ExecutionTarget.WEB_STATIC)

    decision = evaluate_web_profile_promotion(
        scope,
        catalog=evidence_catalog(
            ExecutionTarget.WEB_STATIC,
            conflicting_runner=True,
        ),
    )

    assert decision.status is WebProfilePromotionStatus.CONFLICTING


def test_complete_static_evidence_promotes_exact_scope_and_runner_contract() -> None:
    catalog = evidence_catalog(ExecutionTarget.WEB_STATIC)
    registry = create_sprint08_web_profile_registry(evidence_catalog=catalog)
    profile = registry.for_target(ExecutionTarget.WEB_STATIC)
    assert profile is not None
    assert profile.scope.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D
    assert profile.scope.validation_evidence_refs

    source = snapshot({"index.html": "<!doctype html><title>Ready</title>"})
    detection = detect_web_project(source)
    assert detection.selected is not None
    selection = detection.selected.selection
    locks = validate_web_dependency_locks(source, selection=selection)

    validation = profile.validate(source, selection=selection, lock_report=locks)
    contract = profile.create_contract(
        source,
        selection=selection,
        lock_report=locks,
        source_revision_content_hash="b" * 64,
        source_tree_hash="c" * 64,
        runners=WebProfileRunnerSet(
            execution_runner_image_digest=EXECUTION_RUNNER_DIGEST,
            browser_runner_image_digest=BROWSER_RUNNER_DIGEST,
        ),
    )

    assert validation.capability_status is ExecutionCapabilityStatus.VALIDATED_LEVEL_D
    assert validation.validation_evidence_refs == profile.scope.validation_evidence_refs
    assert contract.validation.validation_scope_hash == profile.scope.content_hash

    with pytest.raises(ValueError, match="runner digest differs"):
        profile.create_contract(
            source,
            selection=selection,
            lock_report=locks,
            source_revision_content_hash="b" * 64,
            source_tree_hash="c" * 64,
            runners=WebProfileRunnerSet(
                execution_runner_image_digest="1" * 64,
                browser_runner_image_digest=BROWSER_RUNNER_DIGEST,
            ),
        )
