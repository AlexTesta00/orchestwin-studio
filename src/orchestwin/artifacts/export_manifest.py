"""Canonical final-export manifests bound to an approved Gate 8 review."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final
from uuid import UUID, uuid4

from orchestwin.projects.requirements_primitives import (
    normalize_required_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus
from orchestwin.workflow.final_review import FinalReviewAssessment
from orchestwin.workflow.gates import HumanGate, HumanGateStatus, HumanGateType

_MAX_PATH_LENGTH: Final = 240
_MAX_TEXT_LENGTH: Final = 2_000
_MAX_MEDIA_TYPE_LENGTH: Final = 128
_SYNTHETIC_FEEDBACK_DISCLAIMER: Final = (
    "Synthetic User Twin feedback is simulated feedback and a design hypothesis; "
    "it is not empirical evidence of real-user behaviour."
)


class ExportArtifactCategory(StrEnum):
    """Stable categories visible in final package manifests."""

    PROJECT_BRIEF = "PROJECT_BRIEF"
    TEAM_SELECTION = "TEAM_SELECTION"
    PERSONA = "PERSONA"
    USER_TWIN = "USER_TWIN"
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"
    ARCHITECTURE = "ARCHITECTURE"
    TEST_PLAN = "TEST_PLAN"
    SOURCE = "SOURCE"
    TESTS = "TESTS"
    EXECUTION_EVIDENCE = "EXECUTION_EVIDENCE"
    SYNTHETIC_EVALUATION = "SYNTHETIC_EVALUATION"
    HUMAN_DECISIONS = "HUMAN_DECISIONS"
    TRACEABILITY = "TRACEABILITY"
    LIMITATIONS = "LIMITATIONS"
    SETUP_AND_RUN = "SETUP_AND_RUN"
    FINAL_REVIEW = "FINAL_REVIEW"


@dataclass(frozen=True, slots=True)
class FinalExportEntry:
    """One exact content-addressed file declared by an export manifest."""

    path: str
    category: ExportArtifactCategory
    artifact_id: UUID
    artifact_version: int
    content_hash: str
    media_type: str
    size_bytes: int
    required: bool

    def __post_init__(self) -> None:
        validate_export_path(self.path)
        validate_positive_integer(self.artifact_version, label="export artifact version")
        validate_sha256(self.content_hash, label="export artifact content hash")
        normalized_media_type = normalize_required_text(
            self.media_type,
            label="export artifact media type",
            maximum_length=_MAX_MEDIA_TYPE_LENGTH,
        )
        if normalized_media_type != self.media_type:
            raise ValueError("export artifact media type must be normalized")
        if isinstance(self.size_bytes, bool) or self.size_bytes < 0:
            raise ValueError("export artifact size must be a non-negative integer")

    @property
    def sort_key(self) -> tuple[str, str, int, str]:
        return (self.path, self.artifact_id.hex, self.artifact_version, self.content_hash)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "path": self.path,
            "category": self.category.value,
            "artifact_id": str(self.artifact_id),
            "artifact_version": self.artifact_version,
            "content_hash": self.content_hash,
            "media_type": self.media_type,
            "size_bytes": self.size_bytes,
            "required": self.required,
        }


@dataclass(frozen=True, slots=True)
class FinalExportOmission:
    """One expected category intentionally absent from the final package."""

    category: ExportArtifactCategory
    reason: str
    accepted_limitation_id: str | None = None

    def __post_init__(self) -> None:
        normalized_reason = normalize_required_text(
            self.reason,
            label="export omission reason",
            maximum_length=_MAX_TEXT_LENGTH,
        )
        if normalized_reason != self.reason:
            raise ValueError("export omission reason must be normalized")
        if self.accepted_limitation_id is not None:
            normalized_id = normalize_required_text(
                self.accepted_limitation_id,
                label="accepted limitation ID",
                maximum_length=128,
            )
            if normalized_id != self.accepted_limitation_id:
                raise ValueError("accepted limitation ID must be normalized")

    @property
    def sort_key(self) -> tuple[str, str]:
        return (self.category.value, self.accepted_limitation_id or "")

    def to_snapshot(self) -> dict[str, object]:
        return {
            "category": self.category.value,
            "reason": self.reason,
            "accepted_limitation_id": self.accepted_limitation_id,
        }


@dataclass(frozen=True, slots=True)
class FinalExportManifest:
    """Immutable complete package declaration for one approved workflow run."""

    id: UUID
    project_id: UUID
    workflow_run_id: UUID
    owner_user_id: UUID
    final_review_id: UUID
    final_review_version: int
    final_review_hash: str
    final_approval_gate_id: UUID
    final_approval_event_id: UUID
    capability_status: ExecutionCapabilityStatus | None
    entries: tuple[FinalExportEntry, ...]
    omissions: tuple[FinalExportOmission, ...]
    accepted_limitation_ids: tuple[str, ...]
    created_at: datetime
    content_hash: str
    schema_version: int = 1
    synthetic_feedback_disclaimer: str = _SYNTHETIC_FEEDBACK_DISCLAIMER
    owner_approval_is_empirical_validation: bool = False

    def __post_init__(self) -> None:
        validate_positive_integer(self.schema_version, label="export manifest schema version")
        validate_positive_integer(self.final_review_version, label="final review version")
        validate_sha256(self.final_review_hash, label="final review content hash")
        validate_sha256(self.content_hash, label="export manifest content hash")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("export manifest timestamp must be timezone-aware")
        if self.synthetic_feedback_disclaimer != _SYNTHETIC_FEEDBACK_DISCLAIMER:
            raise ValueError("export manifest must preserve the methodological disclaimer")
        if self.owner_approval_is_empirical_validation:
            raise ValueError("owner approval cannot be represented as empirical validation")
        if tuple(sorted(self.entries, key=lambda item: item.sort_key)) != self.entries:
            raise ValueError("export entries must use canonical order")
        if len({item.path for item in self.entries}) != len(self.entries):
            raise ValueError("export entry paths must be unique")
        if tuple(sorted(self.omissions, key=lambda item: item.sort_key)) != self.omissions:
            raise ValueError("export omissions must use canonical order")
        omitted_categories = {item.category for item in self.omissions}
        if len(omitted_categories) != len(self.omissions):
            raise ValueError("each export category may be omitted only once")
        present_categories = {item.category for item in self.entries}
        if present_categories & omitted_categories:
            raise ValueError("an export category cannot be present and omitted")
        normalized_limitation_ids = tuple(
            normalize_required_text(
                item,
                label="accepted limitation ID",
                maximum_length=128,
            )
            for item in self.accepted_limitation_ids
        )
        if normalized_limitation_ids != self.accepted_limitation_ids:
            raise ValueError("accepted limitation IDs must be normalized")
        if normalized_limitation_ids != tuple(sorted(set(normalized_limitation_ids))):
            raise ValueError("accepted limitation IDs must be canonical and unique")
        limitation_ids = set(self.accepted_limitation_ids)
        unknown_limitation_ids = {
            item.accepted_limitation_id
            for item in self.omissions
            if item.accepted_limitation_id is not None
            and item.accepted_limitation_id not in limitation_ids
        }
        if unknown_limitation_ids:
            raise ValueError("export omissions reference an unknown accepted limitation")
        accounted_categories = present_categories | omitted_categories
        if accounted_categories != set(ExportArtifactCategory):
            raise ValueError("every export category must be present or explicitly omitted")
        expected_hash = final_export_manifest_content_hash(
            manifest_id=self.id,
            project_id=self.project_id,
            workflow_run_id=self.workflow_run_id,
            owner_user_id=self.owner_user_id,
            final_review_id=self.final_review_id,
            final_review_version=self.final_review_version,
            final_review_hash=self.final_review_hash,
            final_approval_gate_id=self.final_approval_gate_id,
            final_approval_event_id=self.final_approval_event_id,
            capability_status=self.capability_status,
            entries=self.entries,
            omissions=self.omissions,
            accepted_limitation_ids=self.accepted_limitation_ids,
            schema_version=self.schema_version,
        )
        if expected_hash != self.content_hash:
            raise ValueError("export manifest content hash is inconsistent")

    def semantic_snapshot(self) -> dict[str, object]:
        return _final_export_manifest_snapshot(
            manifest_id=self.id,
            project_id=self.project_id,
            workflow_run_id=self.workflow_run_id,
            owner_user_id=self.owner_user_id,
            final_review_id=self.final_review_id,
            final_review_version=self.final_review_version,
            final_review_hash=self.final_review_hash,
            final_approval_gate_id=self.final_approval_gate_id,
            final_approval_event_id=self.final_approval_event_id,
            capability_status=self.capability_status,
            entries=self.entries,
            omissions=self.omissions,
            accepted_limitation_ids=self.accepted_limitation_ids,
            schema_version=self.schema_version,
        )

    def to_snapshot(self) -> dict[str, object]:
        return {
            **self.semantic_snapshot(),
            "created_at": self.created_at.isoformat(),
            "content_hash": self.content_hash,
            "synthetic_feedback_disclaimer": self.synthetic_feedback_disclaimer,
            "owner_approval_is_empirical_validation": False,
        }


def create_final_export_manifest(
    review: FinalReviewAssessment,
    *,
    approved_gate: HumanGate,
    approval_event_id: UUID,
    entries: tuple[FinalExportEntry, ...],
    omissions: tuple[FinalExportOmission, ...] = (),
    manifest_id: UUID | None = None,
    created_at: datetime,
) -> FinalExportManifest:
    """Create a canonical manifest only for the exact approved Gate 8 review."""
    if not review.ready_for_gate8:
        raise ValueError("final export requires a Gate 8-ready final review")
    if approved_gate.gate_type is not HumanGateType.FINAL_OUTPUT:
        raise ValueError("final export requires the Gate 8 final-output gate")
    if approved_gate.status is not HumanGateStatus.APPROVED:
        raise ValueError("final export requires an approved Gate 8")
    if (
        approved_gate.project_id != review.project_id
        or approved_gate.owner_user_id != review.owner_user_id
        or approved_gate.artifact.artifact_id != review.id
        or approved_gate.artifact.version != review.version_number
        or approved_gate.artifact.content_hash != review.content_hash
    ):
        raise ValueError("Gate 8 does not govern the exact final-review version")

    ordered_entries = tuple(sorted(entries, key=lambda item: item.sort_key))
    ordered_omissions = tuple(sorted(omissions, key=lambda item: item.sort_key))
    limitation_ids = {item.limitation_id for item in review.accepted_limitations}
    for omission in ordered_omissions:
        if (
            omission.accepted_limitation_id is not None
            and omission.accepted_limitation_id not in limitation_ids
        ):
            raise ValueError("export omission is not backed by the final review")
    identifier = manifest_id or uuid4()
    content_hash = final_export_manifest_content_hash(
        manifest_id=identifier,
        project_id=review.project_id,
        workflow_run_id=review.workflow_run_id,
        owner_user_id=review.owner_user_id,
        final_review_id=review.id,
        final_review_version=review.version_number,
        final_review_hash=review.content_hash,
        final_approval_gate_id=approved_gate.id,
        final_approval_event_id=approval_event_id,
        capability_status=review.capability_status,
        entries=ordered_entries,
        omissions=ordered_omissions,
        accepted_limitation_ids=tuple(sorted(limitation_ids)),
        schema_version=1,
    )
    return FinalExportManifest(
        id=identifier,
        project_id=review.project_id,
        workflow_run_id=review.workflow_run_id,
        owner_user_id=review.owner_user_id,
        final_review_id=review.id,
        final_review_version=review.version_number,
        final_review_hash=review.content_hash,
        final_approval_gate_id=approved_gate.id,
        final_approval_event_id=approval_event_id,
        capability_status=review.capability_status,
        entries=ordered_entries,
        omissions=ordered_omissions,
        accepted_limitation_ids=tuple(sorted(limitation_ids)),
        created_at=created_at,
        content_hash=content_hash,
    )


def final_export_manifest_content_hash(
    *,
    manifest_id: UUID,
    project_id: UUID,
    workflow_run_id: UUID,
    owner_user_id: UUID,
    final_review_id: UUID,
    final_review_version: int,
    final_review_hash: str,
    final_approval_gate_id: UUID,
    final_approval_event_id: UUID,
    capability_status: ExecutionCapabilityStatus | None,
    entries: tuple[FinalExportEntry, ...],
    omissions: tuple[FinalExportOmission, ...],
    accepted_limitation_ids: tuple[str, ...],
    schema_version: int,
) -> str:
    return snapshot_content_hash(
        _final_export_manifest_snapshot(
            manifest_id=manifest_id,
            project_id=project_id,
            workflow_run_id=workflow_run_id,
            owner_user_id=owner_user_id,
            final_review_id=final_review_id,
            final_review_version=final_review_version,
            final_review_hash=final_review_hash,
            final_approval_gate_id=final_approval_gate_id,
            final_approval_event_id=final_approval_event_id,
            capability_status=capability_status,
            entries=entries,
            omissions=omissions,
            accepted_limitation_ids=accepted_limitation_ids,
            schema_version=schema_version,
        )
    )


def validate_export_path(path: str) -> None:
    """Reject traversal, platform-specific, ambiguous, and reserved ZIP paths."""
    normalized = normalize_required_text(
        path,
        label="export path",
        maximum_length=_MAX_PATH_LENGTH,
    )
    if normalized != path:
        raise ValueError("export path must be normalized")
    if "\\" in path or path.startswith("/"):
        raise ValueError("export path must be a relative POSIX path")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("export path contains an unsafe segment")
    if pure.parts[0].endswith(":"):
        raise ValueError("export path must not contain a drive prefix")
    if path == "manifest.json":
        raise ValueError("manifest.json is reserved for the generated package manifest")


def _final_export_manifest_snapshot(
    *,
    manifest_id: UUID,
    project_id: UUID,
    workflow_run_id: UUID,
    owner_user_id: UUID,
    final_review_id: UUID,
    final_review_version: int,
    final_review_hash: str,
    final_approval_gate_id: UUID,
    final_approval_event_id: UUID,
    capability_status: ExecutionCapabilityStatus | None,
    entries: tuple[FinalExportEntry, ...],
    omissions: tuple[FinalExportOmission, ...],
    accepted_limitation_ids: tuple[str, ...],
    schema_version: int,
) -> dict[str, object]:
    return {
        "schema_version": schema_version,
        "manifest_id": str(manifest_id),
        "project_id": str(project_id),
        "workflow_run_id": str(workflow_run_id),
        "owner_user_id": str(owner_user_id),
        "final_review": {
            "id": str(final_review_id),
            "version": final_review_version,
            "content_hash": final_review_hash,
        },
        "final_approval": {
            "gate_id": str(final_approval_gate_id),
            "event_id": str(final_approval_event_id),
        },
        "capability_status": capability_status.value if capability_status else None,
        "entries": [item.to_snapshot() for item in entries],
        "omissions": [item.to_snapshot() for item in omissions],
        "accepted_limitation_ids": list(accepted_limitation_ids),
    }
