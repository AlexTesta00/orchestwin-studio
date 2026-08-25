"""Owner-scoped append-only persistence for brownfield source intake."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self, cast
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.brownfield_intake import (
    BROWNFIELD_INTAKE_SCHEMA_VERSION,
    BrownfieldIntakeVersion,
)
from orchestwin.projects.domain import Project, ProjectMode
from orchestwin.projects.execution_capabilities import CapabilityNegotiationStatus
from orchestwin.projects.requirements_primitives import (
    canonical_json,
    snapshot_content_hash,
    validate_positive_integer,
    validate_sha256,
)
from orchestwin.sandbox.execution_profiles import (
    ExecutionCapabilityStatus,
    ExecutionProfileReference,
)

BROWNFIELD_INTAKE_VERSIONS = sa.Table(
    "brownfield_intake_versions",
    OrmBase.metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column(
        "project_id",
        sa.Uuid,
        sa.ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("version_number", sa.Integer, nullable=False),
    sa.Column("based_on_version_number", sa.Integer, nullable=True),
    sa.Column("schema_version", sa.Integer, nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("archive_sha256", sa.String(64), nullable=False),
    sa.Column("archive_size_bytes", sa.BigInteger, nullable=False),
    sa.Column("archive_storage_key", sa.Text, nullable=False),
    sa.Column("inventory_content_hash", sa.String(64), nullable=False),
    sa.Column("capability_status", sa.String(40), nullable=False),
    sa.Column("effective_capability_status", sa.String(32), nullable=False),
    sa.Column("selected_profile_id", sa.String(128), nullable=True),
    sa.Column("selected_profile_version", sa.String(64), nullable=True),
    sa.Column("selected_profile_content_hash", sa.String(64), nullable=True),
    sa.Column("intake_snapshot", JSONB, nullable=False),
    sa.Column(
        "created_by_user_id",
        sa.Uuid,
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["project_id", "based_on_version_number"],
        [
            "brownfield_intake_versions.project_id",
            "brownfield_intake_versions.version_number",
        ],
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "project_id",
        "version_number",
        name="uq_brownfield_intake_versions_project_version",
    ),
    sa.UniqueConstraint(
        "project_id",
        "content_hash",
        name="uq_brownfield_intake_versions_project_hash",
    ),
    sa.CheckConstraint(
        "version_number > 0",
        name="positive_version",
    ),
    sa.CheckConstraint(
        "schema_version > 0",
        name="positive_schema",
    ),
    sa.CheckConstraint(
        "archive_size_bytes >= 0",
        name="archive_size_non_negative",
    ),
    sa.CheckConstraint(
        "(version_number = 1 AND based_on_version_number IS NULL) OR "
        "(version_number > 1 AND based_on_version_number = version_number - 1)",
        name="linear_lineage",
    ),
    sa.CheckConstraint(
        "content_hash ~ '^[0-9a-f]{64}$'",
        name="content_hash",
    ),
    sa.CheckConstraint(
        "archive_sha256 ~ '^[0-9a-f]{64}$'",
        name="archive_hash",
    ),
    sa.CheckConstraint(
        "inventory_content_hash ~ '^[0-9a-f]{64}$'",
        name="inventory_hash",
    ),
    sa.CheckConstraint(
        "selected_profile_content_hash IS NULL OR selected_profile_content_hash ~ '^[0-9a-f]{64}$'",
        name="selected_profile_hash",
    ),
    sa.CheckConstraint(
        "capability_status IN ("
        "'VALIDATED_LEVEL_D_SELECTED', "
        "'EXPERIMENTAL_LEVEL_D_SELECTED', "
        "'DESIGN_ONLY_LEVEL_C_SELECTED', "
        "'HUMAN_DECISION_REQUIRED', "
        "'UNSUPPORTED'"
        ")",
        name="capability_status",
    ),
    sa.CheckConstraint(
        "effective_capability_status IN ("
        "'VALIDATED_LEVEL_D', "
        "'EXPERIMENTAL_LEVEL_D', "
        "'DESIGN_ONLY_LEVEL_C'"
        ")",
        name="effective_capability_status",
    ),
    sa.CheckConstraint(
        "(selected_profile_id IS NULL "
        "AND selected_profile_version IS NULL "
        "AND selected_profile_content_hash IS NULL) OR "
        "(selected_profile_id IS NOT NULL "
        "AND selected_profile_version IS NOT NULL "
        "AND selected_profile_content_hash IS NOT NULL)",
        name="selected_profile_shape",
    ),
)


class BrownfieldIntakeAppendStatus(StrEnum):
    """Typed owner-safe outcomes of appending one intake version."""

    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    PROJECT_MODE_UNSUPPORTED = "PROJECT_MODE_UNSUPPORTED"
    VERSION_CONFLICT = "VERSION_CONFLICT"


@dataclass(frozen=True, slots=True)
class PersistedBrownfieldIntakeVersion:
    """Validated persisted metadata with immutable canonical snapshot JSON."""

    id: UUID
    project_id: UUID
    version_number: int
    based_on_version_number: int | None
    schema_version: int
    content_hash: str
    archive_sha256: str
    archive_size_bytes: int
    archive_storage_key: str
    inventory_content_hash: str
    capability_status: CapabilityNegotiationStatus
    effective_capability_status: ExecutionCapabilityStatus
    selected_profile_reference: ExecutionProfileReference | None
    snapshot_json: str
    created_by_user_id: UUID
    created_at: datetime

    def __post_init__(self) -> None:
        """Validate lineage, digests, canonical JSON, and projected columns."""
        validate_positive_integer(
            self.version_number,
            label="persisted brownfield intake version",
        )
        if self.schema_version != BROWNFIELD_INTAKE_SCHEMA_VERSION:
            raise ValueError("unsupported persisted brownfield intake schema")
        for value, label in (
            (self.content_hash, "persisted brownfield intake content hash"),
            (self.archive_sha256, "persisted brownfield archive digest"),
            (self.inventory_content_hash, "persisted brownfield inventory hash"),
        ):
            validate_sha256(value, label=label)

        if self.version_number == 1:
            if self.based_on_version_number is not None:
                raise ValueError("first persisted brownfield intake cannot have a predecessor")
        elif self.based_on_version_number != self.version_number - 1:
            raise ValueError("persisted brownfield intake requires linear lineage")
        if self.archive_size_bytes < 0:
            raise ValueError("persisted brownfield archive size must not be negative")
        if not self.archive_storage_key:
            raise ValueError("persisted brownfield archive storage key is required")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("persisted brownfield intake timestamp must be timezone-aware")

        payload = _snapshot_payload(self.snapshot_json)
        if snapshot_content_hash(payload) != self.content_hash:
            raise ValueError("persisted brownfield intake snapshot hash is inconsistent")
        if payload.get("schema_version") != self.schema_version:
            raise ValueError("persisted brownfield intake snapshot schema is inconsistent")
        if payload.get("project_id") != str(self.project_id):
            raise ValueError("persisted brownfield intake snapshot project is inconsistent")

        archive = _mapping(payload.get("archive"), label="brownfield archive snapshot")
        inventory = _mapping(payload.get("inventory"), label="brownfield inventory snapshot")
        capability = _mapping(payload.get("capability"), label="brownfield capability snapshot")
        if archive.get("sha256_digest") != self.archive_sha256:
            raise ValueError("persisted brownfield archive projection is inconsistent")
        if archive.get("size_bytes") != self.archive_size_bytes:
            raise ValueError("persisted brownfield archive size projection is inconsistent")
        if archive.get("storage_key") != self.archive_storage_key:
            raise ValueError("persisted brownfield archive key projection is inconsistent")
        if inventory.get("content_hash") != self.inventory_content_hash:
            raise ValueError("persisted brownfield inventory projection is inconsistent")
        if capability.get("status") != self.capability_status.value:
            raise ValueError("persisted brownfield capability status is inconsistent")
        if capability.get("effective_capability_status") != (
            self.effective_capability_status.value
        ):
            raise ValueError("persisted brownfield effective capability is inconsistent")

        selected = capability.get("selected_profile_reference")
        if self.selected_profile_reference is None:
            if selected is not None:
                raise ValueError("persisted brownfield selected profile is inconsistent")
        elif _mapping(selected, label="selected profile") != (
            self.selected_profile_reference.to_snapshot()
        ):
            raise ValueError("persisted brownfield selected profile projection is inconsistent")

    @property
    def snapshot(self) -> dict[str, object]:
        """Return a fresh JSON-compatible snapshot copy."""
        return _snapshot_payload(self.snapshot_json)

    def to_snapshot(self) -> dict[str, object]:
        """Return version metadata and exact nested intake content."""
        return {
            "id": str(self.id),
            "project_id": str(self.project_id),
            "version_number": self.version_number,
            "based_on_version_number": self.based_on_version_number,
            "schema_version": self.schema_version,
            "content_hash": self.content_hash,
            "snapshot": self.snapshot,
            "created_by_user_id": str(self.created_by_user_id),
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class BrownfieldIntakeAppendResult:
    """Result of append or idempotent reuse without authorization leakage."""

    status: BrownfieldIntakeAppendStatus
    version: PersistedBrownfieldIntakeVersion | None

    def __post_init__(self) -> None:
        successful = self.status in {
            BrownfieldIntakeAppendStatus.APPENDED,
            BrownfieldIntakeAppendStatus.ALREADY_PRESENT,
        }
        if successful != (self.version is not None):
            raise ValueError("brownfield intake append result shape is inconsistent")


class BrownfieldIntakeRepository(Protocol):
    """Owner-scoped append-only brownfield intake persistence port."""

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> PersistedBrownfieldIntakeVersion | None:
        """Return the latest owned intake version."""
        ...

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PersistedBrownfieldIntakeVersion, ...]:
        """Return owned intake history in version order."""
        ...

    async def append(
        self,
        version: BrownfieldIntakeVersion,
    ) -> BrownfieldIntakeAppendResult:
        """Append or reuse one exact intake snapshot."""
        ...


class BrownfieldIntakeUnitOfWork(Protocol):
    """Transactional boundary for brownfield source intake."""

    intakes: BrownfieldIntakeRepository

    async def __aenter__(self) -> Self:
        """Enter the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Leave the transaction."""
        ...

    async def commit(self) -> None:
        """Commit all writes."""
        ...

    async def rollback(self) -> None:
        """Rollback all writes."""
        ...


class BrownfieldIntakeUnitOfWorkFactory(Protocol):
    """Create one owner-scoped brownfield intake transaction."""

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> BrownfieldIntakeUnitOfWork:
        """Create one unopened transaction."""
        ...


class SqlAlchemyBrownfieldIntakeRepository:
    """PostgreSQL-backed owner-scoped intake repository."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> PersistedBrownfieldIntakeVersion | None:
        """Return the current version only for the authenticated owner."""
        statement = (
            _owned_intake_select(
                project_id=project_id,
                owner_user_id=self._owner_user_id,
            )
            .order_by(BROWNFIELD_INTAKE_VERSIONS.c.version_number.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else persisted_brownfield_intake_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PersistedBrownfieldIntakeVersion, ...]:
        """Return canonical owner-scoped intake history."""
        statement = _owned_intake_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(BROWNFIELD_INTAKE_VERSIONS.c.version_number.asc())
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(persisted_brownfield_intake_from_record(row) for row in rows)

    async def append(
        self,
        version: BrownfieldIntakeVersion,
    ) -> BrownfieldIntakeAppendResult:
        """Append under a project lock while preserving idempotency."""
        if version.created_by_user_id != self._owner_user_id:
            return BrownfieldIntakeAppendResult(
                BrownfieldIntakeAppendStatus.PROJECT_NOT_FOUND,
                None,
            )

        projects = sa.table(
            "projects",
            sa.column("id"),
            sa.column("owner_user_id"),
            sa.column("mode"),
            sa.column("archived_at"),
        )
        project_mode = await self._session.scalar(
            sa.select(projects.c.mode)
            .where(
                projects.c.id == version.project_id,
                projects.c.owner_user_id == self._owner_user_id,
                projects.c.archived_at.is_(None),
            )
            .with_for_update()
        )
        if project_mode is None:
            return BrownfieldIntakeAppendResult(
                BrownfieldIntakeAppendStatus.PROJECT_NOT_FOUND,
                None,
            )
        if project_mode != ProjectMode.BROWNFIELD_ASSESSMENT.value:
            return BrownfieldIntakeAppendResult(
                BrownfieldIntakeAppendStatus.PROJECT_MODE_UNSUPPORTED,
                None,
            )

        existing = await self._by_content_hash(
            project_id=version.project_id,
            content_hash=version.content_hash,
        )
        if existing is not None:
            return BrownfieldIntakeAppendResult(
                BrownfieldIntakeAppendStatus.ALREADY_PRESENT,
                existing,
            )

        current = await self._current_for_update(project_id=version.project_id)
        if current is None:
            valid_lineage = version.version_number == 1 and version.based_on_version_number is None
        else:
            valid_lineage = (
                version.version_number == current.version_number + 1
                and version.based_on_version_number == current.version_number
            )
        if not valid_lineage:
            return BrownfieldIntakeAppendResult(
                BrownfieldIntakeAppendStatus.VERSION_CONFLICT,
                None,
            )

        try:
            await self._session.execute(
                sa.insert(BROWNFIELD_INTAKE_VERSIONS).values(
                    **brownfield_intake_version_to_record(version)
                )
            )
        except IntegrityError:
            return BrownfieldIntakeAppendResult(
                BrownfieldIntakeAppendStatus.VERSION_CONFLICT,
                None,
            )

        return BrownfieldIntakeAppendResult(
            BrownfieldIntakeAppendStatus.APPENDED,
            persisted_brownfield_intake_from_domain(version),
        )

    async def _current_for_update(
        self,
        *,
        project_id: UUID,
    ) -> PersistedBrownfieldIntakeVersion | None:
        statement = (
            _owned_intake_select(
                project_id=project_id,
                owner_user_id=self._owner_user_id,
            )
            .order_by(BROWNFIELD_INTAKE_VERSIONS.c.version_number.desc())
            .limit(1)
            .with_for_update()
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else persisted_brownfield_intake_from_record(row)

    async def _by_content_hash(
        self,
        *,
        project_id: UUID,
        content_hash: str,
    ) -> PersistedBrownfieldIntakeVersion | None:
        statement = _owned_intake_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(BROWNFIELD_INTAKE_VERSIONS.c.content_hash == content_hash)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else persisted_brownfield_intake_from_record(row)


class SqlAlchemyBrownfieldIntakeUnitOfWork:
    """SQLAlchemy transaction coordinator for brownfield source intake."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session = session
        self._completed = False
        self.intakes = SqlAlchemyBrownfieldIntakeRepository(
            session,
            owner_user_id=owner_user_id,
        )

    async def __aenter__(self) -> SqlAlchemyBrownfieldIntakeUnitOfWork:
        self._completed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback
        if not self._completed:
            await self.rollback()

    async def commit(self) -> None:
        await self._session.commit()
        self._completed = True

    async def rollback(self) -> None:
        await self._session.rollback()
        self._completed = True


class SqlAlchemyBrownfieldIntakeUnitOfWorkFactory:
    """Create owner-scoped intake Units of Work with fresh sessions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> SqlAlchemyBrownfieldIntakeUnitOfWork:
        return SqlAlchemyBrownfieldIntakeUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


class InMemoryBrownfieldIntakeRepository:
    """Deterministic repository adapter for application and contract tests."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        projects: Mapping[UUID, Project],
    ) -> None:
        self._owner_user_id = owner_user_id
        self._projects = dict(projects)
        self._versions: dict[UUID, list[PersistedBrownfieldIntakeVersion]] = {}

    async def current(
        self,
        *,
        project_id: UUID,
    ) -> PersistedBrownfieldIntakeVersion | None:
        if not self._is_owned(project_id):
            return None
        versions = self._versions.get(project_id, [])
        return None if not versions else versions[-1]

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PersistedBrownfieldIntakeVersion, ...]:
        if not self._is_owned(project_id):
            return ()
        return tuple(self._versions.get(project_id, []))

    async def append(
        self,
        version: BrownfieldIntakeVersion,
    ) -> BrownfieldIntakeAppendResult:
        project = self._projects.get(version.project_id)
        if (
            project is None
            or project.owner_user_id != self._owner_user_id
            or project.archived_at is not None
            or version.created_by_user_id != self._owner_user_id
        ):
            return BrownfieldIntakeAppendResult(
                BrownfieldIntakeAppendStatus.PROJECT_NOT_FOUND,
                None,
            )
        if project.mode is not ProjectMode.BROWNFIELD_ASSESSMENT:
            return BrownfieldIntakeAppendResult(
                BrownfieldIntakeAppendStatus.PROJECT_MODE_UNSUPPORTED,
                None,
            )

        versions = self._versions.setdefault(version.project_id, [])
        existing = next(
            (item for item in versions if item.content_hash == version.content_hash),
            None,
        )
        if existing is not None:
            return BrownfieldIntakeAppendResult(
                BrownfieldIntakeAppendStatus.ALREADY_PRESENT,
                existing,
            )

        current = None if not versions else versions[-1]
        expected_number = 1 if current is None else current.version_number + 1
        expected_base = None if current is None else current.version_number
        if (
            version.version_number != expected_number
            or version.based_on_version_number != expected_base
        ):
            return BrownfieldIntakeAppendResult(
                BrownfieldIntakeAppendStatus.VERSION_CONFLICT,
                None,
            )

        persisted = persisted_brownfield_intake_from_domain(version)
        versions.append(persisted)
        return BrownfieldIntakeAppendResult(
            BrownfieldIntakeAppendStatus.APPENDED,
            persisted,
        )

    def _is_owned(self, project_id: UUID) -> bool:
        project = self._projects.get(project_id)
        return (
            project is not None
            and project.owner_user_id == self._owner_user_id
            and project.archived_at is None
        )


def brownfield_intake_version_to_record(
    version: BrownfieldIntakeVersion,
) -> dict[str, object]:
    """Convert one validated domain version into database values."""
    selected = version.snapshot.capability.selected_profile_reference
    return {
        "id": version.id,
        "project_id": version.project_id,
        "version_number": version.version_number,
        "based_on_version_number": version.based_on_version_number,
        "schema_version": version.snapshot.schema_version,
        "content_hash": version.content_hash,
        "archive_sha256": version.snapshot.archive.sha256_digest,
        "archive_size_bytes": version.snapshot.archive.size_bytes,
        "archive_storage_key": version.snapshot.archive.storage_key,
        "inventory_content_hash": version.snapshot.inventory.content_hash,
        "capability_status": version.snapshot.capability.status.value,
        "effective_capability_status": (
            version.snapshot.capability.effective_capability_status.value
        ),
        "selected_profile_id": None if selected is None else selected.profile_id,
        "selected_profile_version": None if selected is None else selected.profile_version,
        "selected_profile_content_hash": None if selected is None else selected.content_hash,
        "intake_snapshot": version.snapshot.to_snapshot(),
        "created_by_user_id": version.created_by_user_id,
        "created_at": version.created_at,
    }


def persisted_brownfield_intake_from_domain(
    version: BrownfieldIntakeVersion,
) -> PersistedBrownfieldIntakeVersion:
    """Project a domain version into its validated immutable persistence view."""
    values = brownfield_intake_version_to_record(version)
    return persisted_brownfield_intake_from_record(values)


def persisted_brownfield_intake_from_record(
    record: Mapping[str, object],
) -> PersistedBrownfieldIntakeVersion:
    """Validate one database row before exposing it to application code."""
    selected_id = _optional_string(record.get("selected_profile_id"))
    selected_version = _optional_string(record.get("selected_profile_version"))
    selected_hash = _optional_string(record.get("selected_profile_content_hash"))
    selected_values = (selected_id, selected_version, selected_hash)
    if all(value is None for value in selected_values):
        selected = None
    elif all(value is not None for value in selected_values):
        selected = ExecutionProfileReference(
            profile_id=cast(str, selected_id),
            profile_version=cast(str, selected_version),
            content_hash=cast(str, selected_hash),
        )
    else:
        raise ValueError("persisted selected profile metadata must be all-null or complete")

    snapshot = _mapping(record.get("intake_snapshot"), label="brownfield intake snapshot")
    return PersistedBrownfieldIntakeVersion(
        id=_uuid(record.get("id"), label="brownfield intake ID"),
        project_id=_uuid(record.get("project_id"), label="brownfield project ID"),
        version_number=_integer(
            record.get("version_number"),
            label="brownfield intake version",
        ),
        based_on_version_number=_optional_integer(record.get("based_on_version_number")),
        schema_version=_integer(
            record.get("schema_version"),
            label="brownfield intake schema version",
        ),
        content_hash=_string(record.get("content_hash"), label="brownfield intake hash"),
        archive_sha256=_string(record.get("archive_sha256"), label="archive digest"),
        archive_size_bytes=_integer(
            record.get("archive_size_bytes"),
            label="archive size",
        ),
        archive_storage_key=_string(
            record.get("archive_storage_key"),
            label="archive storage key",
        ),
        inventory_content_hash=_string(
            record.get("inventory_content_hash"),
            label="inventory content hash",
        ),
        capability_status=CapabilityNegotiationStatus(
            _string(record.get("capability_status"), label="capability status")
        ),
        effective_capability_status=ExecutionCapabilityStatus(
            _string(
                record.get("effective_capability_status"),
                label="effective capability status",
            )
        ),
        selected_profile_reference=selected,
        snapshot_json=canonical_json(snapshot),
        created_by_user_id=_uuid(
            record.get("created_by_user_id"),
            label="brownfield intake creator",
        ),
        created_at=_datetime(record.get("created_at"), label="brownfield intake time"),
    )


def _owned_intake_select(
    *,
    project_id: UUID,
    owner_user_id: UUID,
) -> sa.Select[tuple[object, ...]]:
    projects = sa.table(
        "projects",
        sa.column("id"),
        sa.column("owner_user_id"),
        sa.column("archived_at"),
    )
    return (
        sa.select(BROWNFIELD_INTAKE_VERSIONS)
        .select_from(
            BROWNFIELD_INTAKE_VERSIONS.join(
                projects,
                projects.c.id == BROWNFIELD_INTAKE_VERSIONS.c.project_id,
            )
        )
        .where(
            BROWNFIELD_INTAKE_VERSIONS.c.project_id == project_id,
            projects.c.owner_user_id == owner_user_id,
            projects.c.archived_at.is_(None),
        )
    )


def _snapshot_payload(value: str) -> dict[str, object]:
    if not isinstance(value, str):
        raise TypeError("brownfield intake snapshot JSON must be text")
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as error:
        raise ValueError("brownfield intake snapshot JSON is invalid") from error
    if not isinstance(parsed, dict) or any(not isinstance(key, str) for key in parsed):
        raise ValueError("brownfield intake snapshot must be a JSON object")
    payload = cast(dict[str, object], parsed)
    if canonical_json(payload) != value:
        raise ValueError("brownfield intake snapshot JSON must be canonical")
    return payload


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return {str(key): item for key, item in value.items()}


def _uuid(value: object, *, label: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError as error:
            raise ValueError(f"{label} must be a UUID") from error
    raise TypeError(f"{label} must be a UUID")


def _integer(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{label} must be an integer")
    return value


def _optional_integer(value: object) -> int | None:
    if value is None:
        return None
    return _integer(value, label="brownfield base version")


def _string(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be text")
    return value


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return _string(value, label="selected profile metadata")


def _datetime(value: object, *, label: str) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{label} must be a datetime")
    return value
