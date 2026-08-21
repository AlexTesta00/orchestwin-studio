"""Application service for owner-controlled Design Package revisions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.artifacts.design_packages import (
    DesignExplorationPackage,
    DesignPackageVersion,
)
from orchestwin.artifacts.design_revisions import (
    DesignPackageDiff,
    DesignRevisionDecision,
    DesignRevisionDecisionStatus,
    DesignRevisionIssueCode,
    DesignRevisionProposalStatus,
    decide_design_revision,
    propose_design_revision,
)
from orchestwin.projects.design_application import (
    DesignPackageRepository,
    DesignVersionAppendStatus,
)


class DesignRevisionStatus(StrEnum):
    """Stable application-level Design Package revision outcomes."""

    CREATED = "CREATED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class DesignRevisionApplicationIssueCode(StrEnum):
    """Expected reasons a Design Package revision cannot continue."""

    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    DIFF_ALREADY_PENDING = "DIFF_ALREADY_PENDING"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    DIFF_NOT_FOUND = "DIFF_NOT_FOUND"
    DECISION_REJECTED = "DECISION_REJECTED"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


class DesignDiffPersistenceStatus(StrEnum):
    """Stable outcomes of Design Package diff persistence operations."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    CONTEXT_NOT_FOUND = "CONTEXT_NOT_FOUND"
    CONFLICT = "CONFLICT"


class DesignPackageDiffRepository(Protocol):
    """Persistence boundary for reviewable Design Package diffs."""

    async def create(
        self,
        diff: DesignPackageDiff,
    ) -> DesignDiffPersistenceStatus:
        """Persist one proposed diff."""

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> DesignPackageDiff | None:
        """Return one exact owner-scoped diff."""

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_version_id: UUID,
    ) -> DesignPackageDiff | None:
        """Return the proposed diff for one exact base version."""

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[DesignPackageDiff, ...]:
        """Return owner-scoped diff history in creation order."""

    async def save_decision(
        self,
        diff: DesignPackageDiff,
    ) -> DesignDiffPersistenceStatus:
        """Persist an approved or rejected decision."""


class DesignRevisionUnitOfWork(Protocol):
    """Transactional boundary for Design Package revisions."""

    packages: DesignPackageRepository
    diffs: DesignPackageDiffRepository

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


class DesignRevisionUnitOfWorkFactory(Protocol):
    """Create one owner-scoped Design Package revision Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> DesignRevisionUnitOfWork:
        """Create one transactional boundary."""


@dataclass(frozen=True, slots=True)
class DesignRevisionResult:
    """Typed result of proposing or deciding one Design Package revision."""

    status: DesignRevisionStatus
    diff: DesignPackageDiff | None = None
    version: DesignPackageVersion | None = None
    issue: DesignRevisionApplicationIssueCode | None = None
    domain_issue: DesignRevisionIssueCode | None = None
    diff_persistence_status: DesignDiffPersistenceStatus | None = None
    version_persistence_status: DesignVersionAppendStatus | None = None


class LocalDesignRevisionService:
    """Coordinate owner-approved immutable Design Package revisions."""

    def __init__(
        self,
        *,
        uow_factory: DesignRevisionUnitOfWorkFactory,
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
        proposed_package: DesignExplorationPackage,
    ) -> DesignRevisionResult:
        """Persist one explicit diff against the current Design Package."""
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current = await unit.packages.current(project_id=project_id)

            if current is None:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    issue=DesignRevisionApplicationIssueCode.PACKAGE_NOT_FOUND,
                )

            existing = await unit.diffs.current_proposed(
                project_id=project_id,
                base_version_id=current.id,
            )

            if existing is not None:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    diff=existing,
                    issue=DesignRevisionApplicationIssueCode.DIFF_ALREADY_PENDING,
                )

            proposal = propose_design_revision(
                diff_id=self._uuid_factory(),
                owner_user_id=owner_user_id,
                base_version=current,
                proposed_package=proposed_package,
                created_at=_aware(self._clock()),
            )

            if proposal.status is not DesignRevisionProposalStatus.CREATED or proposal.diff is None:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    issue=DesignRevisionApplicationIssueCode.INVALID_PROPOSAL,
                    domain_issue=proposal.issue,
                )

            persistence_status = await unit.diffs.create(proposal.diff)

            if persistence_status is not DesignDiffPersistenceStatus.CREATED:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    diff=proposal.diff,
                    issue=DesignRevisionApplicationIssueCode.PERSISTENCE_REJECTED,
                    diff_persistence_status=persistence_status,
                )

            await unit.commit()

        return DesignRevisionResult(
            status=DesignRevisionStatus.CREATED,
            diff=proposal.diff,
        )

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: DesignRevisionDecision,
        reason: str | None = None,
    ) -> DesignRevisionResult:
        """Approve or reject one diff and version approved content atomically."""
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current_diff = await unit.diffs.get(
                project_id=project_id,
                diff_id=diff_id,
            )

            if current_diff is None:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    issue=DesignRevisionApplicationIssueCode.DIFF_NOT_FOUND,
                )

            current = await unit.packages.current(project_id=project_id)

            if current is None:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    diff=current_diff,
                    issue=DesignRevisionApplicationIssueCode.PACKAGE_NOT_FOUND,
                )

            if not _diff_targets_version(current_diff, current):
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    diff=current_diff,
                    issue=DesignRevisionApplicationIssueCode.CONTEXT_CHANGED,
                )

            domain_decision = decide_design_revision(
                diff=current_diff,
                current_version=current,
                decision=decision,
                actor_user_id=owner_user_id,
                occurred_at=_aware(self._clock()),
                resulting_version_id=(
                    self._uuid_factory() if decision is DesignRevisionDecision.APPROVE else None
                ),
                reason=reason,
            )

            if domain_decision.status is DesignRevisionDecisionStatus.REJECTED:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    diff=current_diff,
                    issue=DesignRevisionApplicationIssueCode.DECISION_REJECTED,
                    domain_issue=domain_decision.issue,
                )

            decided_diff = domain_decision.diff
            version = domain_decision.version

            if version is not None:
                version_status = await unit.packages.append(version)

                if version_status is not DesignVersionAppendStatus.APPENDED:
                    return DesignRevisionResult(
                        status=DesignRevisionStatus.REJECTED,
                        diff=decided_diff,
                        issue=DesignRevisionApplicationIssueCode.PERSISTENCE_REJECTED,
                        version_persistence_status=version_status,
                    )

            diff_status = await unit.diffs.save_decision(decided_diff)

            if diff_status is not DesignDiffPersistenceStatus.UPDATED:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    diff=decided_diff,
                    version=version,
                    issue=DesignRevisionApplicationIssueCode.PERSISTENCE_REJECTED,
                    diff_persistence_status=diff_status,
                )

            await unit.commit()

        return DesignRevisionResult(
            status=DesignRevisionStatus.APPLIED,
            diff=decided_diff,
            version=version,
        )


def _diff_targets_version(
    diff: DesignPackageDiff,
    version: DesignPackageVersion,
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
        raise ValueError("Design revision clock must be timezone-aware")

    return value


def _utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)


__all__ = [
    "DesignDiffPersistenceStatus",
    "DesignPackageDiffRepository",
    "DesignRevisionApplicationIssueCode",
    "DesignRevisionResult",
    "DesignRevisionStatus",
    "DesignRevisionUnitOfWork",
    "DesignRevisionUnitOfWorkFactory",
    "LocalDesignRevisionService",
]
