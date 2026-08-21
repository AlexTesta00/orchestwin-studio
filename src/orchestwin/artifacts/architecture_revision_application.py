"""Application service for owner-controlled Architecture Package revisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.artifacts.architecture_packages import (
    ArchitecturePackageVersion,
    ArchitecturePlanningPackage,
)
from orchestwin.artifacts.architecture_revisions import (
    ArchitecturePackageDiff,
    ArchitectureRevisionDecision,
    ArchitectureRevisionDecisionStatus,
    ArchitectureRevisionIssueCode,
    ArchitectureRevisionProposalStatus,
    decide_architecture_revision,
    propose_architecture_revision,
)
from orchestwin.projects.architecture_application import (
    ArchitecturePackageRepository,
    ArchitectureVersionAppendStatus,
)


class ArchitectureRevisionStatus(StrEnum):
    """Stable application-level Architecture Package revision outcomes."""

    CREATED = "CREATED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class ArchitectureRevisionApplicationIssueCode(StrEnum):
    """Expected reasons a Architecture Package revision cannot continue."""

    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    DIFF_ALREADY_PENDING = "DIFF_ALREADY_PENDING"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    DIFF_NOT_FOUND = "DIFF_NOT_FOUND"
    DECISION_REJECTED = "DECISION_REJECTED"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


class ArchitectureDiffPersistenceStatus(StrEnum):
    """Stable outcomes of Architecture Package diff persistence operations."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    CONTEXT_NOT_FOUND = "CONTEXT_NOT_FOUND"
    CONFLICT = "CONFLICT"


class ArchitecturePackageDiffRepository(Protocol):
    """Persistence boundary for reviewable Architecture Package diffs."""

    async def create(
        self,
        diff: ArchitecturePackageDiff,
    ) -> ArchitectureDiffPersistenceStatus:
        """Persist one proposed diff."""

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> ArchitecturePackageDiff | None:
        """Return one exact owner-scoped diff."""

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_version_id: UUID,
    ) -> ArchitecturePackageDiff | None:
        """Return the proposed diff for one exact base version."""

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[ArchitecturePackageDiff, ...]:
        """Return owner-scoped diff history in creation order."""

    async def save_decision(
        self,
        diff: ArchitecturePackageDiff,
    ) -> ArchitectureDiffPersistenceStatus:
        """Persist an approved or rejected decision."""


class ArchitectureRevisionUnitOfWork(Protocol):
    """Transactional boundary for Architecture Package revisions."""

    packages: ArchitecturePackageRepository
    diffs: ArchitecturePackageDiffRepository

    async def __aenter__(self) -> Self:
        """Enter the transactional boundary."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the transactional boundary."""

    async def commit(self) -> None:
        """Commit all persistence changes."""

    async def rollback(self) -> None:
        """Rollback all persistence changes."""


class ArchitectureRevisionUnitOfWorkFactory(Protocol):
    """Create one owner-scoped Architecture Package revision Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> ArchitectureRevisionUnitOfWork:
        """Create one transactional boundary."""


@dataclass(frozen=True, slots=True)
class ArchitectureRevisionResult:
    """Typed result of proposing or deciding one Architecture Package revision."""

    status: ArchitectureRevisionStatus
    diff: ArchitecturePackageDiff | None = None
    version: ArchitecturePackageVersion | None = None
    issue: ArchitectureRevisionApplicationIssueCode | None = None
    domain_issue: ArchitectureRevisionIssueCode | None = None
    diff_persistence_status: ArchitectureDiffPersistenceStatus | None = None
    version_persistence_status: ArchitectureVersionAppendStatus | None = None


class LocalArchitectureRevisionService:
    """Coordinate owner-approved immutable Architecture Package revisions."""

    def __init__(
        self,
        *,
        uow_factory: ArchitectureRevisionUnitOfWorkFactory,
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
        proposed_package: ArchitecturePlanningPackage,
    ) -> ArchitectureRevisionResult:
        """Persist one explicit diff against the current Architecture Package."""
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current = await unit.packages.current(project_id=project_id)

            if current is None:
                return ArchitectureRevisionResult(
                    status=ArchitectureRevisionStatus.REJECTED,
                    issue=ArchitectureRevisionApplicationIssueCode.PACKAGE_NOT_FOUND,
                )

            existing = await unit.diffs.current_proposed(
                project_id=project_id,
                base_version_id=current.id,
            )

            if existing is not None:
                return ArchitectureRevisionResult(
                    status=ArchitectureRevisionStatus.REJECTED,
                    diff=existing,
                    issue=ArchitectureRevisionApplicationIssueCode.DIFF_ALREADY_PENDING,
                )

            proposal = propose_architecture_revision(
                diff_id=self._uuid_factory(),
                owner_user_id=owner_user_id,
                base_version=current,
                proposed_package=proposed_package,
                created_at=_aware(self._clock()),
            )

            if (
                proposal.status is not ArchitectureRevisionProposalStatus.CREATED
                or proposal.diff is None
            ):
                return ArchitectureRevisionResult(
                    status=ArchitectureRevisionStatus.REJECTED,
                    issue=ArchitectureRevisionApplicationIssueCode.INVALID_PROPOSAL,
                    domain_issue=proposal.issue,
                )

            persistence_status = await unit.diffs.create(proposal.diff)

            if persistence_status is not ArchitectureDiffPersistenceStatus.CREATED:
                return ArchitectureRevisionResult(
                    status=ArchitectureRevisionStatus.REJECTED,
                    diff=proposal.diff,
                    issue=ArchitectureRevisionApplicationIssueCode.PERSISTENCE_REJECTED,
                    diff_persistence_status=persistence_status,
                )

            await unit.commit()

        return ArchitectureRevisionResult(
            status=ArchitectureRevisionStatus.CREATED,
            diff=proposal.diff,
        )

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: ArchitectureRevisionDecision,
        reason: str | None = None,
    ) -> ArchitectureRevisionResult:
        """Approve or reject one diff and version approved content atomically."""
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current_diff = await unit.diffs.get(
                project_id=project_id,
                diff_id=diff_id,
            )

            if current_diff is None:
                return ArchitectureRevisionResult(
                    status=ArchitectureRevisionStatus.REJECTED,
                    issue=ArchitectureRevisionApplicationIssueCode.DIFF_NOT_FOUND,
                )

            current = await unit.packages.current(project_id=project_id)

            if current is None:
                return ArchitectureRevisionResult(
                    status=ArchitectureRevisionStatus.REJECTED,
                    diff=current_diff,
                    issue=ArchitectureRevisionApplicationIssueCode.PACKAGE_NOT_FOUND,
                )

            if not _diff_targets_version(current_diff, current):
                return ArchitectureRevisionResult(
                    status=ArchitectureRevisionStatus.REJECTED,
                    diff=current_diff,
                    issue=ArchitectureRevisionApplicationIssueCode.CONTEXT_CHANGED,
                )

            domain_decision = decide_architecture_revision(
                diff=current_diff,
                current_version=current,
                decision=decision,
                actor_user_id=owner_user_id,
                occurred_at=_aware(self._clock()),
                resulting_version_id=(
                    self._uuid_factory()
                    if decision is ArchitectureRevisionDecision.APPROVE
                    else None
                ),
                reason=reason,
            )

            if domain_decision.status is ArchitectureRevisionDecisionStatus.REJECTED:
                return ArchitectureRevisionResult(
                    status=ArchitectureRevisionStatus.REJECTED,
                    diff=current_diff,
                    issue=ArchitectureRevisionApplicationIssueCode.DECISION_REJECTED,
                    domain_issue=domain_decision.issue,
                )

            decided_diff = domain_decision.diff
            version = domain_decision.version

            if version is not None:
                version_status = await unit.packages.append(version)

                if version_status is not ArchitectureVersionAppendStatus.APPENDED:
                    return ArchitectureRevisionResult(
                        status=ArchitectureRevisionStatus.REJECTED,
                        diff=decided_diff,
                        issue=ArchitectureRevisionApplicationIssueCode.PERSISTENCE_REJECTED,
                        version_persistence_status=version_status,
                    )

            diff_status = await unit.diffs.save_decision(decided_diff)

            if diff_status is not ArchitectureDiffPersistenceStatus.UPDATED:
                return ArchitectureRevisionResult(
                    status=ArchitectureRevisionStatus.REJECTED,
                    diff=decided_diff,
                    version=version,
                    issue=ArchitectureRevisionApplicationIssueCode.PERSISTENCE_REJECTED,
                    diff_persistence_status=diff_status,
                )

            await unit.commit()

        return ArchitectureRevisionResult(
            status=ArchitectureRevisionStatus.APPLIED,
            diff=decided_diff,
            version=version,
        )


def _diff_targets_version(
    diff: ArchitecturePackageDiff,
    version: ArchitecturePackageVersion,
) -> bool:
    """Return whether a diff still targets the exact current package version."""
    return (
        diff.project_id == version.project_id
        and diff.base_version_id == version.id
        and diff.base_version_number == version.version_number
        and diff.base_content_hash == version.content_hash
    )


def _aware(value: datetime) -> datetime:
    """Require timezone-aware application timestamps."""
    if value.utcoffset() is None:
        raise ValueError("Architecture revision clock must be timezone-aware")

    return value


def _utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)


__all__ = [
    "ArchitectureDiffPersistenceStatus",
    "ArchitecturePackageDiffRepository",
    "ArchitectureRevisionApplicationIssueCode",
    "ArchitectureRevisionResult",
    "ArchitectureRevisionStatus",
    "ArchitectureRevisionUnitOfWork",
    "ArchitectureRevisionUnitOfWorkFactory",
    "LocalArchitectureRevisionService",
]
