"""PostgreSQL owner-scoped Web operation claims and immutable approval inputs."""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.artifacts.web_source_persistence import WEB_SOURCE_REVISIONS
from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.web_execution.operation_governance import (
    WebGovernedOperation,
    WebOperationError,
    WebOperationKind,
    WebOperationScope,
    WebOperationState,
)
from orchestwin.web_execution.static_browser_jobs import content_hash
from orchestwin.workflow.gates import HumanGateType
from orchestwin.workflow.persistence.models import HumanGateRecord
from orchestwin.workflow.persistence.repositories import (
    SqlAlchemyHumanGateRepository,
    gate_record_to_domain,
    owned_gates_statement,
)

WEB_GOVERNED_OPERATIONS = sa.Table(
    "web_governed_operations",
    OrmBase.metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column(
        "project_id", sa.Uuid, sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    ),
    sa.Column(
        "owner_user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    ),
    sa.Column("source_revision_id", sa.Uuid, nullable=False),
    sa.Column("kind", sa.String(16), nullable=False),
    sa.Column("payload_json", sa.Text, nullable=False),
    sa.Column("payload_content_hash", sa.String(64), nullable=False),
    sa.Column("content_hash", sa.String(64), nullable=False),
    sa.Column(
        "gate_id",
        sa.Uuid,
        sa.ForeignKey("human_gates.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("result_json", sa.Text),
    sa.Column("result_content_hash", sa.String(64)),
    sa.ForeignKeyConstraint(
        ["project_id", "source_revision_id"],
        ["web_source_revisions.project_id", "web_source_revisions.id"],
        ondelete="RESTRICT",
        name="fk_web_governed_operations_source",
    ),
    sa.CheckConstraint("kind IN ('EXECUTION', 'REPAIR')", name="kind_valid"),
    sa.CheckConstraint(
        "state IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')", name="state_valid"
    ),
    sa.CheckConstraint(
        "content_hash ~ '^[0-9a-f]{64}$' AND payload_content_hash ~ '^[0-9a-f]{64}$'",
        name="hashes_valid",
    ),
    sa.CheckConstraint("octet_length(payload_json) BETWEEN 1 AND 4194304", name="payload_bounded"),
    sa.CheckConstraint("jsonb_typeof(payload_json::jsonb) = 'object'", name="payload_object"),
    sa.CheckConstraint(
        "result_json IS NULL OR (octet_length(result_json) BETWEEN 1 AND 4194304 AND jsonb_typeof(result_json::jsonb) = 'object')",
        name="result_bounded",
    ),
    sa.CheckConstraint(
        "result_content_hash IS NULL OR result_content_hash ~ '^[0-9a-f]{64}$'",
        name="result_hash_valid",
    ),
    sa.CheckConstraint("started_at IS NULL OR started_at >= created_at", name="started_order"),
    sa.CheckConstraint(
        "finished_at IS NULL OR finished_at >= COALESCE(started_at, created_at)",
        name="finished_order",
    ),
    sa.CheckConstraint(
        "(state = 'PENDING' AND started_at IS NULL AND finished_at IS NULL AND result_json IS NULL AND result_content_hash IS NULL) OR "
        "(state = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND result_json IS NULL AND result_content_hash IS NULL) OR "
        "(state = 'COMPLETED' AND started_at IS NOT NULL AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_content_hash IS NOT NULL) OR "
        "(state = 'FAILED' AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_content_hash IS NOT NULL AND "
        "(started_at IS NOT NULL OR result_json::jsonb = jsonb_build_object('failure_code', 'WEB_OPERATION_CANCELLED', 'execution_started', false)))",
        name="lifecycle_valid",
    ),
    sa.Index("ix_web_governed_operations_project_created", "project_id", "created_at"),
    sa.Index(
        "uq_web_governed_operations_project_running",
        "project_id",
        unique=True,
        postgresql_where=sa.text("state = 'RUNNING'"),
    ),
)

_MUTABLE = {"state", "started_at", "finished_at", "result_json", "result_content_hash"}


def record_values(operation: WebGovernedOperation) -> dict:
    return {
        "id": operation.id,
        "project_id": operation.project_id,
        "owner_user_id": operation.owner_user_id,
        "source_revision_id": operation.source_revision_id,
        "kind": operation.kind.value,
        "payload_json": operation.payload_json,
        "payload_content_hash": operation.payload_content_hash,
        "content_hash": operation.content_hash,
        "gate_id": operation.gate_id,
        "state": operation.state.value,
        "created_at": operation.created_at,
        "started_at": operation.started_at,
        "finished_at": operation.finished_at,
        "result_json": operation.result_json,
        "result_content_hash": None if operation.result is None else content_hash(operation.result),
    }


def record_from_row(row) -> WebGovernedOperation:
    try:
        operation = WebGovernedOperation(
            id=row["id"],
            project_id=row["project_id"],
            owner_user_id=row["owner_user_id"],
            source_revision_id=row["source_revision_id"],
            kind=WebOperationKind(row["kind"]),
            payload_json=row["payload_json"],
            gate_id=row["gate_id"],
            state=WebOperationState(row["state"]),
            created_at=row["created_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            result_json=row["result_json"],
        )
        if any(row[name] != value for name, value in record_values(operation).items()):
            raise ValueError
        return operation
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError):
        raise WebOperationError("WEB_OPERATION_STORAGE_INTEGRITY_FAILED") from None


class SqlAlchemyWebOperationScope(WebOperationScope):
    def __init__(self, session: AsyncSession, owner_user_id: UUID, project_id: UUID):
        self.session, self.owner_user_id, self.project_id = session, owner_user_id, project_id
        self.gates = SqlAlchemyHumanGateRepository(session)

    def _owned(self):
        table = WEB_GOVERNED_OPERATIONS
        return (
            sa.select(table)
            .join(ProjectRecord, ProjectRecord.id == table.c.project_id)
            .where(
                ProjectRecord.id == self.project_id,
                ProjectRecord.owner_user_id == self.owner_user_id,
                ProjectRecord.archived_at.is_(None),
                table.c.project_id == self.project_id,
                table.c.owner_user_id == self.owner_user_id,
            )
        )

    async def get(self, operation_id):
        row = (
            (
                await self.session.execute(
                    self._owned().where(WEB_GOVERNED_OPERATIONS.c.id == operation_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else record_from_row(row)

    async def history(self, kind=None):
        query = self._owned()
        if kind is not None:
            query = query.where(WEB_GOVERNED_OPERATIONS.c.kind == WebOperationKind(kind).value)
        rows = (
            (
                await self.session.execute(
                    query.order_by(
                        WEB_GOVERNED_OPERATIONS.c.created_at, WEB_GOVERNED_OPERATIONS.c.id
                    )
                )
            )
            .mappings()
            .all()
        )
        return tuple(record_from_row(row) for row in rows)

    async def source_owned(self, source_revision_id):
        return (
            await self.session.scalar(
                sa.select(WEB_SOURCE_REVISIONS.c.id).where(
                    WEB_SOURCE_REVISIONS.c.id == source_revision_id,
                    WEB_SOURCE_REVISIONS.c.project_id == self.project_id,
                    WEB_SOURCE_REVISIONS.c.created_by_user_id == self.owner_user_id,
                )
            )
            is not None
        )

    async def latest_gate(self):
        return await self.gates.get_latest_owned_for_update(
            project_id=self.project_id,
            owner_user_id=self.owner_user_id,
            gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
        )

    async def load_gate(self, gate_id):
        row = await self.session.scalar(
            owned_gates_statement(
                project_id=self.project_id,
                owner_user_id=self.owner_user_id,
                gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
            ).where(HumanGateRecord.id == gate_id)
        )
        return None if row is None else gate_record_to_domain(row)

    async def add_gate(self, gate, event):
        await self.gates.add_with_event(gate=gate, event=event)

    async def save_gate(self, previous, updated, event):
        await self.gates.save_transition(previous_gate=previous, updated_gate=updated, event=event)

    async def insert(self, operation):
        if operation.owner_user_id != self.owner_user_id or operation.project_id != self.project_id:
            raise WebOperationError("WEB_OPERATION_NOT_FOUND", 404)
        await self.session.execute(
            sa.insert(WEB_GOVERNED_OPERATIONS).values(**record_values(operation))
        )

    async def update(self, previous, updated):
        old, new = record_values(previous), record_values(updated)
        if previous.project_id != self.project_id or previous.owner_user_id != self.owner_user_id:
            raise WebOperationError("WEB_OPERATION_NOT_FOUND", 404)
        if any(old[key] != new[key] for key in old.keys() - _MUTABLE):
            raise WebOperationError("WEB_OPERATION_INPUT_IMMUTABLE")
        table = WEB_GOVERNED_OPERATIONS
        result = await self.session.execute(
            sa.update(table)
            .where(
                table.c.id == previous.id,
                table.c.project_id == self.project_id,
                table.c.owner_user_id == self.owner_user_id,
                table.c.content_hash == previous.content_hash,
                table.c.state == previous.state.value,
                table.c.started_at.is_not_distinct_from(previous.started_at),
                table.c.finished_at.is_not_distinct_from(previous.finished_at),
                table.c.result_content_hash.is_not_distinct_from(old["result_content_hash"]),
            )
            .values(**{key: new[key] for key in _MUTABLE})
        )
        if result.rowcount != 1:
            raise WebOperationError("WEB_OPERATION_STATE_CONFLICT")


class SqlAlchemyWebOperationStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session_factory = session_factory

    @asynccontextmanager
    async def scope(self, *, owner_user_id: UUID, project_id: UUID):
        async with self._session_factory() as session, session.begin():
            project = await session.scalar(
                sa.select(ProjectRecord)
                .where(
                    ProjectRecord.id == project_id,
                    ProjectRecord.owner_user_id == owner_user_id,
                    ProjectRecord.archived_at.is_(None),
                )
                .with_for_update()
            )
            if project is None:
                raise WebOperationError("WEB_OPERATION_PROJECT_NOT_FOUND", 404)
            yield SqlAlchemyWebOperationScope(session, owner_user_id, project_id)

    async def create(
        self, *, owner_user_id, project_id, source_revision_id, kind, payload, operation_id=None
    ):
        async with self.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            return await scope.propose(
                source_revision_id=source_revision_id,
                kind=kind,
                payload=payload,
                operation_id=operation_id,
            )

    async def get(self, *, owner_user_id, project_id, operation_id):
        async with self.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            operation = await scope.get(operation_id)
            if operation is None:
                raise WebOperationError("WEB_OPERATION_NOT_FOUND", 404)
            return await scope.snapshot(operation)

    async def history(self, *, owner_user_id, project_id, kind=None):
        async with self.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            return tuple([await scope.snapshot(item) for item in await scope.history(kind=kind)])

    async def decide(
        self,
        *,
        owner_user_id,
        project_id,
        operation_id,
        expected_hash,
        expected_event_sequence,
        action,
        reason=None,
    ):
        async with self.scope(owner_user_id=owner_user_id, project_id=project_id) as scope:
            operation = await scope.get(operation_id)
            if operation is None:
                raise WebOperationError("WEB_OPERATION_NOT_FOUND", 404)
            decided = await scope.decide(
                operation,
                expected_hash=expected_hash,
                expected_event_sequence=expected_event_sequence,
                action=action,
                reason=reason,
            )
            return await scope.snapshot(decided)
