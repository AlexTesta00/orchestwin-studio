"""Immutable, content-addressed examples for User Twin evaluator training."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.evaluation.findings import (
    SyntheticFinding,
    SyntheticFindingCriterion,
)
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    normalize_optional_text,
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.twins.user_twins import UserTwinLifecycleStatus

DATASET_EXAMPLE_SCHEMA_VERSION: Final = 1
SIMULATED_FEEDBACK_DISCLAIMER: Final = (
    "This is simulated feedback based on the available profile, evidence, and project "
    "artifacts. It is a design hypothesis and not empirical evidence of real-user behavior."
)

_EXAMPLE_ID_PATTERN: Final = re.compile(r"UTE-[0-9]{6}")
_MAX_IDENTIFIER_LENGTH: Final = 256
_MAX_TEXT_LENGTH: Final = 8_000
_MAX_REFERENCE_LENGTH: Final = 512
_MAX_MEDIA_TYPE_LENGTH: Final = 200


class DatasetLanguage(StrEnum):
    """Languages deliberately supported by the first evaluator dataset."""

    ENGLISH = "en"
    ITALIAN = "it"


class DatasetExampleSourceKind(StrEnum):
    """Origin of one accepted training example."""

    RESEARCHER_CURATED = "RESEARCHER_CURATED"
    SYNTHETIC_GENERATED = "SYNTHETIC_GENERATED"
    DETERMINISTIC_FIXTURE = "DETERMINISTIC_FIXTURE"


class DatasetUseRestriction(StrEnum):
    """Whether an example must remain outside model training."""

    NONE = "NONE"
    FORMAL_CASE_STUDY = "FORMAL_CASE_STUDY"
    EXTERNAL_EXPERT_SAMPLE = "EXTERNAL_EXPERT_SAMPLE"


class DatasetEvidenceKind(StrEnum):
    """Inspectable source categories available to a dataset example."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    USER_TWIN_PROFILE = "USER_TWIN_PROFILE"
    REQUIREMENT = "REQUIREMENT"
    PROJECT_ARTIFACT = "PROJECT_ARTIFACT"
    DETERMINISTIC_TEST = "DETERMINISTIC_TEST"
    OWNER_INPUT = "OWNER_INPUT"
    EMPIRICAL_RESEARCH = "EMPIRICAL_RESEARCH"
    HUMAN_VALIDATION = "HUMAN_VALIDATION"


@dataclass(frozen=True, slots=True)
class DatasetVersionedArtifactReference:
    """Exact identity of one immutable versioned project artifact."""

    artifact_id: UUID
    version_number: int
    content_hash: str

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.version_number,
            label="dataset artifact version number",
        )
        validate_sha256(
            self.content_hash,
            label="dataset artifact content hash",
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "artifact_id": str(self.artifact_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
        }


@dataclass(frozen=True, slots=True)
class DatasetUserTwinReference:
    """Exact User Twin profile version and its declared lifecycle status."""

    twin_id: UUID
    version_number: int
    content_hash: str
    lifecycle_status: UserTwinLifecycleStatus

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.version_number,
            label="dataset User Twin version number",
        )
        validate_sha256(
            self.content_hash,
            label="dataset User Twin content hash",
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "twin_id": str(self.twin_id),
            "version_number": self.version_number,
            "content_hash": self.content_hash,
            "lifecycle_status": self.lifecycle_status.value,
        }


@dataclass(frozen=True, slots=True)
class DatasetArtifactSnapshot:
    """Versioned artifact identity plus the model-visible structured description."""

    reference: DatasetVersionedArtifactReference
    media_type: str
    description: str

    def __post_init__(self) -> None:
        normalized_media_type = normalize_required_text(
            self.media_type,
            label="dataset artifact media type",
            maximum_length=_MAX_MEDIA_TYPE_LENGTH,
        )
        if normalized_media_type != self.media_type:
            raise ValueError("dataset artifact media type must be normalized")

        normalized_description = normalize_required_text(
            self.description,
            label="dataset artifact description",
            maximum_length=_MAX_TEXT_LENGTH,
        )
        if normalized_description != self.description:
            raise ValueError("dataset artifact description must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "reference": self.reference.to_snapshot(),
            "media_type": self.media_type,
            "description": self.description,
        }


@dataclass(frozen=True, slots=True)
class DatasetEvidenceReference:
    """One allowed reference with explicit empirical and validation semantics."""

    reference_id: str
    kind: DatasetEvidenceKind
    source_id: str
    source_version: int | None
    content_hash: str
    locator: str | None = None
    is_target_user_empirical_evidence: bool = False
    is_human_validation_activity: bool = False

    def __post_init__(self) -> None:
        for value, label in (
            (self.reference_id, "dataset evidence reference ID"),
            (self.source_id, "dataset evidence source ID"),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=_MAX_REFERENCE_LENGTH,
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")

        if self.source_version is not None:
            validate_positive_integer(
                self.source_version,
                label="dataset evidence source version",
            )

        validate_sha256(
            self.content_hash,
            label="dataset evidence content hash",
        )

        normalized_locator = normalize_optional_text(
            self.locator,
            label="dataset evidence locator",
            maximum_length=_MAX_REFERENCE_LENGTH,
        )
        if normalized_locator != self.locator:
            raise ValueError("dataset evidence locator must be normalized")

        empirical_kind = self.kind in {
            DatasetEvidenceKind.EMPIRICAL_RESEARCH,
            DatasetEvidenceKind.HUMAN_VALIDATION,
        }
        if self.is_target_user_empirical_evidence != empirical_kind:
            raise ValueError("dataset evidence empirical flag is inconsistent with its kind")

        human_validation_kind = self.kind is DatasetEvidenceKind.HUMAN_VALIDATION
        if self.is_human_validation_activity != human_validation_kind:
            raise ValueError("dataset evidence human-validation flag is inconsistent with its kind")

    @property
    def sort_key(self) -> tuple[str, str, str, int, str]:
        return (
            self.reference_id,
            self.kind.value,
            self.source_id,
            self.source_version or 0,
            self.content_hash,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "reference_id": self.reference_id,
            "kind": self.kind.value,
            "source_id": self.source_id,
            "source_version": self.source_version,
            "content_hash": self.content_hash,
            "locator": self.locator,
            "is_target_user_empirical_evidence": self.is_target_user_empirical_evidence,
            "is_human_validation_activity": self.is_human_validation_activity,
        }


@dataclass(frozen=True, slots=True)
class DatasetRubric:
    """Versioned evaluation rubric attached to each training example."""

    rubric_id: str
    version_number: int
    criteria: tuple[SyntheticFindingCriterion, ...]
    output_schema_ref: str

    def __post_init__(self) -> None:
        normalized_id = normalize_required_text(
            self.rubric_id,
            label="dataset rubric ID",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        if normalized_id != self.rubric_id:
            raise ValueError("dataset rubric ID must be normalized")

        validate_positive_integer(
            self.version_number,
            label="dataset rubric version number",
        )

        normalized_schema_ref = normalize_required_text(
            self.output_schema_ref,
            label="dataset rubric output schema reference",
            maximum_length=_MAX_REFERENCE_LENGTH,
        )
        if normalized_schema_ref != self.output_schema_ref:
            raise ValueError("dataset rubric output schema reference must be normalized")

        if not self.criteria:
            raise ValueError("dataset rubric criteria must not be empty")
        if len(self.criteria) != len(set(self.criteria)):
            raise ValueError("dataset rubric criteria must be unique")

        criterion_order = {
            criterion: index for index, criterion in enumerate(SyntheticFindingCriterion)
        }
        expected_order = tuple(sorted(self.criteria, key=criterion_order.__getitem__))
        if self.criteria != expected_order:
            raise ValueError("dataset rubric criteria must use canonical order")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "rubric_id": self.rubric_id,
            "version_number": self.version_number,
            "criteria": [criterion.value for criterion in self.criteria],
            "output_schema_ref": self.output_schema_ref,
        }


@dataclass(frozen=True, slots=True)
class ExpectedUserTwinEvaluation:
    """Expected structured evaluator output used as the supervised target."""

    overall_summary: str
    findings: tuple[SyntheticFinding, ...]
    evidence_gaps: tuple[str, ...]
    abstained: bool
    disclaimer: str = SIMULATED_FEEDBACK_DISCLAIMER

    def __post_init__(self) -> None:
        normalized_summary = normalize_required_text(
            self.overall_summary,
            label="expected evaluation summary",
            maximum_length=_MAX_TEXT_LENGTH,
        )
        if normalized_summary != self.overall_summary:
            raise ValueError("expected evaluation summary must be normalized")

        finding_ids = tuple(finding.finding_id for finding in self.findings)
        if len(finding_ids) != len(set(finding_ids)):
            raise ValueError("expected evaluation finding IDs must be unique")
        if finding_ids != tuple(sorted(finding_ids)):
            raise ValueError("expected evaluation findings must use canonical ID order")

        gaps = normalize_text_items(
            self.evidence_gaps,
            label="expected evaluation evidence gap",
            maximum_item_length=_MAX_TEXT_LENGTH,
            require_items=False,
        )
        canonical_gaps = tuple(sorted(gaps))
        if gaps != self.evidence_gaps or gaps != canonical_gaps:
            raise ValueError("expected evaluation evidence gaps must be normalized and canonical")

        if self.abstained and self.findings:
            raise ValueError("an abstained expected evaluation must not contain findings")
        if self.abstained and not self.evidence_gaps:
            raise ValueError("an abstained expected evaluation must explain an evidence gap")

        if self.disclaimer != SIMULATED_FEEDBACK_DISCLAIMER:
            raise ValueError("expected evaluation must preserve the methodological disclaimer")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "overall_summary": self.overall_summary,
            "findings": [finding.to_snapshot() for finding in self.findings],
            "evidence_gaps": list(self.evidence_gaps),
            "abstained": self.abstained,
            "disclaimer": self.disclaimer,
        }


@dataclass(frozen=True, slots=True)
class EvaluatorDatasetExample:
    """One complete immutable supervised example for the shared evaluator adapter."""

    example_id: str
    project_id: UUID
    scenario_family_id: str
    language: DatasetLanguage
    source_kind: DatasetExampleSourceKind
    use_restriction: DatasetUseRestriction
    project_brief_reference: DatasetVersionedArtifactReference
    project_brief_summary: str
    user_twin_reference: DatasetUserTwinReference
    user_twin_profile_json: str
    scenario: str
    target_task: str
    artifact: DatasetArtifactSnapshot
    evidence: tuple[DatasetEvidenceReference, ...]
    rubric: DatasetRubric
    expected_output: ExpectedUserTwinEvaluation
    generation_ref: str | None
    content_hash: str

    def __post_init__(self) -> None:
        if _EXAMPLE_ID_PATTERN.fullmatch(self.example_id) is None:
            raise ValueError("dataset example ID must use the UTE-NNNNNN format")

        normalized_family_id = normalize_required_text(
            self.scenario_family_id,
            label="dataset scenario family ID",
            maximum_length=_MAX_IDENTIFIER_LENGTH,
        )
        if normalized_family_id != self.scenario_family_id:
            raise ValueError("dataset scenario family ID must be normalized")

        for value, label in (
            (self.project_brief_summary, "dataset Project Brief summary"),
            (self.scenario, "dataset scenario"),
            (self.target_task, "dataset target task"),
        ):
            normalized = normalize_required_text(
                value,
                label=label,
                maximum_length=_MAX_TEXT_LENGTH,
            )
            if normalized != value:
                raise ValueError(f"{label} must be normalized")

        try:
            profile_snapshot = json.loads(self.user_twin_profile_json)
        except json.JSONDecodeError as error:
            raise ValueError("dataset User Twin profile JSON must be valid") from error
        if not isinstance(profile_snapshot, dict):
            raise ValueError("dataset User Twin profile JSON must contain an object")
        if canonical_json(profile_snapshot) != self.user_twin_profile_json:
            raise ValueError("dataset User Twin profile JSON must be canonical")

        evidence_ids = tuple(item.reference_id for item in self.evidence)
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("dataset evidence reference IDs must be unique")
        expected_evidence = tuple(sorted(self.evidence, key=lambda item: item.sort_key))
        if self.evidence != expected_evidence:
            raise ValueError("dataset evidence references must use canonical order")

        normalized_generation_ref = normalize_optional_text(
            self.generation_ref,
            label="dataset generation reference",
            maximum_length=_MAX_REFERENCE_LENGTH,
        )
        if normalized_generation_ref != self.generation_ref:
            raise ValueError("dataset generation reference must be normalized")
        if (
            self.source_kind is DatasetExampleSourceKind.SYNTHETIC_GENERATED
            and self.generation_ref is None
        ):
            raise ValueError("a synthetic dataset example requires a generation reference")

        validate_sha256(
            self.content_hash,
            label="dataset example content hash",
        )
        expected_hash = dataset_example_hash(
            example_id=self.example_id,
            project_id=self.project_id,
            scenario_family_id=self.scenario_family_id,
            language=self.language,
            source_kind=self.source_kind,
            use_restriction=self.use_restriction,
            project_brief_reference=self.project_brief_reference,
            project_brief_summary=self.project_brief_summary,
            user_twin_reference=self.user_twin_reference,
            user_twin_profile_json=self.user_twin_profile_json,
            scenario=self.scenario,
            target_task=self.target_task,
            artifact=self.artifact,
            evidence=self.evidence,
            rubric=self.rubric,
            expected_output=self.expected_output,
            generation_ref=self.generation_ref,
        )
        if self.content_hash != expected_hash:
            raise ValueError("dataset example content hash is inconsistent")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "schema_version": DATASET_EXAMPLE_SCHEMA_VERSION,
            "example_id": self.example_id,
            "project_id": str(self.project_id),
            "scenario_family_id": self.scenario_family_id,
            "language": self.language.value,
            "source_kind": self.source_kind.value,
            "use_restriction": self.use_restriction.value,
            "project_brief_reference": self.project_brief_reference.to_snapshot(),
            "project_brief_summary": self.project_brief_summary,
            "user_twin_reference": self.user_twin_reference.to_snapshot(),
            "user_twin_profile": json.loads(self.user_twin_profile_json),
            "scenario": self.scenario,
            "target_task": self.target_task,
            "artifact": self.artifact.to_snapshot(),
            "evidence": [item.to_snapshot() for item in self.evidence],
            "rubric": self.rubric.to_snapshot(),
            "expected_output": self.expected_output.to_snapshot(),
            "generation_ref": self.generation_ref,
            "content_hash": self.content_hash,
        }


def create_evaluator_dataset_example(
    *,
    example_id: str,
    project_id: UUID,
    scenario_family_id: str,
    language: DatasetLanguage,
    source_kind: DatasetExampleSourceKind,
    use_restriction: DatasetUseRestriction,
    project_brief_reference: DatasetVersionedArtifactReference,
    project_brief_summary: str,
    user_twin_reference: DatasetUserTwinReference,
    user_twin_profile: Mapping[str, object],
    scenario: str,
    target_task: str,
    artifact: DatasetArtifactSnapshot,
    evidence: Iterable[DatasetEvidenceReference],
    rubric_id: str,
    rubric_version: int,
    rubric_criteria: Iterable[SyntheticFindingCriterion],
    output_schema_ref: str,
    overall_summary: str,
    findings: Iterable[SyntheticFinding],
    evidence_gaps: Iterable[str],
    abstained: bool,
    generation_ref: str | None = None,
) -> EvaluatorDatasetExample:
    """Canonicalize one example and calculate its complete content digest."""
    canonical_evidence = tuple(sorted(tuple(evidence), key=lambda item: item.sort_key))
    criterion_order = {
        criterion: index for index, criterion in enumerate(SyntheticFindingCriterion)
    }
    canonical_criteria = tuple(
        sorted(
            tuple(rubric_criteria),
            key=criterion_order.__getitem__,
        )
    )
    rubric = DatasetRubric(
        rubric_id=rubric_id,
        version_number=rubric_version,
        criteria=canonical_criteria,
        output_schema_ref=output_schema_ref,
    )
    expected_output = ExpectedUserTwinEvaluation(
        overall_summary=overall_summary,
        findings=tuple(sorted(tuple(findings), key=lambda item: item.finding_id)),
        evidence_gaps=tuple(sorted(tuple(evidence_gaps))),
        abstained=abstained,
    )
    profile_json = canonical_json(dict(user_twin_profile))
    content_hash = dataset_example_hash(
        example_id=example_id,
        project_id=project_id,
        scenario_family_id=scenario_family_id,
        language=language,
        source_kind=source_kind,
        use_restriction=use_restriction,
        project_brief_reference=project_brief_reference,
        project_brief_summary=project_brief_summary,
        user_twin_reference=user_twin_reference,
        user_twin_profile_json=profile_json,
        scenario=scenario,
        target_task=target_task,
        artifact=artifact,
        evidence=canonical_evidence,
        rubric=rubric,
        expected_output=expected_output,
        generation_ref=generation_ref,
    )
    return EvaluatorDatasetExample(
        example_id=example_id,
        project_id=project_id,
        scenario_family_id=scenario_family_id,
        language=language,
        source_kind=source_kind,
        use_restriction=use_restriction,
        project_brief_reference=project_brief_reference,
        project_brief_summary=project_brief_summary,
        user_twin_reference=user_twin_reference,
        user_twin_profile_json=profile_json,
        scenario=scenario,
        target_task=target_task,
        artifact=artifact,
        evidence=canonical_evidence,
        rubric=rubric,
        expected_output=expected_output,
        generation_ref=generation_ref,
        content_hash=content_hash,
    )


def dataset_example_hash(
    *,
    example_id: str,
    project_id: UUID,
    scenario_family_id: str,
    language: DatasetLanguage,
    source_kind: DatasetExampleSourceKind,
    use_restriction: DatasetUseRestriction,
    project_brief_reference: DatasetVersionedArtifactReference,
    project_brief_summary: str,
    user_twin_reference: DatasetUserTwinReference,
    user_twin_profile_json: str,
    scenario: str,
    target_task: str,
    artifact: DatasetArtifactSnapshot,
    evidence: tuple[DatasetEvidenceReference, ...],
    rubric: DatasetRubric,
    expected_output: ExpectedUserTwinEvaluation,
    generation_ref: str | None,
) -> str:
    """Hash all semantic, provenance, and governance fields of one example."""
    return snapshot_content_hash(
        {
            "schema_version": DATASET_EXAMPLE_SCHEMA_VERSION,
            "example_id": example_id,
            "project_id": str(project_id),
            "scenario_family_id": scenario_family_id,
            "language": language.value,
            "source_kind": source_kind.value,
            "use_restriction": use_restriction.value,
            "project_brief_reference": project_brief_reference.to_snapshot(),
            "project_brief_summary": project_brief_summary,
            "user_twin_reference": user_twin_reference.to_snapshot(),
            "user_twin_profile": json.loads(user_twin_profile_json),
            "scenario": scenario,
            "target_task": target_task,
            "artifact": artifact.to_snapshot(),
            "evidence": [item.to_snapshot() for item in evidence],
            "rubric": rubric.to_snapshot(),
            "expected_output": expected_output.to_snapshot(),
            "generation_ref": generation_ref,
        }
    )
