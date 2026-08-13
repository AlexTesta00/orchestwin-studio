"""Owner-scoped SQLAlchemy repositories for User Modeling versions."""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.twins.persistence.snapshots import (
    persona_version_from_record,
    persona_version_to_record,
    user_modeling_snapshot_version_from_record,
    user_modeling_snapshot_version_to_record,
    user_twin_version_from_record,
    user_twin_version_to_record,
)
from orchestwin.twins.personas import (
    PersonaProfileVersion,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinProfileVersion,
)


class VersionAppendStatus(StrEnum):
    """Stable outcomes of an append-only persistence operation."""

    APPENDED = "APPENDED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    CONTEXT_NOT_FOUND = "CONTEXT_NOT_FOUND"


class PersonaVersionRepository(Protocol):
    """Persistence boundary for immutable persona histories."""

    async def append(
        self,
        version: PersonaProfileVersion,
    ) -> VersionAppendStatus:
        """Append one persona version."""

    async def get(
        self,
        *,
        project_id: UUID,
        persona_id: UUID,
        version_number: int,
    ) -> PersonaProfileVersion | None:
        """Read an exact owner-scoped persona version."""

    async def current(
        self,
        *,
        project_id: UUID,
        persona_id: UUID,
    ) -> PersonaProfileVersion | None:
        """Read the latest owner-scoped persona version."""

    async def history(
        self,
        *,
        project_id: UUID,
        persona_id: UUID,
    ) -> tuple[
        PersonaProfileVersion,
        ...,
    ]:
        """Read persona history in ascending version order."""

    async def list_current(
        self,
        *,
        project_id: UUID,
    ) -> tuple[
        PersonaProfileVersion,
        ...,
    ]:
        """Read the latest version of every project persona."""


class UserTwinVersionRepository(Protocol):
    """Persistence boundary for immutable User Twin histories."""

    async def append(
        self,
        version: UserTwinProfileVersion,
    ) -> VersionAppendStatus:
        """Append one User Twin version."""

    async def get(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
        version_number: int,
    ) -> UserTwinProfileVersion | None:
        """Read one exact User Twin version."""

    async def current(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
    ) -> UserTwinProfileVersion | None:
        """Read the latest User Twin version."""

    async def history(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
    ) -> tuple[
        UserTwinProfileVersion,
        ...,
    ]:
        """Read User Twin history."""

    async def list_current(
        self,
        *,
        project_id: UUID,
    ) -> tuple[
        UserTwinProfileVersion,
        ...,
    ]:
        """Read latest project User Twin versions."""


class UserModelingSnapshotRepository(Protocol):
    """Persistence boundary for complete User Modeling history."""

    async def append(
        self,
        version: UserModelingSnapshotVersion,
    ) -> VersionAppendStatus:
        """Append one complete User Modeling version."""

    async def get(
        self,
        *,
        project_id: UUID,
        version_number: int,
    ) -> UserModelingSnapshotVersion | None:
        """Read an exact snapshot version."""

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> UserModelingSnapshotVersion | None:
        """Read the current User Modeling snapshot."""

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[
        UserModelingSnapshotVersion,
        ...,
    ]:
        """Read complete snapshot history."""


_UUID = postgresql.UUID(as_uuid=True)

PROJECTS = sa.table(
    "projects",
    sa.column(
        "id",
        _UUID,
    ),
    sa.column(
        "owner_user_id",
        _UUID,
    ),
)

PROJECT_BRIEF_VERSIONS = sa.table(
    "project_brief_versions",
    sa.column(
        "id",
        _UUID,
    ),
    sa.column(
        "project_id",
        _UUID,
    ),
    sa.column(
        "version_number",
        sa.Integer(),
    ),
    sa.column(
        "content_hash",
        sa.String(64),
    ),
)

TEAM_PROPOSALS = sa.table(
    "team_proposals",
    sa.column(
        "id",
        _UUID,
    ),
    sa.column(
        "project_id",
        _UUID,
    ),
    sa.column(
        "version_number",
        sa.Integer(),
    ),
    sa.column(
        "content_hash",
        sa.String(64),
    ),
)

PERSONA_PROFILE_VERSIONS = sa.table(
    "persona_profile_versions",
    sa.column(
        "id",
        _UUID,
    ),
    sa.column(
        "project_id",
        _UUID,
    ),
    sa.column(
        "persona_id",
        _UUID,
    ),
    sa.column(
        "version_number",
        sa.Integer(),
    ),
    sa.column(
        "based_on_version_number",
        sa.Integer(),
    ),
    sa.column(
        "profile_schema_version",
        sa.Integer(),
    ),
    sa.column(
        "profile_source",
        sa.String(32),
    ),
    sa.column(
        "profile_kind",
        sa.String(32),
    ),
    sa.column(
        "confirmation_status",
        sa.String(32),
    ),
    sa.column(
        "rejection_reason",
        sa.Text(),
    ),
    sa.column(
        "content_hash",
        sa.String(64),
    ),
    sa.column(
        "profile_snapshot",
        postgresql.JSONB(),
    ),
    sa.column(
        "created_by_user_id",
        _UUID,
    ),
    sa.column(
        "created_at",
        sa.DateTime(timezone=True),
    ),
)

USER_TWIN_PROFILE_VERSIONS = sa.table(
    "user_twin_profile_versions",
    sa.column(
        "id",
        _UUID,
    ),
    sa.column(
        "project_id",
        _UUID,
    ),
    sa.column(
        "twin_id",
        _UUID,
    ),
    sa.column(
        "version_number",
        sa.Integer(),
    ),
    sa.column(
        "based_on_version_number",
        sa.Integer(),
    ),
    sa.column(
        "profile_schema_version",
        sa.Integer(),
    ),
    sa.column(
        "persona_id",
        _UUID,
    ),
    sa.column(
        "persona_version_number",
        sa.Integer(),
    ),
    sa.column(
        "validation_status",
        sa.String(40),
    ),
    sa.column(
        "content_hash",
        sa.String(64),
    ),
    sa.column(
        "profile_snapshot",
        postgresql.JSONB(),
    ),
    sa.column(
        "created_by_user_id",
        _UUID,
    ),
    sa.column(
        "created_at",
        sa.DateTime(timezone=True),
    ),
)

USER_MODELING_SNAPSHOT_VERSIONS = sa.table(
    "user_modeling_snapshot_versions",
    sa.column(
        "id",
        _UUID,
    ),
    sa.column(
        "project_id",
        _UUID,
    ),
    sa.column(
        "version_number",
        sa.Integer(),
    ),
    sa.column(
        "based_on_version_number",
        sa.Integer(),
    ),
    sa.column(
        "snapshot_schema_version",
        sa.Integer(),
    ),
    sa.column(
        "brief_version_id",
        _UUID,
    ),
    sa.column(
        "brief_version_number",
        sa.Integer(),
    ),
    sa.column(
        "brief_content_hash",
        sa.String(64),
    ),
    sa.column(
        "team_proposal_id",
        _UUID,
    ),
    sa.column(
        "team_version_number",
        sa.Integer(),
    ),
    sa.column(
        "team_content_hash",
        sa.String(64),
    ),
    sa.column(
        "catalog_version",
        sa.Integer(),
    ),
    sa.column(
        "catalog_content_hash",
        sa.String(64),
    ),
    sa.column(
        "persona_count",
        sa.SmallInteger(),
    ),
    sa.column(
        "twin_count",
        sa.SmallInteger(),
    ),
    sa.column(
        "content_hash",
        sa.String(64),
    ),
    sa.column(
        "snapshot",
        postgresql.JSONB(),
    ),
    sa.column(
        "created_by_user_id",
        _UUID,
    ),
    sa.column(
        "created_at",
        sa.DateTime(timezone=True),
    ),
)


class SqlAlchemyPersonaVersionRepository:
    """SQLAlchemy implementation of owner-scoped persona persistence."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Bind repository access to one authenticated owner."""
        self._session = session
        self._owner_user_id = owner_user_id

    async def append(
        self,
        version: PersonaProfileVersion,
    ) -> VersionAppendStatus:
        """Append a version only when the owner controls the project."""
        if not await _project_is_owned(
            self._session,
            project_id=(version.project_id),
            owner_user_id=(self._owner_user_id),
        ):
            return VersionAppendStatus.PROJECT_NOT_FOUND

        await self._session.execute(
            sa.insert(PERSONA_PROFILE_VERSIONS).values(**persona_version_to_record(version))
        )

        return VersionAppendStatus.APPENDED

    async def get(
        self,
        *,
        project_id: UUID,
        persona_id: UUID,
        version_number: int,
    ) -> PersonaProfileVersion | None:
        """Read one exact persona version without leaking foreign projects."""
        statement = _owned_select(
            PERSONA_PROFILE_VERSIONS,
            project_id=project_id,
            owner_user_id=(self._owner_user_id),
        ).where(
            PERSONA_PROFILE_VERSIONS.c.persona_id == persona_id,
            PERSONA_PROFILE_VERSIONS.c.version_number == version_number,
        )

        row = (await self._session.execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return persona_version_from_record(row)

    async def current(
        self,
        *,
        project_id: UUID,
        persona_id: UUID,
    ) -> PersonaProfileVersion | None:
        """Read the most recent persona revision."""
        statement = (
            _owned_select(
                PERSONA_PROFILE_VERSIONS,
                project_id=project_id,
                owner_user_id=(self._owner_user_id),
            )
            .where(PERSONA_PROFILE_VERSIONS.c.persona_id == persona_id)
            .order_by(PERSONA_PROFILE_VERSIONS.c.version_number.desc())
            .limit(1)
        )

        row = (await self._session.execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return persona_version_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
        persona_id: UUID,
    ) -> tuple[
        PersonaProfileVersion,
        ...,
    ]:
        """Read complete persona history."""
        statement = (
            _owned_select(
                PERSONA_PROFILE_VERSIONS,
                project_id=project_id,
                owner_user_id=(self._owner_user_id),
            )
            .where(PERSONA_PROFILE_VERSIONS.c.persona_id == persona_id)
            .order_by(PERSONA_PROFILE_VERSIONS.c.version_number.asc())
        )

        rows = (await self._session.execute(statement)).mappings().all()

        return tuple(persona_version_from_record(row) for row in rows)

    async def list_current(
        self,
        *,
        project_id: UUID,
    ) -> tuple[
        PersonaProfileVersion,
        ...,
    ]:
        """Return latest persona versions in deterministic identity order."""
        statement = _owned_select(
            PERSONA_PROFILE_VERSIONS,
            project_id=project_id,
            owner_user_id=(self._owner_user_id),
        ).order_by(
            PERSONA_PROFILE_VERSIONS.c.persona_id.asc(),
            PERSONA_PROFILE_VERSIONS.c.version_number.asc(),
        )

        rows = (await self._session.execute(statement)).mappings().all()

        versions = tuple(persona_version_from_record(row) for row in rows)

        latest: dict[
            UUID,
            PersonaProfileVersion,
        ] = {}

        for version in versions:
            latest[version.persona_id] = version

        return tuple(
            latest[persona_id]
            for persona_id in sorted(
                latest,
                key=lambda value: value.hex,
            )
        )


class SqlAlchemyUserTwinVersionRepository:
    """SQLAlchemy implementation of User Twin version persistence."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Bind repository access to one authenticated owner."""
        self._session = session
        self._owner_user_id = owner_user_id

    async def append(
        self,
        version: UserTwinProfileVersion,
    ) -> VersionAppendStatus:
        """Append one User Twin after project and persona checks."""
        if not await _project_is_owned(
            self._session,
            project_id=(version.project_id),
            owner_user_id=(self._owner_user_id),
        ):
            return VersionAppendStatus.PROJECT_NOT_FOUND

        persona_reference = version.profile.persona_reference

        if not await _persona_context_exists(
            self._session,
            project_id=(version.project_id),
            persona_id=(persona_reference.persona_id),
            version_number=(persona_reference.version_number),
            content_hash=(persona_reference.content_hash),
        ):
            return VersionAppendStatus.CONTEXT_NOT_FOUND

        await self._session.execute(
            sa.insert(USER_TWIN_PROFILE_VERSIONS).values(**user_twin_version_to_record(version))
        )

        return VersionAppendStatus.APPENDED

    async def get(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
        version_number: int,
    ) -> UserTwinProfileVersion | None:
        """Read one exact User Twin version."""
        statement = _owned_select(
            USER_TWIN_PROFILE_VERSIONS,
            project_id=project_id,
            owner_user_id=(self._owner_user_id),
        ).where(
            USER_TWIN_PROFILE_VERSIONS.c.twin_id == twin_id,
            USER_TWIN_PROFILE_VERSIONS.c.version_number == version_number,
        )

        row = (await self._session.execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return user_twin_version_from_record(row)

    async def current(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
    ) -> UserTwinProfileVersion | None:
        """Read the most recent User Twin revision."""
        statement = (
            _owned_select(
                USER_TWIN_PROFILE_VERSIONS,
                project_id=project_id,
                owner_user_id=(self._owner_user_id),
            )
            .where(USER_TWIN_PROFILE_VERSIONS.c.twin_id == twin_id)
            .order_by(USER_TWIN_PROFILE_VERSIONS.c.version_number.desc())
            .limit(1)
        )

        row = (await self._session.execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return user_twin_version_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
        twin_id: UUID,
    ) -> tuple[
        UserTwinProfileVersion,
        ...,
    ]:
        """Read complete User Twin history."""
        statement = (
            _owned_select(
                USER_TWIN_PROFILE_VERSIONS,
                project_id=project_id,
                owner_user_id=(self._owner_user_id),
            )
            .where(USER_TWIN_PROFILE_VERSIONS.c.twin_id == twin_id)
            .order_by(USER_TWIN_PROFILE_VERSIONS.c.version_number.asc())
        )

        rows = (await self._session.execute(statement)).mappings().all()

        return tuple(user_twin_version_from_record(row) for row in rows)

    async def list_current(
        self,
        *,
        project_id: UUID,
    ) -> tuple[
        UserTwinProfileVersion,
        ...,
    ]:
        """Return latest User Twin versions in canonical identity order."""
        statement = _owned_select(
            USER_TWIN_PROFILE_VERSIONS,
            project_id=project_id,
            owner_user_id=(self._owner_user_id),
        ).order_by(
            USER_TWIN_PROFILE_VERSIONS.c.twin_id.asc(),
            USER_TWIN_PROFILE_VERSIONS.c.version_number.asc(),
        )

        rows = (await self._session.execute(statement)).mappings().all()

        versions = tuple(user_twin_version_from_record(row) for row in rows)

        latest: dict[
            UUID,
            UserTwinProfileVersion,
        ] = {}

        for version in versions:
            latest[version.twin_id] = version

        return tuple(
            latest[twin_id]
            for twin_id in sorted(
                latest,
                key=lambda value: value.hex,
            )
        )


class SqlAlchemyUserModelingSnapshotRepository:
    """SQLAlchemy implementation of complete User Modeling history."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Bind snapshot access to one owner."""
        self._session = session
        self._owner_user_id = owner_user_id

    async def append(
        self,
        version: UserModelingSnapshotVersion,
    ) -> VersionAppendStatus:
        """Append a snapshot only for its exact governed context."""
        if not await _project_is_owned(
            self._session,
            project_id=(version.project_id),
            owner_user_id=(self._owner_user_id),
        ):
            return VersionAppendStatus.PROJECT_NOT_FOUND

        if not await _snapshot_context_exists(
            self._session,
            version,
        ):
            return VersionAppendStatus.CONTEXT_NOT_FOUND

        await self._session.execute(
            sa.insert(USER_MODELING_SNAPSHOT_VERSIONS).values(
                **user_modeling_snapshot_version_to_record(version)
            )
        )

        return VersionAppendStatus.APPENDED

    async def get(
        self,
        *,
        project_id: UUID,
        version_number: int,
    ) -> UserModelingSnapshotVersion | None:
        """Read an exact complete User Modeling version."""
        statement = _owned_select(
            USER_MODELING_SNAPSHOT_VERSIONS,
            project_id=project_id,
            owner_user_id=(self._owner_user_id),
        ).where(USER_MODELING_SNAPSHOT_VERSIONS.c.version_number == version_number)

        row = (await self._session.execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return user_modeling_snapshot_version_from_record(row)

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> UserModelingSnapshotVersion | None:
        """Read the current complete User Modeling state."""
        statement = (
            _owned_select(
                USER_MODELING_SNAPSHOT_VERSIONS,
                project_id=project_id,
                owner_user_id=(self._owner_user_id),
            )
            .order_by(USER_MODELING_SNAPSHOT_VERSIONS.c.version_number.desc())
            .limit(1)
        )

        row = (await self._session.execute(statement)).mappings().one_or_none()

        if row is None:
            return None

        return user_modeling_snapshot_version_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[
        UserModelingSnapshotVersion,
        ...,
    ]:
        """Read complete modeling history in ascending order."""
        statement = _owned_select(
            USER_MODELING_SNAPSHOT_VERSIONS,
            project_id=project_id,
            owner_user_id=(self._owner_user_id),
        ).order_by(USER_MODELING_SNAPSHOT_VERSIONS.c.version_number.asc())

        rows = (await self._session.execute(statement)).mappings().all()

        return tuple(user_modeling_snapshot_version_from_record(row) for row in rows)


def _owned_select(
    table: sa.TableClause,
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> sa.Select:
    """Create a project-and-owner-scoped select."""
    return sa.select(*table.c).where(
        table.c.project_id == project_id,
        _owned_project_exists(
            project_id=project_id,
            owner_user_id=(owner_user_id),
        ),
    )


def _owned_project_exists(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> sa.ColumnElement[bool]:
    """Return an EXISTS predicate that prevents cross-owner access."""
    return sa.exists(
        sa.select(sa.literal(1))
        .select_from(PROJECTS)
        .where(
            PROJECTS.c.id == project_id,
            PROJECTS.c.owner_user_id == owner_user_id,
        )
    )


async def _project_is_owned(
    session: AsyncSession,
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> bool:
    """Resolve ownership without distinguishing missing and foreign projects."""
    statement = sa.select(sa.literal(True)).where(
        _owned_project_exists(
            project_id=project_id,
            owner_user_id=(owner_user_id),
        )
    )

    result = await session.execute(statement)

    return result.scalar_one_or_none() is True


async def _persona_context_exists(
    session: AsyncSession,
    *,
    project_id: UUID,
    persona_id: UUID,
    version_number: int,
    content_hash: str,
) -> bool:
    """Verify exact persisted persona grounding before twin insertion."""
    exists_clause = sa.exists(
        sa.select(sa.literal(1))
        .select_from(PERSONA_PROFILE_VERSIONS)
        .where(
            PERSONA_PROFILE_VERSIONS.c.project_id == project_id,
            PERSONA_PROFILE_VERSIONS.c.persona_id == persona_id,
            PERSONA_PROFILE_VERSIONS.c.version_number == version_number,
            PERSONA_PROFILE_VERSIONS.c.content_hash == content_hash,
        )
    )

    result = await session.execute(sa.select(sa.literal(True)).where(exists_clause))

    return result.scalar_one_or_none() is True


async def _snapshot_context_exists(
    session: AsyncSession,
    version: UserModelingSnapshotVersion,
) -> bool:
    """Verify exact brief and team references before snapshot insertion."""
    snapshot = version.snapshot
    brief = snapshot.project_brief_reference
    team = snapshot.agent_team_reference

    brief_exists = sa.exists(
        sa.select(sa.literal(1))
        .select_from(PROJECT_BRIEF_VERSIONS)
        .where(
            PROJECT_BRIEF_VERSIONS.c.id == brief.artifact_id,
            PROJECT_BRIEF_VERSIONS.c.project_id == version.project_id,
            PROJECT_BRIEF_VERSIONS.c.version_number == brief.version_number,
            PROJECT_BRIEF_VERSIONS.c.content_hash == brief.content_hash,
        )
    )

    team_exists = sa.exists(
        sa.select(sa.literal(1))
        .select_from(TEAM_PROPOSALS)
        .where(
            TEAM_PROPOSALS.c.id == team.artifact_id,
            TEAM_PROPOSALS.c.project_id == version.project_id,
            TEAM_PROPOSALS.c.version_number == team.version_number,
            TEAM_PROPOSALS.c.content_hash == team.content_hash,
        )
    )

    result = await session.execute(
        sa.select(sa.literal(True)).where(
            brief_exists,
            team_exists,
        )
    )

    return result.scalar_one_or_none() is True
