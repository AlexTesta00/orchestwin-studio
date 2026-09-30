from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.knowledge.state import MAX_LEARNED_OBSERVATIONS
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.twin_learning import (
    KeptObservation,
    LearnedObservation,
    LearningSource,
    ObservationDraft,
    TwinUpdate,
    UpdateDecision,
    UpdateDecisionKind,
    UpdateStatus,
    development_version,
    learned_observations,
    observation_code,
    proposed_observation_from_snapshot,
)

PENDING_INDEX: Final = "uq_twin_updates_pending"

UPDATES = sa.table(
    "twin_updates",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_name", sa.String(length=200)),
    sa.column("created_at", sa.DateTime(timezone=True)),
    sa.column("locale", sa.String(length=20)),
    sa.column("status", sa.String(length=10)),
    sa.column("base_profile_version", sa.Integer()),
    sa.column("base_development_version", sa.Integer()),
    sa.column("comment", sa.String(length=600)),
    sa.column("observations", postgresql.JSONB()),
    sa.column("material_changes", sa.Integer()),
    sa.column("material_tests", sa.Integer()),
    sa.column("decided_at", sa.DateTime(timezone=True)),
    sa.column("kept", postgresql.JSONB(none_as_null=True)),
    sa.column("decision_reason", sa.String(length=300)),
    sa.column("generation_ids", postgresql.JSONB()),
    sa.column("cost_microusd", sa.BigInteger()),
)

OBSERVATIONS = sa.table(
    "twin_learned_observations",
    sa.column("project_id", postgresql.UUID(as_uuid=True)),
    sa.column("owner_user_id", postgresql.UUID(as_uuid=True)),
    sa.column("twin_id", postgresql.UUID(as_uuid=True)),
    sa.column("number", sa.Integer()),
    sa.column("code", sa.String(length=12)),
    sa.column("statement", sa.String(length=400)),
    sa.column("basis", sa.String(length=300)),
    sa.column("source", sa.String(length=16)),
    sa.column("requirement", sa.String(length=12)),
    sa.column("screen", sa.String(length=12)),
    sa.column("contradicts_profile", sa.String(length=300)),
    sa.column("added_in_version", sa.Integer()),
    sa.column("approved_at", sa.DateTime(timezone=True)),
    sa.column("update_id", postgresql.UUID(as_uuid=True)),
    sa.column("retired_in_version", sa.Integer()),
    sa.column("retired_at", sa.DateTime(timezone=True)),
    sa.column("retire_reason", sa.String(length=300)),
)


class TwinLearningWriteStatus(StrEnum):
    RECORDED = "RECORDED"
    PROJECT_NOT_FOUND = "PROJECT_NOT_FOUND"
    UPDATE_NOT_FOUND = "UPDATE_NOT_FOUND"
    UPDATE_PENDING = "UPDATE_PENDING"
    ALREADY_DECIDED = "ALREADY_DECIDED"
    CONTEXT_CHANGED = "CONTEXT_CHANGED"
    LIMIT_REACHED = "LIMIT_REACHED"
    INDEX_UNKNOWN = "INDEX_UNKNOWN"
    OBSERVATION_NOT_FOUND = "OBSERVATION_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class TwinLearningWriteResult:
    status: TwinLearningWriteStatus
    update: TwinUpdate | None = None
    observations: tuple[LearnedObservation, ...] = ()
    pending: TwinUpdate | None = None
    position: int | None = None


def _utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.astimezone(UTC)


def _observation(row: Mapping[str, object]) -> LearnedObservation:
    observation = LearnedObservation(
        twin_id=row["twin_id"],
        number=row["number"],
        statement=row["statement"],
        source=LearningSource(row["source"]),
        added_in_version=row["added_in_version"],
        approved_at=_utc(row["approved_at"]),
        basis=row["basis"],
        requirement=row["requirement"],
        screen=row["screen"],
        contradicts_profile=row["contradicts_profile"],
        update_id=row["update_id"],
        retired_in_version=row["retired_in_version"],
        retired_at=_utc(row["retired_at"]),
        retire_reason=row["retire_reason"],
    )
    if observation.code != row["code"]:
        raise ValueError("stored observation code does not match its number")
    return observation


def _update(row: Mapping[str, object]) -> TwinUpdate:
    decision = None
    if row["decided_at"] is not None:
        decision = UpdateDecision(
            decided_at=_utc(row["decided_at"]),
            kept=tuple(row["kept"]),
            reason=row["decision_reason"],
        )
    return TwinUpdate(
        id=row["id"],
        twin_id=row["twin_id"],
        twin_name=row["twin_name"],
        created_at=_utc(row["created_at"]),
        locale=row["locale"],
        status=UpdateStatus(row["status"]),
        base_profile_version=row["base_profile_version"],
        base_development_version=row["base_development_version"],
        comment=row["comment"],
        observations=tuple(
            proposed_observation_from_snapshot(item) for item in row["observations"]
        ),
        material_changes=row["material_changes"],
        material_tests=row["material_tests"],
        decision=decision,
        generation_ids=tuple(UUID(str(item)) for item in row["generation_ids"]),
        cost_microusd=row["cost_microusd"],
    )


class SqlAlchemyTwinLearningRepository:
    def __init__(self, session: AsyncSession, *, owner_user_id: UUID) -> None:
        self._session = session
        self._owner_user_id = owner_user_id

    def _owned_project(self, project_id: UUID):
        return sa.select(ProjectRecord.id).where(
            ProjectRecord.id == project_id,
            ProjectRecord.owner_user_id == self._owner_user_id,
            ProjectRecord.archived_at.is_(None),
        )

    async def project_exists(self, project_id: UUID) -> bool:
        return (
            await self._session.execute(self._owned_project(project_id))
        ).scalar_one_or_none() is not None

    async def _lock_project(self, project_id: UUID) -> bool:
        statement = self._owned_project(project_id).with_for_update()
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    def _owned(self, table, project_id: UUID):
        return sa.select(*table.c).where(
            table.c.project_id == project_id,
            table.c.owner_user_id == self._owner_user_id,
        )

    async def observations(self, project_id: UUID, twin_id: UUID) -> tuple[LearnedObservation, ...]:
        statement = (
            self._owned(OBSERVATIONS, project_id)
            .where(OBSERVATIONS.c.twin_id == twin_id)
            .order_by(OBSERVATIONS.c.number)
        )
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(_observation(row) for row in rows)

    async def _by_twin(self, statement) -> Mapping[UUID, tuple[LearnedObservation, ...]]:
        rows = (
            (await self._session.execute(statement.order_by(OBSERVATIONS.c.number)))
            .mappings()
            .all()
        )
        grouped: dict[UUID, list[LearnedObservation]] = {}
        for row in rows:
            grouped.setdefault(row["twin_id"], []).append(_observation(row))
        return {twin_id: tuple(items) for twin_id, items in grouped.items()}

    async def active(self, project_id: UUID) -> Mapping[UUID, tuple[LearnedObservation, ...]]:
        return await self._by_twin(
            self._owned(OBSERVATIONS, project_id).where(OBSERVATIONS.c.retired_at.is_(None))
        )

    async def project_observations(
        self, project_id: UUID
    ) -> Mapping[UUID, tuple[LearnedObservation, ...]]:
        return await self._by_twin(self._owned(OBSERVATIONS, project_id))

    async def development_version(self, project_id: UUID, twin_id: UUID) -> int:
        return development_version(await self.observations(project_id, twin_id))

    async def next_observation_number(self, project_id: UUID) -> int:
        statement = sa.select(sa.func.max(OBSERVATIONS.c.number)).where(
            OBSERVATIONS.c.project_id == project_id
        )
        latest = (await self._session.execute(statement)).scalar_one()
        return (latest or 0) + 1

    async def _store_observations(
        self, project_id: UUID, observations: Sequence[LearnedObservation]
    ) -> None:
        for item in observations:
            await self._session.execute(
                sa.insert(OBSERVATIONS).values(
                    project_id=project_id,
                    owner_user_id=self._owner_user_id,
                    twin_id=item.twin_id,
                    number=item.number,
                    code=observation_code(item.number),
                    statement=item.statement,
                    basis=item.basis,
                    source=item.source.value,
                    requirement=item.requirement,
                    screen=item.screen,
                    contradicts_profile=item.contradicts_profile,
                    added_in_version=item.added_in_version,
                    approved_at=item.approved_at,
                    update_id=item.update_id,
                    retired_in_version=None,
                    retired_at=None,
                    retire_reason=None,
                )
            )

    async def _store_retirement(self, project_id: UUID, observation: LearnedObservation) -> None:
        await self._session.execute(
            sa.update(OBSERVATIONS)
            .where(
                OBSERVATIONS.c.project_id == project_id,
                OBSERVATIONS.c.owner_user_id == self._owner_user_id,
                OBSERVATIONS.c.number == observation.number,
            )
            .values(
                retired_in_version=observation.retired_in_version,
                retired_at=observation.retired_at,
                retire_reason=observation.retire_reason,
            )
        )

    async def _store_update(self, project_id: UUID, update: TwinUpdate) -> None:
        await self._session.execute(
            sa.insert(UPDATES).values(
                id=update.id,
                project_id=project_id,
                owner_user_id=self._owner_user_id,
                twin_id=update.twin_id,
                twin_name=update.twin_name,
                created_at=update.created_at,
                locale=update.locale,
                status=update.status.value,
                base_profile_version=update.base_profile_version,
                base_development_version=update.base_development_version,
                comment=update.comment,
                observations=[item.to_snapshot() for item in update.observations],
                material_changes=update.material_changes,
                material_tests=update.material_tests,
                decided_at=None,
                kept=None,
                decision_reason=None,
                generation_ids=[str(item) for item in update.generation_ids],
                cost_microusd=update.cost_microusd,
            )
        )

    async def _store_decision(self, update: TwinUpdate) -> None:
        await self._session.execute(
            sa.update(UPDATES)
            .where(UPDATES.c.id == update.id, UPDATES.c.owner_user_id == self._owner_user_id)
            .values(
                status=update.status.value,
                decided_at=update.decision.decided_at,
                kept=list(update.decision.kept),
                decision_reason=update.decision.reason,
            )
        )

    async def _insert(
        self,
        project_id: UUID,
        twin_id: UUID,
        drafts: Sequence[ObservationDraft],
        *,
        version: int,
        source: LearningSource,
        approved_at: datetime,
        update_id: UUID | None,
    ) -> tuple[LearnedObservation, ...]:
        observations = learned_observations(
            drafts,
            twin_id=twin_id,
            first_number=await self.next_observation_number(project_id),
            version=version,
            approved_at=approved_at,
            source=source,
            update_id=update_id,
        )
        await self._store_observations(project_id, observations)
        return observations

    async def add(
        self,
        project_id: UUID,
        twin_id: UUID,
        drafts: Sequence[ObservationDraft],
        *,
        approved_at: datetime,
        source: LearningSource = LearningSource.OWNER,
        update_id: UUID | None = None,
    ) -> TwinLearningWriteResult:
        if not drafts:
            raise ValueError("a new version adds at least one observation")
        if not await self._lock_project(project_id):
            return TwinLearningWriteResult(TwinLearningWriteStatus.PROJECT_NOT_FOUND)
        records = await self.observations(project_id, twin_id)
        active = sum(1 for item in records if item.active)
        if active + len(drafts) > MAX_LEARNED_OBSERVATIONS:
            return TwinLearningWriteResult(TwinLearningWriteStatus.LIMIT_REACHED)
        pending = await self.pending_update(project_id, twin_id)
        if pending is not None and pending.id != update_id:
            return TwinLearningWriteResult(TwinLearningWriteStatus.UPDATE_PENDING, pending=pending)
        added = await self._insert(
            project_id,
            twin_id,
            drafts,
            version=development_version(records) + 1,
            source=source,
            approved_at=approved_at,
            update_id=update_id,
        )
        return TwinLearningWriteResult(TwinLearningWriteStatus.RECORDED, observations=added)

    async def retire(
        self,
        project_id: UUID,
        twin_id: UUID,
        number: int,
        *,
        retired_at: datetime,
        reason: str | None = None,
    ) -> TwinLearningWriteResult:
        if not await self._lock_project(project_id):
            return TwinLearningWriteResult(TwinLearningWriteStatus.PROJECT_NOT_FOUND)
        records = await self.observations(project_id, twin_id)
        target = next((item for item in records if item.number == number and item.active), None)
        if target is None:
            return TwinLearningWriteResult(TwinLearningWriteStatus.OBSERVATION_NOT_FOUND)
        pending = await self.pending_update(project_id, twin_id)
        if pending is not None:
            return TwinLearningWriteResult(TwinLearningWriteStatus.UPDATE_PENDING, pending=pending)
        retired = target.retire(
            version=development_version(records) + 1, retired_at=retired_at, reason=reason
        )
        await self._store_retirement(project_id, retired)
        return TwinLearningWriteResult(TwinLearningWriteStatus.RECORDED, observations=(retired,))

    def _updates(self, project_id: UUID):
        return self._owned(UPDATES, project_id).order_by(
            UPDATES.c.created_at.desc(), UPDATES.c.id.desc()
        )

    async def _first_update(self, statement) -> TwinUpdate | None:
        row = (await self._session.execute(statement.limit(1))).mappings().one_or_none()
        return None if row is None else _update(row)

    async def update(self, project_id: UUID, update_id: UUID) -> TwinUpdate | None:
        return await self._first_update(self._updates(project_id).where(UPDATES.c.id == update_id))

    async def updates(self, project_id: UUID, twin_id: UUID) -> tuple[TwinUpdate, ...]:
        statement = self._updates(project_id).where(UPDATES.c.twin_id == twin_id)
        rows = (await self._session.execute(statement)).mappings().all()
        return tuple(_update(row) for row in rows)

    async def pending_update(self, project_id: UUID, twin_id: UUID) -> TwinUpdate | None:
        return await self._first_update(
            self._updates(project_id).where(
                UPDATES.c.twin_id == twin_id, UPDATES.c.status == UpdateStatus.PROPOSED.value
            )
        )

    async def latest_update(self, project_id: UUID, twin_id: UUID) -> TwinUpdate | None:
        return await self._first_update(
            self._updates(project_id).where(UPDATES.c.twin_id == twin_id)
        )

    async def create_update(self, project_id: UUID, update: TwinUpdate) -> TwinLearningWriteResult:
        if update.status not in (UpdateStatus.PROPOSED, UpdateStatus.EMPTY):
            raise ValueError("a new update is proposed or empty")
        if not await self._lock_project(project_id):
            return TwinLearningWriteResult(TwinLearningWriteStatus.PROJECT_NOT_FOUND)
        pending = await self.pending_update(project_id, update.twin_id)
        if pending is not None:
            return TwinLearningWriteResult(TwinLearningWriteStatus.UPDATE_PENDING, pending=pending)
        await self._store_update(project_id, update)
        return TwinLearningWriteResult(TwinLearningWriteStatus.RECORDED, update=update)

    async def decide_update(
        self,
        project_id: UUID,
        update_id: UUID,
        decision: UpdateDecisionKind,
        kept: Sequence[KeptObservation] = (),
        *,
        decided_at: datetime,
        reason: str | None = None,
    ) -> TwinLearningWriteResult:
        if not await self._lock_project(project_id):
            return TwinLearningWriteResult(TwinLearningWriteStatus.PROJECT_NOT_FOUND)
        current = await self.update(project_id, update_id)
        if current is None:
            return TwinLearningWriteResult(TwinLearningWriteStatus.UPDATE_NOT_FOUND)
        if not current.pending:
            return TwinLearningWriteResult(TwinLearningWriteStatus.ALREADY_DECIDED, update=current)
        records = await self.observations(project_id, current.twin_id)
        version = development_version(records)
        approving = decision is UpdateDecisionKind.APPROVE
        if approving and version != current.base_development_version:
            return TwinLearningWriteResult(TwinLearningWriteStatus.CONTEXT_CHANGED, update=current)
        active = sum(1 for item in records if item.active)
        if approving and active + len(kept) > MAX_LEARNED_OBSERVATIONS:
            return TwinLearningWriteResult(TwinLearningWriteStatus.LIMIT_REACHED, update=current)
        position = next(
            (place for place, item in enumerate(kept) if item.index >= len(current.observations)),
            None,
        )
        if position is not None:
            return TwinLearningWriteResult(
                TwinLearningWriteStatus.INDEX_UNKNOWN, update=current, position=position
            )
        decided = current.decided(
            decision,
            kept=(item.index for item in kept),
            reason=reason,
            decided_at=decided_at,
        )
        await self._store_decision(decided)
        added: tuple[LearnedObservation, ...] = ()
        if approving:
            added = await self._insert(
                project_id,
                current.twin_id,
                current.kept_drafts(kept),
                version=version + 1,
                source=LearningSource.TWIN_CRITIQUE,
                approved_at=decided_at,
                update_id=current.id,
            )
        return TwinLearningWriteResult(
            TwinLearningWriteStatus.RECORDED, update=decided, observations=added
        )


__all__ = [
    "OBSERVATIONS",
    "PENDING_INDEX",
    "UPDATES",
    "SqlAlchemyTwinLearningRepository",
    "TwinLearningWriteResult",
    "TwinLearningWriteStatus",
]
