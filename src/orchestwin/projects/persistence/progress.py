from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.projects.domain import Project, ProjectMode
from orchestwin.projects.persistence.models import ProjectBriefVersionRecord, ProjectRecord
from orchestwin.projects.progress import (
    ArtifactVersion,
    CatalogVersion,
    GateState,
    ProjectOverview,
    ProjectProgressFacts,
    TeamState,
    UserTwinsState,
    project_progress,
)
from orchestwin.workflow.gates import HumanGateStatus, HumanGateType
from orchestwin.workflow.persistence.models import HumanGateRecord

_UUID = postgresql.UUID(as_uuid=True)

TEAM_PROPOSALS: Final = sa.table(
    "team_proposals",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("version_number", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
    sa.column("brief_version_id", _UUID),
    sa.column("brief_version_number", sa.Integer()),
    sa.column("brief_content_hash", sa.String(64)),
    sa.column("catalog_version", sa.Integer()),
    sa.column("catalog_content_hash", sa.String(64)),
)

USER_MODELING_SNAPSHOTS: Final = sa.table(
    "user_modeling_snapshot_versions",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("version_number", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
    sa.column("brief_version_id", _UUID),
    sa.column("brief_version_number", sa.Integer()),
    sa.column("brief_content_hash", sa.String(64)),
    sa.column("team_proposal_id", _UUID),
    sa.column("team_version_number", sa.Integer()),
    sa.column("team_content_hash", sa.String(64)),
    sa.column("catalog_version", sa.Integer()),
    sa.column("catalog_content_hash", sa.String(64)),
)

REQUIREMENTS_VERSIONS: Final = sa.table(
    "requirements_specification_versions",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("version_number", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
)

DESIGN_VERSIONS: Final = sa.table(
    "design_package_versions",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("version_number", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
)

GATES: Final = {
    "brief_gate": HumanGateType.PROJECT_BRIEF,
    "team_gate": HumanGateType.AGENT_TEAM,
    "twins_gate": HumanGateType.USER_MODELING,
    "requirements_gate": HumanGateType.REQUIREMENTS,
    "design_gate": HumanGateType.DESIGN,
}

_ARTIFACT: Final = ("id", "version_number", "content_hash")
_TEAM: Final = (
    *_ARTIFACT,
    "brief_version_id",
    "brief_version_number",
    "brief_content_hash",
    "catalog_version",
    "catalog_content_hash",
)
_TWINS: Final = (
    *_TEAM,
    "team_proposal_id",
    "team_version_number",
    "team_content_hash",
)
_LABELS: Final = {
    "id": "id",
    "version_number": "version",
    "content_hash": "hash",
    "brief_version_id": "brief_id",
    "brief_version_number": "brief_version",
    "brief_content_hash": "brief_hash",
    "catalog_version": "catalog_version",
    "catalog_content_hash": "catalog_hash",
    "team_proposal_id": "team_id",
    "team_version_number": "team_version",
    "team_content_hash": "team_hash",
}
_PROJECT: Final = (
    "id",
    "owner_user_id",
    "display_name",
    "mode",
    "current_brief_version",
    "archived_at",
    "created_at",
    "updated_at",
)


def _latest_version(table: sa.TableClause, columns: Sequence[str], name: str) -> sa.Lateral:
    return (
        sa.select(*(table.c[column] for column in columns))
        .where(table.c.project_id == ProjectRecord.id)
        .order_by(table.c.version_number.desc())
        .limit(1)
        .lateral(name)
    )


def _latest_gate(gate_type: HumanGateType, name: str) -> sa.Lateral:
    return (
        sa.select(
            HumanGateRecord.status,
            HumanGateRecord.artifact_id,
            HumanGateRecord.artifact_version,
            HumanGateRecord.artifact_hash,
        )
        .where(
            HumanGateRecord.project_id == ProjectRecord.id,
            HumanGateRecord.gate_type == gate_type.value,
        )
        .order_by(
            HumanGateRecord.iteration.desc(),
            HumanGateRecord.created_at.desc(),
            HumanGateRecord.id.desc(),
        )
        .limit(1)
        .lateral(name)
    )


def overview_statement(*, owner_user_id: UUID, project_id: UUID | None = None) -> sa.Select:
    brief = sa.alias(ProjectBriefVersionRecord.__table__, "current_brief")
    versions = {
        "team": (_latest_version(TEAM_PROPOSALS, _TEAM, "latest_team"), _TEAM),
        "twins": (_latest_version(USER_MODELING_SNAPSHOTS, _TWINS, "latest_twins"), _TWINS),
        "requirements": (
            _latest_version(REQUIREMENTS_VERSIONS, _ARTIFACT, "latest_requirements"),
            _ARTIFACT,
        ),
        "design": (_latest_version(DESIGN_VERSIONS, _ARTIFACT, "latest_design"), _ARTIFACT),
    }
    gates = {name: _latest_gate(gate_type, name) for name, gate_type in GATES.items()}
    projects = ProjectRecord.__table__
    columns: list[sa.ColumnElement[Any]] = [
        *(projects.c[column].label(f"project_{column}") for column in _PROJECT),
        brief.c.id.label("brief_id"),
        brief.c.version_number.label("brief_version"),
        brief.c.content_hash.label("brief_hash"),
    ]
    for prefix, (lateral, names) in versions.items():
        columns.extend(lateral.c[name].label(f"{prefix}_{_LABELS[name]}") for name in names)
    for name, lateral in gates.items():
        columns.extend(
            (
                lateral.c.status.label(f"{name}_status"),
                lateral.c.artifact_id.label(f"{name}_id"),
                lateral.c.artifact_version.label(f"{name}_version"),
                lateral.c.artifact_hash.label(f"{name}_hash"),
            )
        )
    source = projects.outerjoin(
        brief,
        sa.and_(
            brief.c.project_id == projects.c.id,
            brief.c.version_number == projects.c.current_brief_version,
        ),
    )
    for lateral, _names in versions.values():
        source = source.outerjoin(lateral, sa.true())
    for lateral in gates.values():
        source = source.outerjoin(lateral, sa.true())
    statement = (
        sa.select(*columns)
        .select_from(source)
        .where(projects.c.owner_user_id == owner_user_id, projects.c.archived_at.is_(None))
        .order_by(projects.c.created_at.desc(), projects.c.id)
    )
    if project_id is not None:
        statement = statement.where(projects.c.id == project_id)
    return statement


def _artifact(row: Mapping[str, Any], prefix: str) -> ArtifactVersion | None:
    artifact_id = row[f"{prefix}_id"]
    if artifact_id is None:
        return None
    return ArtifactVersion(
        artifact_id=artifact_id,
        version_number=row[f"{prefix}_version"],
        content_hash=row[f"{prefix}_hash"],
    )


def _required_artifact(row: Mapping[str, Any], prefix: str) -> ArtifactVersion:
    artifact = _artifact(row, prefix)
    if artifact is None:
        raise ValueError(f"{prefix} reference is missing")
    return artifact


def _gate(row: Mapping[str, Any], prefix: str) -> GateState | None:
    artifact = _artifact(row, prefix)
    if artifact is None:
        return None
    return GateState(status=HumanGateStatus(row[f"{prefix}_status"]), artifact=artifact)


def _catalog(row: Mapping[str, Any], prefix: str) -> CatalogVersion:
    return CatalogVersion(
        version=row[f"{prefix}_catalog_version"],
        content_hash=row[f"{prefix}_catalog_hash"],
    )


def _team(row: Mapping[str, Any]) -> TeamState | None:
    artifact = _artifact(row, "team")
    if artifact is None:
        return None
    return TeamState(
        artifact=artifact,
        brief=_required_artifact(row, "team_brief"),
        catalog=_catalog(row, "team"),
    )


def _user_twins(row: Mapping[str, Any]) -> UserTwinsState | None:
    artifact = _artifact(row, "twins")
    if artifact is None:
        return None
    return UserTwinsState(
        artifact=artifact,
        brief=_required_artifact(row, "twins_brief"),
        team=_required_artifact(row, "twins_team"),
        catalog=_catalog(row, "twins"),
    )


def progress_facts(row: Mapping[str, Any]) -> ProjectProgressFacts:
    return ProjectProgressFacts(
        brief=_artifact(row, "brief"),
        brief_gate=_gate(row, "brief_gate"),
        team=_team(row),
        team_gate=_gate(row, "team_gate"),
        user_twins=_user_twins(row),
        user_twins_gate=_gate(row, "twins_gate"),
        requirements=_artifact(row, "requirements"),
        requirements_gate=_gate(row, "requirements_gate"),
        design=_artifact(row, "design"),
        design_gate=_gate(row, "design_gate"),
    )


def _project(row: Mapping[str, Any]) -> Project:
    return Project(
        id=row["project_id"],
        owner_user_id=row["project_owner_user_id"],
        display_name=row["project_display_name"],
        mode=ProjectMode(row["project_mode"]),
        current_brief_version=row["project_current_brief_version"],
        archived_at=row["project_archived_at"],
        created_at=row["project_created_at"],
        updated_at=row["project_updated_at"],
    )


def project_overview(row: Mapping[str, Any]) -> ProjectOverview:
    return ProjectOverview(project=_project(row), progress=project_progress(progress_facts(row)))


class SqlAlchemyProjectOverviewRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_active_owned(self, *, owner_user_id: UUID) -> tuple[ProjectOverview, ...]:
        result = await self._session.execute(overview_statement(owner_user_id=owner_user_id))
        return tuple(project_overview(row) for row in result.mappings().all())

    async def get_owned(self, *, project_id: UUID, owner_user_id: UUID) -> ProjectOverview | None:
        result = await self._session.execute(
            overview_statement(owner_user_id=owner_user_id, project_id=project_id)
        )
        row = result.mappings().first()
        return None if row is None else project_overview(row)


__all__ = [
    "DESIGN_VERSIONS",
    "GATES",
    "REQUIREMENTS_VERSIONS",
    "TEAM_PROPOSALS",
    "USER_MODELING_SNAPSHOTS",
    "SqlAlchemyProjectOverviewRepository",
    "overview_statement",
    "progress_facts",
    "project_overview",
]
