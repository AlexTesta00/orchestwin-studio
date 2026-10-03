from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.project_import import FolderOrigin
from orchestwin.projects.persistence.models import ProjectRecord

SOURCE_NAME_LIMIT: Final = 200
DEFAULT_IMPORT_LIMIT: Final = 50
STAGE_VERSION_KEYS: Final = frozenset({"version_id", "version_number", "content_hash"})
IMPORT_METADATA_KEY: Final = "_import_metadata"

PROJECT_IMPORTS = sa.table(
    "project_imports",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("source_project_id", postgresql.UUID(as_uuid=True)),
    sa.column("source_project_name", sa.String(length=SOURCE_NAME_LIMIT)),
    sa.column("package_version", sa.Integer()),
    sa.column("package_content_hash", sa.String(length=64)),
    sa.column("schema_version", sa.Integer()),
    sa.column("archive_hash", sa.String(length=64)),
    sa.column("archive_size", sa.Integer()),
    sa.column("stage_versions", postgresql.JSONB()),
    sa.column("imported_at", sa.DateTime(timezone=True)),
)


@dataclass(frozen=True, slots=True)
class ProjectImportRecord:
    id: UUID
    project_id: UUID
    owner_user_id: UUID
    source_project_id: UUID
    source_project_name: str
    package_version: int
    package_content_hash: str
    schema_version: int
    archive_hash: str
    archive_size: int
    stage_versions: Mapping[str, Mapping[str, object]]
    imported_at: datetime
    import_limits: tuple[str, ...] = ()
    omitted_sections: tuple[Mapping[str, object], ...] = ()

    def __post_init__(self) -> None:
        if set(self.stage_versions) != set(STAGES) or any(
            set(entry) != STAGE_VERSION_KEYS for entry in self.stage_versions.values()
        ):
            raise ValueError("project import must name the version of every stage")
        if self.imported_at.tzinfo is None or self.imported_at.utcoffset() is None:
            raise ValueError("project import timestamp must be timezone-aware")
        if any(not isinstance(item, str) or not item for item in self.import_limits) or any(
            not isinstance(item, Mapping) or not isinstance(item.get("reason"), str)
            for item in self.omitted_sections
        ):
            raise ValueError("project import metadata is invalid")

    @property
    def origin(self) -> FolderOrigin:
        return FolderOrigin(
            project_id=self.source_project_id,
            project_name=self.source_project_name,
            package_version=self.package_version,
            package_content_hash=self.package_content_hash,
            schema_version=self.schema_version,
        )

    def to_snapshot(self) -> dict[str, object]:
        result = {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "owner_user_id": str(self.owner_user_id),
            "source_project_id": str(self.source_project_id),
            "source_project_name": self.source_project_name,
            "package_version": self.package_version,
            "package_content_hash": self.package_content_hash,
            "schema_version": self.schema_version,
            "archive_hash": self.archive_hash,
            "archive_size": self.archive_size,
            "stage_versions": {stage: dict(self.stage_versions[stage]) for stage in STAGES},
            "imported_at": self.imported_at.isoformat(),
        }
        if self.import_limits:
            result["import_limits"] = list(self.import_limits)
        if self.omitted_sections:
            result["omitted_sections"] = [dict(item) for item in self.omitted_sections]
        return result


def _record_values(record: ProjectImportRecord) -> dict[str, object]:
    stages = {stage: dict(record.stage_versions[stage]) for stage in STAGES}
    if record.import_limits or record.omitted_sections:
        stages[IMPORT_METADATA_KEY] = {
            "import_limits": list(record.import_limits),
            "omitted_sections": [dict(item) for item in record.omitted_sections],
        }
    return {
        "id": record.id,
        "project_id": record.project_id,
        "owner_user_id": record.owner_user_id,
        "source_project_id": record.source_project_id,
        "source_project_name": record.source_project_name,
        "package_version": record.package_version,
        "package_content_hash": record.package_content_hash,
        "schema_version": record.schema_version,
        "archive_hash": record.archive_hash,
        "archive_size": record.archive_size,
        "stage_versions": stages,
        "imported_at": record.imported_at,
    }


def _import_record(row: sa.RowMapping) -> ProjectImportRecord:
    stages = dict(row["stage_versions"])
    metadata = stages.pop(IMPORT_METADATA_KEY, {})
    if not isinstance(metadata, Mapping) or set(metadata) - {"import_limits", "omitted_sections"}:
        raise ValueError("project import metadata is invalid")
    limits = metadata.get("import_limits", [])
    omissions = metadata.get("omitted_sections", [])
    if not isinstance(limits, list) or not isinstance(omissions, list):
        raise ValueError("project import metadata is invalid")
    return ProjectImportRecord(
        id=row["id"],
        project_id=row["project_id"],
        owner_user_id=row["owner_user_id"],
        source_project_id=row["source_project_id"],
        source_project_name=row["source_project_name"],
        package_version=row["package_version"],
        package_content_hash=row["package_content_hash"],
        schema_version=row["schema_version"],
        archive_hash=row["archive_hash"],
        archive_size=row["archive_size"],
        stage_versions={stage: dict(entry) for stage, entry in stages.items()},
        imported_at=row["imported_at"],
        import_limits=tuple(limits),
        omitted_sections=tuple(omissions),
    )


class SqlAlchemyProjectImportRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    def _owned(self) -> sa.Select:
        return (
            sa.select(*PROJECT_IMPORTS.columns)
            .join(ProjectRecord, ProjectRecord.id == PROJECT_IMPORTS.c.project_id)
            .where(
                PROJECT_IMPORTS.c.owner_user_id == self._owner_user_id,
                ProjectRecord.owner_user_id == self._owner_user_id,
                ProjectRecord.archived_at.is_(None),
            )
        )

    async def add(self, record: ProjectImportRecord) -> None:
        if record.owner_user_id != self._owner_user_id:
            raise ValueError("project import owner does not match the repository owner")
        await self._session.execute(sa.insert(PROJECT_IMPORTS).values(**_record_values(record)))

    async def for_project(self, project_id: UUID) -> ProjectImportRecord | None:
        statement = self._owned().where(PROJECT_IMPORTS.c.project_id == project_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else _import_record(row)

    async def list(self, limit: int = DEFAULT_IMPORT_LIMIT) -> tuple[ProjectImportRecord, ...]:
        if limit < 1:
            raise ValueError("project import limit must be positive")
        statement = (
            self._owned()
            .order_by(PROJECT_IMPORTS.c.imported_at.desc(), PROJECT_IMPORTS.c.id.desc())
            .limit(limit)
        )
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(_import_record(row) for row in rows)


__all__ = [
    "DEFAULT_IMPORT_LIMIT",
    "PROJECT_IMPORTS",
    "SOURCE_NAME_LIMIT",
    "STAGE_VERSION_KEYS",
    "ProjectImportRecord",
    "SqlAlchemyProjectImportRepository",
]
