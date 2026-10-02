from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

from orchestwin.agents.persistence.repositories import proposal_from_snapshot
from orchestwin.agents.realignment import team_selection_can_realign
from orchestwin.artifacts.design_realignment import _cited_items
from orchestwin.artifacts.design_serialization import design_package_from_snapshot
from orchestwin.projects.briefs import ProjectBrief
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
from orchestwin.projects.requirements_persistence import specification_from_snapshot
from orchestwin.projects.requirements_realignment import referenced_twin_ids
from orchestwin.projects.sections import (
    BriefFacts,
    DesignFacts,
    RequirementsFacts,
    SectionFacts,
    TeamFacts,
    UserTwinsFacts,
    project_sections,
    requirements_actor_codes,
)
from orchestwin.twins.persistence.repositories import PERSONA_PROFILE_VERSIONS
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
    sa.column("content", postgresql.JSONB()),
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
    sa.column("snapshot", postgresql.JSONB()),
)

REQUIREMENTS_VERSIONS: Final = sa.table(
    "requirements_specification_versions",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("version_number", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
    sa.column("specification_snapshot", postgresql.JSONB()),
)

DESIGN_VERSIONS: Final = sa.table(
    "design_package_versions",
    sa.column("id", _UUID),
    sa.column("project_id", _UUID),
    sa.column("version_number", sa.Integer()),
    sa.column("content_hash", sa.String(64)),
    sa.column("package_snapshot", postgresql.JSONB()),
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
    "content": "content",
    "snapshot": "snapshot",
    "specification_snapshot": "content",
    "package_snapshot": "content",
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
        "team": (
            _latest_version(TEAM_PROPOSALS, (*_TEAM, "content"), "latest_team"),
            (*_TEAM, "content"),
        ),
        "twins": (
            _latest_version(USER_MODELING_SNAPSHOTS, (*_TWINS, "snapshot"), "latest_twins"),
            (*_TWINS, "snapshot"),
        ),
        "requirements": (
            _latest_version(
                REQUIREMENTS_VERSIONS, (*_ARTIFACT, "specification_snapshot"), "latest_requirements"
            ),
            (*_ARTIFACT, "specification_snapshot"),
        ),
        "design": (
            _latest_version(DESIGN_VERSIONS, (*_ARTIFACT, "package_snapshot"), "latest_design"),
            (*_ARTIFACT, "package_snapshot"),
        ),
    }
    gates = {name: _latest_gate(gate_type, name) for name, gate_type in GATES.items()}
    projects = ProjectRecord.__table__
    columns: list[sa.ColumnElement[Any]] = [
        *(projects.c[column].label(f"project_{column}") for column in _PROJECT),
        brief.c.id.label("brief_id"),
        brief.c.version_number.label("brief_version"),
        brief.c.content_hash.label("brief_hash"),
        brief.c.content.label("brief_content"),
    ]
    personas = PERSONA_PROFILE_VERSIONS
    roster_versions = (
        sa.select(
            personas.c.id,
            personas.c.persona_id,
            personas.c.version_number,
            personas.c.content_hash,
            personas.c.profile_snapshot,
        )
        .where(personas.c.project_id == ProjectRecord.id)
        .distinct(personas.c.persona_id)
        .order_by(personas.c.persona_id, personas.c.version_number.desc())
        .correlate(ProjectRecord)
        .subquery("latest_archetype_versions")
    )
    roster = (
        sa.select(
            sa.func.jsonb_agg(
                sa.func.jsonb_build_object(
                    "id",
                    roster_versions.c.id,
                    "persona_id",
                    roster_versions.c.persona_id,
                    "version_number",
                    roster_versions.c.version_number,
                    "content_hash",
                    roster_versions.c.content_hash,
                    "profile",
                    roster_versions.c.profile_snapshot,
                )
            ).label("versions")
        )
        .select_from(roster_versions)
        .lateral("current_archetypes")
    )
    columns.append(roster.c.versions.label("archetype_versions"))
    for key, name, base in (
        ("twins", "user_twin_profile_diffs", "base_snapshot_version_id"),
        ("requirements", "requirements_specification_diffs", "base_version_id"),
        ("design", "design_package_diffs", "base_version_id"),
    ):
        diffs = sa.table(
            name,
            sa.column("project_id", _UUID),
            sa.column(base, _UUID),
            sa.column("status", sa.String()),
        )
        columns.append(
            sa.exists(
                sa.select(1)
                .select_from(diffs)
                .where(
                    diffs.c.project_id == ProjectRecord.id,
                    sa.true() if key == "twins" else diffs.c[base] == versions[key][0].c.id,
                    diffs.c.status == "PROPOSED",
                )
            ).label(f"{key}_revision_pending")
        )
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
    ).outerjoin(roster, sa.true())
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


def _json_reference(value: Mapping[str, Any]) -> ArtifactVersion:
    return ArtifactVersion(
        UUID(value["artifact_id"]), value["version_number"], value["content_hash"]
    )


def _json_twins(values: Sequence[Mapping[str, Any]]) -> frozenset[ArtifactVersion]:
    return frozenset(
        ArtifactVersion(UUID(value["twin_id"]), value["version_number"], value["content_hash"])
        for value in values
    )


def _roster_matches(snapshot: Mapping[str, Any], roster: Sequence[Mapping[str, Any]]) -> bool:
    active = [
        version
        for version in roster
        if not version["profile"].get("archived", False)
        and version["profile"]["confirmation_status"] != "REJECTED"
    ]
    if not active or any(
        version["profile"]["confirmation_status"] != "CONFIRMED" for version in active
    ):
        return False
    current = {
        str(version["persona_id"]): (
            str(version["id"]),
            version["version_number"],
            version["content_hash"],
        )
        for version in active
    }
    held = {
        version["persona_id"]: (version["id"], version["version_number"], version["content_hash"])
        for version in snapshot["persona_versions"]
    }
    return len(current) == len(active) and current == held


def overview_section_facts(row: Mapping[str, Any]) -> SectionFacts | None:
    if "twins_snapshot" not in row:
        return None
    progress = progress_facts(row)
    team = progress.team
    brief = (
        None
        if progress.brief is None
        else BriefFacts(
            progress.brief,
            progress.brief_gate is not None and progress.brief_gate.approves(progress.brief),
        )
    )
    team_facts = None
    if team is not None:
        proposal = proposal_from_snapshot(row["team_content"])
        alignable = (
            brief is not None
            and brief.approved
            and team_selection_can_realign(
                proposal,
                brief=ProjectBrief.from_snapshot(row["brief_content"]),
                project_mode=ProjectMode(row["project_mode"]),
            )
        )
        team_facts = TeamFacts(
            team.artifact,
            progress.team_gate is not None and progress.team_gate.approves(team.artifact),
            team.brief,
            alignable=alignable,
        )
    twins = None
    snapshot = row["twins_snapshot"]
    if progress.user_twins is not None:
        version = progress.user_twins
        twins = UserTwinsFacts(
            version.artifact,
            progress.user_twins_gate is not None
            and progress.user_twins_gate.approves(version.artifact),
            version.brief,
            version.team,
            twins=_json_twins(snapshot["twin_versions"]),
            revision_pending=bool(row["twins_revision_pending"]),
            archetypes_current=_roster_matches(snapshot, row["archetype_versions"] or ()),
        )
    requirements = None
    specification = None
    if progress.requirements is not None:
        specification = specification_from_snapshot(row["requirements_content"])
        requirements = RequirementsFacts(
            progress.requirements,
            progress.requirements_gate is not None
            and progress.requirements_gate.approves(progress.requirements),
            _json_reference(specification.project_brief_reference.to_snapshot()),
            _json_reference(specification.agent_team_reference.to_snapshot()),
            _json_reference(specification.user_modeling_reference.to_snapshot()),
            twins=_json_twins(
                [reference.to_snapshot() for reference in specification.user_twin_references]
            ),
            cited_twin_ids=referenced_twin_ids(specification),
            actor_codes=requirements_actor_codes(specification),
            revision_pending=bool(row["requirements_revision_pending"]),
        )
    design = None
    if progress.design is not None:
        package = design_package_from_snapshot(row["design_content"])
        grounding = package.grounding
        missing = False
        if specification is not None:
            available = (
                frozenset(item.id for item in specification.requirements),
                frozenset(item.id for item in specification.user_stories),
                frozenset(item.id for item in specification.acceptance_criteria),
            )
            missing = any(
                cited - present
                for cited, present in zip(_cited_items(package), available, strict=True)
            )
        design = DesignFacts(
            progress.design,
            progress.design_gate is not None and progress.design_gate.approves(progress.design),
            _json_reference(grounding.requirements_reference.to_snapshot()),
            _json_reference(grounding.agent_team_reference.to_snapshot()),
            _json_reference(grounding.user_modeling_reference.to_snapshot()),
            twins=_json_twins(
                [reference.to_snapshot() for reference in grounding.user_twin_references]
            ),
            revision_pending=bool(row["design_revision_pending"]),
            missing_codes=("MISSING_REFERENCES",) if missing else (),
        )
    return SectionFacts(
        brief=brief, team=team_facts, user_twins=twins, requirements=requirements, design=design
    )


def project_overview(row: Mapping[str, Any]) -> ProjectOverview:
    sections = overview_section_facts(row)
    return ProjectOverview(
        project=_project(row),
        progress=project_progress(
            progress_facts(row),
            sections=None if sections is None else project_sections(sections),
        ),
    )


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
