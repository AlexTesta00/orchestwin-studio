"""Owner-scoped append-only persistence for Gate 7 operation requests."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import TracebackType
from typing import Protocol, Self
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.domain import Project
from orchestwin.workflow.high_impact import (
    HighImpactClassificationResult,
    HighImpactOperationRequestVersion,
    high_impact_classification_from_snapshot,
    high_impact_version_from_snapshot,
)
from orchestwin.workflow.repository import HumanGateRepository

HIGH_IMPACT_OPERATION_VERSIONS = sa.Table(
    "high_impact_operation_versions",
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
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column("policy_content_hash", sa.String(64), nullable=False),
    sa.Column("classification", sa.String(40), nullable=False),
    sa.Column("request_snapshot", JSONB, nullable=False),
    sa.Column("classification_snapshot", JSONB, nullable=False),
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
            "high_impact_operation_versions.project_id",
            "high_impact_operation_versions.version_number",
        ],
        ondelete="RESTRICT",
    ),
    sa.UniqueConstraint(
        "project_id",
        "version_number",
        name="uq_high_impact_operation_versions_project_version",
    ),
    sa.UniqueConstraint(
        "project_id",
        "content_hash",
        name="uq_high_impact_operation_versions_project_hash",
    ),
    sa.CheckConstraint("version_number > 0", name="positive_version"),
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
        "policy_content_hash ~ '^[0-9a-f]{64}$'",
        name="policy_content_hash",
    ),
    sa.CheckConstraint(
        "classification IN ("
        "'ALLOWED_WITHOUT_APPROVAL', "
        "'REQUIRES_OWNER_APPROVAL', "
        "'FORBIDDEN_BY_POLICY'"
        ")",
        name="classification",
    ),
)


class HighImpactAppendStatus(StrEnum):
    """Typed outcomes of appending one operation request version."""

    APPENDED = "APPENDED"
    ALREADY_PRESENT = "ALREADY_PRESENT"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    VERSION_CONFLICT = "VERSION_CONFLICT"


@dataclass(frozen=True, slots=True)
class PersistedHighImpactOperation:
    """Exact immutable request version and deterministic classification."""

    version: HighImpactOperationRequestVersion
    classification: HighImpactClassificationResult

    def __post_init__(self) -> None:
        if self.classification.request_reference != self.version.reference:
            raise ValueError("high-impact classification must target its persisted request")

    @property
    def project_id(self) -> UUID:
        return self.version.project_id

    @property
    def version_number(self) -> int:
        return self.version.version_number

    @property
    def content_hash(self) -> str:
        return self.version.content_hash

    def to_snapshot(self) -> dict[str, object]:
        return {
            "version": self.version.to_snapshot(),
            "classification": self.classification.to_snapshot(),
        }


@dataclass(frozen=True, slots=True)
class HighImpactAppendResult:
    """Owner-safe append result with idempotent reuse."""

    status: HighImpactAppendStatus
    operation: PersistedHighImpactOperation | None

    def __post_init__(self) -> None:
        successful = self.status in {
            HighImpactAppendStatus.APPENDED,
            HighImpactAppendStatus.ALREADY_PRESENT,
        }
        if successful != (self.operation is not None):
            raise ValueError("high-impact append result shape is inconsistent")


class HighImpactOperationRepository(Protocol):
    """Owner-scoped append-only operation repository."""

    async def current(self, *, project_id: UUID) -> PersistedHighImpactOperation | None: ...

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PersistedHighImpactOperation, ...]: ...

    async def append(
        self,
        version: HighImpactOperationRequestVersion,
        classification: HighImpactClassificationResult,
    ) -> HighImpactAppendResult: ...


class HighImpactApprovalUnitOfWork(Protocol):
    """Transaction containing operation artifacts and generic human gates."""

    operations: HighImpactOperationRepository
    gates: HumanGateRepository

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class HighImpactApprovalUnitOfWorkFactory(Protocol):
    """Create one owner-scoped Gate 7 transaction."""

    def __call__(self, *, owner_user_id: UUID) -> HighImpactApprovalUnitOfWork: ...


class SqlAlchemyHighImpactOperationRepository:
    """PostgreSQL-backed owner-scoped high-impact operation repository."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    async def current(self, *, project_id: UUID) -> PersistedHighImpactOperation | None:
        statement = (
            _owned_select(project_id=project_id, owner_user_id=self._owner_user_id)
            .order_by(HIGH_IMPACT_OPERATION_VERSIONS.c.version_number.desc())
            .limit(1)
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else persisted_high_impact_from_record(row)

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PersistedHighImpactOperation, ...]:
        statement = _owned_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).order_by(HIGH_IMPACT_OPERATION_VERSIONS.c.version_number.asc())
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(persisted_high_impact_from_record(row) for row in rows)

    async def append(
        self,
        version: HighImpactOperationRequestVersion,
        classification: HighImpactClassificationResult,
    ) -> HighImpactAppendResult:
        operation = PersistedHighImpactOperation(version, classification)
        if version.created_by_user_id != self._owner_user_id:
            return HighImpactAppendResult(HighImpactAppendStatus.PROJECT_NOT_FOUND, None)

        projects = sa.table(
            "projects",
            sa.column("id"),
            sa.column("owner_user_id"),
            sa.column("archived_at"),
        )
        owned_project_id = await self._session.scalar(
            sa.select(projects.c.id)
            .where(
                projects.c.id == version.project_id,
                projects.c.owner_user_id == self._owner_user_id,
                projects.c.archived_at.is_(None),
            )
            .with_for_update()
        )
        if owned_project_id is None:
            return HighImpactAppendResult(HighImpactAppendStatus.PROJECT_NOT_FOUND, None)

        existing = await self._by_hash(
            project_id=version.project_id,
            content_hash=version.content_hash,
        )
        if existing is not None:
            return HighImpactAppendResult(HighImpactAppendStatus.ALREADY_PRESENT, existing)

        current = await self._current_for_update(project_id=version.project_id)
        expected_number = 1 if current is None else current.version_number + 1
        expected_base = None if current is None else current.version_number
        if (
            version.version_number != expected_number
            or version.based_on_version_number != expected_base
        ):
            return HighImpactAppendResult(HighImpactAppendStatus.VERSION_CONFLICT, None)

        try:
            await self._session.execute(
                sa.insert(HIGH_IMPACT_OPERATION_VERSIONS).values(**high_impact_to_record(operation))
            )
        except IntegrityError:
            return HighImpactAppendResult(HighImpactAppendStatus.VERSION_CONFLICT, None)
        return HighImpactAppendResult(HighImpactAppendStatus.APPENDED, operation)

    async def _current_for_update(
        self,
        *,
        project_id: UUID,
    ) -> PersistedHighImpactOperation | None:
        statement = (
            _owned_select(project_id=project_id, owner_user_id=self._owner_user_id)
            .order_by(HIGH_IMPACT_OPERATION_VERSIONS.c.version_number.desc())
            .limit(1)
            .with_for_update()
        )
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else persisted_high_impact_from_record(row)

    async def _by_hash(
        self,
        *,
        project_id: UUID,
        content_hash: str,
    ) -> PersistedHighImpactOperation | None:
        statement = _owned_select(
            project_id=project_id,
            owner_user_id=self._owner_user_id,
        ).where(HIGH_IMPACT_OPERATION_VERSIONS.c.content_hash == content_hash)
        row = (await self._session.execute(statement)).mappings().one_or_none()
        return None if row is None else persisted_high_impact_from_record(row)


class SqlAlchemyHighImpactApprovalUnitOfWork:
    """SQLAlchemy transaction coordinator for Gate 7."""

    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._completed = False
        self.operations = SqlAlchemyHighImpactOperationRepository(
            session,
            owner_user_id=owner_user_id,
        )
        from orchestwin.workflow.persistence.repositories import (
            SqlAlchemyHumanGateRepository,
        )

        self.gates = SqlAlchemyHumanGateRepository(session)

    async def __aenter__(self) -> SqlAlchemyHighImpactApprovalUnitOfWork:
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
        await self._session.close()

    async def commit(self) -> None:
        await self._session.commit()
        self._completed = True

    async def rollback(self) -> None:
        await self._session.rollback()
        self._completed = True


class SqlAlchemyHighImpactApprovalUnitOfWorkFactory:
    """Create owner-scoped Gate 7 Units of Work with fresh sessions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> SqlAlchemyHighImpactApprovalUnitOfWork:
        return SqlAlchemyHighImpactApprovalUnitOfWork(
            self._session_factory(),
            owner_user_id=owner_user_id,
        )


class InMemoryHighImpactOperationRepository:
    """Deterministic owner-scoped adapter for service tests."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        projects: Mapping[UUID, Project],
        shared_versions: dict[UUID, list[PersistedHighImpactOperation]] | None = None,
    ) -> None:
        self._owner_user_id = owner_user_id
        self._projects = dict(projects)
        self._versions = shared_versions if shared_versions is not None else {}

    async def current(self, *, project_id: UUID) -> PersistedHighImpactOperation | None:
        if not self._is_owned(project_id):
            return None
        versions = self._versions.get(project_id, [])
        return None if not versions else versions[-1]

    async def history(
        self,
        *,
        project_id: UUID,
    ) -> tuple[PersistedHighImpactOperation, ...]:
        if not self._is_owned(project_id):
            return ()
        return tuple(self._versions.get(project_id, []))

    async def append(
        self,
        version: HighImpactOperationRequestVersion,
        classification: HighImpactClassificationResult,
    ) -> HighImpactAppendResult:
        operation = PersistedHighImpactOperation(version, classification)
        if not self._is_owned(version.project_id) or (
            version.created_by_user_id != self._owner_user_id
        ):
            return HighImpactAppendResult(HighImpactAppendStatus.PROJECT_NOT_FOUND, None)
        versions = self._versions.setdefault(version.project_id, [])
        existing = next(
            (item for item in versions if item.content_hash == version.content_hash),
            None,
        )
        if existing is not None:
            return HighImpactAppendResult(HighImpactAppendStatus.ALREADY_PRESENT, existing)
        current = None if not versions else versions[-1]
        expected_number = 1 if current is None else current.version_number + 1
        expected_base = None if current is None else current.version_number
        if (
            version.version_number != expected_number
            or version.based_on_version_number != expected_base
        ):
            return HighImpactAppendResult(HighImpactAppendStatus.VERSION_CONFLICT, None)
        versions.append(operation)
        return HighImpactAppendResult(HighImpactAppendStatus.APPENDED, operation)

    def _is_owned(self, project_id: UUID) -> bool:
        project = self._projects.get(project_id)
        return (
            project is not None
            and project.owner_user_id == self._owner_user_id
            and project.archived_at is None
        )


def high_impact_to_record(operation: PersistedHighImpactOperation) -> dict[str, object]:
    """Project one exact operation into immutable database columns."""
    version = operation.version
    return {
        "id": version.id,
        "project_id": version.project_id,
        "version_number": version.version_number,
        "based_on_version_number": version.based_on_version_number,
        "content_hash": version.content_hash,
        "policy_content_hash": operation.classification.policy_content_hash,
        "classification": operation.classification.classification.value,
        "request_snapshot": version.to_snapshot(),
        "classification_snapshot": operation.classification.to_snapshot(),
        "created_by_user_id": version.created_by_user_id,
        "created_at": version.created_at,
    }


def persisted_high_impact_from_record(
    record: Mapping[str, object],
) -> PersistedHighImpactOperation:
    """Validate canonical snapshots before returning a persisted operation."""
    version = high_impact_version_from_snapshot(record.get("request_snapshot"))
    classification = high_impact_classification_from_snapshot(record.get("classification_snapshot"))
    if record.get("id") != version.id or record.get("project_id") != version.project_id:
        raise ValueError("persisted high-impact identity projection is inconsistent")
    if record.get("version_number") != version.version_number:
        raise ValueError("persisted high-impact version projection is inconsistent")
    if record.get("content_hash") != version.content_hash:
        raise ValueError("persisted high-impact hash projection is inconsistent")
    if record.get("policy_content_hash") != classification.policy_content_hash:
        raise ValueError("persisted high-impact policy projection is inconsistent")
    if record.get("classification") != classification.classification.value:
        raise ValueError("persisted high-impact classification projection is inconsistent")
    return PersistedHighImpactOperation(version, classification)


def _owned_select(
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
        sa.select(HIGH_IMPACT_OPERATION_VERSIONS)
        .select_from(
            HIGH_IMPACT_OPERATION_VERSIONS.join(
                projects,
                projects.c.id == HIGH_IMPACT_OPERATION_VERSIONS.c.project_id,
            )
        )
        .where(
            HIGH_IMPACT_OPERATION_VERSIONS.c.project_id == project_id,
            projects.c.owner_user_id == owner_user_id,
            projects.c.archived_at.is_(None),
        )
    )


class InMemoryHighImpactGateRepository:
    """Deterministic generic gate repository used by Gate 7 service tests."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        projects: Mapping[UUID, Project],
        gates: dict[UUID, list[object]],
        events: dict[UUID, list[object]],
    ) -> None:
        self._owner_user_id = owner_user_id
        self._projects = dict(projects)
        self._gates = gates
        self._events = events

    async def add_with_event(self, *, gate: object, event: object) -> object:
        from orchestwin.workflow.gates import HumanGate, HumanGateEvent

        if not isinstance(gate, HumanGate) or not isinstance(event, HumanGateEvent):
            raise TypeError("in-memory Gate 7 repository requires gate domain objects")
        if not self._is_owned(gate.project_id) or gate.owner_user_id != self._owner_user_id:
            raise ValueError("Gate 7 project is not owned")
        self._gates.setdefault(gate.project_id, []).append(gate)
        self._events.setdefault(gate.id, []).append(event)
        return gate

    async def get_latest_owned_for_update(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_type: object,
    ) -> object | None:
        from orchestwin.workflow.gates import HumanGateType

        if owner_user_id != self._owner_user_id or not self._is_owned(project_id):
            return None
        if not isinstance(gate_type, HumanGateType):
            raise TypeError("Gate 7 gate type is invalid")
        matches = [
            gate
            for gate in self._gates.get(project_id, [])
            if getattr(gate, "gate_type", None) is gate_type
        ]
        return None if not matches else matches[-1]

    async def save_transition(
        self,
        *,
        previous_gate: object,
        updated_gate: object,
        event: object,
    ) -> object:
        from orchestwin.workflow.gates import HumanGate, HumanGateEvent

        if not isinstance(previous_gate, HumanGate) or not isinstance(updated_gate, HumanGate):
            raise TypeError("in-memory Gate 7 transition requires gate objects")
        if not isinstance(event, HumanGateEvent):
            raise TypeError("in-memory Gate 7 transition requires an event")
        gates = self._gates.get(previous_gate.project_id, [])
        for index, gate in enumerate(gates):
            if getattr(gate, "id", None) == previous_gate.id:
                if gate != previous_gate:
                    raise RuntimeError("human gate changed concurrently")
                gates[index] = updated_gate
                self._events.setdefault(updated_gate.id, []).append(event)
                return updated_gate
        raise RuntimeError("human gate changed concurrently")

    async def list_events_owned(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        gate_id: UUID,
    ) -> tuple[object, ...]:
        if owner_user_id != self._owner_user_id or not self._is_owned(project_id):
            return ()
        gates = self._gates.get(project_id, [])
        if not any(getattr(gate, "id", None) == gate_id for gate in gates):
            return ()
        return tuple(self._events.get(gate_id, []))

    def _is_owned(self, project_id: UUID) -> bool:
        project = self._projects.get(project_id)
        return (
            project is not None
            and project.owner_user_id == self._owner_user_id
            and project.archived_at is None
        )


class InMemoryHighImpactApprovalUnitOfWork:
    """No-op transaction around shared in-memory Gate 7 state."""

    def __init__(
        self,
        *,
        owner_user_id: UUID,
        projects: Mapping[UUID, Project],
        versions: dict[UUID, list[PersistedHighImpactOperation]],
        gates: dict[UUID, list[object]],
        events: dict[UUID, list[object]],
    ) -> None:
        self.operations = InMemoryHighImpactOperationRepository(
            owner_user_id=owner_user_id,
            projects=projects,
            shared_versions=versions,
        )
        self.gates = InMemoryHighImpactGateRepository(
            owner_user_id=owner_user_id,
            projects=projects,
            gates=gates,
            events=events,
        )

    async def __aenter__(self) -> InMemoryHighImpactApprovalUnitOfWork:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del exc_type, exc_value, traceback

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


class InMemoryHighImpactApprovalUnitOfWorkFactory:
    """Share deterministic Gate 7 state across owner-scoped Units of Work."""

    def __init__(self, *, projects: Mapping[UUID, Project]) -> None:
        self._projects = dict(projects)
        self._versions: dict[UUID, list[PersistedHighImpactOperation]] = {}
        self._gates: dict[UUID, list[object]] = {}
        self._events: dict[UUID, list[object]] = {}

    def __call__(
        self,
        *,
        owner_user_id: UUID,
    ) -> InMemoryHighImpactApprovalUnitOfWork:
        return InMemoryHighImpactApprovalUnitOfWork(
            owner_user_id=owner_user_id,
            projects=self._projects,
            versions=self._versions,
            gates=self._gates,
            events=self._events,
        )
