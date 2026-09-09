"""PostgreSQL-backed scope for static inspections; all access is owner/project-bound."""

from __future__ import annotations

from contextlib import asynccontextmanager
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.persistence.orm import OrmBase
from orchestwin.projects.domain import ProjectMode
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.web_execution.static_browser_jobs import canonical_bytes, content_hash
from orchestwin.web_execution.static_inspections import (
    Inspection,
    InspectionError,
    InspectionPlan,
    InspectionState,
    SourceContext,
)
from orchestwin.web_execution.verified_browser_runner import read_json
from orchestwin.workflow.gates import GateArtifactReference, HumanGateStatus, HumanGateType
from orchestwin.workflow.persistence.models import HumanGateRecord
from orchestwin.workflow.persistence.repositories import (
    SqlAlchemyHumanGateRepository,
    gate_record_to_domain,
    owned_gates_statement,
)

STATIC_BROWSER_INSPECTIONS = sa.Table(
    "static_browser_inspections",
    OrmBase.metadata,
    sa.Column("id", sa.Uuid, primary_key=True),
    sa.Column(
        "project_id", sa.Uuid, sa.ForeignKey("projects.id", ondelete="RESTRICT"), nullable=False
    ),
    sa.Column(
        "owner_user_id", sa.Uuid, sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    ),
    sa.Column(
        "source_revision_id",
        sa.Uuid,
        sa.ForeignKey("web_source_revisions.id", ondelete="RESTRICT"),
        nullable=False,
    ),
    sa.Column(
        "gate_id",
        sa.Uuid,
        sa.ForeignKey("human_gates.id", ondelete="RESTRICT"),
        nullable=False,
        unique=True,
    ),
    sa.Column("plan_hash", sa.String(64), nullable=False),
    sa.Column("job_hash", sa.String(64), nullable=False),
    sa.Column("plan_json", sa.Text, nullable=False),
    sa.Column("state", sa.String(16), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("started_at", sa.DateTime(timezone=True)),
    sa.Column("finished_at", sa.DateTime(timezone=True)),
    sa.Column("result_json", sa.Text),
    sa.Column("result_hash", sa.String(64)),
    sa.CheckConstraint(
        "state IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')", name="state_valid"
    ),
    sa.CheckConstraint(
        "plan_hash ~ '^[0-9a-f]{64}$' AND job_hash ~ '^[0-9a-f]{64}$'", name="hashes_valid"
    ),
    sa.CheckConstraint("octet_length(plan_json) BETWEEN 1 AND 5242880", name="plan_size_valid"),
    sa.CheckConstraint(
        "(state = 'PENDING' AND started_at IS NULL AND finished_at IS NULL AND result_json IS NULL AND result_hash IS NULL) OR "
        "(state = 'RUNNING' AND started_at IS NOT NULL AND finished_at IS NULL AND result_json IS NULL AND result_hash IS NULL) OR "
        "(state IN ('COMPLETED', 'FAILED') AND started_at IS NOT NULL AND finished_at IS NOT NULL AND result_json IS NOT NULL AND result_hash IS NOT NULL)",
        name="lifecycle_consistent",
    ),
    sa.CheckConstraint("started_at IS NULL OR started_at >= created_at", name="start_order"),
    sa.CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="finish_order"),
    sa.Index("ix_static_browser_inspections_project_created", "project_id", "created_at"),
)


def record_values(record: Inspection) -> dict[str, object]:
    return {
        "id": record.id,
        "project_id": record.plan.job.project_id,
        "owner_user_id": record.plan.job.owner_user_id,
        "source_revision_id": record.plan.job.revision_id,
        "gate_id": record.gate_id,
        "plan_hash": record.plan.content_hash,
        "job_hash": record.plan.job.content_hash,
        "plan_json": canonical_bytes(record.plan.snapshot()).decode("utf-8"),
        "state": record.state.value,
        "created_at": record.created_at,
        "started_at": record.started_at,
        "finished_at": record.finished_at,
        "result_json": record.result_json,
        "result_hash": None
        if record.result_json is None
        else content_hash(read_json(record.result_json.encode())),
    }


def record_from_row(row) -> Inspection:
    plan = InspectionPlan.from_json(row["plan_json"])
    if (
        row["result_json"] is not None
        and canonical_bytes(read_json(row["result_json"].encode("utf-8"))).decode("utf-8")
        != row["result_json"]
    ):
        raise InspectionError("STATIC_INSPECTION_RESULT_NOT_CANONICAL", 503)
    record = Inspection(
        id=row["id"],
        gate_id=row["gate_id"],
        plan=plan,
        state=InspectionState(row["state"]),
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        result_json=row["result_json"],
    )
    if any(row[name] != value for name, value in record_values(record).items()):
        raise InspectionError("STATIC_INSPECTION_STORAGE_INTEGRITY_FAILED", 503)
    return record


class SqlAlchemyInspectionScope:
    def __init__(self, session: AsyncSession, owner_user_id: UUID, project_id: UUID) -> None:
        self.session = session
        self.owner_user_id = owner_user_id
        self.project_id = project_id
        self.gates = SqlAlchemyHumanGateRepository(session)

    def _owned(self):
        table = STATIC_BROWSER_INSPECTIONS
        return sa.select(table).where(
            table.c.project_id == self.project_id, table.c.owner_user_id == self.owner_user_id
        )

    async def get(self, request_id: UUID) -> Inspection | None:
        row = (
            (
                await self.session.execute(
                    self._owned().where(STATIC_BROWSER_INSPECTIONS.c.id == request_id)
                )
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else record_from_row(row)

    async def history(self) -> tuple[Inspection, ...]:
        rows = (
            (
                await self.session.execute(
                    self._owned().order_by(
                        STATIC_BROWSER_INSPECTIONS.c.created_at, STATIC_BROWSER_INSPECTIONS.c.id
                    )
                )
            )
            .mappings()
            .all()
        )
        return tuple(record_from_row(row) for row in rows)

    async def source_context(self, revision_id: UUID) -> SourceContext:
        # Reuse the existing immutable snapshot decoders and current-version repositories.
        from orchestwin.artifacts.architecture_persistence import (
            SqlAlchemyArchitecturePackageRepository,
        )
        from orchestwin.artifacts.web_source_persistence import (
            SqlAlchemyWebSourceRevisionRepository,
        )

        source = await SqlAlchemyWebSourceRevisionRepository(
            self.session, owner_user_id=self.owner_user_id
        ).current(project_id=self.project_id)
        if (
            source is None
            or source.id != revision_id
            or source.created_by_user_id != self.owner_user_id
        ):
            raise InspectionError("STATIC_INSPECTION_SOURCE_NOT_CURRENT")
        architecture = await SqlAlchemyArchitecturePackageRepository(
            self.session, owner_user_id=self.owner_user_id
        ).get_current_owned_for_update(project_id=self.project_id, owner_user_id=self.owner_user_id)
        gate = await self.gates.get_latest_owned_for_update(
            project_id=self.project_id,
            owner_user_id=self.owner_user_id,
            gate_type=HumanGateType.ARCHITECTURE,
        )
        if architecture is None or gate is None:
            raise InspectionError("STATIC_INSPECTION_ARCHITECTURE_APPROVAL_REQUIRED")
        reference = GateArtifactReference(
            self.project_id,
            HumanGateType.ARCHITECTURE,
            architecture.id,
            architecture.version_number,
            architecture.content_hash,
        )
        if gate.status is not HumanGateStatus.APPROVED or gate.artifact != reference:
            raise InspectionError("STATIC_INSPECTION_ARCHITECTURE_STALE")
        if not any(
            item.kind.value == "ARCHITECTURE"
            and item.reference_id == f"architecture:{architecture.id}"
            and item.version_number == architecture.version_number
            and item.content_hash == architecture.content_hash
            for item in source.provenance_references
        ):
            raise InspectionError("STATIC_INSPECTION_SOURCE_PROVENANCE_STALE")
        return SourceContext(source.to_snapshot(), reference)

    async def latest_gate(self):
        return await self.gates.get_latest_owned_for_update(
            project_id=self.project_id,
            owner_user_id=self.owner_user_id,
            gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
        )

    async def gate(self, gate_id):
        row = await self.session.scalar(
            owned_gates_statement(
                project_id=self.project_id,
                owner_user_id=self.owner_user_id,
                gate_type=HumanGateType.HIGH_IMPACT_OPERATION,
            ).where(HumanGateRecord.id == gate_id)
        )
        if row is None:
            raise InspectionError("STATIC_INSPECTION_GATE_NOT_FOUND", 404)
        return gate_record_to_domain(row)

    async def add_gate(self, gate, event):
        await self.gates.add_with_event(gate=gate, event=event)

    async def save_gate(self, previous, updated, event):
        await self.gates.save_transition(previous_gate=previous, updated_gate=updated, event=event)

    async def insert(self, inspection):
        await self.session.execute(
            sa.insert(STATIC_BROWSER_INSPECTIONS).values(**record_values(inspection))
        )

    async def update(self, previous, updated):
        old = record_values(previous)
        new = record_values(updated)
        mutable = {"state", "started_at", "finished_at", "result_json", "result_hash"}
        if any(old[key] != new[key] for key in old.keys() - mutable):
            raise InspectionError("STATIC_INSPECTION_INPUT_IMMUTABLE")
        table = STATIC_BROWSER_INSPECTIONS
        result = await self.session.execute(
            sa.update(table)
            .where(
                table.c.id == previous.id,
                table.c.project_id == self.project_id,
                table.c.owner_user_id == self.owner_user_id,
                table.c.plan_hash == previous.plan.content_hash,
                table.c.state == previous.state.value,
            )
            .values(**{name: new[name] for name in mutable})
        )
        if result.rowcount != 1:
            raise InspectionError("STATIC_INSPECTION_STATE_CONFLICT")


class SqlAlchemyInspectionStore:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
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
                raise InspectionError("STATIC_INSPECTION_PROJECT_NOT_FOUND", 404)
            if project.mode != ProjectMode.GREENFIELD_GENERATION.value:
                raise InspectionError("STATIC_INSPECTION_REQUIRES_GREENFIELD")
            yield SqlAlchemyInspectionScope(session, owner_user_id, project_id)
