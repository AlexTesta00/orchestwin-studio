"""Tests for governed brownfield source-archive intake."""

from __future__ import annotations

import asyncio
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType
from typing import Self
from uuid import UUID

from orchestwin.projects.brownfield_application import (
    BrownfieldSourceIntakeIssueCode,
    BrownfieldSourceIntakeStatus,
    LocalBrownfieldSourceIntakeService,
)
from orchestwin.projects.brownfield_persistence import (
    BrownfieldIntakeRepository,
    InMemoryBrownfieldIntakeRepository,
)
from orchestwin.projects.domain import Project, ProjectMode, create_project
from orchestwin.projects.execution_capabilities import (
    CapabilityNegotiationRequest,
    CapabilityNegotiationStatus,
)
from orchestwin.sandbox.archive_store import (
    FileSystemSourceArchiveStore,
    SourceArchiveStoreStatus,
)
from orchestwin.sandbox.builtin_execution_profiles import (
    create_builtin_execution_profile_registry,
)
from orchestwin.sandbox.execution_profiles import ExecutionCapabilityStatus

OWNER_ID = UUID("00000000-0000-4000-8000-000000007601")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000007602")
CREATED_AT = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)


class _ProjectQuery:
    def __init__(self, projects: tuple[Project, ...]) -> None:
        self._projects = {project.id: project for project in projects}

    async def get_owned(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> Project | None:
        project = self._projects.get(project_id)
        if (
            project is None
            or project.owner_user_id != owner_user_id
            or project.archived_at is not None
        ):
            return None
        return project


class _IntakeUnitOfWork:
    def __init__(self, repository: BrownfieldIntakeRepository) -> None:
        self.intakes = repository
        self.committed = False
        self.rolled_back = False

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if exc_type is not None or not self.committed:
            self.rolled_back = True

    async def commit(self) -> None:
        self.committed = True

    async def rollback(self) -> None:
        self.rolled_back = True


class _IntakeUnitOfWorkFactory:
    def __init__(self, repository: BrownfieldIntakeRepository) -> None:
        self._repository = repository
        self.created: list[_IntakeUnitOfWork] = []

    def __call__(self, *, owner_user_id: UUID) -> _IntakeUnitOfWork:
        assert owner_user_id == OWNER_ID
        unit = _IntakeUnitOfWork(self._repository)
        self.created.append(unit)
        return unit


def _project(mode: ProjectMode = ProjectMode.BROWNFIELD_ASSESSMENT) -> Project:
    return create_project(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="Brownfield application fixture",
        mode=mode,
        created_at=CREATED_AT,
    )


def _archive(path: Path, *, unsafe: bool = False) -> Path:
    with zipfile.ZipFile(path, mode="w") as archive:
        if unsafe:
            archive.writestr("../escape.py", "print('unsafe')\n")
        else:
            archive.writestr("index.html", "<!doctype html><title>Fixture</title>\n")
            archive.writestr("assets/site.css", "body { font-family: sans-serif; }\n")
            archive.writestr("node_modules/ignored.js", "generated\n")
    return path


def _request() -> CapabilityNegotiationRequest:
    return CapabilityNegotiationRequest(
        requested_target=None,
        available_runners=(),
        approved_experimental_profiles=(),
    )


def _service(
    tmp_path: Path,
    *,
    project: Project | None = None,
    workspace_cleaner=None,
):
    selected_project = project or _project()
    repository = InMemoryBrownfieldIntakeRepository(
        owner_user_id=OWNER_ID,
        projects={selected_project.id: selected_project},
    )
    uow_factory = _IntakeUnitOfWorkFactory(repository)
    service = LocalBrownfieldSourceIntakeService(
        projects=_ProjectQuery((selected_project,)),
        archive_store=FileSystemSourceArchiveStore(tmp_path / "archive-store"),
        profile_registry=create_builtin_execution_profile_registry(),
        uow_factory=uow_factory,
        workspace_root=tmp_path / "workspaces",
        clock=lambda: CREATED_AT,
        workspace_cleaner=workspace_cleaner,
    )
    return service, repository, uow_factory


def test_service_validates_inventories_negotiates_and_persists_one_snapshot(
    tmp_path: Path,
) -> None:
    """Complete intake without Docker, network, or live-model dependencies."""
    service, repository, uow_factory = _service(tmp_path)
    archive_path = _archive(tmp_path / "source.zip")

    result = asyncio.run(
        service.ingest(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            archive_path=archive_path,
            capability_request=_request(),
        )
    )

    assert result.status is BrownfieldSourceIntakeStatus.CREATED
    assert result.version is not None
    assert result.version.capability_status is (
        CapabilityNegotiationStatus.DESIGN_ONLY_LEVEL_C_SELECTED
    )
    assert result.version.effective_capability_status is (
        ExecutionCapabilityStatus.DESIGN_ONLY_LEVEL_C
    )
    assert result.version.selected_profile_reference is not None
    assert result.version.selected_profile_reference.profile_id == "WEB_STATIC"
    assert result.archive_store_status is SourceArchiveStoreStatus.STORED
    assert len(asyncio.run(repository.history(project_id=PROJECT_ID))) == 1
    assert uow_factory.created[-1].committed is True
    assert list((tmp_path / "workspaces").iterdir()) == []


def test_service_reuses_identical_intake_without_version_drift(tmp_path: Path) -> None:
    """Make retried uploads idempotent by exact immutable snapshot content."""
    service, repository, _uow_factory = _service(tmp_path)
    archive_path = _archive(tmp_path / "source.zip")

    first = asyncio.run(
        service.ingest(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            archive_path=archive_path,
            capability_request=_request(),
        )
    )
    second = asyncio.run(
        service.ingest(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            archive_path=archive_path,
            capability_request=_request(),
        )
    )

    assert first.status is BrownfieldSourceIntakeStatus.CREATED
    assert second.status is BrownfieldSourceIntakeStatus.REUSED
    assert second.version == first.version
    assert second.archive_store_status is SourceArchiveStoreStatus.ALREADY_PRESENT
    assert len(asyncio.run(repository.history(project_id=PROJECT_ID))) == 1


def test_service_rejects_unsafe_archive_before_storage_or_extraction(tmp_path: Path) -> None:
    """Preserve complete preflight as the first archive-processing boundary."""
    service, repository, uow_factory = _service(tmp_path)
    archive_path = _archive(tmp_path / "unsafe.zip", unsafe=True)

    result = asyncio.run(
        service.ingest(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            archive_path=archive_path,
            capability_request=_request(),
        )
    )

    assert result.status is BrownfieldSourceIntakeStatus.REJECTED
    assert result.issue is BrownfieldSourceIntakeIssueCode.ARCHIVE_REJECTED
    assert result.validation_report is not None
    assert result.validation_report.is_accepted is False
    assert not (tmp_path / "archive-store").exists()
    assert not (tmp_path / "workspaces").exists()
    assert asyncio.run(repository.history(project_id=PROJECT_ID)) == ()
    assert uow_factory.created == []


def test_service_checks_owner_and_mode_before_touching_archive(tmp_path: Path) -> None:
    """Avoid filesystem side effects for missing or greenfield projects."""
    greenfield = _project(ProjectMode.GREENFIELD_GENERATION)
    service, repository, uow_factory = _service(tmp_path, project=greenfield)

    result = asyncio.run(
        service.ingest(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            archive_path=tmp_path / "missing.zip",
            capability_request=_request(),
        )
    )

    assert result.issue is BrownfieldSourceIntakeIssueCode.PROJECT_MODE_UNSUPPORTED
    assert not (tmp_path / "archive-store").exists()
    assert asyncio.run(repository.history(project_id=PROJECT_ID)) == ()
    assert uow_factory.created == []


def test_service_does_not_persist_when_workspace_cleanup_cannot_be_confirmed(
    tmp_path: Path,
) -> None:
    """Pause intake rather than leaving an untracked extracted workspace."""
    service, repository, uow_factory = _service(
        tmp_path,
        workspace_cleaner=lambda _path: False,
    )
    archive_path = _archive(tmp_path / "source.zip")

    result = asyncio.run(
        service.ingest(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            archive_path=archive_path,
            capability_request=_request(),
        )
    )

    assert result.status is BrownfieldSourceIntakeStatus.REJECTED
    assert result.issue is BrownfieldSourceIntakeIssueCode.WORKSPACE_CLEANUP_FAILED
    assert asyncio.run(repository.history(project_id=PROJECT_ID)) == ()
    assert uow_factory.created == []
    shutil.rmtree(tmp_path / "workspaces")
