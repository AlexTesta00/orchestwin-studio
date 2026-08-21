"""Tests for governed Design Package revision application behavior."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from types import TracebackType
from uuid import UUID

from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_revision_application import (
    DesignDiffPersistenceStatus,
    DesignRevisionApplicationIssueCode,
    DesignRevisionStatus,
    LocalDesignRevisionService,
)
from orchestwin.artifacts.design_revisions import (
    DesignPackageDiff,
    DesignRevisionDecision,
    DesignRevisionIssueCode,
)
from orchestwin.projects.design_application import DesignVersionAppendStatus

from .design_fixtures import OWNER_ID, PROJECT_ID, design_version

DIFF_ID = UUID("00000000-0000-4000-8000-000000000610")
NEXT_VERSION_ID = UUID("00000000-0000-4000-8000-000000000611")
DECIDED_AT = datetime(2026, 8, 20, 10, 0, tzinfo=UTC)


class _PackageRepository:
    """In-memory append-only Design Package repository."""

    def __init__(self, current: DesignPackageVersion | None) -> None:
        self.value = current
        self.appended: list[DesignPackageVersion] = []
        self.append_status = DesignVersionAppendStatus.APPENDED

    async def current(self, *, project_id: UUID) -> DesignPackageVersion | None:
        if self.value is None or self.value.project_id != project_id:
            return None

        return self.value

    async def append(self, version: DesignPackageVersion) -> DesignVersionAppendStatus:
        if self.append_status is not DesignVersionAppendStatus.APPENDED:
            return self.append_status

        self.appended.append(version)
        self.value = version
        return DesignVersionAppendStatus.APPENDED


class _DiffRepository:
    """In-memory Design Package diff repository."""

    def __init__(self) -> None:
        self.value: DesignPackageDiff | None = None
        self.create_status = DesignDiffPersistenceStatus.CREATED
        self.save_status = DesignDiffPersistenceStatus.UPDATED

    async def create(self, diff: DesignPackageDiff) -> DesignDiffPersistenceStatus:
        if self.create_status is DesignDiffPersistenceStatus.CREATED:
            self.value = diff

        return self.create_status

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> DesignPackageDiff | None:
        if self.value is None or self.value.project_id != project_id or self.value.id != diff_id:
            return None

        return self.value

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_version_id: UUID,
    ) -> DesignPackageDiff | None:
        if (
            self.value is not None
            and self.value.project_id == project_id
            and self.value.base_version_id == base_version_id
        ):
            return self.value

        return None

    async def history(self, *, project_id: UUID) -> tuple[DesignPackageDiff, ...]:
        return () if self.value is None or self.value.project_id != project_id else (self.value,)

    async def save_decision(
        self,
        diff: DesignPackageDiff,
    ) -> DesignDiffPersistenceStatus:
        if self.save_status is DesignDiffPersistenceStatus.UPDATED:
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
    """Create a stable owner-edited Design Package."""
    base = design_version().package
    return replace(
        base,
        open_questions=(
            *base.open_questions,
            "Which keyboard shortcuts must be visible?",
        ),
    )


def service(unit: _UnitOfWork) -> LocalDesignRevisionService:
    """Create a deterministic revision service."""
    identifiers = iter((DIFF_ID, NEXT_VERSION_ID))

    return LocalDesignRevisionService(
        uow_factory=_Factory(unit),
        uuid_factory=lambda: next(identifiers),
        clock=lambda: DECIDED_AT,
    )


def test_propose_revision_persists_an_explicit_owner_diff() -> None:
    """Create a reviewable diff without mutating the current version."""
    packages = _PackageRepository(design_version())
    diffs = _DiffRepository()
    unit = _UnitOfWork(packages, diffs)

    result = asyncio.run(
        service(unit).propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            proposed_package=proposed_package(),
        )
    )

    assert result.status is DesignRevisionStatus.CREATED
    assert result.diff is diffs.value
    assert result.diff is not None
    assert result.diff.id == DIFF_ID
    assert packages.value == design_version()
    assert unit.commits == 1


def test_propose_revision_rejects_a_second_pending_diff() -> None:
    """Keep one active owner decision per exact Design Package baseline."""
    packages = _PackageRepository(design_version())
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

    assert first.status is DesignRevisionStatus.CREATED
    assert second.status is DesignRevisionStatus.REJECTED
    assert second.issue is DesignRevisionApplicationIssueCode.DIFF_ALREADY_PENDING


def test_approve_revision_appends_n_plus_one_and_decides_diff_atomically() -> None:
    """Create immutable N+1 only after the owner approves the exact diff."""
    packages = _PackageRepository(design_version())
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
            decision=DesignRevisionDecision.APPROVE,
            reason="Select and prototype the reviewed direction.",
        )
    )

    assert result.status is DesignRevisionStatus.APPLIED
    assert result.version is not None
    assert result.version.id == NEXT_VERSION_ID
    assert result.version.version_number == 2
    assert result.diff is diffs.value
    assert packages.appended == [result.version]
    assert unit.commits == 2


def test_reject_revision_requires_an_owner_reason() -> None:
    """Preserve an auditable rationale for rejected Design changes."""
    packages = _PackageRepository(design_version())
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
            decision=DesignRevisionDecision.REJECT,
        )
    )

    assert result.status is DesignRevisionStatus.REJECTED
    assert result.issue is DesignRevisionApplicationIssueCode.DECISION_REJECTED
    assert result.domain_issue is DesignRevisionIssueCode.REASON_REQUIRED
    assert packages.appended == []


def test_approve_revision_rolls_back_when_diff_decision_cannot_be_saved() -> None:
    """Do not commit an appended version without its matching audit decision."""
    packages = _PackageRepository(design_version())
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

    diffs.save_status = DesignDiffPersistenceStatus.CONFLICT
    result = asyncio.run(
        revisions.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposal.diff.id,
            decision=DesignRevisionDecision.APPROVE,
        )
    )

    assert result.status is DesignRevisionStatus.REJECTED
    assert result.issue is DesignRevisionApplicationIssueCode.PERSISTENCE_REJECTED
    assert result.diff_persistence_status is DesignDiffPersistenceStatus.CONFLICT
    assert unit.rollbacks == 1
