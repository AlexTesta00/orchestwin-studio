"""Immutable multimodal artifact bundles supplied to synthetic evaluators."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final
from uuid import UUID, uuid4

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    normalize_text_items,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)

_MAX_MEDIA_TYPE_LENGTH: Final = 127
_MAX_LOCATION_LENGTH: Final = 500
_MAX_SCENARIO_NAME_LENGTH: Final = 200
_MAX_SCENARIO_TASK_LENGTH: Final = 2_000
_MAX_OUTCOME_LENGTH: Final = 1_000


class EvaluationArtifactModality(StrEnum):
    """Stable input modalities kept distinct during synthetic evaluation."""

    VISUAL = "VISUAL"
    STRUCTURAL = "STRUCTURAL"
    DETERMINISTIC_EVIDENCE = "DETERMINISTIC_EVIDENCE"
    DESIGN_CONTEXT = "DESIGN_CONTEXT"
    SOURCE_CONTEXT = "SOURCE_CONTEXT"


class EvaluationArtifactKind(StrEnum):
    """Supported immutable artifacts that an evaluator may inspect."""

    SCREENSHOT = "SCREENSHOT"
    DOM_SNAPSHOT = "DOM_SNAPSHOT"
    ACCESSIBILITY_TREE = "ACCESSIBILITY_TREE"
    AXE_REPORT = "AXE_REPORT"
    FUNCTIONAL_TEST_REPORT = "FUNCTIONAL_TEST_REPORT"
    EXECUTION_REPORT = "EXECUTION_REPORT"
    DESIGN_SPECIFICATION = "DESIGN_SPECIFICATION"
    PROTOTYPE_MANIFEST = "PROTOTYPE_MANIFEST"
    SOURCE_SNAPSHOT = "SOURCE_SNAPSHOT"

    @property
    def modality(self) -> EvaluationArtifactModality:
        return _ARTIFACT_MODALITIES[self]


_ARTIFACT_MODALITIES: Final = {
    EvaluationArtifactKind.SCREENSHOT: EvaluationArtifactModality.VISUAL,
    EvaluationArtifactKind.DOM_SNAPSHOT: EvaluationArtifactModality.STRUCTURAL,
    EvaluationArtifactKind.ACCESSIBILITY_TREE: EvaluationArtifactModality.STRUCTURAL,
    EvaluationArtifactKind.AXE_REPORT: EvaluationArtifactModality.DETERMINISTIC_EVIDENCE,
    EvaluationArtifactKind.FUNCTIONAL_TEST_REPORT: (
        EvaluationArtifactModality.DETERMINISTIC_EVIDENCE
    ),
    EvaluationArtifactKind.EXECUTION_REPORT: EvaluationArtifactModality.DETERMINISTIC_EVIDENCE,
    EvaluationArtifactKind.DESIGN_SPECIFICATION: EvaluationArtifactModality.DESIGN_CONTEXT,
    EvaluationArtifactKind.PROTOTYPE_MANIFEST: EvaluationArtifactModality.DESIGN_CONTEXT,
    EvaluationArtifactKind.SOURCE_SNAPSHOT: EvaluationArtifactModality.SOURCE_CONTEXT,
}


@dataclass(frozen=True, slots=True)
class EvaluationArtifactReference:
    """Content-addressed exact artifact version included in an evaluation bundle."""

    artifact_id: UUID
    version_number: int
    kind: EvaluationArtifactKind
    media_type: str
    sha256_digest: str
    size_bytes: int
    storage_key: str
    location: str

    def __post_init__(self) -> None:
        validate_positive_integer(
            self.version_number,
            label="evaluation artifact version",
        )
        validate_positive_integer(
            self.size_bytes,
            label="evaluation artifact size",
        )
        validate_sha256(
            self.sha256_digest,
            label="evaluation artifact digest",
        )
        media_type = normalize_required_text(
            self.media_type,
            label="evaluation artifact media type",
            maximum_length=_MAX_MEDIA_TYPE_LENGTH,
        )
        if media_type != self.media_type or "/" not in media_type:
            raise ValueError("evaluation artifact media type must be normalized")
        location = normalize_required_text(
            self.location,
            label="evaluation artifact location",
            maximum_length=_MAX_LOCATION_LENGTH,
        )
        if location != self.location:
            raise ValueError("evaluation artifact location must be normalized")
        expected_storage_key = f"sha256/{self.sha256_digest[:2]}/{self.sha256_digest}"
        if self.storage_key != expected_storage_key:
            raise ValueError("evaluation artifact storage key must be content-addressed")
        if self.kind is EvaluationArtifactKind.SCREENSHOT and not self.media_type.startswith(
            "image/"
        ):
            raise ValueError("evaluation screenshots require an image media type")

    @property
    def sort_key(self) -> tuple[str, str, int, str]:
        return (
            self.kind.value,
            self.artifact_id.hex,
            self.version_number,
            self.location,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            "artifact_id": str(self.artifact_id),
            "version_number": self.version_number,
            "kind": self.kind.value,
            "modality": self.kind.modality.value,
            "media_type": self.media_type,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "storage_key": self.storage_key,
            "location": self.location,
        }


@dataclass(frozen=True, slots=True)
class EvaluationScenario:
    """Explicit role-neutral task context for evaluating supplied artifacts."""

    id: UUID
    name: str
    task: str
    locale: str
    expected_outcomes: tuple[str, ...]

    def __post_init__(self) -> None:
        name = normalize_required_text(
            self.name,
            label="evaluation scenario name",
            maximum_length=_MAX_SCENARIO_NAME_LENGTH,
        )
        task = normalize_required_text(
            self.task,
            label="evaluation scenario task",
            maximum_length=_MAX_SCENARIO_TASK_LENGTH,
        )
        locale = normalize_required_text(
            self.locale,
            label="evaluation scenario locale",
            maximum_length=20,
        )
        outcomes = normalize_text_items(
            self.expected_outcomes,
            label="evaluation expected outcome",
            maximum_item_length=_MAX_OUTCOME_LENGTH,
            require_items=True,
        )
        if name != self.name or task != self.task or locale != self.locale:
            raise ValueError("evaluation scenario text must be normalized")
        if outcomes != self.expected_outcomes:
            raise ValueError("evaluation expected outcomes must be normalized")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "name": self.name,
            "task": self.task,
            "locale": self.locale,
            "expected_outcomes": list(self.expected_outcomes),
        }


@dataclass(frozen=True, slots=True)
class EvaluationArtifactBundle:
    """Immutable collection of exact multimodal inputs for one evaluation task."""

    id: UUID
    project_id: UUID
    workflow_run_id: UUID
    scenario: EvaluationScenario
    artifacts: tuple[EvaluationArtifactReference, ...]
    created_at: datetime
    content_hash: str

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            raise ValueError("evaluation artifact bundle timestamp must be timezone-aware")
        if not self.artifacts:
            raise ValueError("evaluation artifact bundle must contain at least one artifact")
        ordered = tuple(sorted(self.artifacts, key=lambda item: item.sort_key))
        if ordered != self.artifacts:
            raise ValueError("evaluation artifacts must use canonical order")
        identities = {
            (item.artifact_id, item.version_number, item.kind, item.location)
            for item in self.artifacts
        }
        if len(identities) != len(self.artifacts):
            raise ValueError("evaluation artifact references must be unique")
        validate_sha256(
            self.content_hash,
            label="evaluation artifact bundle content hash",
        )
        if self.content_hash != evaluation_artifact_bundle_hash(
            project_id=self.project_id,
            workflow_run_id=self.workflow_run_id,
            scenario=self.scenario,
            artifacts=self.artifacts,
        ):
            raise ValueError("evaluation artifact bundle content hash is inconsistent")

    @property
    def modalities(self) -> tuple[EvaluationArtifactModality, ...]:
        return tuple(sorted({item.kind.modality for item in self.artifacts}, key=str))

    @property
    def is_multimodal(self) -> bool:
        return len(self.modalities) > 1

    def to_snapshot(self) -> dict[str, object]:
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "workflow_run_id": str(self.workflow_run_id),
            "scenario": self.scenario.to_snapshot(),
            "artifacts": [item.to_snapshot() for item in self.artifacts],
            "modalities": [item.value for item in self.modalities],
            "is_multimodal": self.is_multimodal,
            "created_at": self.created_at.isoformat(),
            "content_hash": self.content_hash,
        }


def create_evaluation_artifact_bundle(
    *,
    project_id: UUID,
    workflow_run_id: UUID,
    scenario: EvaluationScenario,
    artifacts: tuple[EvaluationArtifactReference, ...],
    created_at: datetime,
    bundle_id: UUID | None = None,
) -> EvaluationArtifactBundle:
    """Create a canonically ordered immutable artifact bundle."""
    ordered = tuple(sorted(artifacts, key=lambda item: item.sort_key))
    return EvaluationArtifactBundle(
        id=bundle_id or uuid4(),
        project_id=project_id,
        workflow_run_id=workflow_run_id,
        scenario=scenario,
        artifacts=ordered,
        created_at=created_at,
        content_hash=evaluation_artifact_bundle_hash(
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            scenario=scenario,
            artifacts=ordered,
        ),
    )


def evaluation_artifact_bundle_hash(
    *,
    project_id: UUID,
    workflow_run_id: UUID,
    scenario: EvaluationScenario,
    artifacts: tuple[EvaluationArtifactReference, ...],
) -> str:
    """Hash semantic bundle content independently from storage identity and time."""
    return snapshot_content_hash(
        {
            "project_id": str(project_id),
            "workflow_run_id": str(workflow_run_id),
            "scenario": scenario.to_snapshot(),
            "artifacts": [item.to_snapshot() for item in artifacts],
        }
    )
