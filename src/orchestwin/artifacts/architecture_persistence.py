"""PostgreSQL persistence for immutable Architecture Packages and owner diffs."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from types import TracebackType
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.artifacts.architecture_packages import (
    ARCHITECTURE_PACKAGE_SCHEMA_VERSION,
    ArchitecturePackageVersion,
)
from orchestwin.artifacts.architecture_revision_application import (
    ArchitectureDiffPersistenceStatus,
)
from orchestwin.artifacts.architecture_revisions import (
    ArchitecturePackageDiff,
    ArchitecturePackageDiffStatus,
)
from orchestwin.artifacts.architecture_serialization import (
    architecture_diff_from_snapshot,
    architecture_diff_proposal_snapshot,
    architecture_package_from_snapshot,
)
from orchestwin.projects.architecture_application import ArchitectureVersionAppendStatus

_UUID = postgresql.UUID(as_uuid=True)

PROJECTS = sa.table(
    "projects",
    sa.column("id", _UUID),
    sa.column("owner_user_id", _UUID),
)

PACKAGE_VERSIONS = sa.table(
    "architecture_package_versions",
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
    "architecture_package_diffs",
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


class SqlAlchemyArchitecturePackageRepository:
    """Append-only owner-scoped Architecture Package repository."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Bind Architecture Package access to one authenticated owner."""
        self._session = session
        self._owner_user_id = owner_user_id

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        """Return the latest owner-scoped Architecture Package version."""
        return await self._current(project_id=project_id, for_update=False)

    async def get_current_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        """Lock and return the current Architecture Package for Gate 5."""
        if owner_user_id != self._owner_user_id:
            return None

        return await self._current(project_id=project_id, for_update=True)

    async def get(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
    ) -> ArchitecturePackageVersion | None:
        """Return one exact owner-scoped Architecture Package version."""
        statement = _owned_package_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(PACKAGE_VERSIONS.c.id == version_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else architecture_package_version_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[ArchitecturePackageVersion, ...]:
        """Return immutable Architecture Package history in version order."""
        statement = _owned_package_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(PACKAGE_VERSIONS.c.version_number.asc())
        rows = (await self._session.execute(statement)).mappings().all()

        return tuple(architecture_package_version_from_record(row) for row in rows)

    async def append(
        self,
        version: ArchitecturePackageVersion,
    ) -> ArchitectureVersionAppendStatus:
        """Append one version after locking its current project baseline."""
        if version.created_by_user_id != self._owner_user_id:
            return ArchitectureVersionAppendStatus.PROJECT_NOT_FOUND

        if not await _project_is_owned(
            self._session,
            project_id=version.project_id,
            owner_user_id=self._owner_user_id,
        ):
            return ArchitectureVersionAppendStatus.PROJECT_NOT_FOUND

        current = await self._current(project_id=version.project_id, for_update=True)

        if current is None:
            if version.version_number != 1 or version.based_on_version_number is not None:
                return ArchitectureVersionAppendStatus.VERSION_CONFLICT
        else:
            if (
                version.version_number != current.version_number + 1
                or version.based_on_version_number != current.version_number
            ):
                return ArchitectureVersionAppendStatus.VERSION_CONFLICT

            if version.content_hash == current.content_hash:
                return ArchitectureVersionAppendStatus.CONTENT_CONFLICT

        try:
            await self._session.execute(
                sa.insert(PACKAGE_VERSIONS).values(
                    **architecture_package_version_to_record(version)
                )
            )
        except IntegrityError:
            return ArchitectureVersionAppendStatus.VERSION_CONFLICT

        return ArchitectureVersionAppendStatus.APPENDED

    async def _current(
        self,
        *,
        project_id: UUID,
        for_update: bool,
    ) -> ArchitecturePackageVersion | None:
        """Read the latest Architecture Package with optional row locking."""
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

        return None if row is None else architecture_package_version_from_record(row)


class SqlAlchemyArchitectureDiffRepository:
    """Owner-scoped repository for reviewable Architecture Package diffs."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Bind Architecture Package diff access to one authenticated owner."""
        self._session = session
        self._owner_user_id = owner_user_id

    async def create(
        self,
        diff: ArchitecturePackageDiff,
    ) -> ArchitectureDiffPersistenceStatus:
        """Persist a proposed diff against an exact owned base version."""
        if diff.owner_user_id != self._owner_user_id:
            return ArchitectureDiffPersistenceStatus.PROJECT_NOT_FOUND

        if not await _project_is_owned(
            self._session,
            project_id=diff.project_id,
            owner_user_id=self._owner_user_id,
        ):
            return ArchitectureDiffPersistenceStatus.PROJECT_NOT_FOUND

        if not await _base_version_exists(self._session, diff):
            return ArchitectureDiffPersistenceStatus.CONTEXT_NOT_FOUND

        try:
            await self._session.execute(
                sa.insert(PACKAGE_DIFFS).values(**architecture_diff_to_record(diff))
            )
        except IntegrityError:
            return ArchitectureDiffPersistenceStatus.CONFLICT

        return ArchitectureDiffPersistenceStatus.CREATED

    async def get(
        self,
        *,
        project_id: UUID,
        diff_id: UUID,
    ) -> ArchitecturePackageDiff | None:
        """Return one exact owner-scoped Architecture Package diff."""
        statement = _owned_diff_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(PACKAGE_DIFFS.c.id == diff_id)
        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else architecture_diff_from_record(row)

    async def current_proposed(
        self,
        *,
        project_id: UUID,
        base_version_id: UUID,
    ) -> ArchitecturePackageDiff | None:
        """Return the proposed diff for an exact base version."""
        statement = (
            _owned_diff_select(
                project_id=project_id,
                owner_user_id=self._owner_user_id,
            )
            .where(
                PACKAGE_DIFFS.c.base_version_id == base_version_id,
                PACKAGE_DIFFS.c.status == ArchitecturePackageDiffStatus.PROPOSED.value,
            )
            .limit(1)
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()

        return None if row is None else architecture_diff_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[ArchitecturePackageDiff, ...]:
        """Return Architecture Package diff history in creation order."""
        statement = _owned_diff_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(PACKAGE_DIFFS.c.created_at.asc(), PACKAGE_DIFFS.c.id.asc())
        rows = (await self._session.execute(statement)).mappings().all()

        return tuple(architecture_diff_from_record(row) for row in rows)

    async def save_decision(
        self,
        diff: ArchitecturePackageDiff,
    ) -> ArchitectureDiffPersistenceStatus:
        """Update only decision metadata of one proposed Architecture Package diff."""
        if diff.status is ArchitecturePackageDiffStatus.PROPOSED:
            raise ValueError(
                "cannot persist a decision while Architecture Package diff is PROPOSED"
            )

        if diff.decided_by_user_id != self._owner_user_id:
            return ArchitectureDiffPersistenceStatus.CONFLICT

        statement = (
            sa.update(PACKAGE_DIFFS)
            .where(
                PACKAGE_DIFFS.c.id == diff.id,
                PACKAGE_DIFFS.c.project_id == diff.project_id,
                PACKAGE_DIFFS.c.status == ArchitecturePackageDiffStatus.PROPOSED.value,
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
            return ArchitectureDiffPersistenceStatus.CONFLICT

        return ArchitectureDiffPersistenceStatus.UPDATED


class SqlAlchemyArchitectureUnitOfWork:
    """SQLAlchemy transaction coordinator for Architecture persistence."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        """Create owner-scoped repositories over one shared session."""
        self._session = session
        self._completed = False
        self.packages = SqlAlchemyArchitecturePackageRepository(
            session,
            owner_user_id=owner_user_id,
        )
        self.diffs = SqlAlchemyArchitectureDiffRepository(
            session,
            owner_user_id=owner_user_id,
        )

    async def __aenter__(self) -> SqlAlchemyArchitectureUnitOfWork:
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


class SqlAlchemyArchitectureUnitOfWorkFactory:
    """Create owner-scoped Architecture Units of Work."""

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
    ) -> SqlAlchemyArchitectureUnitOfWork:
        """Create one Unit of Work with a fresh async session."""
        return SqlAlchemyArchitectureUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


def architecture_package_version_to_record(
    version: ArchitecturePackageVersion,
) -> dict[str, object]:
    """Convert one Architecture Package version to database values."""
    return {
        "id": version.id,
        "project_id": version.project_id,
        "version_number": version.version_number,
        "based_on_version_number": version.based_on_version_number,
        "schema_version": ARCHITECTURE_PACKAGE_SCHEMA_VERSION,
        "content_hash": version.content_hash,
        "package_snapshot": version.package.to_snapshot(),
        "created_by_user_id": version.created_by_user_id,
        "created_at": version.created_at,
    }


def architecture_package_version_from_record(
    record: Mapping[str, object],
) -> ArchitecturePackageVersion:
    """Reconstruct and validate one persisted Architecture Package version."""
    schema_version = _integer(
        _required(record, "schema_version"),
        label="Architecture Package schema version",
    )

    if schema_version != ARCHITECTURE_PACKAGE_SCHEMA_VERSION:
        raise ValueError("unsupported persisted Architecture Package schema")

    package = architecture_package_from_snapshot(
        _mapping(
            _required(record, "package_snapshot"),
            label="persisted Architecture Package snapshot",
        )
    )

    return ArchitecturePackageVersion(
        id=_uuid(
            _required(record, "id"),
            label="Architecture Package version ID",
        ),
        project_id=_uuid(
            _required(record, "project_id"),
            label="Architecture Package project ID",
        ),
        version_number=_integer(
            _required(record, "version_number"),
            label="Architecture Package version number",
        ),
        based_on_version_number=_optional_integer(
            record.get("based_on_version_number"),
            label="Architecture Package base version number",
        ),
        package=package,
        content_hash=_string(
            _required(record, "content_hash"),
            label="Architecture Package content hash",
        ),
        created_by_user_id=_uuid(
            _required(record, "created_by_user_id"),
            label="Architecture Package creator ID",
        ),
        created_at=_datetime(
            _required(record, "created_at"),
            label="Architecture Package creation timestamp",
        ),
    )


def architecture_diff_to_record(
    diff: ArchitecturePackageDiff,
) -> dict[str, object]:
    """Convert one Architecture Package diff to database values."""
    return {
        "id": diff.id,
        "project_id": diff.project_id,
        "owner_user_id": diff.owner_user_id,
        "base_version_id": diff.base_version_id,
        "base_version_number": diff.base_version_number,
        "base_content_hash": diff.base_content_hash,
        "proposal_hash": diff.proposal_hash,
        "diff_snapshot": architecture_diff_proposal_snapshot(diff),
        "status": diff.status.value,
        "created_at": diff.created_at,
        "decided_by_user_id": diff.decided_by_user_id,
        "decided_at": diff.decided_at,
        "decision_reason": diff.decision_reason,
        "applied_version_id": diff.applied_version_id,
    }


def architecture_diff_from_record(
    record: Mapping[str, object],
) -> ArchitecturePackageDiff:
    """Reconstruct and validate one persisted Architecture Package diff."""
    payload = _mapping(
        _required(record, "diff_snapshot"),
        label="persisted Architecture Package diff snapshot",
    )
    diff = architecture_diff_from_snapshot(
        payload,
        status=ArchitecturePackageDiffStatus(
            _string(
                _required(record, "status"),
                label="Architecture Package diff status",
            )
        ),
        decided_by_user_id=_optional_uuid(
            record.get("decided_by_user_id"),
            label="Architecture Package diff decision actor",
        ),
        decided_at=_optional_datetime(
            record.get("decided_at"),
            label="Architecture Package diff decision timestamp",
        ),
        decision_reason=_optional_string(
            record.get("decision_reason"),
            label="Architecture Package diff decision reason",
        ),
        applied_version_id=_optional_uuid(
            record.get("applied_version_id"),
            label="applied Architecture Package version ID",
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
            raise ValueError(f"persisted Architecture Package diff {label} does not match")

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
    diff: ArchitecturePackageDiff,
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
        raise ValueError(f"missing persisted Architecture Package field: {key}")

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
    "SqlAlchemyArchitectureDiffRepository",
    "SqlAlchemyArchitecturePackageRepository",
    "SqlAlchemyArchitectureUnitOfWork",
    "SqlAlchemyArchitectureUnitOfWorkFactory",
    "architecture_diff_from_record",
    "architecture_diff_to_record",
    "architecture_package_version_from_record",
    "architecture_package_version_to_record",
]
