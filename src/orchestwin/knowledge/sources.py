from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from uuid import UUID

from orchestwin.agents.proposals import TeamProposalVersion
from orchestwin.artifacts.design_discussion import DesignDiscussion, DiscussionStatus
from orchestwin.artifacts.design_evaluation import DesignEvaluationRun
from orchestwin.artifacts.design_finding_validations import FindingValidation
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.knowledge.layout import STAGES
from orchestwin.knowledge.state import ProjectStateSources
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
    team: TeamProposalVersion | None = None
    team_gate: HumanGate | None = None
    modeling: UserModelingSnapshotVersion | None = None
    modeling_gate: HumanGate | None = None
    requirements: RequirementsSpecificationVersion | None = None
    requirements_gate: HumanGate | None = None
    design: DesignPackageVersion | None = None
    design_gate: HumanGate | None = None
    feedback: KnowledgeFeedback = field(default_factory=KnowledgeFeedback)
    state: ProjectStateSources = field(default_factory=ProjectStateSources)

    def __post_init__(self) -> None:
        given = [self._given(stage) for stage in STAGES]
        if not given[0]:
            raise ValueError("knowledge sources need the approved project brief")
        if given != sorted(given, reverse=True):
            raise ValueError("knowledge sources hold a stage only after every stage before it")

    def _pair(self, stage: str) -> tuple[object | None, HumanGate | None]:
        return {
            "brief": (self.brief, self.brief_gate),
            "team": (self.team, self.team_gate),
            "twins": (self.modeling, self.modeling_gate),
            "requirements": (self.requirements, self.requirements_gate),
            "design": (self.design, self.design_gate),
        }[stage]

    def _given(self, stage: str) -> bool:
        version, gate = self._pair(stage)
        return version is not None and gate is not None

    @property
    def present_stages(self) -> tuple[str, ...]:
        return tuple(stage for stage in STAGES if self._given(stage))

    @property
    def pending_stage(self) -> str | None:
        present = self.present_stages
        return None if len(present) == len(STAGES) else STAGES[len(present)]

    @property
    def complete(self) -> bool:
        return self.pending_stage is None

    def version(self, stage: str):
        if not self._given(stage):
            raise KeyError(stage)
        return self._pair(stage)[0]

    def gate(self, stage: str) -> HumanGate:
        if not self._given(stage):
            raise KeyError(stage)
        return self._pair(stage)[1]

    def payload(self, stage: str) -> dict[str, object]:
        version = self.version(stage)
        return {
            "brief": lambda: version.brief.to_snapshot(),
            "team": lambda: version.proposal.to_snapshot(),
            "twins": lambda: version.snapshot.to_snapshot(),
            "requirements": lambda: version.specification.to_snapshot(),
            "design": lambda: version.package.to_snapshot(),
        }[stage]()


@dataclass(frozen=True, slots=True)
class StageIdentity:
    id: UUID
    project_id: UUID
    version_number: int
    content_hash: str


def _same(
    reference: Mapping[str, object], version: object | None, key: str = "artifact_id"
) -> bool:
    return (
        version is not None
        and str(reference[key]) == str(version.id)
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
    brief, team, modeling = (versions.get(stage) for stage in ("brief", "team", "twins"))
    if "team" in versions and not _same(payloads["team"]["brief_version"], brief, "id"):
        return "TEAM_OUTDATED"
    if "twins" in versions:
        snapshot = payloads["twins"]
        if not _same(snapshot["project_brief_reference"], brief) or not _same(
            snapshot["agent_team_reference"], team
        ):
            return "USER_TWINS_OUTDATED"
    if "requirements" in versions:
        context = payloads["requirements"]["context"]
        if (
            not _same(context["project_brief"], brief)
            or not _same(context["agent_team"], team)
            or not _same(context["user_modeling"], modeling)
        ):
            return "REQUIREMENTS_OUTDATED"
    if "design" in versions:
        grounding = payloads["design"]["grounding"]
        if (
            not _same(grounding["requirements_reference"], versions.get("requirements"))
            or not _same(grounding["agent_team_reference"], team)
            or not _same(grounding["user_modeling_reference"], modeling)
        ):
            return "DESIGN_OUTDATED"
    return None


def consistency_issue(sources: KnowledgeSources) -> str | None:
    stages = sources.present_stages
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
