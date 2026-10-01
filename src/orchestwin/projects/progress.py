from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

from orchestwin.agents.catalog import AGENT_CATALOG_CONTENT_HASH, AGENT_CATALOG_VERSION
from orchestwin.projects.domain import Project
from orchestwin.workflow.gates import HumanGateStatus


class ProjectStage(StrEnum):
    BRIEF = "BRIEF"
    TEAM = "TEAM"
    USER_TWINS = "USER_TWINS"
    REQUIREMENTS = "REQUIREMENTS"
    DESIGN = "DESIGN"
    PACKAGE = "PACKAGE"


class ProjectNextAction(StrEnum):
    DESCRIBE_IDEA = "DESCRIBE_IDEA"
    APPROVE_BRIEF = "APPROVE_BRIEF"
    APPROVE_TEAM = "APPROVE_TEAM"
    CONFIRM_TWINS = "CONFIRM_TWINS"
    APPROVE_REQUIREMENTS = "APPROVE_REQUIREMENTS"
    APPROVE_DESIGN = "APPROVE_DESIGN"
    DOWNLOAD_FOLDER = "DOWNLOAD_FOLDER"
    UPDATE_SECTIONS = "UPDATE_SECTIONS"
    PREPARE_TWINS = "PREPARE_TWINS"
    PREPARE_DESIGN = "PREPARE_DESIGN"


STAGE_ACTIONS: Final = {
    ProjectStage.BRIEF: ProjectNextAction.APPROVE_BRIEF,
    ProjectStage.TEAM: ProjectNextAction.APPROVE_TEAM,
    ProjectStage.USER_TWINS: ProjectNextAction.CONFIRM_TWINS,
    ProjectStage.REQUIREMENTS: ProjectNextAction.APPROVE_REQUIREMENTS,
    ProjectStage.DESIGN: ProjectNextAction.APPROVE_DESIGN,
    ProjectStage.PACKAGE: ProjectNextAction.DOWNLOAD_FOLDER,
}


@dataclass(frozen=True, slots=True)
class ArtifactVersion:
    artifact_id: UUID
    version_number: int
    content_hash: str


@dataclass(frozen=True, slots=True)
class GateState:
    status: HumanGateStatus
    artifact: ArtifactVersion

    def approves(self, artifact: ArtifactVersion | None) -> bool:
        return (
            artifact is not None
            and self.status is HumanGateStatus.APPROVED
            and self.artifact == artifact
        )


@dataclass(frozen=True, slots=True)
class CatalogVersion:
    version: int
    content_hash: str


CURRENT_CATALOG: Final = CatalogVersion(
    version=AGENT_CATALOG_VERSION,
    content_hash=AGENT_CATALOG_CONTENT_HASH,
)


@dataclass(frozen=True, slots=True)
class TeamState:
    artifact: ArtifactVersion
    brief: ArtifactVersion
    catalog: CatalogVersion


@dataclass(frozen=True, slots=True)
class UserTwinsState:
    artifact: ArtifactVersion
    brief: ArtifactVersion
    team: ArtifactVersion
    catalog: CatalogVersion


@dataclass(frozen=True, slots=True)
class ProjectProgressFacts:
    brief: ArtifactVersion | None = None
    brief_gate: GateState | None = None
    team: TeamState | None = None
    team_gate: GateState | None = None
    user_twins: UserTwinsState | None = None
    user_twins_gate: GateState | None = None
    requirements: ArtifactVersion | None = None
    requirements_gate: GateState | None = None
    design: ArtifactVersion | None = None
    design_gate: GateState | None = None


@dataclass(frozen=True, slots=True)
class ProjectProgress:
    current_stage: ProjectStage
    next_action: ProjectNextAction


@dataclass(frozen=True, slots=True)
class ProjectOverview:
    project: Project
    progress: ProjectProgress


class ProgressSectionView(Protocol):
    key: ProjectStage
    state: str
    blocked: str | None


class ProgressSectionAlignmentView(Protocol):
    available: bool
    sections: tuple[ProjectStage, ...]


class ProgressSectionsView(Protocol):
    sections: tuple[ProgressSectionView, ...]
    alignment: ProgressSectionAlignmentView


def _sections_progress(sections: ProgressSectionsView) -> ProjectProgress | None:
    for section in sections.sections:
        if section.key is ProjectStage.PACKAGE:
            break
        if section.state in {"NOT_STARTED", "IN_PROGRESS"}:
            return None
        if section.state != "TO_UPDATE":
            continue
        if sections.alignment.available:
            return ProjectProgress(section.key, ProjectNextAction.UPDATE_SECTIONS)
        if section.blocked == "PREPARE_TWINS":
            return ProjectProgress(ProjectStage.USER_TWINS, ProjectNextAction.PREPARE_TWINS)
        if section.key is ProjectStage.DESIGN and section.blocked in {
            "REQUIREMENT_NO_LONGER_AVAILABLE",
            "PREPARE_AGAIN",
        }:
            return ProjectProgress(ProjectStage.DESIGN, ProjectNextAction.PREPARE_DESIGN)
        return ProjectProgress(section.key, STAGE_ACTIONS[section.key])
    return None


def _approved(gate: GateState | None, artifact: ArtifactVersion | None) -> bool:
    return gate is not None and gate.approves(artifact)


def _team_approved(facts: ProjectProgressFacts) -> bool:
    team = facts.team
    return (
        team is not None and team.brief == facts.brief and _approved(facts.team_gate, team.artifact)
    )


def _user_twins_approved(facts: ProjectProgressFacts) -> bool:
    team = facts.team
    twins = facts.user_twins
    if team is None or twins is None:
        return False
    governed = _approved(facts.team_gate, team.artifact) and team.catalog == CURRENT_CATALOG
    grounded = (
        twins.brief == facts.brief and twins.team == team.artifact and twins.catalog == team.catalog
    )
    return governed and grounded and _approved(facts.user_twins_gate, twins.artifact)


def project_progress(
    facts: ProjectProgressFacts, *, sections: ProgressSectionsView | None = None
) -> ProjectProgress:
    if sections is not None:
        updated = _sections_progress(sections)
        if updated is not None:
            return updated
    brief_approved = _approved(facts.brief_gate, facts.brief)
    checks = (
        (ProjectStage.BRIEF, brief_approved),
        (ProjectStage.TEAM, brief_approved and _team_approved(facts)),
        (ProjectStage.USER_TWINS, brief_approved and _user_twins_approved(facts)),
        (ProjectStage.REQUIREMENTS, _approved(facts.requirements_gate, facts.requirements)),
        (ProjectStage.DESIGN, _approved(facts.design_gate, facts.design)),
    )
    for stage, complete in checks:
        if complete:
            continue
        if stage is ProjectStage.BRIEF and facts.brief is None:
            return ProjectProgress(stage, ProjectNextAction.DESCRIBE_IDEA)
        return ProjectProgress(stage, STAGE_ACTIONS[stage])
    return ProjectProgress(ProjectStage.PACKAGE, STAGE_ACTIONS[ProjectStage.PACKAGE])


__all__ = [
    "CURRENT_CATALOG",
    "STAGE_ACTIONS",
    "ArtifactVersion",
    "CatalogVersion",
    "GateState",
    "ProjectNextAction",
    "ProjectOverview",
    "ProjectProgress",
    "ProjectProgressFacts",
    "ProjectStage",
    "TeamState",
    "UserTwinsState",
    "project_progress",
]
