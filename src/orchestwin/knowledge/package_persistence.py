from __future__ import annotations

from enum import StrEnum
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.knowledge.packages import KnowledgePackageVersion
from orchestwin.projects.persistence.models import ProjectRecord

PROJECT_VERSION_CONSTRAINT: Final = "uq_knowledge_package_versions_project_version"

PACKAGE_VERSIONS = sa.table(
    "knowledge_package_versions",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("version_number", sa.Integer()),
    sa.column("schema_version", sa.Integer()),
    sa.column("content_hash", sa.String(length=64)),
    sa.column("archive_hash", sa.String(length=64)),
    sa.column("file_name", sa.String(length=200)),
    sa.column("file_count", sa.Integer()),
    sa.column("archive_size", sa.Integer()),
    sa.column("manifest", postgresql.JSONB()),
    sa.column("archive", sa.LargeBinary()),
    sa.column("created_at", sa.DateTime(timezone=True)),
)

_METADATA_COLUMNS: Final = tuple(
    column for column in PACKAGE_VERSIONS.columns if column.name != "archive"
)


class KnowledgePackageWriteStatus(StrEnum):
    WRITTEN = "WRITTEN"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"


def _violated_constraint(error: sa.exc.IntegrityError) -> str | None:
    diagnostic = getattr(getattr(error, "orig", None), "diag", None)
    return getattr(diagnostic, "constraint_name", None)


def _package_version(row: sa.RowMapping) -> KnowledgePackageVersion:
    return KnowledgePackageVersion(
        id=row["id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        version_number=row["version_number"],
        schema_version=row["schema_version"],
        content_hash=row["content_hash"],
        archive_hash=row["archive_hash"],
        file_name=row["file_name"],
        file_count=row["file_count"],
        archive_size=row["archive_size"],
        manifest=dict(row["manifest"]),
        created_at=row["created_at"],
    )


class SqlAlchemyKnowledgePackageRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    def _owned_project(self, project_id: UUID) -> sa.Select:
        return sa.select(ProjectRecord.id).where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == self._owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )

    def _owned_versions(self, project_id: UUID, *columns: sa.ColumnElement) -> sa.Select:
        return (
            sa.select(*columns)
            .join(ProjectRecord, ProjectRecord.id == PACKAGE_VERSIONS.c.project_id)
            .where(
                PACKAGE_VERSIONS.c.project_id == project_id,
                PACKAGE_VERSIONS.c.owner_user_id == self._owner_user_id,
                ProjectRecord.owner_user_id == self._owner_user_id,
                ProjectRecord.archived_at.is_(None),
            )
        )

    async def lock_project(self, *, project_id: UUID) -> bool:
        statement = self._owned_project(project_id).with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def latest(self, *, project_id: UUID) -> KnowledgePackageVersion | None:
        versions = await self.list(project_id=project_id, limit=1)
        return versions[0] if versions else None

    async def list(
        self, *, project_id: UUID, limit: int = 50
    ) -> tuple[KnowledgePackageVersion, ...]:
        statement = (
            self._owned_versions(project_id, *_METADATA_COLUMNS)
            .order_by(PACKAGE_VERSIONS.c.version_number.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(_package_version(row) for row in rows)

    async def get(self, *, project_id: UUID, version_number: int) -> KnowledgePackageVersion | None:
        statement = self._owned_versions(project_id, *_METADATA_COLUMNS).where(
            PACKAGE_VERSIONS.c.version_number == version_number
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else _package_version(row)

    async def archive(self, *, project_id: UUID, version_number: int) -> bytes | None:
        statement = self._owned_versions(project_id, PACKAGE_VERSIONS.c.archive).where(
            PACKAGE_VERSIONS.c.version_number == version_number
        )
        content = (await self._session.execute(statement)).scalar_one_or_none()
        return None if content is None else bytes(content)

    async def create(
        self, version: KnowledgePackageVersion, archive: bytes
    ) -> KnowledgePackageWriteStatus:
        if version.owner_user_id != self._owner_user_id:
            raise ValueError("knowledge package owner does not match the repository owner")
        if not version.matches(archive):
            raise ValueError("knowledge package archive does not match its hash and size")
        owned = await self._session.execute(self._owned_project(version.project_id))
        if owned.scalar_one_or_none() is None:
            return KnowledgePackageWriteStatus.PROJECT_NOT_FOUND
        try:
            async with self._session.begin_nested():
                await self._session.execute(
                    sa.insert(PACKAGE_VERSIONS).values(
                        id=version.id,
                        project_id=version.project_id,
                        owner_user_id=version.owner_user_id,
                        version_number=version.version_number,
                        schema_version=version.schema_version,
                        content_hash=version.content_hash,
                        archive_hash=version.archive_hash,
                        file_name=version.file_name,
                        file_count=version.file_count,
                        archive_size=version.archive_size,
                        manifest=dict(version.manifest),
                        archive=archive,
                        created_at=version.created_at,
                    )
                )
        except sa.exc.IntegrityError as error:
            if _violated_constraint(error) == PROJECT_VERSION_CONSTRAINT:
                return KnowledgePackageWriteStatus.VERSION_CONFLICT
            raise
        return KnowledgePackageWriteStatus.WRITTEN


__all__ = [
    "PACKAGE_VERSIONS",
    "PROJECT_VERSION_CONSTRAINT",
    "KnowledgePackageWriteStatus",
    "SqlAlchemyKnowledgePackageRepository",
]
