"""SQLAlchemy persistence for immutable Project Brief versions."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.briefs import (
    ProjectBrief,
    ProjectBriefVersion,
)
from orchestwin.projects.persistence.models import (
    ProjectBriefVersionRecord,
    ProjectRecord,
)
from orchestwin.projects.repository import (
    BriefVersionCreationResult,
    BriefVersionCreationStatus,
)

Clock = Callable[[], datetime]
UuidFactory = Callable[[], UUID]


def utc_now() -> datetime:
    """Return the current timezone-aware UTC timestamp."""
    return datetime.now(UTC)


def brief_record_to_domain(
    record: ProjectBriefVersionRecord,
) -> ProjectBriefVersion:
    """Translate an immutable record into a domain version."""
    brief = ProjectBrief.from_snapshot(record.content)

    return ProjectBriefVersion(
        id=record.id,
        project_id=record.project_id,
        version_number=record.version_number,
        schema_version=record.schema_version,
        brief=brief,
        content_hash=record.content_hash,
        created_by_user_id=(record.created_by_user_id),
        created_at=record.created_at,
    )


def owned_project_for_update_statement(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> Select[tuple[ProjectRecord]]:
    """Lock one active project through its owner boundary."""
    return (
        select(ProjectRecord)
        .where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )
        .with_for_update()
    )


class SqlAlchemyProjectBriefRepository:
    """Owner-scoped immutable brief-version repository."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock = utc_now,
        uuid_factory: UuidFactory = uuid4,
    ) -> None:
        self._session = session
        self._clock = clock
        self._uuid_factory = uuid_factory

    async def create_owned_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        created_by_user_id: UUID,
        brief: ProjectBrief,
    ) -> BriefVersionCreationResult:
        """Create a serialized next version or reuse identical content."""
        project = await self._session.scalar(
            owned_project_for_update_statement(
                project_id=project_id,
                owner_user_id=owner_user_id,
            )
        )

        if project is None:
            return BriefVersionCreationResult(status=(BriefVersionCreationStatus.PROJECT_NOT_FOUND))

        if project.current_brief_version > 0:
            current = await self._session.scalar(
                select(ProjectBriefVersionRecord).where(
                    ProjectBriefVersionRecord.project_id == project.id,
                    ProjectBriefVersionRecord.version_number == project.current_brief_version,
                )
            )

            if current is None:
                raise RuntimeError("project current brief version is missing")

            if current.content_hash == brief.content_hash:
                return BriefVersionCreationResult(
                    status=(BriefVersionCreationStatus.UNCHANGED),
                    version=brief_record_to_domain(current),
                )

        created_at = self._clock()

        if created_at.tzinfo is None:
            raise ValueError("brief-version clock must be timezone-aware")

        version_number = project.current_brief_version + 1
        record = ProjectBriefVersionRecord(
            id=self._uuid_factory(),
            project_id=project.id,
            version_number=version_number,
            schema_version=(brief.SCHEMA_VERSION),
            content=brief.to_snapshot(),
            content_hash=brief.content_hash,
            created_by_user_id=(created_by_user_id),
            created_at=created_at,
        )

        self._session.add(record)
        project.current_brief_version = version_number
        project.updated_at = created_at
        await self._session.flush()

        return BriefVersionCreationResult(
            status=(BriefVersionCreationStatus.CREATED),
            version=brief_record_to_domain(record),
        )

    async def get_current_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ProjectBriefVersion | None:
        """Return the current version of an active owned project."""
        record = await self._session.scalar(
            select(ProjectBriefVersionRecord)
            .join(
                ProjectRecord,
                ProjectRecord.id == ProjectBriefVersionRecord.project_id,
            )
            .where(
                ProjectRecord.id == project_id,
                ProjectRecord.owner_user_id == owner_user_id,
                ProjectRecord.archived_at.is_(None),
                ProjectBriefVersionRecord.version_number == ProjectRecord.current_brief_version,
            )
        )

        if record is None:
            return None

        return brief_record_to_domain(record)

    async def get_owned_version(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        version_number: int,
    ) -> ProjectBriefVersion | None:
        """Return one immutable version for an active owned project."""
        record = await self._session.scalar(
            select(ProjectBriefVersionRecord)
            .join(
                ProjectRecord,
                ProjectRecord.id == ProjectBriefVersionRecord.project_id,
            )
            .where(
                ProjectRecord.id == project_id,
                ProjectRecord.owner_user_id == owner_user_id,
                ProjectRecord.archived_at.is_(None),
                ProjectBriefVersionRecord.version_number == version_number,
            )
        )

        if record is None:
            return None

        return brief_record_to_domain(record)

    async def list_owned_versions(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> tuple[ProjectBriefVersion, ...]:
        """Return the immutable history for an active owned project."""
        result = await self._session.scalars(
            select(ProjectBriefVersionRecord)
            .join(
                ProjectRecord,
                ProjectRecord.id == ProjectBriefVersionRecord.project_id,
            )
            .where(
                ProjectRecord.id == project_id,
                ProjectRecord.owner_user_id == owner_user_id,
                ProjectRecord.archived_at.is_(None),
            )
            .order_by(ProjectBriefVersionRecord.version_number)
        )

        return tuple(brief_record_to_domain(record) for record in result.all())
