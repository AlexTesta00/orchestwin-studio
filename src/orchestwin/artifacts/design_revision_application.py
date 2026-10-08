"""Application service for owner-controlled Design Package revisions."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from types import TracebackType
from typing import Final, Protocol, Self
from uuid import UUID, uuid4

from orchestwin.artifacts.design import DesignAlternative
from orchestwin.artifacts.design_packages import (
    DesignExplorationPackage,
    DesignGrounding,
    DesignPackageVersion,
)
from orchestwin.artifacts.design_realignment import DesignRealignmentIssue
from orchestwin.artifacts.design_revisions import (
    DesignPackageDiff,
    DesignRevisionDecision,
    DesignRevisionDecisionResult,
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
from orchestwin.projects.requirements_primitives import (
    UserTwinVersionReference,
    canonical_user_twin_references,
)

DESIGN_VERSION_NOT_FOUND: Final = "DESIGN_VERSION_NOT_FOUND"
DESIGN_RESTORE_CURRENT: Final = "DESIGN_RESTORE_CURRENT"


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


class DesignRestoreFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DesignPackageHistoryRepository(DesignPackageRepository, Protocol):
    async def history(self, *, project_id: UUID) -> tuple[DesignPackageVersion, ...]: ...


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

    packages: DesignPackageHistoryRepository
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

    async def restore_version(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        version_number: int,
        note: str,
    ) -> DesignRevisionResult:
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            current = await unit.packages.current(project_id=project_id)

            if current is None:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    issue=DesignRevisionApplicationIssueCode.PACKAGE_NOT_FOUND,
                )

            if version_number == current.version_number:
                raise DesignRestoreFailure(DESIGN_RESTORE_CURRENT)

            restored = next(
                (
                    version
                    for version in await unit.packages.history(project_id=project_id)
                    if version.version_number == version_number
                ),
                None,
            )

            if restored is None:
                raise DesignRestoreFailure(DESIGN_VERSION_NOT_FOUND)

            pending = await unit.diffs.current_proposed(
                project_id=project_id,
                base_version_id=current.id,
            )

            if pending is not None:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    diff=pending,
                    issue=DesignRevisionApplicationIssueCode.DIFF_ALREADY_PENDING,
                )

            package = _restored_package(restored.package, current.package.grounding)

            if package.content_hash == current.content_hash:
                raise DesignRestoreFailure(DESIGN_RESTORE_CURRENT)

            occurred_at = _aware(self._clock())
            proposal = propose_design_revision(
                diff_id=self._uuid_factory(),
                owner_user_id=owner_user_id,
                base_version=current,
                proposed_package=package,
                created_at=occurred_at,
            )

            if proposal.status is not DesignRevisionProposalStatus.CREATED or proposal.diff is None:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    issue=DesignRevisionApplicationIssueCode.INVALID_PROPOSAL,
                    domain_issue=proposal.issue,
                )

            decision = decide_design_revision(
                diff=proposal.diff,
                current_version=current,
                decision=DesignRevisionDecision.APPROVE,
                actor_user_id=owner_user_id,
                occurred_at=occurred_at,
                resulting_version_id=self._uuid_factory(),
                reason=note,
            )

            if decision.status is DesignRevisionDecisionStatus.REJECTED:
                return DesignRevisionResult(
                    status=DesignRevisionStatus.REJECTED,
                    diff=proposal.diff,
                    issue=DesignRevisionApplicationIssueCode.DECISION_REJECTED,
                    domain_issue=decision.issue,
                )

            refused = await _persisted_restore(unit, proposal.diff, decision)

            if refused is not None:
                return refused

            await unit.commit()

        return DesignRevisionResult(
            status=DesignRevisionStatus.APPLIED,
            diff=decision.diff,
            version=decision.version,
        )


async def _persisted_restore(
    unit: DesignRevisionUnitOfWork,
    proposed: DesignPackageDiff,
    decision: DesignRevisionDecisionResult,
) -> DesignRevisionResult | None:
    version = decision.version

    if version is None:
        raise RuntimeError("an approved restore requires the new Design Package version")

    created = await unit.diffs.create(proposed)

    if created is not DesignDiffPersistenceStatus.CREATED:
        return DesignRevisionResult(
            status=DesignRevisionStatus.REJECTED,
            diff=proposed,
            issue=DesignRevisionApplicationIssueCode.PERSISTENCE_REJECTED,
            diff_persistence_status=created,
        )

    appended = await unit.packages.append(version)

    if appended is not DesignVersionAppendStatus.APPENDED:
        return DesignRevisionResult(
            status=DesignRevisionStatus.REJECTED,
            diff=decision.diff,
            issue=DesignRevisionApplicationIssueCode.PERSISTENCE_REJECTED,
            version_persistence_status=appended,
        )

    saved = await unit.diffs.save_decision(decision.diff)

    if saved is not DesignDiffPersistenceStatus.UPDATED:
        return DesignRevisionResult(
            status=DesignRevisionStatus.REJECTED,
            diff=decision.diff,
            version=version,
            issue=DesignRevisionApplicationIssueCode.PERSISTENCE_REJECTED,
            diff_persistence_status=saved,
        )

    return None


def _restored_package(
    package: DesignExplorationPackage,
    grounding: DesignGrounding,
) -> DesignExplorationPackage:
    if package.grounding == grounding:
        return package

    twins = {reference.twin_id: reference for reference in grounding.user_twin_references}

    if {reference.twin_id for reference in package.grounding.user_twin_references} != set(twins):
        raise DesignRestoreFailure(DesignRealignmentIssue.TWIN_SET_CHANGED.value)

    try:
        return replace(
            package,
            grounding=grounding,
            alternatives=tuple(
                _restored_alternative(alternative, twins) for alternative in package.alternatives
            ),
            critiques=tuple(
                replace(critique, user_twin_reference=twins[critique.user_twin_reference.twin_id])
                for critique in package.critiques
            ),
        )
    except ValueError as error:
        raise DesignRestoreFailure(
            DesignRealignmentIssue.REQUIREMENT_NO_LONGER_AVAILABLE.value
        ) from error


def _restored_alternative(
    alternative: DesignAlternative,
    twins: Mapping[UUID, UserTwinVersionReference],
) -> DesignAlternative:
    language = alternative.visual_language

    return replace(
        alternative,
        user_twin_references=canonical_user_twin_references(
            (twins[reference.twin_id] for reference in alternative.user_twin_references),
            require_items=True,
        ),
        visual_language=(
            None
            if language is None
            else replace(
                language,
                twin_fit=tuple(
                    replace(fit, name=twins[fit.twin_id].name) if fit.twin_id in twins else fit
                    for fit in language.twin_fit
                ),
            )
        ),
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
    "DESIGN_RESTORE_CURRENT",
    "DESIGN_VERSION_NOT_FOUND",
    "DesignDiffPersistenceStatus",
    "DesignPackageDiffRepository",
    "DesignPackageHistoryRepository",
    "DesignRestoreFailure",
    "DesignRevisionApplicationIssueCode",
    "DesignRevisionResult",
    "DesignRevisionStatus",
    "DesignRevisionUnitOfWork",
    "DesignRevisionUnitOfWorkFactory",
    "LocalDesignRevisionService",
]
