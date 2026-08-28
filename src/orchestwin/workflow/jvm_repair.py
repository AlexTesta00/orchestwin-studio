"""Bounded, approval-aware JVM repair revisions and minimal rerun planning."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final
from uuid import UUID

from orchestwin.artifacts.jvm_change_sets import (
    JvmSourceChange,
    JvmSourceChangeOperation,
    JvmSourceChangeSet,
    JvmSourceChangeValidationReport,
    JvmSourceChangeValidationStatus,
    validate_jvm_source_change_set,
)
from orchestwin.artifacts.jvm_source_plans import JvmSourceContentStore
from orchestwin.artifacts.jvm_sources import (
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    JvmSourceRevision,
    JvmSourceRevisionReference,
)
from orchestwin.jvm_execution.evidence import JvmFailureSignature
from orchestwin.jvm_execution.plans import JvmExecutionPhase

_HASH_CHUNK_SIZE: Final = 1024 * 1024
_TEST_DIRECTORY_NAMES: Final = frozenset({"spec", "specs", "test", "tests"})


class JvmRepairApplicationStatus(StrEnum):
    """Typed result of applying one exact JVM repair proposal."""

    APPLIED = "APPLIED"
    REQUIRES_OWNER_APPROVAL = "REQUIRES_OWNER_APPROVAL"
    REJECTED = "REJECTED"
    PAUSED_NEEDS_HUMAN = "PAUSED_NEEDS_HUMAN"
    STALE_BASE_REVISION = "STALE_BASE_REVISION"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class JvmRepairPolicy:
    """Operational limits that pause instead of fabricating repair success."""

    maximum_attempts_per_failure_signature: int = 5
    maximum_identical_failure_occurrences: int = 2

    def __post_init__(self) -> None:
        values = (
            self.maximum_attempts_per_failure_signature,
            self.maximum_identical_failure_occurrences,
        )
        if any(isinstance(value, bool) or value < 1 for value in values):
            raise ValueError("JVM repair limits must be positive integers")


DEFAULT_JVM_REPAIR_POLICY: Final = JvmRepairPolicy()


@dataclass(frozen=True, slots=True)
class JvmRepairApprovalReference:
    """Gate 7 approval bound to the exact repair, base, and failure tuple."""

    approval_id: UUID
    project_id: UUID
    change_set_id: UUID
    change_set_content_hash: str
    base_revision_content_hash: str
    failure_signature: str
    approved_by_user_id: UUID

    def __post_init__(self) -> None:
        for value, label in (
            (self.change_set_content_hash, "JVM repair approval change-set hash"),
            (self.base_revision_content_hash, "JVM repair approval base hash"),
            (self.failure_signature, "JVM repair approval failure signature"),
        ):
            _validate_sha256(value, label=label)

    def approves(
        self,
        *,
        proposal: JvmRepairProposal,
        base_revision: JvmSourceRevision,
    ) -> bool:
        return (
            self.project_id == proposal.project_id
            and self.change_set_id == proposal.change_set.id
            and self.change_set_content_hash == proposal.change_set.content_hash
            and self.base_revision_content_hash == base_revision.content_hash
            and self.failure_signature == proposal.failure_signature.signature
            and self.approved_by_user_id == proposal.created_by_user_id
        )

    def to_snapshot(self) -> dict[str, str]:
        return {
            "approval_id": str(self.approval_id),
            "project_id": str(self.project_id),
            "change_set_id": str(self.change_set_id),
            "change_set_content_hash": self.change_set_content_hash,
            "base_revision_content_hash": self.base_revision_content_hash,
            "failure_signature": self.failure_signature,
            "approved_by_user_id": str(self.approved_by_user_id),
        }


@dataclass(frozen=True, slots=True)
class JvmRepairProposal:
    """One typed JVM repair proposal tied to a stable failure signature."""

    id: UUID
    project_id: UUID
    created_by_user_id: UUID
    base_revision: JvmSourceRevisionReference
    failure_signature: JvmFailureSignature
    change_set: JvmSourceChangeSet
    attempt_number: int
    identical_failure_occurrences: int
    provenance_references: tuple[JvmSourceProvenanceReference, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if self.project_id != self.base_revision.project_id:
            raise ValueError("JVM repair proposal and base revision projects differ")
        if self.project_id != self.change_set.project_id:
            raise ValueError("JVM repair proposal and change-set projects differ")
        if self.change_set.base_revision != self.base_revision:
            raise ValueError("JVM repair change set targets another base revision")
        if isinstance(self.attempt_number, bool) or self.attempt_number < 1:
            raise ValueError("JVM repair attempt number must be positive")
        if (
            isinstance(self.identical_failure_occurrences, bool)
            or self.identical_failure_occurrences < 1
        ):
            raise ValueError("JVM identical failure occurrences must be positive")
        ordered = tuple(
            sorted(
                self.provenance_references,
                key=lambda item: (item.kind.value, item.reference_id, item.version_number),
            )
        )
        if self.provenance_references != ordered or len(ordered) != len(set(ordered)):
            raise ValueError("JVM repair provenance must be canonical and unique")
        if not any(
            reference.kind is JvmSourceProvenanceKind.FAILURE_SIGNATURE
            and reference.content_hash == self.failure_signature.signature
            for reference in self.provenance_references
        ):
            raise ValueError("JVM repair proposal requires exact failure provenance")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("JVM repair proposal timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class JvmRepairApplicationResult:
    """Outcome preserving validation, optional revision, and rerun scope."""

    status: JvmRepairApplicationStatus
    validation_report: JvmSourceChangeValidationReport
    revision: JvmSourceRevision | None
    required_rerun_phases: tuple[JvmExecutionPhase, ...]
    failure_message: str | None

    def __post_init__(self) -> None:
        successful = self.status is JvmRepairApplicationStatus.APPLIED
        if successful:
            if (
                self.revision is None
                or not self.required_rerun_phases
                or self.failure_message is not None
            ):
                raise ValueError("applied JVM repair requires revision and rerun phases")
        elif (
            self.revision is not None or self.required_rerun_phases or self.failure_message is None
        ):
            raise ValueError("unapplied JVM repair requires only a failure message")
        order = {phase: index for index, phase in enumerate(JvmExecutionPhase)}
        if self.required_rerun_phases != tuple(
            sorted(self.required_rerun_phases, key=order.__getitem__)
        ) or len(self.required_rerun_phases) != len(set(self.required_rerun_phases)):
            raise ValueError("JVM repair rerun phases must be canonical and unique")


def apply_jvm_repair_revision(
    proposal: JvmRepairProposal,
    *,
    base_revision: JvmSourceRevision,
    revision_id: UUID,
    created_by_user_id: UUID,
    created_at: datetime,
    content_store: JvmSourceContentStore,
    approval: JvmRepairApprovalReference | None = None,
    policy: JvmRepairPolicy = DEFAULT_JVM_REPAIR_POLICY,
) -> JvmRepairApplicationResult:
    """Validate and project one JVM repair into a new immutable revision."""
    validation = validate_jvm_source_change_set(
        proposal.change_set,
        base_revision=base_revision,
    )
    if proposal.base_revision != base_revision.reference:
        return _failed_result(
            JvmRepairApplicationStatus.STALE_BASE_REVISION,
            validation,
            "Repair proposal targets a stale JVM source revision.",
        )
    if created_by_user_id != proposal.created_by_user_id:
        return _failed_result(
            JvmRepairApplicationStatus.REJECTED,
            validation,
            "Repair revision creator differs from the proposal owner.",
        )
    if (
        proposal.attempt_number > policy.maximum_attempts_per_failure_signature
        or proposal.identical_failure_occurrences > policy.maximum_identical_failure_occurrences
    ):
        return _failed_result(
            JvmRepairApplicationStatus.PAUSED_NEEDS_HUMAN,
            validation,
            "Repair limits were exhausted; human review is required.",
        )
    if validation.status is JvmSourceChangeValidationStatus.REJECTED:
        return _failed_result(
            JvmRepairApplicationStatus.REJECTED,
            validation,
            "Repair change set violates JVM source safety or operation semantics.",
        )
    if validation.status is JvmSourceChangeValidationStatus.REQUIRES_OWNER_APPROVAL and (
        approval is None or not approval.approves(proposal=proposal, base_revision=base_revision)
    ):
        return _failed_result(
            JvmRepairApplicationStatus.REQUIRES_OWNER_APPROVAL,
            validation,
            "High-impact JVM repair requires an exact current Gate 7 approval.",
        )

    projected_files = {file.normalized_path: file for file in base_revision.files}
    for change in proposal.change_set.changes:
        if change.operation is JvmSourceChangeOperation.DELETE:
            projected_files.pop(change.normalized_path)
            continue
        if not _content_matches(change, content_store=content_store):
            return _failed_result(
                JvmRepairApplicationStatus.CONTENT_UNAVAILABLE,
                validation,
                "Repair content is missing or does not match its declared metadata.",
            )
        projected_files[change.normalized_path] = change.to_file_entry()
    if not projected_files:
        return _failed_result(
            JvmRepairApplicationStatus.REJECTED,
            validation,
            "Repair change set cannot remove every JVM source file.",
        )

    provenance = tuple(
        sorted(
            set((*base_revision.provenance_references, *proposal.provenance_references)),
            key=lambda item: (item.kind.value, item.reference_id, item.version_number),
        )
    )
    revision = JvmSourceRevision(
        id=revision_id,
        project_id=base_revision.project_id,
        created_by_user_id=created_by_user_id,
        version_number=base_revision.version_number + 1,
        based_on=base_revision.reference,
        target_selection=base_revision.target_selection,
        validation_scope_hash=base_revision.validation_scope_hash,
        origin=JvmSourceOrigin.REPAIR_CHANGE_SET,
        files=tuple(
            sorted(
                projected_files.values(),
                key=lambda item: (item.normalized_path.casefold(), item.normalized_path),
            )
        ),
        provenance_references=provenance,
        related_failure_signature=proposal.failure_signature.signature,
        created_at=created_at,
    )
    return JvmRepairApplicationResult(
        status=JvmRepairApplicationStatus.APPLIED,
        validation_report=validation,
        revision=revision,
        required_rerun_phases=_required_rerun_phases(proposal.change_set.changes),
        failure_message=None,
    )


def _required_rerun_phases(
    changes: tuple[JvmSourceChange, ...],
) -> tuple[JvmExecutionPhase, ...]:
    if any(change.is_high_impact for change in changes):
        return tuple(JvmExecutionPhase)
    if all(_is_test_path(change.normalized_path) for change in changes):
        included = {
            JvmExecutionPhase.VALIDATE,
            JvmExecutionPhase.TEST,
            JvmExecutionPhase.RUN,
            JvmExecutionPhase.COLLECT_ARTIFACTS,
        }
    else:
        included = {
            JvmExecutionPhase.VALIDATE,
            JvmExecutionPhase.STATIC_CHECKS,
            JvmExecutionPhase.BUILD,
            JvmExecutionPhase.TEST,
            JvmExecutionPhase.RUN,
            JvmExecutionPhase.COLLECT_ARTIFACTS,
        }
    return tuple(phase for phase in JvmExecutionPhase if phase in included)


def _is_test_path(path: str) -> bool:
    pure_path = PurePosixPath(path)
    parts = tuple(part.casefold() for part in pure_path.parts)
    name = pure_path.name.casefold()
    stem = pure_path.stem.casefold()
    return (
        any(part in _TEST_DIRECTORY_NAMES for part in parts[:-1])
        or name.startswith("test_")
        or stem.endswith("test")
        or stem.endswith("spec")
    )


def _content_matches(
    change: JvmSourceChange,
    *,
    content_store: JvmSourceContentStore,
) -> bool:
    assert change.storage_key is not None
    assert change.content_sha256 is not None
    assert change.size_bytes is not None
    content = content_store.read(change.storage_key)
    if content is None or len(content) != change.size_bytes:
        return False
    digest = hashlib.sha256()
    for start in range(0, len(content), _HASH_CHUNK_SIZE):
        digest.update(content[start : start + _HASH_CHUNK_SIZE])
    return digest.hexdigest() == change.content_sha256


def _failed_result(
    status: JvmRepairApplicationStatus,
    validation: JvmSourceChangeValidationReport,
    message: str,
) -> JvmRepairApplicationResult:
    return JvmRepairApplicationResult(
        status=status,
        validation_report=validation,
        revision=None,
        required_rerun_phases=(),
        failure_message=message,
    )


def _validate_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase SHA-256")
