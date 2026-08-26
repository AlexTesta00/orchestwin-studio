"""Composition helpers for brownfield intake, sandbox evidence, and Gate 7."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.config import ApplicationSettings
from orchestwin.projects.brownfield_application import (
    BrownfieldSourceIntakeResult,
    LocalBrownfieldSourceIntakeService,
)
from orchestwin.projects.brownfield_persistence import (
    PersistedBrownfieldIntakeVersion,
    SqlAlchemyBrownfieldIntakeUnitOfWorkFactory,
)
from orchestwin.projects.domain import Project
from orchestwin.projects.execution_capabilities import CapabilityNegotiationRequest
from orchestwin.projects.persistence.repositories import SqlAlchemyProjectRepository
from orchestwin.sandbox.archive_store import FileSystemSourceArchiveStore
from orchestwin.sandbox.builtin_execution_profiles import (
    create_builtin_execution_profile_registry,
)
from orchestwin.sandbox.execution_profile_registry import ExecutionProfileRegistry
from orchestwin.sandbox.execution_profiles import ExecutionProfileMetadata
from orchestwin.sandbox.run_persistence import (
    PersistedProjectSandboxRun,
    SandboxRunUnitOfWorkFactory,
    SqlAlchemySandboxRunUnitOfWorkFactory,
)
from orchestwin.workflow.high_impact import HighImpactOperationPolicy
from orchestwin.workflow.high_impact_gate import LocalHighImpactApprovalService
from orchestwin.workflow.high_impact_persistence import (
    SqlAlchemyHighImpactApprovalUnitOfWorkFactory,
)


class SqlAlchemyBrownfieldProjectQuery:
    """Read one active owner-scoped project with a short-lived session."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get_owned(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> Project | None:
        async with self._session_factory() as session:
            return await SqlAlchemyProjectRepository(session).get_owned(
                owner_user_id=owner_user_id,
                project_id=project_id,
            )


class BrownfieldRuntimeService:
    """Combine governed intake commands with owner-scoped snapshot queries."""

    def __init__(
        self,
        *,
        intake_service: LocalBrownfieldSourceIntakeService,
        session_factory: async_sessionmaker[AsyncSession],
        configured_runners: tuple[str, ...],
    ) -> None:
        self._intake_service = intake_service
        self._uow_factory = SqlAlchemyBrownfieldIntakeUnitOfWorkFactory(session_factory)
        self._configured_runners = configured_runners

    async def ingest(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        archive_path: Path,
        capability_request: CapabilityNegotiationRequest,
    ) -> BrownfieldSourceIntakeResult:
        effective_request = replace(
            capability_request,
            available_runners=tuple(
                sorted(set(capability_request.available_runners) | set(self._configured_runners))
            ),
        )
        return await self._intake_service.ingest(
            owner_user_id=owner_user_id,
            project_id=project_id,
            archive_path=archive_path,
            capability_request=effective_request,
        )

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[PersistedBrownfieldIntakeVersion, ...]:
        async with self._uow_factory(owner_user_id=owner_user_id) as unit_of_work:
            return await unit_of_work.intakes.history(project_id=project_id)

    async def current(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> PersistedBrownfieldIntakeVersion | None:
        async with self._uow_factory(owner_user_id=owner_user_id) as unit_of_work:
            return await unit_of_work.intakes.current(project_id=project_id)


class LocalExecutionQueryService:
    """Expose canonical profile metadata and owner-scoped sandbox evidence."""

    def __init__(
        self,
        *,
        registry: ExecutionProfileRegistry,
        sandbox_uow_factory: SandboxRunUnitOfWorkFactory,
    ) -> None:
        self._registry = registry
        self._sandbox_uow_factory = sandbox_uow_factory

    async def profiles(self) -> tuple[ExecutionProfileMetadata, ...]:
        return tuple(profile.metadata for profile in self._registry.profiles)

    async def profile(
        self,
        *,
        profile_id: str,
        profile_version: str | None,
    ) -> ExecutionProfileMetadata | None:
        if profile_version is None:
            versions = self._registry.versions_for(profile_id)
            return None if not versions else versions[-1].metadata
        profile = self._registry.find(profile_id, profile_version)
        return None if profile is None else profile.metadata

    async def sandbox_history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
    ) -> tuple[PersistedProjectSandboxRun, ...]:
        async with self._sandbox_uow_factory(owner_user_id=owner_user_id) as unit_of_work:
            return await unit_of_work.runs.history(project_id=project_id)

    async def sandbox_run(
        self,
        *,
        owner_user_id: UUID,
        run_id: UUID,
    ) -> PersistedProjectSandboxRun | None:
        async with self._sandbox_uow_factory(owner_user_id=owner_user_id) as unit_of_work:
            return await unit_of_work.runs.get(run_id=run_id)


@dataclass(frozen=True, slots=True)
class Sprint07ServiceBundle:
    """Runtime adapters introduced by the Sprint 07 bounded context."""

    brownfield: BrownfieldRuntimeService
    execution_queries: LocalExecutionQueryService
    high_impact: LocalHighImpactApprovalService
    profile_registry: ExecutionProfileRegistry


def build_sprint07_services(
    settings: ApplicationSettings,
    session_factory: async_sessionmaker[AsyncSession],
) -> Sprint07ServiceBundle:
    """Compose safe filesystem and PostgreSQL adapters without starting Docker."""
    registry = create_builtin_execution_profile_registry()
    intake = LocalBrownfieldSourceIntakeService(
        projects=SqlAlchemyBrownfieldProjectQuery(session_factory),
        archive_store=FileSystemSourceArchiveStore(settings.source_archive_storage_root),
        profile_registry=registry,
        uow_factory=SqlAlchemyBrownfieldIntakeUnitOfWorkFactory(session_factory),
        workspace_root=settings.brownfield_workspace_root,
    )
    brownfield = BrownfieldRuntimeService(
        intake_service=intake,
        session_factory=session_factory,
        configured_runners=settings.available_execution_runners,
    )
    execution_queries = LocalExecutionQueryService(
        registry=registry,
        sandbox_uow_factory=SqlAlchemySandboxRunUnitOfWorkFactory(session_factory),
    )
    policy = HighImpactOperationPolicy(
        approved_image_references=frozenset(settings.sandbox_approved_images),
        baseline_resources=settings.sandbox_resource_limits,
        protected_workspace_components=frozenset({".git", ".orchestwin", ".ssh"}),
    )
    high_impact = LocalHighImpactApprovalService(
        unit_of_work_factory=SqlAlchemyHighImpactApprovalUnitOfWorkFactory(session_factory),
        policy=policy,
    )
    return Sprint07ServiceBundle(
        brownfield=brownfield,
        execution_queries=execution_queries,
        high_impact=high_impact,
        profile_registry=registry,
    )
