from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

from orchestwin.agents.proposals import TeamProposalVersion
from orchestwin.artifacts.design_discussion import DesignDiscussion, DiscussionStatus
from orchestwin.artifacts.design_evaluation import DesignEvaluationRun
from orchestwin.artifacts.design_finding_validations import FindingValidation
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.projects.briefs import ProjectBriefVersion
from orchestwin.projects.insight_applications import InsightApplication
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.twins.user_twins import UserModelingSnapshotVersion
from orchestwin.workflow.gates import HumanGate


@dataclass(frozen=True, slots=True)
class KnowledgeFeedback:
    runs: tuple[DesignEvaluationRun, ...] = ()
    validations: tuple[FindingValidation, ...] = ()
    discussions: tuple[DesignDiscussion, ...] = ()
    applications: tuple[InsightApplication, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (self.runs or self.validations or self.discussions or self.applications)


def knowledge_feedback(
    *,
    runs: Iterable[DesignEvaluationRun] = (),
    validations: Iterable[FindingValidation] = (),
    discussions: Iterable[DesignDiscussion] = (),
    applications: Iterable[InsightApplication] = (),
) -> KnowledgeFeedback:
    kept_runs = tuple(sorted(runs, key=lambda item: (item.started_at, str(item.id))))
    run_ids = {item.id for item in kept_runs}
    return KnowledgeFeedback(
        runs=kept_runs,
        validations=tuple(
            sorted(
                (item for item in validations if item.evaluation_run_id in run_ids),
                key=lambda item: (
                    str(item.evaluation_run_id),
                    str(item.twin_id),
                    item.finding_id,
                    item.sequence_number,
                ),
            )
        ),
        discussions=tuple(
            sorted(
                (item for item in discussions if item.status is DiscussionStatus.APPROVED),
                key=lambda item: (item.created_at, str(item.id)),
            )
        ),
        applications=tuple(sorted(applications, key=lambda item: (item.created_at, str(item.id)))),
    )


@dataclass(frozen=True, slots=True)
class KnowledgeSources:
    project_id: UUID
    project_name: str
    brief: ProjectBriefVersion
    brief_gate: HumanGate
    team: TeamProposalVersion
    team_gate: HumanGate
    modeling: UserModelingSnapshotVersion
    modeling_gate: HumanGate
    requirements: RequirementsSpecificationVersion
    requirements_gate: HumanGate
    design: DesignPackageVersion
    design_gate: HumanGate
    feedback: KnowledgeFeedback = field(default_factory=KnowledgeFeedback)

    def version(self, stage: str):
        return {
            "brief": self.brief,
            "team": self.team,
            "twins": self.modeling,
            "requirements": self.requirements,
            "design": self.design,
        }[stage]

    def gate(self, stage: str) -> HumanGate:
        return {
            "brief": self.brief_gate,
            "team": self.team_gate,
            "twins": self.modeling_gate,
            "requirements": self.requirements_gate,
            "design": self.design_gate,
        }[stage]

    def payload(self, stage: str) -> dict[str, object]:
        return {
            "brief": lambda: self.brief.brief.to_snapshot(),
            "team": lambda: self.team.proposal.to_snapshot(),
            "twins": lambda: self.modeling.snapshot.to_snapshot(),
            "requirements": lambda: self.requirements.specification.to_snapshot(),
            "design": lambda: self.design.package.to_snapshot(),
        }[stage]()


@dataclass(frozen=True, slots=True)
class StageIdentity:
    id: UUID
    project_id: UUID
    version_number: int
    content_hash: str


def _same(reference: Mapping[str, object], version: object, key: str = "artifact_id") -> bool:
    return (
        str(reference[key]) == str(version.id)
        and reference["version_number"] == version.version_number
        and reference["content_hash"] == version.content_hash
    )


def stage_consistency_issue(
    project_id: UUID,
    versions: Mapping[str, object],
    payloads: Mapping[str, Mapping[str, object]],
) -> str | None:
    if any(version.project_id != project_id for version in versions.values()):
        return "PROJECT_MISMATCH"
    brief, team, modeling = versions["brief"], versions["team"], versions["twins"]
    if not _same(payloads["team"]["brief_version"], brief, "id"):
        return "TEAM_OUTDATED"
    snapshot = payloads["twins"]
    if not _same(snapshot["project_brief_reference"], brief) or not _same(
        snapshot["agent_team_reference"], team
    ):
        return "USER_TWINS_OUTDATED"
    context = payloads["requirements"]["context"]
    if (
        not _same(context["project_brief"], brief)
        or not _same(context["agent_team"], team)
        or not _same(context["user_modeling"], modeling)
    ):
        return "REQUIREMENTS_OUTDATED"
    grounding = payloads["design"]["grounding"]
    if (
        not _same(grounding["requirements_reference"], versions["requirements"])
        or not _same(grounding["agent_team_reference"], team)
        or not _same(grounding["user_modeling_reference"], modeling)
    ):
        return "DESIGN_OUTDATED"
    return None


def consistency_issue(sources: KnowledgeSources) -> str | None:
    stages = ("brief", "team", "twins", "requirements", "design")
    return stage_consistency_issue(
        sources.project_id,
        {stage: sources.version(stage) for stage in stages},
        {stage: sources.payload(stage) for stage in stages},
    )


__all__ = [
    "KnowledgeFeedback",
    "KnowledgeSources",
    "StageIdentity",
    "consistency_issue",
    "knowledge_feedback",
    "stage_consistency_issue",
]
