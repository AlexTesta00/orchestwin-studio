"""Owner-scoped append-only persistence for immutable JVM source revisions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.artifacts.jvm_sources import (
    JvmSourceFileEntry,
    JvmSourceOrigin,
    JvmSourceProvenanceKind,
    JvmSourceProvenanceReference,
    JvmSourceRevision,
    JvmSourceRevisionReference,
)
from orchestwin.jvm_execution.targets import (
    JvmBuildSystem,
    JvmImplementationLanguage,
    JvmProjectLayout,
    JvmTargetSelection,
)
from orchestwin.persistence.orm import OrmBase
from orchestwin.sandbox.execution_profiles import ExecutionTarget

JVM_SOURCE_REVISIONS = sa.Table(
    "jvm_source_revisions",
    OrmBase.metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column(
        "project_id",
        sa.Uuid,
        sa.ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("version_number", sa.Integer, nullable=False),
    sa.Column("based_on_revision_id", sa.Uuid, nullable=True),
    sa.Column("based_on_version_number", sa.Integer, nullable=True),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("source_tree_hash", sa.String(64), nullable=False),
    sa.Column("validation_scope_hash", sa.String(64), nullable=False),
    sa.Column("target", sa.String(32), nullable=False),
    sa.Column("layout", sa.String(32), nullable=False),
    sa.Column("origin", sa.String(32), nullable=False),
    sa.Column("related_failure_signature", sa.String(64), nullable=True),
    sa.Column("revision_snapshot", JSONB, nullable=False),
    sa.Column(
        "created_by_user_id",
        sa.Uuid,
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["project_id", "based_on_revision_id"],
        ["jvm_source_revisions.project_id", "jvm_source_revisions.id"],
        ondelete="RESTRICT",
        name="fk_jvm_source_revisions_predecessor_id",
    ),
    sa.ForeignKeyConstraint(
        ["project_id", "based_on_version_number"],
        ["jvm_source_revisions.project_id", "jvm_source_revisions.version_number"],
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "project_id",
        "id",
        name="uq_jvm_source_revisions_project_id",
    ),
    sa.UniqueConstraint(
        "project_id",
        "version_number",
        name="uq_jvm_source_revisions_project_version",
    ),
    sa.UniqueConstraint(
        "project_id",
        "content_hash",
        name="uq_jvm_source_revisions_project_hash",
    ),
    sa.CheckConstraint("version_number > 0", name="positive_version"),
    sa.CheckConstraint(
        "(version_number = 1 AND based_on_revision_id IS NULL "
        "AND based_on_version_number IS NULL) OR "
        "(version_number > 1 AND based_on_revision_id IS NOT NULL "
        "AND based_on_version_number = version_number - 1)",
        name="linear_lineage",
    ),
    sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash"),
    sa.CheckConstraint("source_tree_hash ~ '^[0-9a-f]{64}$'", name="source_tree_hash"),
    sa.CheckConstraint(
        "validation_scope_hash ~ '^[0-9a-f]{64}$'",
        name="validation_scope_hash",
    ),
    sa.CheckConstraint(
        "related_failure_signature IS NULL OR related_failure_signature ~ '^[0-9a-f]{64}$'",
        name="failure_signature",
    ),
)

_PROJECTS = sa.table(
    "projects",
    sa.column("id", sa.Uuid),
    sa.column("owner_user_id", sa.Uuid),
    sa.column("archived_at", sa.DateTime(timezone=True)),
)


class JvmSourceRevisionAppendStatus(StrEnum):
    """Typed append outcomes without cross-owner resource disclosure."""

    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"


@dataclass(frozen=True, slots=True)
class JvmSourceRevisionAppendResult:
    """Append result carrying a revision only for successful outcomes."""

    status: JvmSourceRevisionAppendStatus
    revision: JvmSourceRevision | None

    def __post_init__(self) -> None:
        successful = self.status in {
            JvmSourceRevisionAppendStatus.APPENDED,
            JvmSourceRevisionAppendStatus.ALREADY_PRESENT,
        }
        if successful != (self.revision is not None):
            raise ValueError("Jvm source revision append result shape is inconsistent")


class JvmSourceRevisionRepository(Protocol):
    """Owner-scoped append-only source revision persistence port."""

    async def current(self, *, project_id: UUID) -> JvmSourceRevision | None: ...

    async def history(self, *, project_id: UUID) -> tuple[JvmSourceRevision, ...]: ...

    async def append(self, revision: JvmSourceRevision) -> JvmSourceRevisionAppendResult: ...


class InMemoryJvmSourceRevisionRepository:
    """Deterministic repository used by ordinary tests and application fixtures."""

    def __init__(self, *, owner_user_id: UUID, project_ids: frozenset[UUID]) -> None:
        self._owner_user_id = owner_user_id
        self._project_ids = project_ids
        self._revisions: dict[UUID, list[JvmSourceRevision]] = {}

    async def current(self, *, project_id: UUID) -> JvmSourceRevision | None:
        if project_id not in self._project_ids:
            return None
        history = self._revisions.get(project_id, [])
        return None if not history else history[-1]

    async def history(self, *, project_id: UUID) -> tuple[JvmSourceRevision, ...]:
        if project_id not in self._project_ids:
            return ()
        return tuple(self._revisions.get(project_id, []))

    async def append(self, revision: JvmSourceRevision) -> JvmSourceRevisionAppendResult:
        if (
            revision.project_id not in self._project_ids
            or revision.created_by_user_id != self._owner_user_id
        ):
            return JvmSourceRevisionAppendResult(
                JvmSourceRevisionAppendStatus.PROJECT_NOT_FOUND,
                None,
            )
        history = self._revisions.setdefault(revision.project_id, [])
        existing = next(
            (item for item in history if item.content_hash == revision.content_hash),
            None,
        )
        if existing is not None:
            return JvmSourceRevisionAppendResult(
                JvmSourceRevisionAppendStatus.ALREADY_PRESENT,
                existing,
            )
        if any(item.id == revision.id for item in history):
            return JvmSourceRevisionAppendResult(
                JvmSourceRevisionAppendStatus.VERSION_CONFLICT,
                None,
            )
        current = None if not history else history[-1]
        if not _lineage_matches(current, revision):
            return JvmSourceRevisionAppendResult(
                JvmSourceRevisionAppendStatus.VERSION_CONFLICT,
                None,
            )
        history.append(revision)
        return JvmSourceRevisionAppendResult(
            JvmSourceRevisionAppendStatus.APPENDED,
            revision,
        )


class SqlAlchemyJvmSourceRevisionRepository:
    """PostgreSQL-backed repository bound to one authenticated owner."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def current(self, *, project_id: UUID) -> JvmSourceRevision | None:
        statement = (
            _owned_revision_select(project_id=project_id, owner_user_id=self._owner_user_id)
            .order_by(JVM_SOURCE_REVISIONS.c.version_number.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else jvm_source_revision_from_record(row)

    async def history(self, *, project_id: UUID) -> tuple[JvmSourceRevision, ...]:
        statement = _owned_revision_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(JVM_SOURCE_REVISIONS.c.version_number.asc())
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(jvm_source_revision_from_record(row) for row in rows)

    async def append(self, revision: JvmSourceRevision) -> JvmSourceRevisionAppendResult:
        if revision.created_by_user_id != self._owner_user_id:
            return JvmSourceRevisionAppendResult(
                JvmSourceRevisionAppendStatus.PROJECT_NOT_FOUND,
                None,
            )
        owned_project = await self._session.scalar(
            sa.select(_PROJECTS.c.id)
            .where(
                _PROJECTS.c.id == revision.project_id,
                _PROJECTS.c.owner_user_id == self._owner_user_id,
                _PROJECTS.c.archived_at.is_(None),
            )
            .with_for_update()
        )
        if owned_project is None:
            return JvmSourceRevisionAppendResult(
                JvmSourceRevisionAppendStatus.PROJECT_NOT_FOUND,
                None,
            )
        existing = await self._by_hash(
            project_id=revision.project_id,
            content_hash=revision.content_hash,
        )
        if existing is not None:
            return JvmSourceRevisionAppendResult(
                JvmSourceRevisionAppendStatus.ALREADY_PRESENT,
                existing,
            )
        current = await self._current_for_update(project_id=revision.project_id)
        if not _lineage_matches(current, revision):
            return JvmSourceRevisionAppendResult(
                JvmSourceRevisionAppendStatus.VERSION_CONFLICT,
                None,
            )
        try:
            await self._session.execute(
                sa.insert(JVM_SOURCE_REVISIONS).values(**jvm_source_revision_to_record(revision))
            )
        except IntegrityError:
            return JvmSourceRevisionAppendResult(
                JvmSourceRevisionAppendStatus.VERSION_CONFLICT,
                None,
            )
        return JvmSourceRevisionAppendResult(
            JvmSourceRevisionAppendStatus.APPENDED,
            revision,
        )

    async def _current_for_update(self, *, project_id: UUID) -> JvmSourceRevision | None:
        statement = (
            sa.select(JVM_SOURCE_REVISIONS)
            .where(JVM_SOURCE_REVISIONS.c.project_id == project_id)
            .order_by(JVM_SOURCE_REVISIONS.c.version_number.desc())
            .limit(1)
            .with_for_update()
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else jvm_source_revision_from_record(row)

    async def _by_hash(
        self,
        *,
        project_id: UUID,
        content_hash: str,
    ) -> JvmSourceRevision | None:
        statement = _owned_revision_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(JVM_SOURCE_REVISIONS.c.content_hash == content_hash)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else jvm_source_revision_from_record(row)


class JvmSourceRevisionUnitOfWork(Protocol):
    """Transactional boundary for one or more source revision operations."""

    revisions: JvmSourceRevisionRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlAlchemyJvmSourceRevisionUnitOfWork:
    """Async SQLAlchemy transaction coordinator for Jvm source revisions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session_factory = session_factory
        self._owner_user_id = owner_user_id
        self._session: AsyncSession | None = None
        self.revisions: JvmSourceRevisionRepository

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.revisions = SqlAlchemyJvmSourceRevisionRepository(
            self._session,
            owner_user_id=self._owner_user_id,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_value, traceback
        if self._session is None:
            return
        if exc_type is not None:
            await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        if self._session is None:
            raise RuntimeError("Jvm source revision unit of work is not open")
        await self._session.commit()

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("Jvm source revision unit of work is not open")
        await self._session.rollback()


def jvm_source_revision_to_record(revision: JvmSourceRevision) -> dict[str, object]:
    """Project a revision into immutable relational columns and canonical JSON."""
    return {
        "id": revision.id,
        "project_id": revision.project_id,
        "version_number": revision.version_number,
        "based_on_revision_id": (
            None if revision.based_on is None else revision.based_on.revision_id
        ),
        "based_on_version_number": (
            None if revision.based_on is None else revision.based_on.version_number
        ),
        "content_hash": revision.content_hash,
        "source_tree_hash": revision.source_tree_hash,
        "validation_scope_hash": revision.validation_scope_hash,
        "target": revision.target_selection.target.value,
        "layout": revision.target_selection.layout.value,
        "origin": revision.origin.value,
        "related_failure_signature": revision.related_failure_signature,
        "revision_snapshot": revision.to_snapshot(),
        "created_by_user_id": revision.created_by_user_id,
        "created_at": revision.created_at,
    }


def jvm_source_revision_from_record(record: Mapping[str, object]) -> JvmSourceRevision:
    """Rehydrate and verify a stored revision against every projected column."""
    snapshot = _mapping(record["revision_snapshot"], label="JVM source revision snapshot")
    selection_snapshot = _mapping(
        snapshot["target_selection"],
        label="JVM source target selection",
    )
    based_on_snapshot = snapshot.get("based_on")
    based_on = (
        None
        if based_on_snapshot is None
        else _revision_reference(_mapping(based_on_snapshot, label="JVM source predecessor"))
    )
    files = tuple(
        _source_file(_mapping(item, label="JVM source file"))
        for item in _sequence(snapshot["files"], label="JVM source files")
    )
    provenance = tuple(
        _provenance(_mapping(item, label="JVM source provenance"))
        for item in _sequence(
            snapshot["provenance_references"],
            label="JVM source provenance list",
        )
    )
    revision = JvmSourceRevision(
        id=UUID(str(snapshot["id"])),
        project_id=UUID(str(snapshot["project_id"])),
        created_by_user_id=UUID(str(snapshot["created_by_user_id"])),
        version_number=int(str(snapshot["version_number"])),
        based_on=based_on,
        target_selection=JvmTargetSelection(
            target=ExecutionTarget(str(selection_snapshot["target"])),
            language=JvmImplementationLanguage(str(selection_snapshot["language"])),
            build_system=JvmBuildSystem(str(selection_snapshot["build_system"])),
            layout=JvmProjectLayout(str(selection_snapshot["layout"])),
            jdk_major=int(str(selection_snapshot["jdk_major"])),
        ),
        validation_scope_hash=str(snapshot["validation_scope_hash"]),
        origin=JvmSourceOrigin(str(snapshot["origin"])),
        files=files,
        provenance_references=provenance,
        related_failure_signature=(
            None
            if snapshot.get("related_failure_signature") is None
            else str(snapshot["related_failure_signature"])
        ),
        created_at=datetime.fromisoformat(str(snapshot["created_at"])),
    )
    expected = jvm_source_revision_to_record(revision)
    for key in (
        "id",
        "project_id",
        "version_number",
        "based_on_revision_id",
        "based_on_version_number",
        "content_hash",
        "source_tree_hash",
        "validation_scope_hash",
        "target",
        "layout",
        "origin",
        "related_failure_signature",
        "created_by_user_id",
    ):
        if record[key] != expected[key]:
            raise ValueError(f"persisted JVM source revision {key} is inconsistent")
    return revision


def _owned_revision_select(*, project_id: UUID, owner_user_id: UUID) -> sa.Select:
    return sa.select(JVM_SOURCE_REVISIONS).where(
        JVM_SOURCE_REVISIONS.c.project_id == project_id,
        sa.exists(
            sa.select(sa.literal(1)).where(
                _PROJECTS.c.id == project_id,
                _PROJECTS.c.owner_user_id == owner_user_id,
                _PROJECTS.c.archived_at.is_(None),
            )
        ),
    )


def _lineage_matches(
    current: JvmSourceRevision | None,
    candidate: JvmSourceRevision,
) -> bool:
    if current is None:
        return candidate.version_number == 1 and candidate.based_on is None
    return (
        candidate.version_number == current.version_number + 1
        and candidate.based_on == current.reference
    )


def _revision_reference(value: Mapping[str, object]) -> JvmSourceRevisionReference:
    return JvmSourceRevisionReference(
        revision_id=UUID(str(value["revision_id"])),
        project_id=UUID(str(value["project_id"])),
        version_number=int(str(value["version_number"])),
        content_hash=str(value["content_hash"]),
        source_tree_hash=str(value["source_tree_hash"]),
    )


def _source_file(value: Mapping[str, object]) -> JvmSourceFileEntry:
    return JvmSourceFileEntry(
        normalized_path=str(value["normalized_path"]),
        sha256_digest=str(value["sha256_digest"]),
        size_bytes=int(str(value["size_bytes"])),
        storage_key=str(value["storage_key"]),
        media_type=str(value["media_type"]),
    )


def _provenance(value: Mapping[str, object]) -> JvmSourceProvenanceReference:
    return JvmSourceProvenanceReference(
        kind=JvmSourceProvenanceKind(str(value["kind"])),
        reference_id=str(value["reference_id"]),
        version_number=int(str(value["version_number"])),
        content_hash=str(value["content_hash"]),
    )


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be a sequence")
    return value
