from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID, uuid4

from orchestwin.twins.limits import MAX_USER_TWINS
from orchestwin.twins.persistence.repositories import PersonaVersionRepository, VersionAppendStatus
from orchestwin.twins.personas import PersonaProfile, PersonaProfileVersion
from orchestwin.twins.representation import (
    ArchetypeInput,
    active_archetype,
    archetype_profile,
    archive_archetype_profile,
)


class ArchetypeIssue(StrEnum):
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    ARCHETYPE_NOT_FOUND = "ARCHETYPE_NOT_FOUND"
    ARCHETYPE_LIMIT_REACHED = "ARCHETYPE_LIMIT_REACHED"
    ARCHETYPE_VERSION_CONFLICT = "ARCHETYPE_VERSION_CONFLICT"
    ARCHETYPE_ALREADY_ARCHIVED = "ARCHETYPE_ALREADY_ARCHIVED"
    USER_TWIN_REVISION_PENDING = "USER_TWIN_REVISION_PENDING"
    PERSISTENCE_REJECTED = "PERSISTENCE_REJECTED"


class ArchetypeFailure(Exception):
    def __init__(self, issue: ArchetypeIssue) -> None:
        super().__init__(issue.value)
        self.issue = issue


class ArchetypeUnitOfWork(Protocol):
    personas: PersonaVersionRepository

    async def __aenter__(self) -> ArchetypeUnitOfWork: ...

    async def __aexit__(self, exc_type, exc_value, traceback) -> None: ...

    async def lock_project(self, *, project_id: UUID) -> bool: ...

    async def has_pending_revision(self, *, project_id: UUID) -> bool: ...

    async def commit(self) -> None: ...


class ArchetypeUnitOfWorkFactory(Protocol):
    def __call__(self, *, owner_user_id: UUID) -> ArchetypeUnitOfWork: ...


class ArchetypeService:
    def __init__(
        self,
        *,
        uow_factory: ArchetypeUnitOfWorkFactory,
        uuid_factory: Callable[[], UUID] = uuid4,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._uuid_factory = uuid_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def list_current(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> tuple[PersonaProfileVersion, ...]:
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            await self._owned(unit, project_id)
            versions = await unit.personas.list_current(project_id=project_id)
            return tuple(version for version in versions if active_archetype(version))

    async def create(
        self, *, owner_user_id: UUID, project_id: UUID, data: ArchetypeInput
    ) -> PersonaProfileVersion:
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            await self._owned(unit, project_id)
            versions = await unit.personas.list_current(project_id=project_id)
            await self._editable(unit, project_id)
            if sum(active_archetype(version) for version in versions) >= MAX_USER_TWINS:
                raise ArchetypeFailure(ArchetypeIssue.ARCHETYPE_LIMIT_REACHED)
            return await self._append(
                unit,
                project_id=project_id,
                owner_user_id=owner_user_id,
                persona_id=self._uuid_factory(),
                profile=archetype_profile(data, source_id=str(owner_user_id)),
            )

    async def edit(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        persona_id: UUID,
        based_on_version_number: int,
        data: ArchetypeInput,
    ) -> PersonaProfileVersion:
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            await self._owned(unit, project_id)
            current = await self._current(unit, project_id, persona_id, based_on_version_number)
            profile = archetype_profile(data, source_id=str(owner_user_id))
            if profile.content_hash == current.content_hash:
                return current
            await self._editable(unit, project_id)
            if not active_archetype(current):
                versions = await unit.personas.list_current(project_id=project_id)
                if sum(active_archetype(version) for version in versions) >= MAX_USER_TWINS:
                    raise ArchetypeFailure(ArchetypeIssue.ARCHETYPE_LIMIT_REACHED)
            return await self._append(
                unit,
                project_id=project_id,
                owner_user_id=owner_user_id,
                persona_id=persona_id,
                profile=profile,
                current=current,
            )

    async def archive(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        persona_id: UUID,
        based_on_version_number: int,
    ) -> PersonaProfileVersion:
        async with self._uow_factory(owner_user_id=owner_user_id) as unit:
            await self._owned(unit, project_id)
            current = await self._current(unit, project_id, persona_id, based_on_version_number)
            await self._editable(unit, project_id)
            return await self._append(
                unit,
                project_id=project_id,
                owner_user_id=owner_user_id,
                persona_id=persona_id,
                profile=archive_archetype_profile(current.profile),
                current=current,
            )

    async def _owned(self, unit: ArchetypeUnitOfWork, project_id: UUID) -> None:
        if not await unit.lock_project(project_id=project_id):
            raise ArchetypeFailure(ArchetypeIssue.PROJECT_NOT_FOUND)

    async def _editable(self, unit: ArchetypeUnitOfWork, project_id: UUID) -> None:
        if await unit.has_pending_revision(project_id=project_id):
            raise ArchetypeFailure(ArchetypeIssue.USER_TWIN_REVISION_PENDING)

    async def _current(
        self,
        unit: ArchetypeUnitOfWork,
        project_id: UUID,
        persona_id: UUID,
        based_on_version_number: int,
    ) -> PersonaProfileVersion:
        if type(based_on_version_number) is not int or based_on_version_number < 1:
            raise ValueError("invalid archetype base version")
        current = await unit.personas.current(project_id=project_id, persona_id=persona_id)
        if current is None:
            raise ArchetypeFailure(ArchetypeIssue.ARCHETYPE_NOT_FOUND)
        if current.version_number != based_on_version_number:
            raise ArchetypeFailure(ArchetypeIssue.ARCHETYPE_VERSION_CONFLICT)
        if current.profile.archived:
            raise ArchetypeFailure(ArchetypeIssue.ARCHETYPE_ALREADY_ARCHIVED)
        return current

    async def _append(
        self,
        unit: ArchetypeUnitOfWork,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        persona_id: UUID,
        profile: PersonaProfile,
        current: PersonaProfileVersion | None = None,
    ) -> PersonaProfileVersion:
        version = PersonaProfileVersion(
            id=self._uuid_factory(),
            project_id=project_id,
            persona_id=persona_id,
            version_number=1 if current is None else current.version_number + 1,
            based_on_version_number=None if current is None else current.version_number,
            profile=profile,
            content_hash=profile.content_hash,
            created_by_user_id=owner_user_id,
            created_at=self._clock(),
        )
        if await unit.personas.append(version) is not VersionAppendStatus.APPENDED:
            raise ArchetypeFailure(ArchetypeIssue.PERSISTENCE_REJECTED)
        await unit.commit()
        return version
