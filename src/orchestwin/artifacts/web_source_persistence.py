"""Owner-scoped append-only persistence for immutable Web source revisions."""

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

from orchestwin.artifacts.web_sources import (
    WebSourceFileEntry,
    WebSourceOrigin,
    WebSourceProvenanceKind,
    WebSourceProvenanceReference,
    WebSourceRevision,
    WebSourceRevisionReference,
)
from orchestwin.persistence.orm import OrmBase
from orchestwin.sandbox.execution_profiles import ExecutionTarget
from orchestwin.web_execution.targets import (
    WebImplementationLanguage,
    WebLanguageConfiguration,
    WebProjectLayout,
    WebTargetSelection,
)

WEB_SOURCE_REVISIONS = sa.Table(
    "web_source_revisions",
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
        ["web_source_revisions.project_id", "web_source_revisions.id"],
        ondelete="RESTRICT",
        name="fk_web_source_revisions_predecessor_id",
    ),
    sa.ForeignKeyConstraint(
        ["project_id", "based_on_version_number"],
        ["web_source_revisions.project_id", "web_source_revisions.version_number"],
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "project_id",
        "id",
        name="uq_web_source_revisions_project_id",
    ),
    sa.UniqueConstraint(
        "project_id",
        "version_number",
        name="uq_web_source_revisions_project_version",
    ),
    sa.UniqueConstraint(
        "project_id",
        "content_hash",
        name="uq_web_source_revisions_project_hash",
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


class WebSourceRevisionAppendStatus(StrEnum):
    """Typed append outcomes without cross-owner resource disclosure."""

    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"


@dataclass(frozen=True, slots=True)
class WebSourceRevisionAppendResult:
    """Append result carrying a revision only for successful outcomes."""

    status: WebSourceRevisionAppendStatus
    revision: WebSourceRevision | None

    def __post_init__(self) -> None:
        successful = self.status in {
            WebSourceRevisionAppendStatus.APPENDED,
            WebSourceRevisionAppendStatus.ALREADY_PRESENT,
        }
        if successful != (self.revision is not None):
            raise ValueError("Web source revision append result shape is inconsistent")


class WebSourceRevisionRepository(Protocol):
    """Owner-scoped append-only source revision persistence port."""

    async def current(self, *, project_id: UUID) -> WebSourceRevision | None: ...

    async def history(self, *, project_id: UUID) -> tuple[WebSourceRevision, ...]: ...

    async def append(self, revision: WebSourceRevision) -> WebSourceRevisionAppendResult: ...


class InMemoryWebSourceRevisionRepository:
    """Deterministic repository used by ordinary tests and application fixtures."""

    def __init__(self, *, owner_user_id: UUID, project_ids: frozenset[UUID]) -> None:
        self._owner_user_id = owner_user_id
        self._project_ids = project_ids
        self._revisions: dict[UUID, list[WebSourceRevision]] = {}

    async def current(self, *, project_id: UUID) -> WebSourceRevision | None:
        if project_id not in self._project_ids:
            return None
        history = self._revisions.get(project_id, [])
        return None if not history else history[-1]

    async def history(self, *, project_id: UUID) -> tuple[WebSourceRevision, ...]:
        if project_id not in self._project_ids:
            return ()
        return tuple(self._revisions.get(project_id, []))

    async def append(self, revision: WebSourceRevision) -> WebSourceRevisionAppendResult:
        if (
            revision.project_id not in self._project_ids
            or revision.created_by_user_id != self._owner_user_id
        ):
            return WebSourceRevisionAppendResult(
                WebSourceRevisionAppendStatus.PROJECT_NOT_FOUND,
                None,
            )
        history = self._revisions.setdefault(revision.project_id, [])
        existing = next(
            (item for item in history if item.content_hash == revision.content_hash),
            None,
        )
        if existing is not None:
            return WebSourceRevisionAppendResult(
                WebSourceRevisionAppendStatus.ALREADY_PRESENT,
                existing,
            )
        if any(item.id == revision.id for item in history):
            return WebSourceRevisionAppendResult(
                WebSourceRevisionAppendStatus.VERSION_CONFLICT,
                None,
            )
        current = None if not history else history[-1]
        if not _lineage_matches(current, revision):
            return WebSourceRevisionAppendResult(
                WebSourceRevisionAppendStatus.VERSION_CONFLICT,
                None,
            )
        history.append(revision)
        return WebSourceRevisionAppendResult(
            WebSourceRevisionAppendStatus.APPENDED,
            revision,
        )


class SqlAlchemyWebSourceRevisionRepository:
    """PostgreSQL-backed repository bound to one authenticated owner."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def current(self, *, project_id: UUID) -> WebSourceRevision | None:
        statement = (
            _owned_revision_select(project_id=project_id, owner_user_id=self._owner_user_id)
            .order_by(WEB_SOURCE_REVISIONS.c.version_number.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else web_source_revision_from_record(row)

    async def history(self, *, project_id: UUID) -> tuple[WebSourceRevision, ...]:
        statement = _owned_revision_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(WEB_SOURCE_REVISIONS.c.version_number.asc())
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(web_source_revision_from_record(row) for row in rows)

    async def append(self, revision: WebSourceRevision) -> WebSourceRevisionAppendResult:
        if revision.created_by_user_id != self._owner_user_id:
            return WebSourceRevisionAppendResult(
                WebSourceRevisionAppendStatus.PROJECT_NOT_FOUND,
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
            return WebSourceRevisionAppendResult(
                WebSourceRevisionAppendStatus.PROJECT_NOT_FOUND,
                None,
            )
        existing = await self._by_hash(
            project_id=revision.project_id,
            content_hash=revision.content_hash,
        )
        if existing is not None:
            return WebSourceRevisionAppendResult(
                WebSourceRevisionAppendStatus.ALREADY_PRESENT,
                existing,
            )
        current = await self._current_for_update(project_id=revision.project_id)
        if not _lineage_matches(current, revision):
            return WebSourceRevisionAppendResult(
                WebSourceRevisionAppendStatus.VERSION_CONFLICT,
                None,
            )
        try:
            await self._session.execute(
                sa.insert(WEB_SOURCE_REVISIONS).values(**web_source_revision_to_record(revision))
            )
        except IntegrityError:
            return WebSourceRevisionAppendResult(
                WebSourceRevisionAppendStatus.VERSION_CONFLICT,
                None,
            )
        return WebSourceRevisionAppendResult(
            WebSourceRevisionAppendStatus.APPENDED,
            revision,
        )

    async def _current_for_update(self, *, project_id: UUID) -> WebSourceRevision | None:
        statement = (
            sa.select(WEB_SOURCE_REVISIONS)
            .where(WEB_SOURCE_REVISIONS.c.project_id == project_id)
            .order_by(WEB_SOURCE_REVISIONS.c.version_number.desc())
            .limit(1)
            .with_for_update()
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else web_source_revision_from_record(row)

    async def _by_hash(
        self,
        *,
        project_id: UUID,
        content_hash: str,
    ) -> WebSourceRevision | None:
        statement = _owned_revision_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(WEB_SOURCE_REVISIONS.c.content_hash == content_hash)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else web_source_revision_from_record(row)


class WebSourceRevisionUnitOfWork(Protocol):
    """Transactional boundary for one or more source revision operations."""

    revisions: WebSourceRevisionRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlAlchemyWebSourceRevisionUnitOfWork:
    """Async SQLAlchemy transaction coordinator for Web source revisions."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session_factory = session_factory
        self._owner_user_id = owner_user_id
        self._session: AsyncSession | None = None
        self.revisions: WebSourceRevisionRepository

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.revisions = SqlAlchemyWebSourceRevisionRepository(
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
            raise RuntimeError("Web source revision unit of work is not open")
        await self._session.commit()

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("Web source revision unit of work is not open")
        await self._session.rollback()


def web_source_revision_to_record(revision: WebSourceRevision) -> dict[str, object]:
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


def web_source_revision_from_record(record: Mapping[str, object]) -> WebSourceRevision:
    """Rehydrate and verify a stored revision against every projected column."""
    snapshot = _mapping(record["revision_snapshot"], label="Web source revision snapshot")
    selection_snapshot = _mapping(
        snapshot["target_selection"],
        label="Web source target selection",
    )
    language_snapshot = _mapping(
        selection_snapshot["language_configuration"],
        label="Web source language configuration",
    )
    based_on_snapshot = snapshot.get("based_on")
    based_on = (
        None
        if based_on_snapshot is None
        else _revision_reference(_mapping(based_on_snapshot, label="Web source predecessor"))
    )
    files = tuple(
        _source_file(_mapping(item, label="Web source file"))
        for item in _sequence(snapshot["files"], label="Web source files")
    )
    provenance = tuple(
        _provenance(_mapping(item, label="Web source provenance"))
        for item in _sequence(
            snapshot["provenance_references"],
            label="Web source provenance list",
        )
    )
    frontend_value = language_snapshot.get("frontend")
    backend_value = language_snapshot.get("backend")
    revision = WebSourceRevision(
        id=UUID(str(snapshot["id"])),
        project_id=UUID(str(snapshot["project_id"])),
        created_by_user_id=UUID(str(snapshot["created_by_user_id"])),
        version_number=int(str(snapshot["version_number"])),
        based_on=based_on,
        target_selection=WebTargetSelection(
            target=ExecutionTarget(str(selection_snapshot["target"])),
            language_configuration=WebLanguageConfiguration(
                frontend=(
                    None
                    if frontend_value is None
                    else WebImplementationLanguage(str(frontend_value))
                ),
                backend=(
                    None if backend_value is None else WebImplementationLanguage(str(backend_value))
                ),
            ),
            layout=WebProjectLayout(str(selection_snapshot["layout"])),
        ),
        validation_scope_hash=str(snapshot["validation_scope_hash"]),
        origin=WebSourceOrigin(str(snapshot["origin"])),
        files=files,
        provenance_references=provenance,
        related_failure_signature=(
            None
            if snapshot.get("related_failure_signature") is None
            else str(snapshot["related_failure_signature"])
        ),
        created_at=datetime.fromisoformat(str(snapshot["created_at"])),
    )
    expected = web_source_revision_to_record(revision)
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
            raise ValueError(f"persisted Web source revision {key} is inconsistent")
    return revision


def _owned_revision_select(*, project_id: UUID, owner_user_id: UUID) -> sa.Select:
    return sa.select(WEB_SOURCE_REVISIONS).where(
        WEB_SOURCE_REVISIONS.c.project_id == project_id,
        sa.exists(
            sa.select(sa.literal(1)).where(
                _PROJECTS.c.id == project_id,
                _PROJECTS.c.owner_user_id == owner_user_id,
                _PROJECTS.c.archived_at.is_(None),
            )
        ),
    )


def _lineage_matches(
    current: WebSourceRevision | None,
    candidate: WebSourceRevision,
) -> bool:
    if current is None:
        return candidate.version_number == 1 and candidate.based_on is None
    return (
        candidate.version_number == current.version_number + 1
        and candidate.based_on == current.reference
    )


def _revision_reference(value: Mapping[str, object]) -> WebSourceRevisionReference:
    return WebSourceRevisionReference(
        revision_id=UUID(str(value["revision_id"])),
        project_id=UUID(str(value["project_id"])),
        version_number=int(str(value["version_number"])),
        content_hash=str(value["content_hash"]),
        source_tree_hash=str(value["source_tree_hash"]),
    )


def _source_file(value: Mapping[str, object]) -> WebSourceFileEntry:
    return WebSourceFileEntry(
        normalized_path=str(value["normalized_path"]),
        sha256_digest=str(value["sha256_digest"]),
        size_bytes=int(str(value["size_bytes"])),
        storage_key=str(value["storage_key"]),
        media_type=str(value["media_type"]),
    )


def _provenance(value: Mapping[str, object]) -> WebSourceProvenanceReference:
    return WebSourceProvenanceReference(
        kind=WebSourceProvenanceKind(str(value["kind"])),
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
