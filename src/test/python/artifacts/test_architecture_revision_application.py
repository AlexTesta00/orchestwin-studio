"""Tests for governed Architecture Package revision application behavior."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

from orchestwin.artifacts.architecture_packages import ArchitecturePackageVersion
from orchestwin.artifacts.architecture_revision_application import (
    ArchitectureDiffPersistenceStatus,
    ArchitectureRevisionApplicationIssueCode,
    ArchitectureRevisionStatus,
    LocalArchitectureRevisionService,
)
from orchestwin.artifacts.architecture_revisions import (
    ArchitecturePackageDiff,
    ArchitectureRevisionDecision,
    ArchitectureRevisionIssueCode,
)
from orchestwin.projects.architecture_application import ArchitectureVersionAppendStatus

from .architecture_fixtures import OWNER_ID, PROJECT_ID, architecture_version

DIFF_ID = UUID("00000000-0000-4000-8000-000000000610")
NEXT_VERSION_ID = UUID("00000000-0000-4000-8000-000000000611")
DECIDED_AT = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


class _PackageRepository:
    """In-memory append-only Architecture Package repository."""

    def __init__(self, current: ArchitecturePackageVersion | None) -> None:
        self.value = current
        self.appended: list[ArchitecturePackageVersion] = []
        self.append_status = ArchitectureVersionAppendStatus.APPENDED

    async def current(self, *, project_id: UUID) -> ArchitecturePackageVersion | None:
        if self.value is None or self.value.project_id != project_id:
            return None

        return self.value

    async def append(self, version: ArchitecturePackageVersion) -> ArchitectureVersionAppendStatus:
        if self.append_status is not ArchitectureVersionAppendStatus.APPENDED:
            return self.append_status

        self.appended.append(version)
        self.value = version
        return ArchitectureVersionAppendStatus.APPENDED


class _DiffRepository:
    """In-memory Architecture Package diff repository."""

    def __init__(self) -> None:
        self.value: ArchitecturePackageDiff | None = None
        self.create_status = ArchitectureDiffPersistenceStatus.CREATED
        self.save_status = ArchitectureDiffPersistenceStatus.UPDATED

    async def create(self, diff: ArchitecturePackageDiff) -> ArchitectureDiffPersistenceStatus:
        if self.create_status is ArchitectureDiffPersistenceStatus.CREATED:
            self.value = diff

        return self.create_status

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> ArchitecturePackageDiff | None:
        if self.value is None or self.value.project_id != project_id or self.value.id != diff_id:
            return None

        return self.value

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_version_id: UUID,
    ) -> ArchitecturePackageDiff | None:
        if (
            self.value is not None
            and self.value.project_id == project_id
            and self.value.base_version_id == base_version_id
        ):
            return self.value

        return None

    async def history(self, *, project_id: UUID) -> tuple[ArchitecturePackageDiff, ...]:
        return () if self.value is None or self.value.project_id != project_id else (self.value,)

    async def save_decision(
        self,
        diff: ArchitecturePackageDiff,
    ) -> ArchitectureDiffPersistenceStatus:
        if self.save_status is ArchitectureDiffPersistenceStatus.UPDATED:
            self.value = diff

        return self.save_status


class _UnitOfWork:
    """Record transactional outcomes around in-memory repositories."""

    def __init__(
        self,
        packages: _PackageRepository,
        diffs: _DiffRepository,
    ) -> None:
        self.packages = packages
        self.diffs = diffs
        self.commits = 0
        self.rollbacks = 0
        self._completed = False

    async def __aenter__(self):
        self._completed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

        if not self._completed:
            self.rollbacks += 1
            self._completed = True

    async def commit(self) -> None:
        self.commits += 1
        self._completed = True

    async def rollback(self) -> None:
        self.rollbacks += 1
        self._completed = True


class _Factory:
    """Return one shared test Unit of Work."""

    def __init__(self, unit: _UnitOfWork) -> None:
        self.unit = unit

    def __call__(self, *, owner_user_id: UUID) -> _UnitOfWork:
        assert owner_user_id == OWNER_ID
        return self.unit


def proposed_package():
    """Create a stable owner-edited Architecture Package."""
    base = architecture_version().package
    return replace(
        base,
        open_questions=(
            *base.open_questions,
            "Which execution profile must verify the package?",
        ),
    )


def service(unit: _UnitOfWork) -> LocalArchitectureRevisionService:
    """Create a deterministic revision service."""
    identifiers = iter((DIFF_ID, NEXT_VERSION_ID))

    return LocalArchitectureRevisionService(
        uow_factory=_Factory(unit),
        uuid_factory=lambda: next(identifiers),
        clock=lambda: DECIDED_AT,
    )


def test_propose_revision_persists_an_explicit_owner_diff() -> None:
    """Create a reviewable diff without mutating the current version."""
    packages = _PackageRepository(architecture_version())
    diffs = _DiffRepository()
    unit = _UnitOfWork(packages, diffs)

    result = asyncio.run(
        service(unit).propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_package=proposed_package(),
        )
    )

    assert result.status is ArchitectureRevisionStatus.CREATED
    assert result.diff is diffs.value
    assert result.diff is not None
    assert result.diff.id == DIFF_ID
    assert packages.value == architecture_version()
    assert unit.commits == 1


def test_propose_revision_rejects_a_second_pending_diff() -> None:
    """Keep one active owner decision per exact Architecture Package baseline."""
    packages = _PackageRepository(architecture_version())
    diffs = _DiffRepository()
    unit = _UnitOfWork(packages, diffs)
    revisions = service(unit)

    first = asyncio.run(
        revisions.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_package=proposed_package(),
        )
    )
    second = asyncio.run(
        revisions.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_package=proposed_package(),
        )
    )

    assert first.status is ArchitectureRevisionStatus.CREATED
    assert second.status is ArchitectureRevisionStatus.REJECTED
    assert second.issue is ArchitectureRevisionApplicationIssueCode.DIFF_ALREADY_PENDING


def test_approve_revision_appends_n_plus_one_and_decides_diff_atomically() -> None:
    """Create immutable N+1 only after the owner approves the exact diff."""
    packages = _PackageRepository(architecture_version())
    diffs = _DiffRepository()
    unit = _UnitOfWork(packages, diffs)
    revisions = service(unit)
    proposal = asyncio.run(
        revisions.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_package=proposed_package(),
        )
    )

    if proposal.diff is None:
        raise AssertionError("revision proposal was not created")

    result = asyncio.run(
        revisions.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposal.diff.id,
            decision=ArchitectureRevisionDecision.APPROVE,
            reason="Approve the reviewed architecture and test plan.",
        )
    )

    assert result.status is ArchitectureRevisionStatus.APPLIED
    assert result.version is not None
    assert result.version.id == NEXT_VERSION_ID
    assert result.version.version_number == 2
    assert result.diff is diffs.value
    assert packages.appended == [result.version]
    assert unit.commits == 2


def test_reject_revision_requires_an_owner_reason() -> None:
    """Preserve an auditable rationale for rejected Architecture changes."""
    packages = _PackageRepository(architecture_version())
    diffs = _DiffRepository()
    unit = _UnitOfWork(packages, diffs)
    revisions = service(unit)
    proposal = asyncio.run(
        revisions.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_package=proposed_package(),
        )
    )

    if proposal.diff is None:
        raise AssertionError("revision proposal was not created")

    result = asyncio.run(
        revisions.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposal.diff.id,
            decision=ArchitectureRevisionDecision.REJECT,
        )
    )

    assert result.status is ArchitectureRevisionStatus.REJECTED
    assert result.issue is ArchitectureRevisionApplicationIssueCode.DECISION_REJECTED
    assert result.domain_issue is ArchitectureRevisionIssueCode.REASON_REQUIRED
    assert packages.appended == []


def test_approve_revision_rolls_back_when_diff_decision_cannot_be_saved() -> None:
    """Do not commit an appended version without its matching audit decision."""
    packages = _PackageRepository(architecture_version())
    diffs = _DiffRepository()
    unit = _UnitOfWork(packages, diffs)
    revisions = service(unit)
    proposal = asyncio.run(
        revisions.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_package=proposed_package(),
        )
    )

    if proposal.diff is None:
        raise AssertionError("revision proposal was not created")

    diffs.save_status = ArchitectureDiffPersistenceStatus.CONFLICT
    result = asyncio.run(
        revisions.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposal.diff.id,
            decision=ArchitectureRevisionDecision.APPROVE,
        )
    )

    assert result.status is ArchitectureRevisionStatus.REJECTED
    assert result.issue is ArchitectureRevisionApplicationIssueCode.PERSISTENCE_REJECTED
    assert result.diff_persistence_status is ArchitectureDiffPersistenceStatus.CONFLICT
    assert unit.rollbacks == 1
