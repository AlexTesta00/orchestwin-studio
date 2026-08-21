"""PostgreSQL persistence for immutable Design Packages and owner diffs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import TracebackType
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.artifacts.design_packages import (
    DESIGN_PACKAGE_SCHEMA_VERSION,
    DesignPackageVersion,
)
from orchestwin.artifacts.design_revision_application import (
    DesignDiffPersistenceStatus,
)
from orchestwin.artifacts.design_revisions import (
    DesignPackageDiff,
    DesignPackageDiffStatus,
)
from orchestwin.artifacts.design_serialization import (
    design_diff_from_snapshot,
    design_diff_proposal_snapshot,
    design_package_from_snapshot,
)
from orchestwin.projects.design_application import DesignVersionAppendStatus

_UUID = postgresql.UUID(as_uuid=True)

PROJECTS = sa.table(
    "projects",
    sa.column("id", _UUID),
    sa.column("owner_user_id", _UUID),
)

PACKAGE_VERSIONS = sa.table(
    "design_package_versions",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("version_number", sa.Integer()),
    sa.column("based_on_version_number", sa.Integer()),
    sa.column("schema_version", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
    sa.column("package_snapshot", postgresql.JSONB()),
    sa.column("created_by_user_id", _UUID),
    sa.column("created_at", sa.DateTime(timezone=True)),
)

PACKAGE_DIFFS = sa.table(
    "design_package_diffs",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("owner_user_id", _UUID),
    sa.column("base_version_id", _UUID),
    sa.column("base_version_number", sa.Integer()),
    sa.column("base_content_hash", sa.String(64)),
    sa.column("proposal_hash", sa.String(64)),
    sa.column("diff_snapshot", postgresql.JSONB()),
    sa.column("status", sa.String(16)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("decided_by_user_id", _UUID),
    sa.column("decided_at", sa.DateTime(timezone=True)),
    sa.column("decision_reason", sa.Text()),
    sa.column("applied_version_id", _UUID),
)


class SqlAlchemyDesignPackageRepository:
    """Append-only owner-scoped Design Package repository."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Bind Design Package access to one authenticated owner."""
        self._session = session
        self._owner_user_id = owner_user_id

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> DesignPackageVersion | None:
        """Return the latest owner-scoped Design Package version."""
        return await self._current(project_id=project_id, for_update=False)

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> DesignPackageVersion | None:
        """Lock and return the current Design Package for Gate 5."""
        if owner_user_id != self._owner_user_id:
            return None

        return await self._current(project_id=project_id, for_update=True)

    async def get(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
    ) -> DesignPackageVersion | None:
        """Return one exact owner-scoped Design Package version."""
        statement = _owned_package_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(PACKAGE_VERSIONS.c.id == version_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else design_package_version_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[DesignPackageVersion, ...]:
        """Return immutable Design Package history in version order."""
        statement = _owned_package_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(PACKAGE_VERSIONS.c.version_number.asc())
        rows = (await self._session.execute(statement)).mappings().all()

        return tuple(design_package_version_from_record(row) for row in rows)

    async def append(
        self,
        version: DesignPackageVersion,
    ) -> DesignVersionAppendStatus:
        """Append one version after locking its current project baseline."""
        if version.created_by_user_id != self._owner_user_id:
            return DesignVersionAppendStatus.PROJECT_NOT_FOUND

        if not await _project_is_owned(
            self._session,
            project_id=version.project_id,
            owner_user_id=self._owner_user_id,
        ):
            return DesignVersionAppendStatus.PROJECT_NOT_FOUND

        current = await self._current(project_id=version.project_id, for_update=True)

        if current is None:
            if version.version_number != 1 or version.based_on_version_number is not None:
                return DesignVersionAppendStatus.VERSION_CONFLICT
        else:
            if (
                version.version_number != current.version_number + 1
                or version.based_on_version_number != current.version_number
            ):
                return DesignVersionAppendStatus.VERSION_CONFLICT

            if version.content_hash == current.content_hash:
                return DesignVersionAppendStatus.CONTENT_CONFLICT

        try:
            await self._session.execute(
                sa.insert(PACKAGE_VERSIONS).values(**design_package_version_to_record(version))
            )
        except IntegrityError:
            return DesignVersionAppendStatus.VERSION_CONFLICT

        return DesignVersionAppendStatus.APPENDED

    async def _current(
        self,
        *,
        project_id: UUID,
        for_update: bool,
    ) -> DesignPackageVersion | None:
        """Read the latest Design Package with optional row locking."""
        statement = (
            _owned_package_select(
                project_id=project_id,
                owner_user_id=self._owner_user_id,
            )
            .order_by(PACKAGE_VERSIONS.c.version_number.desc())
            .limit(1)
        )

        if for_update:
            statement = statement.with_for_update()

        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else design_package_version_from_record(row)


class SqlAlchemyDesignDiffRepository:
    """Owner-scoped repository for reviewable Design Package diffs."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Bind Design Package diff access to one authenticated owner."""
        self._session = session
        self._owner_user_id = owner_user_id

    async def create(
        self,
        diff: DesignPackageDiff,
    ) -> DesignDiffPersistenceStatus:
        """Persist a proposed diff against an exact owned base version."""
        if diff.owner_user_id != self._owner_user_id:
            return DesignDiffPersistenceStatus.PROJECT_NOT_FOUND

        if not await _project_is_owned(
            self._session,
            project_id=diff.project_id,
            owner_user_id=self._owner_user_id,
        ):
            return DesignDiffPersistenceStatus.PROJECT_NOT_FOUND

        if not await _base_version_exists(self._session, diff):
            return DesignDiffPersistenceStatus.CONTEXT_NOT_FOUND

        try:
            await self._session.execute(
                sa.insert(PACKAGE_DIFFS).values(**design_diff_to_record(diff))
            )
        except IntegrityError:
            return DesignDiffPersistenceStatus.CONFLICT

        return DesignDiffPersistenceStatus.CREATED

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> DesignPackageDiff | None:
        """Return one exact owner-scoped Design Package diff."""
        statement = _owned_diff_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(PACKAGE_DIFFS.c.id == diff_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else design_diff_from_record(row)

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_version_id: UUID,
    ) -> DesignPackageDiff | None:
        """Return the proposed diff for an exact base version."""
        statement = (
            _owned_diff_select(
                project_id=project_id,
                owner_user_id=self._owner_user_id,
            )
            .where(
                PACKAGE_DIFFS.c.base_version_id == base_version_id,
                PACKAGE_DIFFS.c.status == DesignPackageDiffStatus.PROPOSED.value,
            )
            .limit(1)
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else design_diff_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[DesignPackageDiff, ...]:
        """Return Design Package diff history in creation order."""
        statement = _owned_diff_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(PACKAGE_DIFFS.c.created_at.asc(), PACKAGE_DIFFS.c.id.asc())
        rows = (await self._session.execute(statement)).mappings().all()

        return tuple(design_diff_from_record(row) for row in rows)

    async def save_decision(
        self,
        diff: DesignPackageDiff,
    ) -> DesignDiffPersistenceStatus:
        """Update only decision metadata of one proposed Design Package diff."""
        if diff.status is DesignPackageDiffStatus.PROPOSED:
            raise ValueError("cannot persist a decision while Design Package diff is PROPOSED")

        if diff.decided_by_user_id != self._owner_user_id:
            return DesignDiffPersistenceStatus.CONFLICT

        statement = (
            sa.update(PACKAGE_DIFFS)
            .where(
                PACKAGE_DIFFS.c.id == diff.id,
                PACKAGE_DIFFS.c.project_id == diff.project_id,
                PACKAGE_DIFFS.c.status == DesignPackageDiffStatus.PROPOSED.value,
                _owned_project_exists(
                    project_id=diff.project_id,
                    owner_user_id=self._owner_user_id,
                ),
            )
            .values(
                status=diff.status.value,
                decided_by_user_id=diff.decided_by_user_id,
                decided_at=diff.decided_at,
                decision_reason=diff.decision_reason,
                applied_version_id=diff.applied_version_id,
            )
            .returning(PACKAGE_DIFFS.c.id)
        )
        updated_id = (await self._session.execute(statement)).scalar_one_or_none()

        if updated_id is None:
            return DesignDiffPersistenceStatus.CONFLICT

        return DesignDiffPersistenceStatus.UPDATED


class SqlAlchemyDesignUnitOfWork:
    """SQLAlchemy transaction coordinator for Design persistence."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Create owner-scoped repositories over one shared session."""
        self._session = session
        self._completed = False
        self.packages = SqlAlchemyDesignPackageRepository(
            session,
            owner_user_id=owner_user_id,
        )
        self.diffs = SqlAlchemyDesignDiffRepository(
            session,
            owner_user_id=owner_user_id,
        )

    async def __aenter__(self) -> SqlAlchemyDesignUnitOfWork:
        """Return this transactional boundary."""
        self._completed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Rollback a transaction that was not explicitly committed."""
        del exc_type, exc_value, traceback

        if not self._completed:
            await self.rollback()

    async def commit(self) -> None:
        """Commit the shared SQLAlchemy transaction."""
        await self._session.commit()
        self._completed = True

    async def rollback(self) -> None:
        """Rollback the shared SQLAlchemy transaction."""
        await self._session.rollback()
        self._completed = True


class SqlAlchemyDesignUnitOfWorkFactory:
    """Create owner-scoped Design Units of Work."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Store the shared async session factory."""
        self._session_factory = session_factory

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> SqlAlchemyDesignUnitOfWork:
        """Create one Unit of Work with a fresh async session."""
        return SqlAlchemyDesignUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


def design_package_version_to_record(
    version: DesignPackageVersion,
) -> dict[str, object]:
    """Convert one Design Package version to database values."""
    return {
        "id": version.id,
        "project_id": version.project_id,
        "version_number": version.version_number,
        "based_on_version_number": version.based_on_version_number,
        "schema_version": DESIGN_PACKAGE_SCHEMA_VERSION,
        "content_hash": version.content_hash,
        "package_snapshot": version.package.to_snapshot(),
        "created_by_user_id": version.created_by_user_id,
        "created_at": version.created_at,
    }


def design_package_version_from_record(
    record: Mapping[str, object],
) -> DesignPackageVersion:
    """Reconstruct and validate one persisted Design Package version."""
    schema_version = _integer(
        _required(record, "schema_version"),
        label="Design Package schema version",
    )

    if schema_version != DESIGN_PACKAGE_SCHEMA_VERSION:
        raise ValueError("unsupported persisted Design Package schema")

    package = design_package_from_snapshot(
        _mapping(
            _required(record, "package_snapshot"),
            label="persisted Design Package snapshot",
        )
    )

    return DesignPackageVersion(
        id=_uuid(
            _required(record, "id"),
            label="Design Package version ID",
        ),
        project_id=_uuid(
            _required(record, "project_id"),
            label="Design Package project ID",
        ),
        version_number=_integer(
            _required(record, "version_number"),
            label="Design Package version number",
        ),
        based_on_version_number=_optional_integer(
            record.get("based_on_version_number"),
            label="Design Package base version number",
        ),
        package=package,
        content_hash=_string(
            _required(record, "content_hash"),
            label="Design Package content hash",
        ),
        created_by_user_id=_uuid(
            _required(record, "created_by_user_id"),
            label="Design Package creator ID",
        ),
        created_at=_datetime(
            _required(record, "created_at"),
            label="Design Package creation timestamp",
        ),
    )


def design_diff_to_record(
    diff: DesignPackageDiff,
) -> dict[str, object]:
    """Convert one Design Package diff to database values."""
    return {
        "id": diff.id,
        "project_id": diff.project_id,
        "owner_user_id": diff.owner_user_id,
        "base_version_id": diff.base_version_id,
        "base_version_number": diff.base_version_number,
        "base_content_hash": diff.base_content_hash,
        "proposal_hash": diff.proposal_hash,
        "diff_snapshot": design_diff_proposal_snapshot(diff),
        "status": diff.status.value,
        "created_at": diff.created_at,
        "decided_by_user_id": diff.decided_by_user_id,
        "decided_at": diff.decided_at,
        "decision_reason": diff.decision_reason,
        "applied_version_id": diff.applied_version_id,
    }


def design_diff_from_record(
    record: Mapping[str, object],
) -> DesignPackageDiff:
    """Reconstruct and validate one persisted Design Package diff."""
    payload = _mapping(
        _required(record, "diff_snapshot"),
        label="persisted Design Package diff snapshot",
    )
    diff = design_diff_from_snapshot(
        payload,
        status=DesignPackageDiffStatus(
            _string(
                _required(record, "status"),
                label="Design Package diff status",
            )
        ),
        decided_by_user_id=_optional_uuid(
            record.get("decided_by_user_id"),
            label="Design Package diff decision actor",
        ),
        decided_at=_optional_datetime(
            record.get("decided_at"),
            label="Design Package diff decision timestamp",
        ),
        decision_reason=_optional_string(
            record.get("decision_reason"),
            label="Design Package diff decision reason",
        ),
        applied_version_id=_optional_uuid(
            record.get("applied_version_id"),
            label="applied Design Package version ID",
        ),
    )

    for actual, expected, label in (
        (diff.id, _uuid(_required(record, "id"), label="stored diff ID"), "ID"),
        (
            diff.project_id,
            _uuid(_required(record, "project_id"), label="stored diff project ID"),
            "project ID",
        ),
        (
            diff.owner_user_id,
            _uuid(_required(record, "owner_user_id"), label="stored diff owner ID"),
            "owner ID",
        ),
        (
            diff.base_version_id,
            _uuid(
                _required(record, "base_version_id"),
                label="stored diff base version ID",
            ),
            "base version ID",
        ),
        (
            diff.base_version_number,
            _integer(
                _required(record, "base_version_number"),
                label="stored diff base version number",
            ),
            "base version number",
        ),
        (
            diff.base_content_hash,
            _string(
                _required(record, "base_content_hash"),
                label="stored diff base content hash",
            ),
            "base content hash",
        ),
        (
            diff.proposal_hash,
            _string(
                _required(record, "proposal_hash"),
                label="stored diff proposal hash",
            ),
            "proposal hash",
        ),
        (
            diff.created_at,
            _datetime(
                _required(record, "created_at"),
                label="stored diff creation timestamp",
            ),
            "creation timestamp",
        ),
    ):
        if actual != expected:
            raise ValueError(f"persisted Design Package diff {label} does not match")

    return diff


def _owned_package_select(
    *,
    project_id: UUID,
    owner_user_id: UUID,
):
    return sa.select(PACKAGE_VERSIONS).where(
        PACKAGE_VERSIONS.c.project_id == project_id,
        _owned_project_exists(
            project_id=project_id,
            owner_user_id=owner_user_id,
        ),
    )


def _owned_diff_select(
    *,
    project_id: UUID,
    owner_user_id: UUID,
):
    return sa.select(PACKAGE_DIFFS).where(
        PACKAGE_DIFFS.c.project_id == project_id,
        _owned_project_exists(
            project_id=project_id,
            owner_user_id=owner_user_id,
        ),
    )


def _owned_project_exists(
    *,
    project_id: UUID,
    owner_user_id: UUID,
):
    return sa.exists(
        sa.select(sa.literal(1)).where(
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
    statement = sa.select(
        _owned_project_exists(
            project_id=project_id,
            owner_user_id=owner_user_id,
        )
    )

    return bool((await session.execute(statement)).scalar_one())


async def _base_version_exists(
    session: AsyncSession,
    diff: DesignPackageDiff,
) -> bool:
    statement = sa.select(
        sa.exists(
            sa.select(sa.literal(1)).where(
                PACKAGE_VERSIONS.c.id == diff.base_version_id,
                PACKAGE_VERSIONS.c.project_id == diff.project_id,
                PACKAGE_VERSIONS.c.version_number == diff.base_version_number,
                PACKAGE_VERSIONS.c.content_hash == diff.base_content_hash,
            )
        )
    )

    return bool((await session.execute(statement)).scalar_one())


def _required(values: Mapping[str, object], key: str) -> object:
    if key not in values:
        raise ValueError(f"missing persisted Design Package field: {key}")

    return values[key]


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")

    return value


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")

    return value


def _optional_string(value: object, *, label: str) -> str | None:
    return None if value is None else _string(value, label=label)


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} must be an integer")

    return value


def _optional_integer(value: object, *, label: str) -> int | None:
    return None if value is None else _integer(value, label=label)


def _uuid(value: object, *, label: str) -> UUID:
    if isinstance(value, UUID):
        return value

    if isinstance(value, str):
        return UUID(value)

    raise ValueError(f"{label} must be a UUID")


def _optional_uuid(value: object, *, label: str) -> UUID | None:
    return None if value is None else _uuid(value, label=label)


def _datetime(value: object, *, label: str) -> datetime:
    if isinstance(value, datetime):
        result = value
    elif isinstance(value, str):
        result = datetime.fromisoformat(value)
    else:
        raise ValueError(f"{label} must be a timestamp")

    if result.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")

    return result


def _optional_datetime(value: object, *, label: str) -> datetime | None:
    return None if value is None else _datetime(value, label=label)


__all__ = [
    "SqlAlchemyDesignDiffRepository",
    "SqlAlchemyDesignPackageRepository",
    "SqlAlchemyDesignUnitOfWork",
    "SqlAlchemyDesignUnitOfWorkFactory",
    "design_diff_from_record",
    "design_diff_to_record",
    "design_package_version_from_record",
    "design_package_version_to_record",
]
