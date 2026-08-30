"""Tests for immutable multimodal synthetic-evaluation artifact bundles."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.evaluation.artifacts import (
    EvaluationArtifactKind,
    EvaluationArtifactModality,
    EvaluationArtifactReference,
    EvaluationScenario,
    create_evaluation_artifact_bundle,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000015001")
RUN_ID = UUID("00000000-0000-4000-8000-000000015002")
SCENARIO_ID = UUID("00000000-0000-4000-8000-000000015003")
BUNDLE_ID = UUID("00000000-0000-4000-8000-000000015004")
NOW = datetime(2026, 8, 30, 15, 0, tzinfo=UTC)


def _artifact(
    identifier: int,
    kind: EvaluationArtifactKind,
    digest_character: str,
    media_type: str,
) -> EvaluationArtifactReference:
    digest = digest_character * 64
    return EvaluationArtifactReference(
        artifact_id=UUID(int=identifier),
        version_number=1,
        kind=kind,
        media_type=media_type,
        sha256_digest=digest,
        size_bytes=120,
        storage_key=f"sha256/{digest[:2]}/{digest}",
        location=f"screen:checkout/artifact:{kind.value.lower()}",
    )


def _scenario() -> EvaluationScenario:
    return EvaluationScenario(
        id=SCENARIO_ID,
        name="Complete the checkout task",
        task="Review the supplied checkout screen and complete the primary task.",
        locale="en",
        expected_outcomes=("The primary action remains understandable and reachable.",),
    )


def test_bundle_orders_exact_artifact_versions_and_exposes_modalities() -> None:
    screenshot = _artifact(15006, EvaluationArtifactKind.SCREENSHOT, "a", "image/png")
    accessibility = _artifact(
        15005,
        EvaluationArtifactKind.ACCESSIBILITY_TREE,
        "b",
        "application/json",
    )
    tests = _artifact(
        15007,
        EvaluationArtifactKind.FUNCTIONAL_TEST_REPORT,
        "c",
        "application/json",
    )

    bundle = create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=RUN_ID,
        scenario=_scenario(),
        artifacts=(screenshot, tests, accessibility),
        created_at=NOW,
        bundle_id=BUNDLE_ID,
    )

    assert [item.kind for item in bundle.artifacts] == [
        EvaluationArtifactKind.ACCESSIBILITY_TREE,
        EvaluationArtifactKind.FUNCTIONAL_TEST_REPORT,
        EvaluationArtifactKind.SCREENSHOT,
    ]
    assert bundle.modalities == (
        EvaluationArtifactModality.DETERMINISTIC_EVIDENCE,
        EvaluationArtifactModality.STRUCTURAL,
        EvaluationArtifactModality.VISUAL,
    )
    assert bundle.is_multimodal is True
    assert bundle.to_snapshot()["content_hash"] == bundle.content_hash


def test_semantically_equal_bundles_have_stable_hashes_across_identity_and_time() -> None:
    artifact = _artifact(15008, EvaluationArtifactKind.EXECUTION_REPORT, "d", "application/json")

    first = create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=RUN_ID,
        scenario=_scenario(),
        artifacts=(artifact,),
        created_at=NOW,
        bundle_id=UUID(int=15009),
    )
    second = create_evaluation_artifact_bundle(
        project_id=PROJECT_ID,
        workflow_run_id=RUN_ID,
        scenario=_scenario(),
        artifacts=(artifact,),
        created_at=datetime(2026, 8, 30, 15, 1, tzinfo=UTC),
        bundle_id=UUID(int=15010),
    )

    assert first.id != second.id
    assert first.created_at != second.created_at
    assert first.content_hash == second.content_hash
    assert first.is_multimodal is False


def test_artifact_references_reject_unsafe_or_inconsistent_metadata() -> None:
    digest = "e" * 64
    with pytest.raises(ValueError, match="content-addressed"):
        EvaluationArtifactReference(
            artifact_id=UUID(int=15011),
            version_number=1,
            kind=EvaluationArtifactKind.DOM_SNAPSHOT,
            media_type="text/html",
            sha256_digest=digest,
            size_bytes=10,
            storage_key="arbitrary/location",
            location="screen:home",
        )

    with pytest.raises(ValueError, match="image media type"):
        _artifact(15012, EvaluationArtifactKind.SCREENSHOT, "f", "text/plain")

    with pytest.raises(ValueError, match="at least one"):
        create_evaluation_artifact_bundle(
            project_id=PROJECT_ID,
            workflow_run_id=RUN_ID,
            scenario=_scenario(),
            artifacts=(),
            created_at=NOW,
        )
