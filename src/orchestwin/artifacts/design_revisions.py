"""Owner-controlled immutable revisions for Design Packages."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from orchestwin.artifacts.design_packages import (
    DesignExplorationPackage,
    DesignPackageVersion,
)
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    normalize_optional_text,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)

_MAX_REVISION_REASON_LENGTH: Final = 2000


class DesignChangeKind(StrEnum):
    """Supported changes in a Design Package replacement diff."""

    ADD = "ADD"
    REPLACE = "REPLACE"
    REMOVE = "REMOVE"


class DesignArtifactKind(StrEnum):
    """Design Package collections represented in an owner diff."""

    ALTERNATIVE = "ALTERNATIVE"
    CRITIQUE = "CRITIQUE"
    CONCERN = "CONCERN"
    PROTOTYPE = "PROTOTYPE"
    SELECTION = "SELECTION"
    OPEN_QUESTIONS = "OPEN_QUESTIONS"


class DesignPackageDiffStatus(StrEnum):
    """Owner decision state of a proposed Design Package diff."""

    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class DesignRevisionDecision(StrEnum):
    """Allowed owner decisions for one proposed Design Package diff."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class DesignRevisionIssueCode(StrEnum):
    """Expected reasons a Design Package revision cannot continue."""

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


class DesignRevisionProposalStatus(StrEnum):
    """Stable outcome of proposing a Design Package replacement."""

    CREATED = "CREATED"
    REJECTED = "REJECTED"


class DesignRevisionDecisionStatus(StrEnum):
    """Stable outcome of deciding a Design Package diff."""

    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class _SnapshotArtifact(Protocol):
    """Identity and snapshot behavior shared by diffable collections."""

    id: UUID
    code: str

    def to_snapshot(self) -> dict[str, object]:
        """Return the artifact snapshot used by the diff."""
        ...


@dataclass(frozen=True, slots=True)
class DesignPackageChange:
    """One explicit before/after change inside a Design Package diff."""

    kind: DesignChangeKind
    artifact_kind: DesignArtifactKind
    artifact_id: UUID
    before: dict[str, object] | None
    after: dict[str, object] | None

    def __post_init__(self) -> None:
        """Protect the snapshot shape selected by the change kind."""
        if self.kind is DesignChangeKind.ADD:
            if self.before is not None or self.after is None:
                raise ValueError("ADD design changes require only an after snapshot")
            return

        if self.kind is DesignChangeKind.REMOVE:
            if self.before is None or self.after is not None:
                raise ValueError("REMOVE design changes require only a before snapshot")
            return

        if self.before is None or self.after is None:
            raise ValueError("REPLACE design changes require before and after snapshots")

        if self.before == self.after:
            raise ValueError("REPLACE design changes require different snapshots")

    @property
    def sort_key(self) -> tuple[str, str, str]:
        """Return deterministic change ordering metadata."""
        return (
            self.artifact_kind.value,
            self.artifact_id.hex,
            self.kind.value,
        )

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic Design Package change snapshot."""
        return {
            "kind": self.kind.value,
            "artifact_kind": self.artifact_kind.value,
            "artifact_id": str(self.artifact_id),
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True, slots=True)
class DesignPackageDiff:
    """One immutable owner-reviewable replacement proposal."""

    id: UUID
    project_id: UUID
    owner_user_id: UUID
    base_version_id: UUID
    base_version_number: int
    base_content_hash: str
    proposed_package: DesignExplorationPackage
    proposal_hash: str
    changes: tuple[DesignPackageChange, ...]
    status: DesignPackageDiffStatus
    created_at: datetime
    decided_by_user_id: UUID | None = None
    decided_at: datetime | None = None
    decision_reason: str | None = None
    applied_version_id: UUID | None = None

    def __post_init__(self) -> None:
        """Protect proposal identity, chronology, and decision metadata."""
        validate_positive_integer(
            self.base_version_number,
            label="Design Package diff base version",
        )

        validate_sha256(
            self.base_content_hash,
            label="Design Package diff base hash",
        )
        validate_sha256(
            self.proposal_hash,
            label="Design Package diff proposal hash",
        )

        if self.proposed_package.project_id != self.project_id:
            raise ValueError("Design Package diff must belong to its project")

        if self.proposal_hash != self.proposed_package.content_hash:
            raise ValueError("Design Package diff proposal hash must match its package")

        if self.created_at.utcoffset() is None:
            raise ValueError("Design Package diff timestamp must be timezone-aware")

        if not self.changes:
            raise ValueError("Design Package diff must contain changes")

        expected_changes = tuple(sorted(self.changes, key=lambda change: change.sort_key))

        if self.changes != expected_changes:
            raise ValueError("Design Package changes must use canonical order")

        change_keys = tuple(change.sort_key for change in self.changes)

        if len(change_keys) != len(set(change_keys)):
            raise ValueError("Design Package changes must be unique")

        normalized_reason = normalize_optional_text(
            self.decision_reason,
            label="Design Package diff decision reason",
            maximum_length=_MAX_REVISION_REASON_LENGTH,
        )

        if normalized_reason != self.decision_reason:
            raise ValueError("Design Package diff decision reason must be normalized")

        if self.status is DesignPackageDiffStatus.PROPOSED:
            if any(
                value is not None
                for value in (
                    self.decided_by_user_id,
                    self.decided_at,
                    self.decision_reason,
                    self.applied_version_id,
                )
            ):
                raise ValueError("a proposed Design Package diff must not be decided")
            return

        if self.decided_by_user_id is None or self.decided_at is None:
            raise ValueError("a decided Design Package diff requires decision metadata")

        if self.decided_at.utcoffset() is None:
            raise ValueError("Design Package diff decision timestamp must be timezone-aware")

        if self.decided_at < self.created_at:
            raise ValueError("Design Package diff decision must not precede creation")

        if self.status is DesignPackageDiffStatus.APPROVED:
            if self.applied_version_id is None:
                raise ValueError("an approved Design Package diff requires an applied version")
        elif self.applied_version_id is not None:
            raise ValueError("a rejected Design Package diff must not apply a version")

        if self.status is DesignPackageDiffStatus.REJECTED and self.decision_reason is None:
            raise ValueError("a rejected Design Package diff requires a reason")

    def to_snapshot(self) -> dict[str, object]:
        """Return a deterministic Design Package diff snapshot."""
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
            "decided_at": None if self.decided_at is None else self.decided_at.isoformat(),
            "decision_reason": self.decision_reason,
            "applied_version_id": (
                None if self.applied_version_id is None else str(self.applied_version_id)
            ),
        }

    def canonical_json(self) -> str:
        """Serialize this Design Package diff deterministically."""
        return canonical_json(self.to_snapshot())

    @property
    def content_hash(self) -> str:
        """Return the SHA-256 hash of this diff."""
        return snapshot_content_hash(self.to_snapshot())


@dataclass(frozen=True, slots=True)
class DesignRevisionProposalResult:
    """Typed outcome of proposing a Design Package revision."""

    status: DesignRevisionProposalStatus
    diff: DesignPackageDiff | None = None
    issue: DesignRevisionIssueCode | None = None


@dataclass(frozen=True, slots=True)
class DesignRevisionDecisionResult:
    """Typed outcome of an owner Design Package diff decision."""

    status: DesignRevisionDecisionStatus
    diff: DesignPackageDiff
    version: DesignPackageVersion | None = None
    issue: DesignRevisionIssueCode | None = None


def propose_design_revision(
    *,
    diff_id: UUID,
    owner_user_id: UUID,
    base_version: DesignPackageVersion,
    proposed_package: DesignExplorationPackage,
    created_at: datetime,
) -> DesignRevisionProposalResult:
    """Create an explicit replacement diff without mutating the base version."""
    if created_at.utcoffset() is None:
        return DesignRevisionProposalResult(
            status=DesignRevisionProposalStatus.REJECTED,
            issue=DesignRevisionIssueCode.TIMESTAMP_NOT_AWARE,
        )

    if created_at < base_version.created_at:
        return DesignRevisionProposalResult(
            status=DesignRevisionProposalStatus.REJECTED,
            issue=DesignRevisionIssueCode.TIMESTAMP_OUT_OF_ORDER,
        )

    if proposed_package.project_id != base_version.project_id:
        return DesignRevisionProposalResult(
            status=DesignRevisionProposalStatus.REJECTED,
            issue=DesignRevisionIssueCode.PROJECT_MISMATCH,
        )

    if not _same_governed_context(base_version.package, proposed_package):
        return DesignRevisionProposalResult(
            status=DesignRevisionProposalStatus.REJECTED,
            issue=DesignRevisionIssueCode.CONTEXT_CHANGED,
        )

    if not _stable_identifiers(base_version.package, proposed_package):
        return DesignRevisionProposalResult(
            status=DesignRevisionProposalStatus.REJECTED,
            issue=DesignRevisionIssueCode.IDENTIFIER_CHANGED,
        )

    changes = _design_package_changes(base_version.package, proposed_package)

    if not changes:
        return DesignRevisionProposalResult(
            status=DesignRevisionProposalStatus.REJECTED,
            issue=DesignRevisionIssueCode.NO_CHANGES,
        )

    diff = DesignPackageDiff(
        id=diff_id,
        project_id=base_version.project_id,
        owner_user_id=owner_user_id,
        base_version_id=base_version.id,
        base_version_number=base_version.version_number,
        base_content_hash=base_version.content_hash,
        proposed_package=proposed_package,
        proposal_hash=proposed_package.content_hash,
        changes=changes,
        status=DesignPackageDiffStatus.PROPOSED,
        created_at=created_at,
    )

    return DesignRevisionProposalResult(
        status=DesignRevisionProposalStatus.CREATED,
        diff=diff,
    )


def decide_design_revision(
    *,
    diff: DesignPackageDiff,
    current_version: DesignPackageVersion,
    decision: DesignRevisionDecision,
    actor_user_id: UUID,
    occurred_at: datetime,
    resulting_version_id: UUID | None = None,
    reason: str | None = None,
) -> DesignRevisionDecisionResult:
    """Apply an owner decision and create N+1 only for approval."""
    if diff.status is not DesignPackageDiffStatus.PROPOSED:
        return _decision_rejected(diff, DesignRevisionIssueCode.DIFF_ALREADY_DECIDED)

    if actor_user_id != diff.owner_user_id:
        return _decision_rejected(diff, DesignRevisionIssueCode.ACTOR_NOT_OWNER)

    if occurred_at.utcoffset() is None:
        return _decision_rejected(diff, DesignRevisionIssueCode.TIMESTAMP_NOT_AWARE)

    if occurred_at < diff.created_at:
        return _decision_rejected(diff, DesignRevisionIssueCode.TIMESTAMP_OUT_OF_ORDER)

    if not _matches_base(diff, current_version):
        return _decision_rejected(diff, DesignRevisionIssueCode.BASE_VERSION_STALE)

    normalized_reason, reason_issue = _normalize_reason(reason)

    if reason_issue is not None:
        return _decision_rejected(diff, reason_issue)

    if decision is DesignRevisionDecision.REJECT and normalized_reason is None:
        return _decision_rejected(diff, DesignRevisionIssueCode.REASON_REQUIRED)

    if decision is DesignRevisionDecision.REJECT:
        rejected_diff = replace(
            diff,
            status=DesignPackageDiffStatus.REJECTED,
            decided_by_user_id=actor_user_id,
            decided_at=occurred_at,
            decision_reason=normalized_reason,
        )

        return DesignRevisionDecisionResult(
            status=DesignRevisionDecisionStatus.APPLIED,
            diff=rejected_diff,
        )

    if resulting_version_id is None:
        raise ValueError("approving a Design Package diff requires a version ID")

    version = DesignPackageVersion(
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
        status=DesignPackageDiffStatus.APPROVED,
        decided_by_user_id=actor_user_id,
        decided_at=occurred_at,
        decision_reason=normalized_reason,
        applied_version_id=version.id,
    )

    return DesignRevisionDecisionResult(
        status=DesignRevisionDecisionStatus.APPLIED,
        diff=approved_diff,
        version=version,
    )


def _normalize_reason(
    value: str | None,
) -> tuple[str | None, DesignRevisionIssueCode | None]:
    """Normalize optional owner rationale into typed validation outcomes."""
    if value is None:
        return None, None

    normalized = " ".join(value.split())

    if not normalized:
        return None, None

    if len(normalized) > _MAX_REVISION_REASON_LENGTH:
        return None, DesignRevisionIssueCode.REASON_TOO_LONG

    return normalized, None


def _same_governed_context(
    base: DesignExplorationPackage,
    proposed: DesignExplorationPackage,
) -> bool:
    """Keep owner revisions inside one exact governed design context."""
    return base.grounding == proposed.grounding


def _stable_identifiers(
    base: DesignExplorationPackage,
    proposed: DesignExplorationPackage,
) -> bool:
    """Require shared artifact identities to preserve display codes."""
    for before_values, after_values in (
        (base.alternatives, proposed.alternatives),
        (base.critiques, proposed.critiques),
        (base.concerns, proposed.concerns),
    ):
        before_codes = {value.id: value.code for value in before_values}
        after_codes = {value.id: value.code for value in after_values}

        for artifact_id in before_codes.keys() & after_codes.keys():
            if before_codes[artifact_id] != after_codes[artifact_id]:
                return False

    if (
        base.prototype is not None
        and proposed.prototype is not None
        and base.prototype.id == proposed.prototype.id
    ):
        return base.prototype.code == proposed.prototype.code

    return True


def _design_package_changes(
    base: DesignExplorationPackage,
    proposed: DesignExplorationPackage,
) -> tuple[DesignPackageChange, ...]:
    """Compute explicit canonical changes between two Design Packages."""
    changes: list[DesignPackageChange] = []

    for artifact_kind, before_values, after_values in (
        (DesignArtifactKind.ALTERNATIVE, base.alternatives, proposed.alternatives),
        (DesignArtifactKind.CRITIQUE, base.critiques, proposed.critiques),
        (DesignArtifactKind.CONCERN, base.concerns, proposed.concerns),
    ):
        changes.extend(
            _collection_changes(
                artifact_kind=artifact_kind,
                before_values=before_values,
                after_values=after_values,
            )
        )

    changes.extend(_prototype_changes(base, proposed))

    before_selection = _selection_snapshot(base)
    after_selection = _selection_snapshot(proposed)

    if before_selection != after_selection:
        changes.append(
            DesignPackageChange(
                kind=DesignChangeKind.REPLACE,
                artifact_kind=DesignArtifactKind.SELECTION,
                artifact_id=base.project_id,
                before=before_selection,
                after=after_selection,
            )
        )

    if base.open_questions != proposed.open_questions:
        changes.append(
            DesignPackageChange(
                kind=DesignChangeKind.REPLACE,
                artifact_kind=DesignArtifactKind.OPEN_QUESTIONS,
                artifact_id=base.project_id,
                before={"items": list(base.open_questions)},
                after={"items": list(proposed.open_questions)},
            )
        )

    return tuple(sorted(changes, key=lambda change: change.sort_key))


def _collection_changes(
    *,
    artifact_kind: DesignArtifactKind,
    before_values: Sequence[_SnapshotArtifact],
    after_values: Sequence[_SnapshotArtifact],
) -> list[DesignPackageChange]:
    """Compute changes for one id-addressed Design Package collection."""
    before = {value.id: value for value in before_values}
    after = {value.id: value for value in after_values}
    changes: list[DesignPackageChange] = []

    for artifact_id in sorted(before.keys() | after.keys(), key=lambda value: value.hex):
        before_value = before.get(artifact_id)
        after_value = after.get(artifact_id)
        before_snapshot = None if before_value is None else before_value.to_snapshot()
        after_snapshot = None if after_value is None else after_value.to_snapshot()

        if before_snapshot == after_snapshot:
            continue

        if before_value is None:
            kind = DesignChangeKind.ADD
        elif after_value is None:
            kind = DesignChangeKind.REMOVE
        else:
            kind = DesignChangeKind.REPLACE

        changes.append(
            DesignPackageChange(
                kind=kind,
                artifact_kind=artifact_kind,
                artifact_id=artifact_id,
                before=before_snapshot,
                after=after_snapshot,
            )
        )

    return changes


def _prototype_changes(
    base: DesignExplorationPackage,
    proposed: DesignExplorationPackage,
) -> list[DesignPackageChange]:
    """Compute add, remove, or replacement for the singleton prototype."""
    before = base.prototype
    after = proposed.prototype

    if before is None and after is None:
        return []

    if before is not None and after is not None and before.to_snapshot() == after.to_snapshot():
        return []

    if after is not None:
        artifact_id = after.id
    elif before is not None:
        artifact_id = before.id
    else:
        raise RuntimeError("prototype change requires before or after state")

    if before is None:
        kind = DesignChangeKind.ADD
    elif after is None:
        kind = DesignChangeKind.REMOVE
    else:
        kind = DesignChangeKind.REPLACE

    return [
        DesignPackageChange(
            kind=kind,
            artifact_kind=DesignArtifactKind.PROTOTYPE,
            artifact_id=artifact_id,
            before=None if before is None else before.to_snapshot(),
            after=None if after is None else after.to_snapshot(),
        )
    ]


def _selection_snapshot(package: DesignExplorationPackage) -> dict[str, object]:
    """Return recommendation and owner selection as one singleton snapshot."""
    return {
        "recommended_alternative_id": (
            None
            if package.recommended_alternative_id is None
            else str(package.recommended_alternative_id)
        ),
        "owner_selected_alternative_id": (
            None
            if package.owner_selected_alternative_id is None
            else str(package.owner_selected_alternative_id)
        ),
    }


def _matches_base(
    diff: DesignPackageDiff,
    current: DesignPackageVersion,
) -> bool:
    """Return whether a diff still targets the exact current version."""
    return (
        diff.project_id == current.project_id
        and diff.base_version_id == current.id
        and diff.base_version_number == current.version_number
        and diff.base_content_hash == current.content_hash
    )


def _decision_rejected(
    diff: DesignPackageDiff,
    issue: DesignRevisionIssueCode,
) -> DesignRevisionDecisionResult:
    """Return a typed rejection without changing the proposed diff."""
    return DesignRevisionDecisionResult(
        status=DesignRevisionDecisionStatus.REJECTED,
        diff=diff,
        issue=issue,
    )


__all__ = [
    "DesignArtifactKind",
    "DesignChangeKind",
    "DesignPackageChange",
    "DesignPackageDiff",
    "DesignPackageDiffStatus",
    "DesignRevisionDecision",
    "DesignRevisionDecisionResult",
    "DesignRevisionDecisionStatus",
    "DesignRevisionIssueCode",
    "DesignRevisionProposalResult",
    "DesignRevisionProposalStatus",
    "decide_design_revision",
    "propose_design_revision",
]
