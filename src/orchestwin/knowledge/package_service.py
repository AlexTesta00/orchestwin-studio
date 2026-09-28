from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.knowledge.export import KnowledgeExportError, KnowledgeSourceLoader
from orchestwin.knowledge.folder import (
    KnowledgeArchive,
    build_knowledge_folder,
    content_files,
    folder_archive,
    folder_content_hash,
)
from orchestwin.knowledge.layout import KNOWLEDGE_SCHEMA_VERSION
from orchestwin.knowledge.package_persistence import (
    KnowledgePackageWriteStatus,
    SqlAlchemyKnowledgePackageRepository,
)
from orchestwin.knowledge.packages import KnowledgePackageVersion
from orchestwin.knowledge.schema import KnowledgeSchemaError, validate_files

DEFAULT_HISTORY_LIMIT: Final = 50
MAX_HISTORY_LIMIT: Final = 200


class KnowledgePackageRepository(Protocol):
    async def lock_project(self, *, project_id: UUID) -> bool: ...

    async def latest(self, *, project_id: UUID) -> KnowledgePackageVersion | None: ...

    async def list(
        self, *, project_id: UUID, limit: int = DEFAULT_HISTORY_LIMIT
    ) -> tuple[KnowledgePackageVersion, ...]: ...

    async def get(
        self, *, project_id: UUID, version_number: int
    ) -> KnowledgePackageVersion | None: ...

    async def archive(self, *, project_id: UUID, version_number: int) -> bytes | None: ...

    async def create(
        self, version: KnowledgePackageVersion, archive: bytes
    ) -> KnowledgePackageWriteStatus: ...


class KnowledgePackageStore(Protocol):
    def transaction(self, *, owner_user_id: UUID): ...


class SqlAlchemyKnowledgePackageStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    @asynccontextmanager
    async def transaction(
        self, *, owner_user_id: UUID
    ) -> AsyncIterator[SqlAlchemyKnowledgePackageRepository]:
        async with self._session_factory() as session, session.begin():
            yield SqlAlchemyKnowledgePackageRepository(session, owner_user_id=owner_user_id)


@dataclass(frozen=True, slots=True)
class KnowledgePackagePublication:
    version: KnowledgePackageVersion
    reused: bool


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgePackageService:
    def __init__(
        self,
        *,
        source_loader: KnowledgeSourceLoader,
        store: KnowledgePackageStore,
        clock: Callable[[], datetime] = _utc_now,
        id_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.source_loader = source_loader
        self.store = store
        self._clock = clock
        self._id_factory = id_factory

    async def publish(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> KnowledgePackagePublication:
        sources = await self.source_loader.load(owner_user_id=owner_user_id, project_id=project_id)
        content = content_files(sources)
        try:
            validate_files(content)
        except KnowledgeSchemaError as error:
            raise KnowledgeExportError("KNOWLEDGE_FOLDER_INVALID") from error
        digest = folder_content_hash(content)
        async with self.store.transaction(owner_user_id=owner_user_id) as repository:
            if not await repository.lock_project(project_id=project_id):
                raise KnowledgeExportError("PROJECT_NOT_FOUND")
            latest = await repository.latest(project_id=project_id)
            if (
                latest is not None
                and latest.content_hash == digest
                and latest.schema_version == KNOWLEDGE_SCHEMA_VERSION
            ):
                return KnowledgePackagePublication(version=latest, reused=True)
            folder = build_knowledge_folder(
                sources,
                version_number=1 if latest is None else latest.version_number + 1,
                created_at=self._clock(),
                content=content,
            )
            archive = folder_archive(folder)
            version = KnowledgePackageVersion(
                id=self._id_factory(),
                project_id=project_id,
                owner_user_id=owner_user_id,
                version_number=folder.version_number,
                schema_version=KNOWLEDGE_SCHEMA_VERSION,
                content_hash=folder.content_hash,
                archive_hash=archive.archive_hash,
                file_name=archive.file_name,
                file_count=len(archive.entries),
                archive_size=len(archive.content),
                manifest=folder.manifest,
                created_at=folder.created_at,
            )
            status = await repository.create(version, archive.content)
            if status is KnowledgePackageWriteStatus.PROJECT_NOT_FOUND:
                raise KnowledgeExportError("PROJECT_NOT_FOUND")
            if status is not KnowledgePackageWriteStatus.WRITTEN:
                raise KnowledgeExportError("KNOWLEDGE_PACKAGE_VERSION_CONFLICT")
        return KnowledgePackagePublication(version=version, reused=False)

    async def history(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        limit: int = DEFAULT_HISTORY_LIMIT,
    ) -> tuple[KnowledgePackageVersion, ...]:
        async with self.store.transaction(owner_user_id=owner_user_id) as repository:
            if not await repository.lock_project(project_id=project_id):
                raise KnowledgeExportError("PROJECT_NOT_FOUND")
            return await repository.list(
                project_id=project_id, limit=max(1, min(limit, MAX_HISTORY_LIMIT))
            )

    async def archive(
        self,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        version_number: int,
    ) -> KnowledgeArchive:
        async with self.store.transaction(owner_user_id=owner_user_id) as repository:
            version = await repository.get(project_id=project_id, version_number=version_number)
            content = (
                None
                if version is None
                else await repository.archive(project_id=project_id, version_number=version_number)
            )
        if version is None or content is None:
            raise KnowledgeExportError("KNOWLEDGE_PACKAGE_NOT_FOUND")
        if not version.matches(content):
            raise KnowledgeExportError("KNOWLEDGE_PACKAGE_CORRUPTED")
        return KnowledgeArchive(
            project_id=version.project_id,
            version_number=version.version_number,
            file_name=version.file_name,
            content=content,
            archive_hash=version.archive_hash,
            content_hash=version.content_hash,
            entries=version.entries,
        )


__all__ = [
    "DEFAULT_HISTORY_LIMIT",
    "MAX_HISTORY_LIMIT",
    "KnowledgePackagePublication",
    "KnowledgePackageRepository",
    "KnowledgePackageService",
    "KnowledgePackageStore",
    "SqlAlchemyKnowledgePackageStore",
]
