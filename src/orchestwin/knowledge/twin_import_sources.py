from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.twins.persistence.repositories import USER_MODELING_SNAPSHOT_VERSIONS
from orchestwin.workflow.gates import HumanGateStatus, HumanGateType
from orchestwin.workflow.persistence.models import HumanGateRecord

DEFAULT_CANDIDATE_LIMIT: Final = 100

_SNAPSHOTS: Final = USER_MODELING_SNAPSHOT_VERSIONS


@dataclass(frozen=True, slots=True)
class TwinImportCandidate:
    project_id: UUID
    project_name: str
    snapshot_version_number: int
    approved_at: datetime
    twin_names: tuple[str, ...]


def _other_active_projects(
    *, owner_user_id: UUID, exclude_project_id: UUID
) -> tuple[sa.ColumnElement[bool], ...]:
    return (
        ProjectRecord.owner_user_id == owner_user_id,
        ProjectRecord.archived_at.is_(None),
        ProjectRecord.id != exclude_project_id,
    )


def _current_snapshots(scope: Sequence[sa.ColumnElement[bool]]) -> sa.Subquery:
    return (
        sa.select(
            _SNAPSHOTS.c.project_id,
            _SNAPSHOTS.c.id,
            _SNAPSHOTS.c.version_number,
            _SNAPSHOTS.c.content_hash,
        )
        .join(ProjectRecord, ProjectRecord.id == _SNAPSHOTS.c.project_id)
        .where(*scope)
        .distinct(_SNAPSHOTS.c.project_id)
        .order_by(_SNAPSHOTS.c.project_id, _SNAPSHOTS.c.version_number.desc())
        .subquery("current_snapshots")
    )


def _latest_user_modeling_gates(scope: Sequence[sa.ColumnElement[bool]]) -> sa.Subquery:
    return (
        sa.select(
            HumanGateRecord.project_id,
            HumanGateRecord.status,
            HumanGateRecord.artifact_id,
            HumanGateRecord.artifact_version,
            HumanGateRecord.artifact_hash,
            HumanGateRecord.updated_at,
        )
        .join(ProjectRecord, ProjectRecord.id == HumanGateRecord.project_id)
        .where(*scope, HumanGateRecord.gate_type == HumanGateType.USER_MODELING.value)
        .distinct(HumanGateRecord.project_id)
        .order_by(
            HumanGateRecord.project_id,
            HumanGateRecord.iteration.desc(),
            HumanGateRecord.created_at.desc(),
            HumanGateRecord.id.desc(),
        )
        .subquery("latest_gates")
    )


def _candidates_statement(
    *, owner_user_id: UUID, exclude_project_id: UUID, limit: int
) -> sa.Select:
    scope = _other_active_projects(
        owner_user_id=owner_user_id, exclude_project_id=exclude_project_id
    )
    snapshots = _current_snapshots(scope)
    gates = _latest_user_modeling_gates(scope)
    return (
        sa.select(
            ProjectRecord.id.label("project_id"),
            ProjectRecord.display_name.label("project_name"),
            snapshots.c.id.label("snapshot_id"),
            snapshots.c.version_number.label("snapshot_version_number"),
            gates.c.updated_at.label("approved_at"),
        )
        .join(snapshots, snapshots.c.project_id == ProjectRecord.id)
        .join(gates, gates.c.project_id == ProjectRecord.id)
        .where(
            gates.c.status == HumanGateStatus.APPROVED.value,
            gates.c.artifact_id == snapshots.c.id,
            gates.c.artifact_version == snapshots.c.version_number,
            gates.c.artifact_hash == snapshots.c.content_hash,
        )
        .order_by(gates.c.updated_at.desc(), ProjectRecord.display_name, ProjectRecord.id)
        .limit(limit)
    )


def _twin_names_statement(snapshot_ids: Iterable[UUID]) -> sa.Select:
    twins = (
        sa.func.jsonb_array_elements(_SNAPSHOTS.c.snapshot["twin_versions"])
        .table_valued(sa.column("twin", postgresql.JSONB))
        .render_derived(name="twins")
        .lateral()
    )
    return (
        sa.select(_SNAPSHOTS.c.id, twins.c.twin[("profile", "name")].astext)
        .select_from(_SNAPSHOTS.join(twins, sa.true()))
        .where(_SNAPSHOTS.c.id.in_(tuple(snapshot_ids)))
    )


def _sorted_names(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(names, key=lambda name: (name.casefold(), name)))


def _names_by_snapshot(rows: Iterable[tuple[UUID, str]]) -> dict[UUID, tuple[str, ...]]:
    found: defaultdict[UUID, list[str]] = defaultdict(list)
    for snapshot_id, name in rows:
        found[snapshot_id].append(name)
    return {snapshot_id: _sorted_names(names) for snapshot_id, names in found.items()}


def _candidate(row: sa.RowMapping, names: Mapping[UUID, tuple[str, ...]]) -> TwinImportCandidate:
    return TwinImportCandidate(
        project_id=row["project_id"],
        project_name=row["project_name"],
        snapshot_version_number=row["snapshot_version_number"],
        approved_at=row["approved_at"],
        twin_names=names.get(row["snapshot_id"], ()),
    )


class SqlAlchemyTwinImportCandidateQuery:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def list(
        self,
        *,
        owner_user_id: UUID,
        exclude_project_id: UUID,
        limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> tuple[TwinImportCandidate, ...]:
        if limit < 1:
            raise ValueError("twin import candidate limit must be positive")
        statement = _candidates_statement(
            owner_user_id=owner_user_id, exclude_project_id=exclude_project_id, limit=limit
        )
        async with self._session_factory() as session:
            rows = (await session.execute(statement)).mappings().all()
            if not rows:
                return ()
            names = await session.execute(_twin_names_statement(row["snapshot_id"] for row in rows))
            found = _names_by_snapshot(names.tuples().all())
        return tuple(_candidate(row, found) for row in rows)


__all__ = [
    "DEFAULT_CANDIDATE_LIMIT",
    "SqlAlchemyTwinImportCandidateQuery",
    "TwinImportCandidate",
]
