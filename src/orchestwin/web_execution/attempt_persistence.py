"""Owner-scoped append-only persistence for Web execution attempts."""

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

from orchestwin.artifacts.web_sources import WebSourceRevisionReference
from orchestwin.persistence.orm import OrmBase
from orchestwin.web_execution.attempts import (
    WebExecutionAttempt,
    WebExecutionAttemptTrigger,
)
from orchestwin.web_execution.plans import WebExecutionPhase
from orchestwin.web_execution.reports import (
    WebEvidenceReference,
    WebExecutionReport,
    WebFailureCategory,
    WebNormalizedFinding,
    WebPhaseResult,
    WebPhaseResultStatus,
)

WEB_EXECUTION_ATTEMPTS = sa.Table(
    "web_execution_attempts",
    OrmBase.metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column(
        "project_id",
        sa.Uuid,
        sa.ForeignKey("projects.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("attempt_number", sa.Integer, nullable=False),
    sa.Column("previous_attempt_id", sa.Uuid, nullable=True),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("source_revision_id", sa.Uuid, nullable=False),
    sa.Column("source_revision_version", sa.Integer, nullable=False),
    sa.Column("source_revision_content_hash", sa.String(64), nullable=False),
    sa.Column("source_tree_hash", sa.String(64), nullable=False),
    sa.Column("profile_id", sa.String(128), nullable=False),
    sa.Column("profile_version", sa.String(64), nullable=False),
    sa.Column("profile_validation_content_hash", sa.String(64), nullable=False),
    sa.Column("execution_plan_content_hash", sa.String(64), nullable=False),
    sa.Column("policy_content_hash", sa.String(64), nullable=False),
    sa.Column("runner_image_digest", sa.String(64), nullable=False),
    sa.Column("trigger", sa.String(32), nullable=False),
    sa.Column("report_status", sa.String(16), nullable=False),
    sa.Column("attempt_snapshot", JSONB, nullable=False),
    sa.Column(
        "created_by_user_id",
        sa.Uuid,
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(
        ["project_id", "source_revision_id"],
        ["web_source_revisions.project_id", "web_source_revisions.id"],
        ondelete="RESTRICT",
        name="fk_web_execution_attempts_source_revision",
    ),
    sa.ForeignKeyConstraint(
        ["project_id", "previous_attempt_id"],
        ["web_execution_attempts.project_id", "web_execution_attempts.id"],
        ondelete="RESTRICT",
        name="fk_web_execution_attempts_previous",
    ),
    sa.UniqueConstraint("project_id", "id", name="uq_web_execution_attempts_project_id"),
    sa.UniqueConstraint(
        "project_id",
        "attempt_number",
        name="uq_web_execution_attempts_project_number",
    ),
    sa.UniqueConstraint(
        "project_id",
        "content_hash",
        name="uq_web_execution_attempts_project_hash",
    ),
    sa.CheckConstraint("attempt_number > 0", name="positive_attempt"),
    sa.CheckConstraint(
        "(attempt_number = 1 AND previous_attempt_id IS NULL) OR "
        "(attempt_number > 1 AND previous_attempt_id IS NOT NULL)",
        name="linear_lineage",
    ),
    sa.CheckConstraint("content_hash ~ '^[0-9a-f]{64}$'", name="content_hash"),
    sa.CheckConstraint(
        "source_revision_content_hash ~ '^[0-9a-f]{64}$'",
        name="source_revision_hash",
    ),
    sa.CheckConstraint("source_tree_hash ~ '^[0-9a-f]{64}$'", name="source_tree_hash"),
    sa.CheckConstraint(
        "profile_validation_content_hash ~ '^[0-9a-f]{64}$'",
        name="profile_validation_hash",
    ),
    sa.CheckConstraint(
        "execution_plan_content_hash ~ '^[0-9a-f]{64}$'",
        name="execution_plan_hash",
    ),
    sa.CheckConstraint("policy_content_hash ~ '^[0-9a-f]{64}$'", name="policy_hash"),
    sa.CheckConstraint("runner_image_digest ~ '^[0-9a-f]{64}$'", name="runner_hash"),
)

_PROJECTS = sa.table(
    "projects",
    sa.column("id", sa.Uuid),
    sa.column("owner_user_id", sa.Uuid),
    sa.column("archived_at", sa.DateTime(timezone=True)),
)


class WebExecutionAttemptAppendStatus(StrEnum):
    """Typed append outcomes without cross-owner resource disclosure."""

    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    ATTEMPT_CONFLICT = "ATTEMPT_CONFLICT"


@dataclass(frozen=True, slots=True)
class WebExecutionAttemptAppendResult:
    """Append result carrying an attempt only for successful outcomes."""

    status: WebExecutionAttemptAppendStatus
    attempt: WebExecutionAttempt | None

    def __post_init__(self) -> None:
        successful = self.status in {
            WebExecutionAttemptAppendStatus.APPENDED,
            WebExecutionAttemptAppendStatus.ALREADY_PRESENT,
        }
        if successful != (self.attempt is not None):
            raise ValueError("Web execution attempt append result shape is inconsistent")


class WebExecutionAttemptRepository(Protocol):
    """Owner-scoped append-only Web execution persistence port."""

    async def current(self, *, project_id: UUID) -> WebExecutionAttempt | None: ...

    async def history(self, *, project_id: UUID) -> tuple[WebExecutionAttempt, ...]: ...

    async def append(
        self,
        attempt: WebExecutionAttempt,
    ) -> WebExecutionAttemptAppendResult: ...


class InMemoryWebExecutionAttemptRepository:
    """Deterministic execution-attempt repository for ordinary tests."""

    def __init__(self, *, owner_user_id: UUID, project_ids: frozenset[UUID]) -> None:
        self._owner_user_id = owner_user_id
        self._project_ids = project_ids
        self._attempts: dict[UUID, list[WebExecutionAttempt]] = {}

    async def current(self, *, project_id: UUID) -> WebExecutionAttempt | None:
        if project_id not in self._project_ids:
            return None
        history = self._attempts.get(project_id, [])
        return None if not history else history[-1]

    async def history(self, *, project_id: UUID) -> tuple[WebExecutionAttempt, ...]:
        if project_id not in self._project_ids:
            return ()
        return tuple(self._attempts.get(project_id, []))

    async def append(
        self,
        attempt: WebExecutionAttempt,
    ) -> WebExecutionAttemptAppendResult:
        if (
            attempt.project_id not in self._project_ids
            or attempt.created_by_user_id != self._owner_user_id
        ):
            return WebExecutionAttemptAppendResult(
                WebExecutionAttemptAppendStatus.PROJECT_NOT_FOUND,
                None,
            )
        history = self._attempts.setdefault(attempt.project_id, [])
        existing = next(
            (item for item in history if item.content_hash == attempt.content_hash),
            None,
        )
        if existing is not None:
            return WebExecutionAttemptAppendResult(
                WebExecutionAttemptAppendStatus.ALREADY_PRESENT,
                existing,
            )
        if any(item.id == attempt.id for item in history):
            return WebExecutionAttemptAppendResult(
                WebExecutionAttemptAppendStatus.ATTEMPT_CONFLICT,
                None,
            )
        current = None if not history else history[-1]
        if not _lineage_matches(current, attempt):
            return WebExecutionAttemptAppendResult(
                WebExecutionAttemptAppendStatus.ATTEMPT_CONFLICT,
                None,
            )
        history.append(attempt)
        return WebExecutionAttemptAppendResult(
            WebExecutionAttemptAppendStatus.APPENDED,
            attempt,
        )


class SqlAlchemyWebExecutionAttemptRepository:
    """PostgreSQL-backed execution repository bound to one owner."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def current(self, *, project_id: UUID) -> WebExecutionAttempt | None:
        statement = (
            _owned_attempt_select(project_id=project_id, owner_user_id=self._owner_user_id)
            .order_by(WEB_EXECUTION_ATTEMPTS.c.attempt_number.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else web_execution_attempt_from_record(row)

    async def history(self, *, project_id: UUID) -> tuple[WebExecutionAttempt, ...]:
        statement = _owned_attempt_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(WEB_EXECUTION_ATTEMPTS.c.attempt_number.asc())
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(web_execution_attempt_from_record(row) for row in rows)

    async def append(
        self,
        attempt: WebExecutionAttempt,
    ) -> WebExecutionAttemptAppendResult:
        if attempt.created_by_user_id != self._owner_user_id:
            return WebExecutionAttemptAppendResult(
                WebExecutionAttemptAppendStatus.PROJECT_NOT_FOUND,
                None,
            )
        owned_project = await self._session.scalar(
            sa.select(_PROJECTS.c.id)
            .where(
                _PROJECTS.c.id == attempt.project_id,
                _PROJECTS.c.owner_user_id == self._owner_user_id,
                _PROJECTS.c.archived_at.is_(None),
            )
            .with_for_update()
        )
        if owned_project is None:
            return WebExecutionAttemptAppendResult(
                WebExecutionAttemptAppendStatus.PROJECT_NOT_FOUND,
                None,
            )
        existing = await self._by_hash(
            project_id=attempt.project_id,
            content_hash=attempt.content_hash,
        )
        if existing is not None:
            return WebExecutionAttemptAppendResult(
                WebExecutionAttemptAppendStatus.ALREADY_PRESENT,
                existing,
            )
        current = await self._current_for_update(project_id=attempt.project_id)
        if not _lineage_matches(current, attempt):
            return WebExecutionAttemptAppendResult(
                WebExecutionAttemptAppendStatus.ATTEMPT_CONFLICT,
                None,
            )
        try:
            await self._session.execute(
                sa.insert(WEB_EXECUTION_ATTEMPTS).values(**web_execution_attempt_to_record(attempt))
            )
        except IntegrityError:
            return WebExecutionAttemptAppendResult(
                WebExecutionAttemptAppendStatus.ATTEMPT_CONFLICT,
                None,
            )
        return WebExecutionAttemptAppendResult(
            WebExecutionAttemptAppendStatus.APPENDED,
            attempt,
        )

    async def _current_for_update(self, *, project_id: UUID) -> WebExecutionAttempt | None:
        statement = (
            sa.select(WEB_EXECUTION_ATTEMPTS)
            .where(WEB_EXECUTION_ATTEMPTS.c.project_id == project_id)
            .order_by(WEB_EXECUTION_ATTEMPTS.c.attempt_number.desc())
            .limit(1)
            .with_for_update()
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else web_execution_attempt_from_record(row)

    async def _by_hash(
        self,
        *,
        project_id: UUID,
        content_hash: str,
    ) -> WebExecutionAttempt | None:
        statement = _owned_attempt_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(WEB_EXECUTION_ATTEMPTS.c.content_hash == content_hash)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else web_execution_attempt_from_record(row)


class WebExecutionAttemptUnitOfWork(Protocol):
    """Transactional boundary for execution-attempt persistence."""

    attempts: WebExecutionAttemptRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class SqlAlchemyWebExecutionAttemptUnitOfWork:
    """Async SQLAlchemy transaction coordinator for Web execution attempts."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        owner_user_id: UUID,
    ) -> None:
        self._session_factory = session_factory
        self._owner_user_id = owner_user_id
        self._session: AsyncSession | None = None
        self.attempts: WebExecutionAttemptRepository

    async def __aenter__(self) -> Self:
        self._session = self._session_factory()
        self.attempts = SqlAlchemyWebExecutionAttemptRepository(
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
            raise RuntimeError("Web execution attempt unit of work is not open")
        await self._session.commit()

    async def rollback(self) -> None:
        if self._session is None:
            raise RuntimeError("Web execution attempt unit of work is not open")
        await self._session.rollback()


def web_execution_attempt_to_record(attempt: WebExecutionAttempt) -> dict[str, object]:
    """Project an attempt into relational columns and an exact snapshot."""
    return {
        "id": attempt.id,
        "project_id": attempt.project_id,
        "attempt_number": attempt.attempt_number,
        "previous_attempt_id": attempt.previous_attempt_id,
        "content_hash": attempt.content_hash,
        "source_revision_id": attempt.source_revision.revision_id,
        "source_revision_version": attempt.source_revision.version_number,
        "source_revision_content_hash": attempt.source_revision.content_hash,
        "source_tree_hash": attempt.source_revision.source_tree_hash,
        "profile_id": attempt.report.profile_id,
        "profile_version": attempt.report.profile_version,
        "profile_validation_content_hash": attempt.profile_validation_content_hash,
        "execution_plan_content_hash": attempt.execution_plan_content_hash,
        "policy_content_hash": attempt.report.policy_content_hash,
        "runner_image_digest": attempt.report.runner_image_digest,
        "trigger": attempt.trigger.value,
        "report_status": attempt.report.status.value,
        "attempt_snapshot": attempt.to_snapshot(),
        "created_by_user_id": attempt.created_by_user_id,
        "started_at": attempt.started_at,
        "completed_at": attempt.completed_at,
    }


def web_execution_attempt_from_record(record: Mapping[str, object]) -> WebExecutionAttempt:
    """Rehydrate and verify a persisted execution attempt and nested evidence."""
    snapshot = _mapping(record["attempt_snapshot"], label="Web execution attempt snapshot")
    source = _mapping(snapshot["source_revision"], label="Web source revision reference")
    report_snapshot = _mapping(snapshot["report"], label="Web execution report")
    attempt = WebExecutionAttempt(
        id=UUID(str(snapshot["id"])),
        project_id=UUID(str(snapshot["project_id"])),
        created_by_user_id=UUID(str(snapshot["created_by_user_id"])),
        attempt_number=int(str(snapshot["attempt_number"])),
        previous_attempt_id=(
            None
            if snapshot.get("previous_attempt_id") is None
            else UUID(str(snapshot["previous_attempt_id"]))
        ),
        source_revision=WebSourceRevisionReference(
            revision_id=UUID(str(source["revision_id"])),
            project_id=UUID(str(source["project_id"])),
            version_number=int(str(source["version_number"])),
            content_hash=str(source["content_hash"]),
            source_tree_hash=str(source["source_tree_hash"]),
        ),
        profile_validation_content_hash=str(snapshot["profile_validation_content_hash"]),
        execution_plan_content_hash=str(snapshot["execution_plan_content_hash"]),
        trigger=WebExecutionAttemptTrigger(str(snapshot["trigger"])),
        executed_phases=tuple(
            WebExecutionPhase(str(item))
            for item in _sequence(snapshot["executed_phases"], label="Web executed phases")
        ),
        report=_report(report_snapshot),
        started_at=datetime.fromisoformat(str(snapshot["started_at"])),
        completed_at=datetime.fromisoformat(str(snapshot["completed_at"])),
    )
    expected = web_execution_attempt_to_record(attempt)
    for key in (
        "id",
        "project_id",
        "attempt_number",
        "previous_attempt_id",
        "content_hash",
        "source_revision_id",
        "source_revision_version",
        "source_revision_content_hash",
        "source_tree_hash",
        "profile_id",
        "profile_version",
        "profile_validation_content_hash",
        "execution_plan_content_hash",
        "policy_content_hash",
        "runner_image_digest",
        "trigger",
        "report_status",
        "created_by_user_id",
    ):
        if record[key] != expected[key]:
            raise ValueError(f"persisted Web execution attempt {key} is inconsistent")
    return attempt


def _report(value: Mapping[str, object]) -> WebExecutionReport:
    return WebExecutionReport(
        source_revision_content_hash=str(value["source_revision_content_hash"]),
        source_tree_hash=str(value["source_tree_hash"]),
        profile_id=str(value["profile_id"]),
        profile_version=str(value["profile_version"]),
        runner_image_digest=str(value["runner_image_digest"]),
        policy_content_hash=str(value["policy_content_hash"]),
        phase_results=tuple(
            _phase_result(_mapping(item, label="Web phase result"))
            for item in _sequence(value["phase_results"], label="Web phase results")
        ),
    )


def _phase_result(value: Mapping[str, object]) -> WebPhaseResult:
    category = value.get("failure_category")
    return WebPhaseResult(
        phase=WebExecutionPhase(str(value["phase"])),
        status=WebPhaseResultStatus(str(value["status"])),
        command_plan_hashes=tuple(
            str(item)
            for item in _sequence(value["command_plan_hashes"], label="command plan hashes")
        ),
        started_at=_optional_datetime(value.get("started_at")),
        completed_at=_optional_datetime(value.get("completed_at")),
        exit_codes=tuple(
            int(str(item)) for item in _sequence(value["exit_codes"], label="Web exit codes")
        ),
        stdout_refs=_evidence_sequence(value["stdout_refs"]),
        stderr_refs=_evidence_sequence(value["stderr_refs"]),
        artifact_refs=_evidence_sequence(value["artifact_refs"]),
        findings=tuple(
            _finding(_mapping(item, label="Web normalized finding"))
            for item in _sequence(value["findings"], label="Web normalized findings")
        ),
        failure_category=None if category is None else WebFailureCategory(str(category)),
        failure_code=(None if value.get("failure_code") is None else str(value["failure_code"])),
        normalized_summary=str(value["normalized_summary"]),
    )


def _evidence_sequence(value: object) -> tuple[WebEvidenceReference, ...]:
    return tuple(
        WebEvidenceReference(
            storage_key=str(item["storage_key"]),
            sha256_digest=str(item["sha256_digest"]),
            size_bytes=int(str(item["size_bytes"])),
            media_type=str(item["media_type"]),
        )
        for item in (
            _mapping(raw, label="Web evidence reference")
            for raw in _sequence(value, label="Web evidence references")
        )
    )


def _finding(value: Mapping[str, object]) -> WebNormalizedFinding:
    return WebNormalizedFinding(
        code=str(value["code"]),
        message=str(value["message"]),
        source_tool=str(value["source_tool"]),
        location=None if value.get("location") is None else str(value["location"]),
    )


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else datetime.fromisoformat(str(value))


def _owned_attempt_select(*, project_id: UUID, owner_user_id: UUID) -> sa.Select:
    return sa.select(WEB_EXECUTION_ATTEMPTS).where(
        WEB_EXECUTION_ATTEMPTS.c.project_id == project_id,
        sa.exists(
            sa.select(sa.literal(1)).where(
                _PROJECTS.c.id == project_id,
                _PROJECTS.c.owner_user_id == owner_user_id,
                _PROJECTS.c.archived_at.is_(None),
            )
        ),
    )


def _lineage_matches(
    current: WebExecutionAttempt | None,
    candidate: WebExecutionAttempt,
) -> bool:
    if current is None:
        return candidate.attempt_number == 1 and candidate.previous_attempt_id is None
    return (
        candidate.attempt_number == current.attempt_number + 1
        and candidate.previous_attempt_id == current.id
    )


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _sequence(value: object, *, label: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise ValueError(f"{label} must be a sequence")
    return value
