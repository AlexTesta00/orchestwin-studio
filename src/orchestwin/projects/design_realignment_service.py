from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from types import TracebackType
from typing import Final, Protocol, Self
from uuid import UUID, uuid4

from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_realignment import (
    DesignRealignmentIssue,
    design_is_aligned,
    design_realignment_issue,
    item_codes,
    missing_item_ids,
    realigned_design_version,
    uncovered_requirement_codes,
)
from orchestwin.artifacts.design_revisions import DesignPackageDiff
from orchestwin.projects.design_application import DesignVersionAppendStatus
from orchestwin.projects.requirements_gate import requirements_gate_is_currently_approved
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.workflow.gates import HumanGate

DESIGN_NOT_FOUND: Final = "DESIGN_NOT_FOUND"
REQUIREMENTS_APPROVAL_REQUIRED: Final = "REQUIREMENTS_APPROVAL_REQUIRED"
DESIGN_REVISION_PENDING: Final = "DESIGN_REVISION_PENDING"
PERSISTENCE_REJECTED: Final = "PERSISTENCE_REJECTED"


class DesignRealignmentFailure(Exception):
    def __init__(self, code: str, *, missing_codes: tuple[str, ...] = ()) -> None:
        super().__init__(code)
        self.code = code
        self.missing_codes = missing_codes


@dataclass(frozen=True, slots=True)
class DesignAlignment:
    aligned: bool
    issue: str | None
    design_version_number: int | None
    grounded_requirements_version_number: int | None
    requirements_version_number: int | None
    missing_codes: tuple[str, ...]
    uncovered_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DesignRealignment:
    version: DesignPackageVersion
    requirements_version_number: int
    uncovered_codes: tuple[str, ...]


class DesignRealignmentPackageRepository(Protocol):
    async def current(self, *, project_id: UUID) -> DesignPackageVersion | None: ...

    async def get_current_owned_for_update(
        self, *, project_id: UUID, owner_user_id: UUID
    ) -> DesignPackageVersion | None: ...

    async def append(self, version: DesignPackageVersion) -> DesignVersionAppendStatus: ...


class DesignRealignmentDiffRepository(Protocol):
    async def current_proposed(
        self, *, project_id: UUID, base_version_id: UUID
    ) -> DesignPackageDiff | None: ...


class DesignRealignmentUnitOfWork(Protocol):
    packages: DesignRealignmentPackageRepository
    diffs: DesignRealignmentDiffRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...


class DesignRealignmentUnitOfWorkFactory(Protocol):
    def __call__(self, *, owner_user_id: UUID) -> DesignRealignmentUnitOfWork: ...


class DesignRealignmentRequirementsQueries(Protocol):
    async def current(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> RequirementsSpecificationVersion | None: ...

    async def history(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[RequirementsSpecificationVersion, ...]: ...


class DesignRealignmentGateQueries(Protocol):
    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID) -> HumanGate | None: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _issue(
    current: DesignPackageVersion | None,
    requirements: RequirementsSpecificationVersion | None,
    *,
    requirements_approved: bool,
    revision_pending: bool,
) -> str | None:
    if current is None:
        return DESIGN_NOT_FOUND
    if requirements is None or not requirements_approved:
        return REQUIREMENTS_APPROVAL_REQUIRED
    issue = design_realignment_issue(current.package, requirements)
    if issue is not None:
        return issue.value
    if revision_pending:
        return DESIGN_REVISION_PENDING
    return None


async def _revision_pending(
    uow: DesignRealignmentUnitOfWork,
    *,
    project_id: UUID,
    current: DesignPackageVersion | None,
) -> bool:
    if current is None:
        return False
    proposed = await uow.diffs.current_proposed(project_id=project_id, base_version_id=current.id)
    return proposed is not None


class DesignRealignmentService:
    def __init__(
        self,
        *,
        uow_factory: DesignRealignmentUnitOfWorkFactory,
        requirements_queries: DesignRealignmentRequirementsQueries,
        requirements_gates: DesignRealignmentGateQueries,
        clock: Callable[[], datetime] = _utc_now,
        uuid_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self._uow_factory = uow_factory
        self._requirements_queries = requirements_queries
        self._requirements_gates = requirements_gates
        self._clock = clock
        self._uuid_factory = uuid_factory

    async def status(self, *, owner_user_id: UUID, project_id: UUID) -> DesignAlignment:
        requirements, approved = await self._requirements(
            owner_user_id=owner_user_id, project_id=project_id
        )
        async with self._uow_factory(owner_user_id=owner_user_id) as uow:
            current = await uow.packages.current(project_id=project_id)
            revision_pending = await _revision_pending(uow, project_id=project_id, current=current)
        missing_codes = await self._missing_codes(
            owner_user_id=owner_user_id,
            project_id=project_id,
            current=current,
            requirements=requirements,
        )
        if current is None or requirements is None:
            aligned, uncovered_codes = False, ()
        else:
            aligned = design_is_aligned(current.package, requirements)
            uncovered_codes = uncovered_requirement_codes(current.package, requirements)
        return DesignAlignment(
            aligned=aligned,
            issue=_issue(
                current,
                requirements,
                requirements_approved=approved,
                revision_pending=revision_pending,
            ),
            design_version_number=None if current is None else current.version_number,
            grounded_requirements_version_number=(
                None
                if current is None
                else current.package.grounding.requirements_reference.version_number
            ),
            requirements_version_number=(
                None if requirements is None else requirements.version_number
            ),
            missing_codes=missing_codes,
            uncovered_codes=uncovered_codes,
        )

    async def realign(self, *, owner_user_id: UUID, project_id: UUID) -> DesignRealignment:
        requirements, approved = await self._requirements(
            owner_user_id=owner_user_id, project_id=project_id
        )
        async with self._uow_factory(owner_user_id=owner_user_id) as uow:
            current = await uow.packages.get_current_owned_for_update(
                project_id=project_id, owner_user_id=owner_user_id
            )
            issue = _issue(
                current,
                requirements,
                requirements_approved=approved,
                revision_pending=await _revision_pending(
                    uow, project_id=project_id, current=current
                ),
            )
            if issue is None and current is not None and requirements is not None:
                version = realigned_design_version(
                    current,
                    requirements,
                    version_id=self._uuid_factory(),
                    created_by_user_id=owner_user_id,
                    created_at=self._clock(),
                )
                status = await uow.packages.append(version)
                if status is not DesignVersionAppendStatus.APPENDED:
                    raise DesignRealignmentFailure(PERSISTENCE_REJECTED)
                await uow.commit()
                return DesignRealignment(
                    version=version,
                    requirements_version_number=requirements.version_number,
                    uncovered_codes=uncovered_requirement_codes(version.package, requirements),
                )
        code = issue or DESIGN_NOT_FOUND
        if code != DesignRealignmentIssue.REQUIREMENT_NO_LONGER_AVAILABLE.value:
            raise DesignRealignmentFailure(code)
        raise DesignRealignmentFailure(
            code,
            missing_codes=await self._missing_codes(
                owner_user_id=owner_user_id,
                project_id=project_id,
                current=current,
                requirements=requirements,
            ),
        )

    async def _requirements(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[RequirementsSpecificationVersion | None, bool]:
        requirements = await self._requirements_queries.current(
            owner_user_id=owner_user_id, project_id=project_id
        )
        if requirements is None:
            return None, False
        gate = await self._requirements_gates.current_gate(
            project_id=project_id, owner_user_id=owner_user_id
        )
        return requirements, requirements_gate_is_currently_approved(gate, requirements)

    async def _missing_codes(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        current: DesignPackageVersion | None,
        requirements: RequirementsSpecificationVersion | None,
    ) -> tuple[str, ...]:
        if current is None or requirements is None:
            return ()
        missing = missing_item_ids(current.package, requirements)
        if not missing:
            return ()
        reference = current.package.grounding.requirements_reference
        history = await self._requirements_queries.history(
            owner_user_id=owner_user_id, project_id=project_id
        )
        grounded = next(
            (version for version in history if version.id == reference.artifact_id), None
        )
        return () if grounded is None else item_codes(grounded.specification, missing)


__all__ = [
    "DESIGN_NOT_FOUND",
    "DESIGN_REVISION_PENDING",
    "PERSISTENCE_REJECTED",
    "REQUIREMENTS_APPROVAL_REQUIRED",
    "DesignAlignment",
    "DesignRealignment",
    "DesignRealignmentDiffRepository",
    "DesignRealignmentFailure",
    "DesignRealignmentGateQueries",
    "DesignRealignmentPackageRepository",
    "DesignRealignmentRequirementsQueries",
    "DesignRealignmentService",
    "DesignRealignmentUnitOfWork",
    "DesignRealignmentUnitOfWorkFactory",
]
