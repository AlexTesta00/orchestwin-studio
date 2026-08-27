"""Bounded, approval-aware Web repair revisions and minimal rerun planning."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Final
from uuid import UUID

from orchestwin.artifacts.web_change_sets import (
    WebSourceChange,
    WebSourceChangeOperation,
    WebSourceChangeSet,
    WebSourceChangeValidationReport,
    WebSourceChangeValidationStatus,
    validate_web_source_change_set,
)
from orchestwin.artifacts.web_source_plans import WebSourceContentStore
from orchestwin.artifacts.web_sources import (
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    WebSourceRevision,
    WebSourceRevisionReference,
)
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.reports import WebFailureSignature

_HASH_CHUNK_SIZE: Final = 1024 * 1024
_TEST_DIRECTORY_NAMES: Final = frozenset({"__tests__", "spec", "specs", "test", "tests"})


class WebRepairApplicationStatus(StrEnum):
    """Typed result of applying one exact repair proposal."""

    APPLIED = "APPLIED"
    REQUIRES_OWNER_APPROVAL = "REQUIRES_OWNER_APPROVAL"
    REJECTED = "REJECTED"
    PAUSED_NEEDS_HUMAN = "PAUSED_NEEDS_HUMAN"
    STALE_BASE_REVISION = "STALE_BASE_REVISION"
    CONTENT_UNAVAILABLE = "CONTENT_UNAVAILABLE"


@dataclass(frozen=True, slots=True)
class WebRepairPolicy:
    """Operational limits that pause rather than fabricate repair success."""

    maximum_attempts_per_failure_signature: int = 5
    maximum_identical_failure_occurrences: int = 2

    def __post_init__(self) -> None:
        values = (
            self.maximum_attempts_per_failure_signature,
            self.maximum_identical_failure_occurrences,
        )
        if any(isinstance(value, bool) or value < 1 for value in values):
            raise ValueError("Web repair limits must be positive integers")


DEFAULT_WEB_REPAIR_POLICY: Final = WebRepairPolicy()


@dataclass(frozen=True, slots=True)
class WebRepairApprovalReference:
    """Gate 7 approval bound to the exact repair, base, and failure tuple."""

    approval_id: UUID
    project_id: UUID
    change_set_id: UUID
    change_set_content_hash: str
    base_revision_content_hash: str
    failure_signature_digest: str
    approved_by_user_id: UUID

    def __post_init__(self) -> None:
        for value, label in (
            (self.change_set_content_hash, "Web repair approval change-set hash"),
            (self.base_revision_content_hash, "Web repair approval base hash"),
            (self.failure_signature_digest, "Web repair approval failure hash"),
        ):
            _validate_sha256(value, label=label)

    def approves(
        self,
        *,
        proposal: WebRepairProposal,
        base_revision: WebSourceRevision,
    ) -> bool:
        return (
            self.project_id == proposal.project_id
            and self.change_set_id == proposal.change_set.id
            and self.change_set_content_hash == proposal.change_set.content_hash
            and self.base_revision_content_hash == base_revision.content_hash
            and self.failure_signature_digest == proposal.failure_signature.digest
        )

    def to_snapshot(self) -> dict[str, str]:
        return {
            "approval_id": str(self.approval_id),
            "project_id": str(self.project_id),
            "change_set_id": str(self.change_set_id),
            "change_set_content_hash": self.change_set_content_hash,
            "base_revision_content_hash": self.base_revision_content_hash,
            "failure_signature_digest": self.failure_signature_digest,
            "approved_by_user_id": str(self.approved_by_user_id),
        }


@dataclass(frozen=True, slots=True)
class WebRepairProposal:
    """One typed repair proposal tied to a stable failure signature."""

    id: UUID
    project_id: UUID
    created_by_user_id: UUID
    base_revision: WebSourceRevisionReference
    failure_signature: WebFailureSignature
    change_set: WebSourceChangeSet
    attempt_number: int
    identical_failure_occurrences: int
    provenance_references: tuple[WebSourceProvenanceReference, ...]
    created_at: datetime

    def __post_init__(self) -> None:
        if self.project_id != self.base_revision.project_id:
            raise ValueError("Web repair proposal and base revision projects differ")
        if self.project_id != self.change_set.project_id:
            raise ValueError("Web repair proposal and change-set projects differ")
        if self.change_set.base_revision != self.base_revision:
            raise ValueError("Web repair change set targets another base revision")
        if isinstance(self.attempt_number, bool) or self.attempt_number < 1:
            raise ValueError("Web repair attempt number must be positive")
        if (
            isinstance(self.identical_failure_occurrences, bool)
            or self.identical_failure_occurrences < 1
        ):
            raise ValueError("Web identical failure occurrences must be positive")
        ordered = tuple(
            sorted(
                self.provenance_references,
                key=lambda item: (item.kind.value, item.reference_id, item.version_number),
            )
        )
        if self.provenance_references != ordered or len(ordered) != len(set(ordered)):
            raise ValueError("Web repair provenance must be canonical and unique")
        if not any(
            reference.kind is WebSourceProvenanceKind.FAILURE_SIGNATURE
            and reference.content_hash == self.failure_signature.digest
            for reference in self.provenance_references
        ):
            raise ValueError("Web repair proposal requires exact failure provenance")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("Web repair proposal timestamp must be timezone-aware")


@dataclass(frozen=True, slots=True)
class WebRepairApplicationResult:
    """Outcome preserving validation, optional revision, and rerun scope."""

    status: WebRepairApplicationStatus
    validation_report: WebSourceChangeValidationReport
    revision: WebSourceRevision | None
    required_rerun_phases: tuple[WebExecutionPhase, ...]
    failure_message: str | None

    def __post_init__(self) -> None:
        successful = self.status is WebRepairApplicationStatus.APPLIED
        if successful:
            if (
                self.revision is None
                or not self.required_rerun_phases
                or self.failure_message is not None
            ):
                raise ValueError("applied Web repair requires revision and rerun phases")
        elif (
            self.revision is not None or self.required_rerun_phases or self.failure_message is None
        ):
            raise ValueError("unapplied Web repair requires only a failure message")
        order = {phase: index for index, phase in enumerate(WebExecutionPhase)}
        if self.required_rerun_phases != tuple(
            sorted(self.required_rerun_phases, key=order.__getitem__)
        ) or len(self.required_rerun_phases) != len(set(self.required_rerun_phases)):
            raise ValueError("Web repair rerun phases must be canonical and unique")


def apply_web_repair_revision(
    proposal: WebRepairProposal,
    *,
    base_revision: WebSourceRevision,
    revision_id: UUID,
    created_by_user_id: UUID,
    created_at: datetime,
    content_store: WebSourceContentStore,
    approval: WebRepairApprovalReference | None = None,
    policy: WebRepairPolicy = DEFAULT_WEB_REPAIR_POLICY,
) -> WebRepairApplicationResult:
    """Validate and project one repair into a new immutable source revision."""
    validation = validate_web_source_change_set(
        proposal.change_set,
        base_revision=base_revision,
    )
    if proposal.base_revision != base_revision.reference:
        return _failed_result(
            WebRepairApplicationStatus.STALE_BASE_REVISION,
            validation,
            "Repair proposal targets a stale source revision.",
        )
    if (
        proposal.attempt_number > policy.maximum_attempts_per_failure_signature
        or proposal.identical_failure_occurrences > policy.maximum_identical_failure_occurrences
    ):
        return _failed_result(
            WebRepairApplicationStatus.PAUSED_NEEDS_HUMAN,
            validation,
            "Repair limits were exhausted; human review is required.",
        )
    if validation.status is WebSourceChangeValidationStatus.REJECTED:
        return _failed_result(
            WebRepairApplicationStatus.REJECTED,
            validation,
            "Repair change set violates source safety or operation semantics.",
        )
    if validation.status is WebSourceChangeValidationStatus.REQUIRES_OWNER_APPROVAL and (
        approval is None or not approval.approves(proposal=proposal, base_revision=base_revision)
    ):
        return _failed_result(
            WebRepairApplicationStatus.REQUIRES_OWNER_APPROVAL,
            validation,
            "High-impact repair requires an exact current Gate 7 approval.",
        )

    projected_files = {file.normalized_path: file for file in base_revision.files}
    for change in proposal.change_set.changes:
        if change.operation is WebSourceChangeOperation.DELETE:
            projected_files.pop(change.normalized_path)
            continue
        if not _content_matches(change, content_store=content_store):
            return _failed_result(
                WebRepairApplicationStatus.CONTENT_UNAVAILABLE,
                validation,
                "Repair content is missing or does not match its declared metadata.",
            )
        projected_files[change.normalized_path] = change.to_file_entry()
    if not projected_files:
        return _failed_result(
            WebRepairApplicationStatus.REJECTED,
            validation,
            "Repair change set cannot remove every source file.",
        )

    provenance = tuple(
        sorted(
            set((*base_revision.provenance_references, *proposal.provenance_references)),
            key=lambda item: (item.kind.value, item.reference_id, item.version_number),
        )
    )
    revision = WebSourceRevision(
        id=revision_id,
        project_id=base_revision.project_id,
        created_by_user_id=created_by_user_id,
        version_number=base_revision.version_number + 1,
        based_on=base_revision.reference,
        target_selection=base_revision.target_selection,
        validation_scope_hash=base_revision.validation_scope_hash,
        origin=WebSourceOrigin.REPAIR_CHANGE_SET,
        files=tuple(
            sorted(
                projected_files.values(),
                key=lambda item: (item.normalized_path.casefold(), item.normalized_path),
            )
        ),
        provenance_references=provenance,
        related_failure_signature=proposal.failure_signature.digest,
        created_at=created_at,
    )
    return WebRepairApplicationResult(
        status=WebRepairApplicationStatus.APPLIED,
        validation_report=validation,
        revision=revision,
        required_rerun_phases=_required_rerun_phases(proposal.change_set.changes),
        failure_message=None,
    )


def _required_rerun_phases(
    changes: tuple[WebSourceChange, ...],
) -> tuple[WebExecutionPhase, ...]:
    if any(change.is_high_impact for change in changes):
        return tuple(WebExecutionPhase)
    if all(_is_test_path(change.normalized_path) for change in changes):
        included = {
            WebExecutionPhase.VALIDATE,
            WebExecutionPhase.TEST,
            WebExecutionPhase.RUN,
            WebExecutionPhase.HEALTH_CHECK,
            WebExecutionPhase.BROWSER_EVIDENCE,
            WebExecutionPhase.COLLECT_ARTIFACTS,
        }
    else:
        included = {
            WebExecutionPhase.VALIDATE,
            WebExecutionPhase.STATIC_CHECK,
            WebExecutionPhase.BUILD,
            WebExecutionPhase.TEST,
            WebExecutionPhase.RUN,
            WebExecutionPhase.HEALTH_CHECK,
            WebExecutionPhase.BROWSER_EVIDENCE,
            WebExecutionPhase.COLLECT_ARTIFACTS,
        }
    return tuple(phase for phase in WebExecutionPhase if phase in included)


def _is_test_path(path: str) -> bool:
    pure_path = PurePosixPath(path)
    parts = tuple(part.casefold() for part in pure_path.parts)
    name = pure_path.name.casefold()
    stem = pure_path.stem.casefold()
    return (
        any(part in _TEST_DIRECTORY_NAMES for part in parts[:-1])
        or name.startswith("test_")
        or stem.endswith("_test")
        or ".spec." in name
        or ".test." in name
    )


def _content_matches(
    change: WebSourceChange,
    *,
    content_store: WebSourceContentStore,
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
    status: WebRepairApplicationStatus,
    validation: WebSourceChangeValidationReport,
    message: str,
) -> WebRepairApplicationResult:
    return WebRepairApplicationResult(
        status=status,
        validation_report=validation,
        revision=None,
        required_rerun_phases=(),
        failure_message=message,
    )


def _validate_sha256(value: str, *, label: str) -> None:
    if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
        raise ValueError(f"{label} must be lowercase SHA-256")
