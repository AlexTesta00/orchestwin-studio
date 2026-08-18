from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID, uuid4

from orchestwin.projects.requirements_application import (
    RequirementsSpecificationRepository,
    RequirementsVersionAppendStatus,
)
from orchestwin.projects.requirements_revisions import (
    RequirementsDiffDecisionStatus,
    RequirementsDiffProposalIssueCode,
    RequirementsDiffProposalStatus,
    RequirementsSpecificationDiff,
    approve_requirements_diff,
    materialize_approved_requirements_diff,
    propose_requirements_diff,
    reject_requirements_diff,
)
from orchestwin.projects.requirements_specifications import (
    RequirementsSpecification,
    RequirementsSpecificationVersion,
)


class RequirementsRevisionDecision(StrEnum):
    """Owner decision on one proposed requirements revision."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RequirementsRevisionStatus(StrEnum):
    """Stable application-level revision outcomes."""

    CREATED = "CREATED"
    APPLIED = "APPLIED"
    NO_CHANGE = "NO_CHANGE"
    REJECTED = "REJECTED"


class RequirementsRevisionIssueCode(StrEnum):
    """Expected reasons a requirements revision cannot continue."""

    SPECIFICATION_NOT_FOUND = "SPECIFICATION_NOT_FOUND"
    DIFF_ALREADY_PENDING = "DIFF_ALREADY_PENDING"
    INVALID_PROPOSAL = "INVALID_PROPOSAL"
    DIFF_NOT_FOUND = "DIFF_NOT_FOUND"
    DECISION_REJECTED = "DECISION_REJECTED"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


class RequirementsDiffPersistenceStatus(StrEnum):
    """Stable outcomes of requirements-diff persistence operations."""

    CREATED = "CREATED"
    UPDATED = "UPDATED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    CONTEXT_NOT_FOUND = "CONTEXT_NOT_FOUND"
    CONFLICT = "CONFLICT"


class RequirementsDiffRepository(Protocol):
    """Persistence boundary for reviewable requirements diffs."""

    async def create(
        self,
        diff: RequirementsSpecificationDiff,
    ) -> RequirementsDiffPersistenceStatus:
        """Persist one proposed diff."""

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> RequirementsSpecificationDiff | None:
        """Return one exact owner-scoped diff."""

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_version_id: UUID,
    ) -> RequirementsSpecificationDiff | None:
        """Return the proposed diff for one exact base version."""

    async def save_decision(
        self,
        diff: RequirementsSpecificationDiff,
    ) -> RequirementsDiffPersistenceStatus:
        """Persist an approved or rejected decision."""


class RequirementsRevisionUnitOfWork(Protocol):
    """Transactional boundary for requirements revisions."""

    specifications: RequirementsSpecificationRepository
    diffs: RequirementsDiffRepository

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


class RequirementsRevisionUnitOfWorkFactory(Protocol):
    """Create one owner-scoped revision Unit of Work."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> RequirementsRevisionUnitOfWork:
        """Create one transactional boundary."""


@dataclass(frozen=True, slots=True)
class RequirementsRevisionResult:
    """Typed result of proposing or deciding one requirements revision."""

    status: RequirementsRevisionStatus
    diff: RequirementsSpecificationDiff | None = None
    version: RequirementsSpecificationVersion | None = None
    issue: RequirementsRevisionIssueCode | None = None
    proposal_issue: RequirementsDiffProposalIssueCode | None = None
    diff_persistence_status: RequirementsDiffPersistenceStatus | None = None
    version_persistence_status: RequirementsVersionAppendStatus | None = None


class LocalRequirementsRevisionService:
    """Coordinate owner-approved immutable specification revisions."""

    def __init__(
        self,
        *,
        uow_factory: RequirementsRevisionUnitOfWorkFactory,
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
        proposed_specification: RequirementsSpecification,
    ) -> RequirementsRevisionResult:
        """Persist one explicit diff against the current specification."""
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current = await unit.specifications.current(project_id=project_id)

            if current is None:
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.REJECTED,
                    issue=RequirementsRevisionIssueCode.SPECIFICATION_NOT_FOUND,
                )

            existing = await unit.diffs.current_proposed(
                project_id=project_id,
                base_version_id=current.id,
            )

            if existing is not None:
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.REJECTED,
                    diff=existing,
                    issue=RequirementsRevisionIssueCode.DIFF_ALREADY_PENDING,
                )

            proposal = propose_requirements_diff(
                base_version=current,
                proposed_specification=proposed_specification,
                diff_id=self._uuid_factory(),
                created_by_user_id=owner_user_id,
                created_at=_aware(self._clock()),
            )

            if (
                proposal.status is not RequirementsDiffProposalStatus.CREATED
                or proposal.diff is None
            ):
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.REJECTED,
                    issue=RequirementsRevisionIssueCode.INVALID_PROPOSAL,
                    proposal_issue=proposal.issue,
                )

            persistence_status = await unit.diffs.create(proposal.diff)

            if persistence_status is not RequirementsDiffPersistenceStatus.CREATED:
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.REJECTED,
                    diff=proposal.diff,
                    issue=RequirementsRevisionIssueCode.PERSISTENCE_REJECTED,
                    diff_persistence_status=persistence_status,
                )

            await unit.commit()

        return RequirementsRevisionResult(
            status=RequirementsRevisionStatus.CREATED,
            diff=proposal.diff,
        )

    async def decide_revision(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        diff_id: UUID,
        decision: RequirementsRevisionDecision,
        reason: str | None = None,
    ) -> RequirementsRevisionResult:
        """Approve or reject one diff and version approved content atomically."""
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current_diff = await unit.diffs.get(
                project_id=project_id,
                diff_id=diff_id,
            )

            if current_diff is None:
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.REJECTED,
                    issue=RequirementsRevisionIssueCode.DIFF_NOT_FOUND,
                )

            occurred_at = _aware(self._clock())

            if decision is RequirementsRevisionDecision.APPROVE:
                domain_decision = approve_requirements_diff(
                    current_diff,
                    actor_user_id=owner_user_id,
                    occurred_at=occurred_at,
                    applied_specification_version_id=self._uuid_factory(),
                    reason=reason,
                )
            else:
                domain_decision = reject_requirements_diff(
                    current_diff,
                    actor_user_id=owner_user_id,
                    occurred_at=occurred_at,
                    reason=reason if reason is not None else "",
                )

            if domain_decision.status is RequirementsDiffDecisionStatus.NO_CHANGE:
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.NO_CHANGE,
                    diff=domain_decision.diff,
                )

            if domain_decision.status is RequirementsDiffDecisionStatus.REJECTED:
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.REJECTED,
                    diff=current_diff,
                    issue=RequirementsRevisionIssueCode.DECISION_REJECTED,
                )

            current = await unit.specifications.current(project_id=project_id)

            if current is None:
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.REJECTED,
                    diff=current_diff,
                    issue=RequirementsRevisionIssueCode.SPECIFICATION_NOT_FOUND,
                )

            if (
                current.id != current_diff.base_version_id
                or current.version_number != current_diff.base_version_number
                or current.content_hash != current_diff.base_content_hash
            ):
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.REJECTED,
                    diff=current_diff,
                    issue=RequirementsRevisionIssueCode.CONTEXT_CHANGED,
                )

            decided_diff = domain_decision.diff

            if decision is RequirementsRevisionDecision.REJECT:
                persistence_status = await unit.diffs.save_decision(decided_diff)

                if persistence_status is not RequirementsDiffPersistenceStatus.UPDATED:
                    return RequirementsRevisionResult(
                        status=RequirementsRevisionStatus.REJECTED,
                        diff=decided_diff,
                        issue=RequirementsRevisionIssueCode.PERSISTENCE_REJECTED,
                        diff_persistence_status=persistence_status,
                    )

                await unit.commit()

                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.APPLIED,
                    diff=decided_diff,
                )

            next_version = materialize_approved_requirements_diff(
                base_version=current,
                approved_diff=decided_diff,
                created_by_user_id=owner_user_id,
                created_at=occurred_at,
            )
            version_status = await unit.specifications.append(next_version)

            if version_status is not RequirementsVersionAppendStatus.APPENDED:
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.REJECTED,
                    diff=decided_diff,
                    issue=RequirementsRevisionIssueCode.PERSISTENCE_REJECTED,
                    version_persistence_status=version_status,
                )

            diff_status = await unit.diffs.save_decision(decided_diff)

            if diff_status is not RequirementsDiffPersistenceStatus.UPDATED:
                return RequirementsRevisionResult(
                    status=RequirementsRevisionStatus.REJECTED,
                    diff=decided_diff,
                    issue=RequirementsRevisionIssueCode.PERSISTENCE_REJECTED,
                    diff_persistence_status=diff_status,
                )

            await unit.commit()

        return RequirementsRevisionResult(
            status=RequirementsRevisionStatus.APPLIED,
            diff=decided_diff,
            version=next_version,
        )


def _aware(value: datetime) -> datetime:
    """Require timezone-aware application timestamps."""
    if value.utcoffset() is None:
        raise ValueError("requirements revision clock must be timezone-aware")

    return value


def _utc_now() -> datetime:
    """Return current UTC time."""
    return datetime.now(UTC)


__all__ = [
    "LocalRequirementsRevisionService",
    "RequirementsDiffPersistenceStatus",
    "RequirementsDiffRepository",
    "RequirementsRevisionDecision",
    "RequirementsRevisionIssueCode",
    "RequirementsRevisionResult",
    "RequirementsRevisionStatus",
    "RequirementsRevisionUnitOfWork",
    "RequirementsRevisionUnitOfWorkFactory",
]
