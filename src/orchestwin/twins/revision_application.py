"""Application service for owner-reviewed User Twin profile revisions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from orchestwin.twins.epistemics import (
    ProfileObservation,
)
from orchestwin.twins.persistence.repositories import (
    VersionAppendStatus,
)
from orchestwin.twins.persistence.uow import (
    UserModelingUnitOfWork,
)
from orchestwin.twins.revision_persistence import (
    DiffPersistenceStatus,
)
from orchestwin.twins.revisions import (
    ProfileDiffDecisionStatus,
    ProfileDiffProposalIssueCode,
    ProfileDiffProposalStatus,
    UserTwinProfileDiff,
    approve_user_twin_profile_diff,
    materialize_approved_user_twin_profile_diff,
    propose_user_twin_profile_diff,
    reject_user_twin_profile_diff,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinProfileVersion,
)


class ProfileRevisionDecision(StrEnum):
    """Owner decision on a proposed profile revision."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ProfileRevisionApplicationStatus(StrEnum):
    """Stable application-level revision outcomes."""

    CREATED = "CREATED"
    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED = "REJECTED"


class ProfileRevisionApplicationIssueCode(StrEnum):
    """Expected reasons profile revision cannot continue."""

    SNAPSHOT_NOT_FOUND = "SNAPSHOT_NOT_FOUND"
    TWIN_NOT_FOUND = "TWIN_NOT_FOUND"
    DIFF_ALREADY_PENDING = "DIFF_ALREADY_PENDING"
    INVALID_REPLACEMENT = "INVALID_REPLACEMENT"
    DIFF_NOT_FOUND = "DIFF_NOT_FOUND"
    DECISION_REJECTED = "DECISION_REJECTED"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


class UserModelingRevisionUowFactory(Protocol):
    """Create an owner-scoped User Modeling Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> UserModelingUnitOfWork:
        """Create one transactional boundary."""


@dataclass(frozen=True, slots=True)
class ProfileRevisionApplicationResult:
    """Typed result of proposing or deciding one profile revision."""

    status: ProfileRevisionApplicationStatus

    diff: UserTwinProfileDiff | None = None
    twin_version: UserTwinProfileVersion | None = None
    snapshot_version: UserModelingSnapshotVersion | None = None

    issue: ProfileRevisionApplicationIssueCode | None = None

    proposal_issue: ProfileDiffProposalIssueCode | None = None

    diff_persistence_status: DiffPersistenceStatus | None = None

    version_persistence_status: VersionAppendStatus | None = None


class LocalUserTwinProfileRevisionService:
    """Coordinate owner-approved immutable User Twin profile revisions."""

    def __init__(
        self,
        *,
        uow_factory: UserModelingRevisionUowFactory,
        uuid_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Configure explicit deterministic dependencies."""
        self._uow_factory = uow_factory
        self._uuid_factory = uuid_factory
        self._clock = clock if clock is not None else _utc_now

    async def propose_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        twin_id: UUID,
        replacements: Mapping[
            UserTwinField,
            ProfileObservation,
        ],
    ) -> ProfileRevisionApplicationResult:
        """Persist one explicit diff against the current User Modeling snapshot."""
        async with self._uow_factory(owner_user_id=owner_user_id) as uow:
            current_snapshot = await uow.snapshots.current(project_id=project_id)

            if current_snapshot is None:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    issue=(ProfileRevisionApplicationIssueCode.SNAPSHOT_NOT_FOUND),
                )

            if not _snapshot_contains_twin(
                current_snapshot,
                twin_id,
            ):
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    issue=(ProfileRevisionApplicationIssueCode.TWIN_NOT_FOUND),
                )

            existing = await uow.diffs.current_proposed(
                project_id=project_id,
                base_snapshot_version_id=(current_snapshot.id),
                twin_id=twin_id,
            )

            if existing is not None:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    diff=existing,
                    issue=(ProfileRevisionApplicationIssueCode.DIFF_ALREADY_PENDING),
                )

            proposal = propose_user_twin_profile_diff(
                base_snapshot_version=(current_snapshot),
                twin_id=twin_id,
                replacements=replacements,
                diff_id=self._uuid_factory(),
                created_by_user_id=(owner_user_id),
                created_at=_aware(self._clock()),
            )

            if proposal.status is not ProfileDiffProposalStatus.CREATED or proposal.diff is None:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    issue=(ProfileRevisionApplicationIssueCode.INVALID_REPLACEMENT),
                    proposal_issue=(proposal.issue),
                )

            persistence_status = await uow.diffs.create(proposal.diff)

            if persistence_status is not DiffPersistenceStatus.CREATED:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    diff=proposal.diff,
                    issue=(ProfileRevisionApplicationIssueCode.PERSISTENCE_REJECTED),
                    diff_persistence_status=(persistence_status),
                )

            await uow.commit()

        return ProfileRevisionApplicationResult(
            status=(ProfileRevisionApplicationStatus.CREATED),
            diff=proposal.diff,
        )

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: ProfileRevisionDecision,
        reason: str | None = None,
    ) -> ProfileRevisionApplicationResult:
        """Approve/reject one diff and atomically version approved content."""
        async with self._uow_factory(owner_user_id=owner_user_id) as uow:
            current_diff = await uow.diffs.get(
                project_id=project_id,
                diff_id=diff_id,
            )

            if current_diff is None:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    issue=(ProfileRevisionApplicationIssueCode.DIFF_NOT_FOUND),
                )

            occurred_at = _aware(self._clock())

            if decision is ProfileRevisionDecision.APPROVE:
                domain_decision = approve_user_twin_profile_diff(
                    current_diff,
                    actor_user_id=(owner_user_id),
                    occurred_at=occurred_at,
                    applied_snapshot_version_id=(self._uuid_factory()),
                    reason=reason,
                )
            else:
                domain_decision = reject_user_twin_profile_diff(
                    current_diff,
                    actor_user_id=(owner_user_id),
                    occurred_at=occurred_at,
                    reason=(reason if reason is not None else ""),
                )

            if domain_decision.status is ProfileDiffDecisionStatus.NO_CHANGE:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.NO_CHANGE),
                    diff=domain_decision.diff,
                )

            if domain_decision.status is ProfileDiffDecisionStatus.REJECTED:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    diff=current_diff,
                    issue=(ProfileRevisionApplicationIssueCode.DECISION_REJECTED),
                )

            current_snapshot = await uow.snapshots.current(project_id=project_id)

            if current_snapshot is None:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    diff=current_diff,
                    issue=(ProfileRevisionApplicationIssueCode.SNAPSHOT_NOT_FOUND),
                )

            if (
                current_snapshot.id != current_diff.base_snapshot_version_id
                or current_snapshot.version_number != current_diff.base_snapshot_version_number
                or current_snapshot.content_hash != current_diff.base_snapshot_content_hash
            ):
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    diff=current_diff,
                    issue=(ProfileRevisionApplicationIssueCode.CONTEXT_CHANGED),
                )

            decided_diff = domain_decision.diff

            if decision is ProfileRevisionDecision.REJECT:
                persistence_status = await uow.diffs.save_decision(decided_diff)

                if persistence_status is not DiffPersistenceStatus.UPDATED:
                    return ProfileRevisionApplicationResult(
                        status=(ProfileRevisionApplicationStatus.REJECTED),
                        diff=decided_diff,
                        issue=(ProfileRevisionApplicationIssueCode.PERSISTENCE_REJECTED),
                        diff_persistence_status=(persistence_status),
                    )

                await uow.commit()

                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.APPLIED),
                    diff=decided_diff,
                )

            revision = materialize_approved_user_twin_profile_diff(
                base_snapshot_version=(current_snapshot),
                approved_diff=(decided_diff),
                twin_version_id=(self._uuid_factory()),
                created_by_user_id=(owner_user_id),
                created_at=occurred_at,
            )

            twin_status = await uow.twins.append(revision.twin_version)

            if twin_status is not VersionAppendStatus.APPENDED:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    diff=decided_diff,
                    issue=(ProfileRevisionApplicationIssueCode.PERSISTENCE_REJECTED),
                    version_persistence_status=(twin_status),
                )

            snapshot_status = await uow.snapshots.append(revision.snapshot_version)

            if snapshot_status is not VersionAppendStatus.APPENDED:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    diff=decided_diff,
                    issue=(ProfileRevisionApplicationIssueCode.PERSISTENCE_REJECTED),
                    version_persistence_status=(snapshot_status),
                )

            diff_status = await uow.diffs.save_decision(decided_diff)

            if diff_status is not DiffPersistenceStatus.UPDATED:
                return ProfileRevisionApplicationResult(
                    status=(ProfileRevisionApplicationStatus.REJECTED),
                    diff=decided_diff,
                    issue=(ProfileRevisionApplicationIssueCode.PERSISTENCE_REJECTED),
                    diff_persistence_status=(diff_status),
                )

            await uow.commit()

        return ProfileRevisionApplicationResult(
            status=(ProfileRevisionApplicationStatus.APPLIED),
            diff=decided_diff,
            twin_version=revision.twin_version,
            snapshot_version=(revision.snapshot_version),
        )


def _snapshot_contains_twin(
    snapshot: UserModelingSnapshotVersion,
    twin_id: UUID,
) -> bool:
    """Return whether the authoritative snapshot contains the requested twin."""
    return any(version.twin_id == twin_id for version in snapshot.snapshot.twin_versions)


def _aware(
    value: datetime,
) -> datetime:
    """Require timezone-aware application timestamps."""
    if value.utcoffset() is None:
        raise ValueError("profile revision clock must return timezone-aware timestamps")

    return value


def _utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)
