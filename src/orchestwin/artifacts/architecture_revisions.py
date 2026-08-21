"""Owner-controlled immutable revisions for Architecture Packages."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from orchestwin.artifacts.architecture_packages import (
    ArchitecturePackageVersion,
    ArchitecturePlanningPackage,
)
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    normalize_optional_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)

_MAX_REVISION_REASON_LENGTH: Final = 2000


class ArchitectureChangeKind(StrEnum):
    """Supported changes in an Architecture Package replacement diff."""

    REPLACE = "REPLACE"


class ArchitectureArtifactKind(StrEnum):
    """Architecture Package sections represented in an owner diff."""

    ARCHITECTURE = "ARCHITECTURE"
    TEST_PLAN = "TEST_PLAN"
    OPEN_QUESTIONS = "OPEN_QUESTIONS"


class ArchitecturePackageDiffStatus(StrEnum):
    """Owner decision state of a proposed Architecture Package diff."""

    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ArchitectureRevisionDecision(StrEnum):
    """Allowed owner decisions for one proposed Architecture Package diff."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ArchitectureRevisionIssueCode(StrEnum):
    """Expected reasons an Architecture Package revision cannot continue."""

    PROJECT_MISMATCH = "PROJECT_MISMATCH"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    IDENTIFIER_CHANGED = "IDENTIFIER_CHANGED"
    NO_CHANGES = "NO_CHANGES"
    DIFF_ALREADY_DECIDED = "DIFF_ALREADY_DECIDED"
    BASE_VERSION_STALE = "BASE_VERSION_STALE"
    ACTOR_NOT_OWNER = "ACTOR_NOT_OWNER"
    REASON_REQUIRED = "REASON_REQUIRED"
    REASON_TOO_LONG = "REASON_TOO_LONG"
    TIMESTAMP_NOT_AWARE = "TIMESTAMP_NOT_AWARE"
    TIMESTAMP_OUT_OF_ORDER = "TIMESTAMP_OUT_OF_ORDER"


class ArchitectureRevisionProposalStatus(StrEnum):
    """Stable outcome of proposing an Architecture Package replacement."""

    CREATED = "CREATED"
    REJECTED = "REJECTED"


class ArchitectureRevisionDecisionStatus(StrEnum):
    """Stable outcome of deciding an Architecture Package diff."""

    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class _CodedArtifact(Protocol):
    """Identity shared by stable architecture and test-plan collections."""

    id: UUID
    code: str


@dataclass(frozen=True, slots=True)
class ArchitecturePackageChange:
    """One explicit before/after replacement inside an Architecture Package diff."""

    kind: ArchitectureChangeKind
    artifact_kind: ArchitectureArtifactKind
    artifact_id: UUID
    before: dict[str, object]
    after: dict[str, object]

    def __post_init__(self) -> None:
        """Protect meaningful replacement snapshots."""
        if self.before == self.after:
            raise ValueError("Architecture Package changes require different snapshots")

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """Return deterministic change ordering metadata."""
        return (
            self.artifact_kind.value,
            self.artifact_id.hex,
            self.kind.value,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic Architecture Package change snapshot."""
        return {
            "kind": self.kind.value,
            "artifact_kind": self.artifact_kind.value,
            "artifact_id": str(self.artifact_id),
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True, slots=True)
class ArchitecturePackageDiff:
    """One immutable owner-reviewable Architecture Package replacement."""

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    base_version_id: UUID
    base_version_number: int
    base_content_hash: str
    proposed_package: ArchitecturePlanningPackage
    proposal_hash: str
    changes: tuple[ArchitecturePackageChange, ...]
    status: ArchitecturePackageDiffStatus
    created_at: datetime
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    applied_version_id: UUID | None = None

    def __post_init__(self) -> None:
        """Protect proposal identity, chronology, and decision metadata."""
        validate_positive_integer(
            self.base_version_number,
            label="Architecture Package diff base version",
        )
        validate_sha256(
            self.base_content_hash,
            label="Architecture Package diff base hash",
        )
        validate_sha256(
            self.proposal_hash,
            label="Architecture Package diff proposal hash",
        )

        if self.proposed_package.project_id != self.project_id:
            raise ValueError("Architecture Package diff must belong to its project")

        if self.proposal_hash != self.proposed_package.content_hash:
            raise ValueError("Architecture Package diff proposal hash must match its package")

        if self.created_at.utcoffset() is None:
            raise ValueError("Architecture Package diff timestamp must be timezone-aware")

        if not self.changes:
            raise ValueError("Architecture Package diff must contain changes")

        expected_changes = tuple(sorted(self.changes, key=lambda change: change.sort_key))

        if self.changes != expected_changes:
            raise ValueError("Architecture Package changes must use canonical order")

        change_keys = tuple(change.sort_key for change in self.changes)
        if len(change_keys) != len(set(change_keys)):
            raise ValueError("Architecture Package changes must be unique")

        normalized_reason = normalize_optional_text(
            self.decision_reason,
            label="Architecture Package diff decision reason",
            maximum_length=_MAX_REVISION_REASON_LENGTH,
        )

        if normalized_reason != self.decision_reason:
            raise ValueError("Architecture Package diff decision reason must be normalized")

        if self.status is ArchitecturePackageDiffStatus.PROPOSED:
            if any(
                value is not None
                for value in (
                    self.decided_by_user_id,
                    self.decided_at,
                    self.decision_reason,
                    self.applied_version_id,
                )
            ):
                raise ValueError("a proposed Architecture Package diff must not be decided")
            return

        if self.decided_by_user_id is None or self.decided_at is None:
            raise ValueError("a decided Architecture Package diff requires decision metadata")

        if self.decided_at.utcoffset() is None:
            raise ValueError("Architecture Package diff decision timestamp must be timezone-aware")

        if self.decided_at < self.created_at:
            raise ValueError("Architecture Package diff decision must not precede creation")

        if self.status is ArchitecturePackageDiffStatus.APPROVED:
            if self.applied_version_id is None:
                raise ValueError(
                    "an approved Architecture Package diff requires an applied version"
                )
        elif self.applied_version_id is not None:
            raise ValueError("a rejected Architecture Package diff must not apply a version")

        if self.status is ArchitecturePackageDiffStatus.REJECTED and self.decision_reason is None:
            raise ValueError("a rejected Architecture Package diff requires a reason")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic Architecture Package diff snapshot."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "owner_user_id": str(self.owner_user_id),
            "base_version_id": str(self.base_version_id),
            "base_version_number": self.base_version_number,
            "base_content_hash": self.base_content_hash,
            "proposed_package": self.proposed_package.to_snapshot(),
            "proposal_hash": self.proposal_hash,
            "changes": [change.to_snapshot() for change in self.changes],
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "decided_by_user_id": (
                None if self.decided_by_user_id is None else str(self.decided_by_user_id)
            ),
            "decided_at": (None if self.decided_at is None else self.decided_at.isoformat()),
            "decision_reason": self.decision_reason,
            "applied_version_id": (
                None if self.applied_version_id is None else str(self.applied_version_id)
            ),
        }

    def canonical_json(self) -> str:
        """Serialize this Architecture Package diff deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this diff."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class ArchitectureRevisionProposalResult:
    """Typed outcome of proposing an Architecture Package revision."""

    status: ArchitectureRevisionProposalStatus
    diff: ArchitecturePackageDiff | None = None
    issue: ArchitectureRevisionIssueCode | None = None


@dataclass(frozen=True, slots=True)
class ArchitectureRevisionDecisionResult:
    """Typed outcome of deciding an Architecture Package diff."""

    status: ArchitectureRevisionDecisionStatus
    diff: ArchitecturePackageDiff
    version: ArchitecturePackageVersion | None = None
    issue: ArchitectureRevisionIssueCode | None = None


def propose_architecture_revision(
    *,
    diff_id: UUID,
    owner_user_id: UUID,
    base_version: ArchitecturePackageVersion,
    proposed_package: ArchitecturePlanningPackage,
    created_at: datetime,
) -> ArchitectureRevisionProposalResult:
    """Create one explicit replacement diff without mutating its base version."""
    if created_at.utcoffset() is None:
        return ArchitectureRevisionProposalResult(
            status=ArchitectureRevisionProposalStatus.REJECTED,
            issue=ArchitectureRevisionIssueCode.TIMESTAMP_NOT_AWARE,
        )

    if proposed_package.project_id != base_version.project_id:
        return ArchitectureRevisionProposalResult(
            status=ArchitectureRevisionProposalStatus.REJECTED,
            issue=ArchitectureRevisionIssueCode.PROJECT_MISMATCH,
        )

    if base_version.package.grounding != proposed_package.grounding:
        return ArchitectureRevisionProposalResult(
            status=ArchitectureRevisionProposalStatus.REJECTED,
            issue=ArchitectureRevisionIssueCode.CONTEXT_CHANGED,
        )

    if not _stable_identifiers(base_version.package, proposed_package):
        return ArchitectureRevisionProposalResult(
            status=ArchitectureRevisionProposalStatus.REJECTED,
            issue=ArchitectureRevisionIssueCode.IDENTIFIER_CHANGED,
        )

    changes = _architecture_package_changes(base_version.package, proposed_package)

    if not changes:
        return ArchitectureRevisionProposalResult(
            status=ArchitectureRevisionProposalStatus.REJECTED,
            issue=ArchitectureRevisionIssueCode.NO_CHANGES,
        )

    diff = ArchitecturePackageDiff(
        id=diff_id,
        project_id=base_version.project_id,
        owner_user_id=owner_user_id,
        base_version_id=base_version.id,
        base_version_number=base_version.version_number,
        base_content_hash=base_version.content_hash,
        proposed_package=proposed_package,
        proposal_hash=proposed_package.content_hash,
        changes=changes,
        status=ArchitecturePackageDiffStatus.PROPOSED,
        created_at=created_at,
    )

    return ArchitectureRevisionProposalResult(
        status=ArchitectureRevisionProposalStatus.CREATED,
        diff=diff,
    )


def decide_architecture_revision(
    *,
    diff: ArchitecturePackageDiff,
    current_version: ArchitecturePackageVersion,
    decision: ArchitectureRevisionDecision,
    actor_user_id: UUID,
    occurred_at: datetime,
    resulting_version_id: UUID | None = None,
    reason: str | None = None,
) -> ArchitectureRevisionDecisionResult:
    """Apply an owner decision and create N+1 only for approval."""
    if diff.status is not ArchitecturePackageDiffStatus.PROPOSED:
        return _decision_rejected(
            diff,
            ArchitectureRevisionIssueCode.DIFF_ALREADY_DECIDED,
        )

    if actor_user_id != diff.owner_user_id:
        return _decision_rejected(diff, ArchitectureRevisionIssueCode.ACTOR_NOT_OWNER)

    if occurred_at.utcoffset() is None:
        return _decision_rejected(
            diff,
            ArchitectureRevisionIssueCode.TIMESTAMP_NOT_AWARE,
        )

    if occurred_at < diff.created_at:
        return _decision_rejected(
            diff,
            ArchitectureRevisionIssueCode.TIMESTAMP_OUT_OF_ORDER,
        )

    if not _matches_base(diff, current_version):
        return _decision_rejected(
            diff,
            ArchitectureRevisionIssueCode.BASE_VERSION_STALE,
        )

    normalized_reason, reason_issue = _normalize_reason(reason)

    if reason_issue is not None:
        return _decision_rejected(diff, reason_issue)

    if decision is ArchitectureRevisionDecision.REJECT and normalized_reason is None:
        return _decision_rejected(diff, ArchitectureRevisionIssueCode.REASON_REQUIRED)

    if decision is ArchitectureRevisionDecision.REJECT:
        rejected_diff = replace(
            diff,
            status=ArchitecturePackageDiffStatus.REJECTED,
            decided_by_user_id=actor_user_id,
            decided_at=occurred_at,
            decision_reason=normalized_reason,
        )

        return ArchitectureRevisionDecisionResult(
            status=ArchitectureRevisionDecisionStatus.APPLIED,
            diff=rejected_diff,
        )

    if resulting_version_id is None:
        raise ValueError("approving an Architecture Package diff requires a version ID")

    version = ArchitecturePackageVersion(
        id=resulting_version_id,
        project_id=diff.project_id,
        version_number=current_version.version_number + 1,
        based_on_version_number=current_version.version_number,
        package=diff.proposed_package,
        content_hash=diff.proposal_hash,
        created_by_user_id=actor_user_id,
        created_at=occurred_at,
    )
    approved_diff = replace(
        diff,
        status=ArchitecturePackageDiffStatus.APPROVED,
        decided_by_user_id=actor_user_id,
        decided_at=occurred_at,
        decision_reason=normalized_reason,
        applied_version_id=version.id,
    )

    return ArchitectureRevisionDecisionResult(
        status=ArchitectureRevisionDecisionStatus.APPLIED,
        diff=approved_diff,
        version=version,
    )


def _normalize_reason(
    value: str | None,
) -> tuple[str | None, ArchitectureRevisionIssueCode | None]:
    """Normalize optional owner rationale into typed validation outcomes."""
    if value is None:
        return None, None

    normalized = " ".join(value.split())

    if not normalized:
        return None, None

    if len(normalized) > _MAX_REVISION_REASON_LENGTH:
        return None, ArchitectureRevisionIssueCode.REASON_TOO_LONG

    return normalized, None


def _stable_identifiers(
    base: ArchitecturePlanningPackage,
    proposed: ArchitecturePlanningPackage,
) -> bool:
    """Protect stable architecture and test-plan identities and display codes."""
    if (
        base.architecture.id != proposed.architecture.id
        or base.architecture.code != proposed.architecture.code
        or base.test_plan.id != proposed.test_plan.id
        or base.test_plan.code != proposed.test_plan.code
    ):
        return False

    for before_values, after_values in (
        (base.architecture.components, proposed.architecture.components),
        (base.architecture.connections, proposed.architecture.connections),
        (base.architecture.decisions, proposed.architecture.decisions),
        (base.architecture.data_entities, proposed.architecture.data_entities),
        (base.architecture.api_operations, proposed.architecture.api_operations),
        (base.architecture.risks, proposed.architecture.risks),
        (base.test_plan.environments, proposed.test_plan.environments),
        (base.test_plan.test_cases, proposed.test_plan.test_cases),
        (base.test_plan.quality_gates, proposed.test_plan.quality_gates),
    ):
        if not _shared_codes_are_stable(before_values, after_values):
            return False

    return True


def _shared_codes_are_stable(
    before_values: Sequence[_CodedArtifact],
    after_values: Sequence[_CodedArtifact],
) -> bool:
    """Require a shared identity to retain its human-readable code."""
    before_codes = {value.id: value.code for value in before_values}
    after_codes = {value.id: value.code for value in after_values}

    return all(
        before_codes[artifact_id] == after_codes[artifact_id]
        for artifact_id in before_codes.keys() & after_codes.keys()
    )


def _architecture_package_changes(
    base: ArchitecturePlanningPackage,
    proposed: ArchitecturePlanningPackage,
) -> tuple[ArchitecturePackageChange, ...]:
    """Compute explicit canonical changes between two Architecture Packages."""
    changes: list[ArchitecturePackageChange] = []

    for artifact_kind, artifact_id, before, after in (
        (
            ArchitectureArtifactKind.ARCHITECTURE,
            base.architecture.id,
            base.architecture.to_snapshot(),
            proposed.architecture.to_snapshot(),
        ),
        (
            ArchitectureArtifactKind.TEST_PLAN,
            base.test_plan.id,
            base.test_plan.to_snapshot(),
            proposed.test_plan.to_snapshot(),
        ),
        (
            ArchitectureArtifactKind.OPEN_QUESTIONS,
            base.project_id,
            {"items": list(base.open_questions)},
            {"items": list(proposed.open_questions)},
        ),
    ):
        if before == after:
            continue

        changes.append(
            ArchitecturePackageChange(
                kind=ArchitectureChangeKind.REPLACE,
                artifact_kind=artifact_kind,
                artifact_id=artifact_id,
                before=before,
                after=after,
            )
        )

    return tuple(sorted(changes, key=lambda change: change.sort_key))


def _matches_base(
    diff: ArchitecturePackageDiff,
    version: ArchitecturePackageVersion,
) -> bool:
    """Return whether one diff still targets the exact current version."""
    return (
        diff.project_id == version.project_id
        and diff.base_version_id == version.id
        and diff.base_version_number == version.version_number
        and diff.base_content_hash == version.content_hash
    )


def _decision_rejected(
    diff: ArchitecturePackageDiff,
    issue: ArchitectureRevisionIssueCode,
) -> ArchitectureRevisionDecisionResult:
    """Return one typed rejected decision without mutating the diff."""
    return ArchitectureRevisionDecisionResult(
        status=ArchitectureRevisionDecisionStatus.REJECTED,
        diff=diff,
        issue=issue,
    )


__all__ = [
    "ArchitectureArtifactKind",
    "ArchitectureChangeKind",
    "ArchitecturePackageChange",
    "ArchitecturePackageDiff",
    "ArchitecturePackageDiffStatus",
    "ArchitectureRevisionDecision",
    "ArchitectureRevisionDecisionResult",
    "ArchitectureRevisionDecisionStatus",
    "ArchitectureRevisionIssueCode",
    "ArchitectureRevisionProposalResult",
    "ArchitectureRevisionProposalStatus",
    "decide_architecture_revision",
    "propose_architecture_revision",
]
