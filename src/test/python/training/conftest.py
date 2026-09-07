"""Shared deterministic factories for training-dataset tests."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest

from orchestwin.evaluation.findings import (
    SyntheticFinding,
    SyntheticFindingCriterion,
    SyntheticFindingEpistemicStatus,
    SyntheticFindingSeverity,
    create_synthetic_finding,
)
from orchestwin.training.dataset_examples import (
    DatasetArtifactSnapshot,
    DatasetEvidenceKind,
    DatasetEvidenceReference,
    DatasetExampleSourceKind,
    DatasetLanguage,
    DatasetUseRestriction,
    DatasetUserTwinReference,
    DatasetVersionedArtifactReference,
    EvaluatorDatasetExample,
    create_evaluator_dataset_example,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

PROJECT_ID = UUID("00000000-0000-4000-8000-000000111001")
BRIEF_ID = UUID("00000000-0000-4000-8000-000000111002")
TWIN_ID = UUID("00000000-0000-4000-8000-000000111003")
ARTIFACT_ID = UUID("00000000-0000-4000-8000-000000111004")


@pytest.fixture
def finding_factory() -> Callable[..., SyntheticFinding]:
    def create(**overrides: object) -> SyntheticFinding:
        values: dict[str, object] = {
            "finding_id": "UTF-001",
            "twin_id": TWIN_ID,
            "twin_version": 3,
            "artifact_id": ARTIFACT_ID,
            "artifact_version": 5,
            "location": "screen:task/field:deadline",
            "summary": "The recovery instruction is not visible near the invalid field.",
            "rationale": (
                "The approved profile requires concise guidance during time-sensitive work."
            ),
            "criterion": SyntheticFindingCriterion.ACTIONABILITY,
            "severity": SyntheticFindingSeverity.MAJOR,
            "epistemic_status": SyntheticFindingEpistemicStatus.MODEL_INFERRED,
            "evidence_refs": ("REQ-NFR-012", "ut-profile-v3.operational_constraints[0]"),
            "confidence": 0.72,
            "recommended_action": "Explain the accepted value and retain keyboard focus.",
            "requires_human_validation": True,
            "model_config_ref": "model-policy-v2",
            "prompt_version_ref": "ut-eval-v4",
        }
        values.update(overrides)
        return create_synthetic_finding(**values)  # type: ignore[arg-type]

    return create


@pytest.fixture
def example_factory(
    finding_factory: Callable[..., SyntheticFinding],
) -> Callable[..., EvaluatorDatasetExample]:
    def create(**overrides: object) -> EvaluatorDatasetExample:
        evidence = (
            DatasetEvidenceReference(
                reference_id="REQ-NFR-012",
                kind=DatasetEvidenceKind.REQUIREMENT,
                source_id="requirements-v4",
                source_version=4,
                content_hash="a" * 64,
                locator="non_functional_requirements[11]",
            ),
            DatasetEvidenceReference(
                reference_id="ut-profile-v3.operational_constraints[0]",
                kind=DatasetEvidenceKind.USER_TWIN_PROFILE,
                source_id=str(TWIN_ID),
                source_version=3,
                content_hash="b" * 64,
                locator="operational_constraints[0]",
            ),
        )
        values: dict[str, object] = {
            "example_id": "UTE-000001",
            "project_id": PROJECT_ID,
            "scenario_family_id": "generic-operations-time-pressure",
            "language": DatasetLanguage.ENGLISH,
            "source_kind": DatasetExampleSourceKind.RESEARCHER_CURATED,
            "use_restriction": DatasetUseRestriction.NONE,
            "project_brief_reference": DatasetVersionedArtifactReference(
                artifact_id=BRIEF_ID,
                version_number=2,
                content_hash="c" * 64,
            ),
            "project_brief_summary": "A small operations interface supports a time-sensitive task.",
            "user_twin_reference": DatasetUserTwinReference(
                twin_id=TWIN_ID,
                version_number=3,
                content_hash="d" * 64,
                lifecycle_status=UserTwinLifecycleStatus.OWNER_APPROVED_UT,
            ),
            "user_twin_profile": {
                "name": "Operations coordinator",
                "role": "Coordinates a time-sensitive operational workflow",
                "validation_status": "OWNER_APPROVED_UT",
            },
            "scenario": "A coordinator corrects an invalid deadline during a busy shift.",
            "target_task": "Recover from validation without losing entered data.",
            "artifact": DatasetArtifactSnapshot(
                reference=DatasetVersionedArtifactReference(
                    artifact_id=ARTIFACT_ID,
                    version_number=5,
                    content_hash="e" * 64,
                ),
                media_type="application/vnd.orchestwin.interface-summary+json",
                description="A form shows an error only at the top of the page.",
            ),
            "evidence": evidence,
            "rubric_id": "ut-evaluator-core",
            "rubric_version": 1,
            "rubric_criteria": (
                SyntheticFindingCriterion.ACTIONABILITY,
                SyntheticFindingCriterion.TASK_ALIGNMENT,
            ),
            "output_schema_ref": "synthetic-finding.schema.json@1",
            "overall_summary": "The artifact creates recoverable but important task friction.",
            "findings": (finding_factory(),),
            "evidence_gaps": (),
            "abstained": False,
            "generation_ref": None,
        }
        values.update(overrides)
        return create_evaluator_dataset_example(**values)  # type: ignore[arg-type]

    return create
