from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Final, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from orchestwin.artifacts.design_evaluation_persistence import RUNS
from orchestwin.artifacts.design_packages import DesignPackageVersion
from orchestwin.artifacts.design_persistence import (
    SqlAlchemyDesignDiffRepository,
    SqlAlchemyDesignPackageRepository,
)
from orchestwin.artifacts.workflow_inputs_persistence import SqlAlchemyWorkflowInputsRepository
from orchestwin.knowledge.package_persistence import SqlAlchemyKnowledgePackageRepository
from orchestwin.knowledge.packages import KnowledgePackageVersion
from orchestwin.projects.persistence.models import ProjectRecord
from orchestwin.projects.persistence.progress import (
    overview_section_facts,
    overview_statement,
    progress_facts,
)
from orchestwin.projects.progress import ArtifactVersion, GateState, ProjectStage
from orchestwin.projects.requirements_persistence import (
    SqlAlchemyRequirementsDiffRepository,
    SqlAlchemyRequirementsSpecificationRepository,
)
from orchestwin.projects.requirements_realignment import referenced_twin_ids
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.projects.sections import (
    BriefFacts,
    DesignFacts,
    FolderFacts,
    ProjectSections,
    RequirementsFacts,
    SectionBlock,
    SectionFacts,
    SectionState,
    TeamFacts,
    UserTwinsFacts,
    project_sections,
    requirements_actor_codes,
)
from orchestwin.twins.persistence.repositories import SqlAlchemyUserModelingSnapshotRepository
from orchestwin.twins.revision_persistence import SqlAlchemyUserTwinProfileDiffRepository
from orchestwin.twins.user_twins import UserModelingSnapshotVersion
from orchestwin.workflow.gates import (
    HumanGate,
    HumanGateAction,
    HumanGateEventKind,
    HumanGateIssueCode,
    HumanGateType,
    next_human_gate_iteration,
)
from orchestwin.workflow.persistence.models import HumanGateEventRecord

ALIGNMENT_REASON: Final = "Aligned to the current upstream versions with unchanged content."
PROJECT_NOT_FOUND: Final = "PROJECT_NOT_FOUND"
ITERATION_LIMIT_REACHED: Final = "ITERATION_LIMIT_REACHED"
FOLDER_STAGE_KEYS: Final = {
    "brief": ProjectStage.BRIEF,
    "team": ProjectStage.TEAM,
    "twins": ProjectStage.USER_TWINS,
    "requirements": ProjectStage.REQUIREMENTS,
    "design": ProjectStage.DESIGN,
}
_SUBMITTED: Final = frozenset({"SUBMITTED", "ALREADY_PENDING"})
_ALREADY_APPROVED: Final = "ALREADY_APPROVED"
_APPLIED: Final = "APPLIED"
_ISSUES: Final = {
    "ARCHETYPES_CHANGED": SectionBlock.PREPARE_TWINS.value,
    "USER_TWIN_REVISION_PENDING": SectionBlock.REVISION_PENDING.value,
    "REQUIREMENTS_REVISION_PENDING": SectionBlock.REVISION_PENDING.value,
    "DESIGN_REVISION_PENDING": SectionBlock.REVISION_PENDING.value,
    "BRIEF_APPROVAL_REQUIRED": SectionBlock.UPSTREAM_NOT_READY.value,
    "TEAM_APPROVAL_REQUIRED": SectionBlock.UPSTREAM_NOT_READY.value,
    "USER_TWINS_REQUIRED": SectionBlock.UPSTREAM_NOT_READY.value,
    "USER_TWINS_APPROVAL_REQUIRED": SectionBlock.UPSTREAM_NOT_READY.value,
    "REQUIREMENTS_APPROVAL_REQUIRED": SectionBlock.UPSTREAM_NOT_READY.value,
}
_LEARNING_STATES: Final = frozenset({SectionState.FINE})
_DESIGN_STATES: Final = frozenset(
    {SectionState.FINE, SectionState.UPDATE_AVAILABLE, SectionState.TO_UPDATE}
)


class SectionsFailure(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SectionOutcome(StrEnum):
    ALIGNED = "ALIGNED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"


class SectionsAlignmentStatus(StrEnum):
    ALIGNED = "ALIGNED"
    PARTIAL = "PARTIAL"
    NOTHING_TO_ALIGN = "NOTHING_TO_ALIGN"


@dataclass(frozen=True, slots=True)
class SectionUpdate:
    key: ProjectStage
    outcome: SectionOutcome
    issue: str | None = None
    version_number: int | None = None
    codes: tuple[str, ...] = ()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "key": self.key.value,
            "outcome": self.outcome.value,
            "issue": self.issue,
            "version_number": self.version_number,
            "codes": list(self.codes),
        }


@dataclass(frozen=True, slots=True)
class SectionsAlignment:
    status: SectionsAlignmentStatus
    results: tuple[SectionUpdate, ...]
    sections: ProjectSections

    def to_snapshot(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "results": [result.to_snapshot() for result in self.results],
            "sections": self.sections.to_snapshot(),
        }


class SectionReads(Protocol):
    async def facts(self, *, owner_user_id: UUID, project_id: UUID) -> SectionFacts | None: ...


class SectionRealignment(Protocol):
    async def status(self, *, owner_user_id: UUID, project_id: UUID) -> object: ...

    async def realign(self, *, owner_user_id: UUID, project_id: UUID) -> object: ...


class DesignAlignmentView(Protocol):
    @property
    def missing_codes(self) -> Sequence[str]: ...

    @property
    def uncovered_codes(self) -> Sequence[str]: ...


class DesignAlignmentQueries(Protocol):
    async def status(self, *, owner_user_id: UUID, project_id: UUID) -> DesignAlignmentView: ...


class GateSubmission(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def gate(self) -> HumanGate | None: ...


class GateDecision(Protocol):
    @property
    def status(self) -> str: ...

    @property
    def gate(self) -> HumanGate | None: ...

    @property
    def issue(self) -> HumanGateIssueCode | None: ...


class SectionGate(Protocol):
    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID) -> HumanGate | None: ...

    async def submit(self, *, project_id: UUID, owner_user_id: UUID) -> GateSubmission: ...

    async def decide(
        self,
        *,
        project_id: UUID,
        owner_user_id: UUID,
        action: HumanGateAction,
        reason: str | None = None,
    ) -> GateDecision: ...


class TwinLearningQueries(Protocol):
    async def learned(self, *, owner_user_id: UUID, project_id: UUID) -> bool: ...


@dataclass(frozen=True, slots=True)
class SectionStep:
    realignment: SectionRealignment
    gate: SectionGate
    failure: type[Exception]


class _Versioned(Protocol):
    @property
    def id(self) -> UUID: ...

    @property
    def version_number(self) -> int: ...

    @property
    def content_hash(self) -> str: ...


class _Referenced(Protocol):
    @property
    def artifact_id(self) -> UUID: ...

    @property
    def version_number(self) -> int: ...

    @property
    def content_hash(self) -> str: ...


class _TwinReferenced(Protocol):
    @property
    def twin_id(self) -> UUID: ...

    @property
    def version_number(self) -> int: ...

    @property
    def content_hash(self) -> str: ...


def _identity(version: _Versioned) -> ArtifactVersion:
    return ArtifactVersion(
        artifact_id=version.id,
        version_number=version.version_number,
        content_hash=version.content_hash,
    )


def _reference(reference: _Referenced) -> ArtifactVersion:
    return ArtifactVersion(
        artifact_id=reference.artifact_id,
        version_number=reference.version_number,
        content_hash=reference.content_hash,
    )


def _twins(references: Iterable[_TwinReferenced]) -> frozenset[ArtifactVersion]:
    return frozenset(
        ArtifactVersion(
            artifact_id=reference.twin_id,
            version_number=reference.version_number,
            content_hash=reference.content_hash,
        )
        for reference in references
    )


def _approved(gate: GateState | None, version: ArtifactVersion) -> bool:
    return gate is not None and gate.approves(version)


def user_twins_facts(
    snapshot: UserModelingSnapshotVersion,
    *,
    gate: GateState | None,
    revision_pending: bool = False,
    archetypes_current: bool = True,
) -> UserTwinsFacts:
    version = _identity(snapshot)
    return UserTwinsFacts(
        version=version,
        approved=_approved(gate, version),
        brief=_reference(snapshot.snapshot.project_brief_reference),
        team=_reference(snapshot.snapshot.agent_team_reference),
        twins=_twins(snapshot.snapshot.twin_versions),
        revision_pending=revision_pending,
        archetypes_current=archetypes_current,
    )


def requirements_facts(
    requirements: RequirementsSpecificationVersion,
    *,
    gate: GateState | None,
    revision_pending: bool = False,
) -> RequirementsFacts:
    version = _identity(requirements)
    specification = requirements.specification
    return RequirementsFacts(
        version=version,
        approved=_approved(gate, version),
        brief=_reference(specification.project_brief_reference),
        team=_reference(specification.agent_team_reference),
        user_modeling=_reference(specification.user_modeling_reference),
        twins=_twins(specification.user_twin_references),
        cited_twin_ids=referenced_twin_ids(specification),
        actor_codes=requirements_actor_codes(specification),
        revision_pending=revision_pending,
    )


def design_has_mockup(design: DesignPackageVersion) -> bool:
    package = design.package
    return package.owner_selected_alternative_id is not None and package.prototype is not None


def design_facts(
    design: DesignPackageVersion,
    *,
    gate: GateState | None,
    revision_pending: bool = False,
    reviewed: bool = False,
) -> DesignFacts:
    version = _identity(design)
    grounding = design.package.grounding
    return DesignFacts(
        version=version,
        approved=_approved(gate, version),
        requirements=_reference(grounding.requirements_reference),
        team=_reference(grounding.agent_team_reference),
        user_modeling=_reference(grounding.user_modeling_reference),
        twins=_twins(grounding.user_twin_references),
        revision_pending=revision_pending,
        has_mockup=design_has_mockup(design),
        reviewed=reviewed,
    )


def _held_stage(entry: object) -> ArtifactVersion | None:
    if not isinstance(entry, Mapping):
        return None
    identifier = entry.get("version_id")
    number = entry.get("version_number")
    content_hash = entry.get("content_hash")
    if (
        not isinstance(identifier, str)
        or isinstance(number, bool)
        or not isinstance(number, int)
        or not isinstance(content_hash, str)
    ):
        return None
    try:
        artifact_id = UUID(identifier)
    except ValueError:
        return None
    return ArtifactVersion(
        artifact_id=artifact_id, version_number=number, content_hash=content_hash
    )


def folder_facts(folder: KnowledgePackageVersion) -> FolderFacts:
    stages = folder.manifest.get("stages")
    held: dict[ProjectStage, ArtifactVersion] = {}
    if isinstance(stages, Mapping):
        for name, key in FOLDER_STAGE_KEYS.items():
            stage = _held_stage(stages.get(name))
            if stage is not None:
                held[key] = stage
    return FolderFacts(version_number=folder.version_number, stages=held)


async def _twins_revision_pending(
    session: AsyncSession,
    snapshot: UserModelingSnapshotVersion,
    *,
    owner_user_id: UUID,
    project_id: UUID,
) -> bool:
    diffs = SqlAlchemyUserTwinProfileDiffRepository(session, owner_user_id=owner_user_id)
    for twin in snapshot.snapshot.twin_versions:
        proposed = await diffs.current_proposed(
            project_id=project_id,
            base_snapshot_version_id=snapshot.id,
            twin_id=twin.twin_id,
        )
        if proposed is not None:
            return True
    return False


async def _design_approved_once(
    session: AsyncSession, *, owner_user_id: UUID, project_id: UUID
) -> bool:
    statement = sa.select(
        sa.exists().where(
            HumanGateEventRecord.project_id == project_id,
            HumanGateEventRecord.gate_type == HumanGateType.DESIGN.value,
            HumanGateEventRecord.kind == HumanGateEventKind.APPROVE.value,
            ProjectRecord.id == HumanGateEventRecord.project_id,
            ProjectRecord.owner_user_id == owner_user_id,
        )
    )
    return bool((await session.execute(statement)).scalar_one())


async def _design_reviewed(
    session: AsyncSession, *, owner_user_id: UUID, project_id: UUID, design_version_id: UUID
) -> bool:
    statement = sa.select(
        sa.exists().where(
            RUNS.c.project_id == project_id,
            RUNS.c.owner_user_id == owner_user_id,
            RUNS.c.design_version_id == design_version_id,
        )
    )
    return bool((await session.execute(statement)).scalar_one())


class SqlAlchemySectionReads:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def facts(self, *, owner_user_id: UUID, project_id: UUID) -> SectionFacts | None:
        scope = {"owner_user_id": owner_user_id, "project_id": project_id}
        async with self._session_factory() as session:
            row = (await session.execute(overview_statement(**scope))).mappings().first()
            if row is None:
                return None
            progress = progress_facts(row)
            base = overview_section_facts(row)
            twins = (
                base.user_twins
                if base is not None
                else (
                    None
                    if progress.user_twins is None
                    else await self._user_twins(session, progress.user_twins_gate, **scope)
                )
            )
            requirements = (
                None
                if progress.requirements is None
                else await self._requirements(session, progress.requirements_gate, **scope)
            )
            design = await self._design(session, progress.design_gate, **scope)
            folder = await SqlAlchemyKnowledgePackageRepository(
                session, owner_user_id=owner_user_id
            ).latest(project_id=project_id)
            approved_once = await _design_approved_once(session, **scope)
        team = progress.team
        return SectionFacts(
            brief=(
                None
                if progress.brief is None
                else BriefFacts(
                    version=progress.brief,
                    approved=_approved(progress.brief_gate, progress.brief),
                )
            ),
            team=base.team
            if base is not None
            else (
                None
                if team is None
                else TeamFacts(
                    version=team.artifact,
                    approved=_approved(progress.team_gate, team.artifact),
                    brief=team.brief,
                )
            ),
            user_twins=twins,
            requirements=requirements,
            design=design,
            folder=None if folder is None else folder_facts(folder),
            design_approved_once=approved_once,
        )

    @staticmethod
    async def _user_twins(
        session: AsyncSession,
        gate: GateState | None,
        *,
        owner_user_id: UUID,
        project_id: UUID,
        archetypes_current: bool = True,
    ) -> UserTwinsFacts | None:
        snapshot = await SqlAlchemyUserModelingSnapshotRepository(
            session, owner_user_id=owner_user_id
        ).current(project_id=project_id)
        if snapshot is None:
            return None
        facts = user_twins_facts(snapshot, gate=gate, archetypes_current=archetypes_current)
        if not facts.approved:
            return facts
        return replace(
            facts,
            revision_pending=await _twins_revision_pending(
                session, snapshot, owner_user_id=owner_user_id, project_id=project_id
            ),
        )

    @staticmethod
    async def _requirements(
        session: AsyncSession, gate: GateState | None, *, owner_user_id: UUID, project_id: UUID
    ) -> RequirementsFacts | None:
        version = await SqlAlchemyRequirementsSpecificationRepository(
            session, owner_user_id=owner_user_id
        ).current(project_id=project_id)
        if version is None:
            return None
        facts = requirements_facts(version, gate=gate)
        if not facts.approved:
            return facts
        proposed = await SqlAlchemyRequirementsDiffRepository(
            session, owner_user_id=owner_user_id
        ).current_proposed(project_id=project_id, base_version_id=version.id)
        return replace(facts, revision_pending=proposed is not None)

    @staticmethod
    async def _design(
        session: AsyncSession, gate: GateState | None, *, owner_user_id: UUID, project_id: UUID
    ) -> DesignFacts | None:
        version = await SqlAlchemyDesignPackageRepository(
            session, owner_user_id=owner_user_id
        ).current(project_id=project_id)
        provided = await SqlAlchemyWorkflowInputsRepository(
            session, owner_user_id=owner_user_id
        ).current(project_id)
        if provided is not None and (
            version is None
            or provided.created_at > version.created_at
            or (gate is not None and gate.artifact.artifact_id == provided.id)
        ):
            definition = await SqlAlchemyRequirementsSpecificationRepository(
                session, owner_user_id=owner_user_id
            ).current(project_id=project_id)
            if definition is not None:
                specification = definition.specification
                present = set(provided.mockup.requirement_codes)
                return DesignFacts(
                    version=_identity(provided),
                    approved=_approved(gate, _identity(provided)),
                    requirements=ArtifactVersion(
                        UUID(provided.definition_reference["artifact_id"]),
                        provided.definition_reference["version_number"],
                        provided.definition_reference["content_hash"],
                    ),
                    team=_reference(specification.agent_team_reference),
                    user_modeling=_reference(specification.user_modeling_reference),
                    twins=_twins(specification.user_twin_references),
                    uncovered_codes=tuple(
                        item.code for item in specification.requirements if item.code not in present
                    ),
                    provided=True,
                )
        if version is None:
            return None
        facts = design_facts(version, gate=gate)
        if not facts.approved:
            return facts
        proposed = await SqlAlchemyDesignDiffRepository(
            session, owner_user_id=owner_user_id
        ).current_proposed(project_id=project_id, base_version_id=version.id)
        reviewed = facts.has_mockup and await _design_reviewed(
            session,
            owner_user_id=owner_user_id,
            project_id=project_id,
            design_version_id=version.id,
        )
        return replace(facts, revision_pending=proposed is not None, reviewed=reviewed)


def _issue(code: str) -> str:
    return _ISSUES.get(code, code)


def _blocked(key: ProjectStage, code: str, codes: Iterable[str] = ()) -> SectionUpdate:
    return SectionUpdate(
        key=key, outcome=SectionOutcome.BLOCKED, issue=_issue(code), codes=tuple(codes)
    )


def _aligned(key: ProjectStage, gate: HumanGate | None) -> SectionUpdate:
    return SectionUpdate(
        key=key,
        outcome=SectionOutcome.ALIGNED,
        version_number=None if gate is None else gate.artifact.version,
    )


def alignment_status(results: Iterable[SectionUpdate]) -> SectionsAlignmentStatus:
    outcomes = [result.outcome for result in results]
    if SectionOutcome.ALIGNED not in outcomes:
        return SectionsAlignmentStatus.NOTHING_TO_ALIGN
    if SectionOutcome.BLOCKED in outcomes:
        return SectionsAlignmentStatus.PARTIAL
    return SectionsAlignmentStatus.ALIGNED


def _needs_design_alignment(facts: SectionFacts, draft: ProjectSections) -> bool:
    design = draft.section(ProjectStage.DESIGN)
    return (
        facts.design is not None
        and design.state in _DESIGN_STATES
        and design.blocked is not SectionBlock.UPSTREAM_NOT_READY
    )


class SectionsService:
    def __init__(
        self,
        *,
        reads: SectionReads,
        user_twins: SectionStep,
        requirements: SectionStep,
        design: SectionStep,
        design_alignment: DesignAlignmentQueries,
        twin_learning: TwinLearningQueries,
        team: SectionStep | None = None,
    ) -> None:
        self._reads = reads
        self._steps = {
            ProjectStage.USER_TWINS: user_twins,
            ProjectStage.REQUIREMENTS: requirements,
            ProjectStage.DESIGN: design,
        }
        if team is not None:
            self._steps[ProjectStage.TEAM] = team
        self._design_alignment = design_alignment
        self._twin_learning = twin_learning

    async def current(self, *, owner_user_id: UUID, project_id: UUID) -> ProjectSections:
        return await self._sections(owner_user_id=owner_user_id, project_id=project_id)

    async def align(self, *, owner_user_id: UUID, project_id: UUID) -> SectionsAlignment:
        before = await self._sections(
            owner_user_id=owner_user_id, project_id=project_id, learning=False
        )
        results: list[SectionUpdate] = []
        for key in before.alignment.sections:
            if results and results[-1].outcome is not SectionOutcome.ALIGNED:
                results.append(SectionUpdate(key=key, outcome=SectionOutcome.SKIPPED))
                continue
            current = (
                await self._sections(
                    owner_user_id=owner_user_id, project_id=project_id, learning=False
                )
                if results
                else before
            )
            section = current.section(key)
            if section.blocked is not None:
                results.append(_blocked(key, section.blocked.value, section.codes))
                continue
            results.append(
                await self._update(key, owner_user_id=owner_user_id, project_id=project_id)
            )
        after = await self._sections(owner_user_id=owner_user_id, project_id=project_id)
        return SectionsAlignment(
            status=alignment_status(results), results=tuple(results), sections=after
        )

    async def _sections(
        self, *, owner_user_id: UUID, project_id: UUID, learning: bool = True
    ) -> ProjectSections:
        facts = await self._reads.facts(owner_user_id=owner_user_id, project_id=project_id)
        if facts is None:
            raise SectionsFailure(PROJECT_NOT_FOUND)
        draft = project_sections(facts)
        twins = facts.user_twins
        if (
            learning
            and twins is not None
            and draft.section(ProjectStage.USER_TWINS).state in _LEARNING_STATES
        ):
            learned = await self._twin_learning.learned(
                owner_user_id=owner_user_id, project_id=project_id
            )
            facts = replace(facts, user_twins=replace(twins, learned=learned))
        if (
            facts.design is not None
            and not facts.design.provided
            and _needs_design_alignment(facts, draft)
        ):
            alignment = await self._design_alignment.status(
                owner_user_id=owner_user_id, project_id=project_id
            )
            facts = replace(
                facts,
                design=replace(
                    facts.design,
                    missing_codes=tuple(alignment.missing_codes),
                    uncovered_codes=tuple(alignment.uncovered_codes),
                ),
            )
        return project_sections(facts)

    async def _update(
        self, key: ProjectStage, *, owner_user_id: UUID, project_id: UUID
    ) -> SectionUpdate:
        if key not in self._steps:
            return _blocked(key, SectionBlock.PREPARE_AGAIN.value)
        step = self._steps[key]
        scope = {"project_id": project_id, "owner_user_id": owner_user_id}
        gate = await step.gate.current_gate(**scope)
        if gate is not None and next_human_gate_iteration(gate) is None:
            return _blocked(key, ITERATION_LIMIT_REACHED)
        try:
            await step.realignment.realign(owner_user_id=owner_user_id, project_id=project_id)
        except step.failure as error:
            return _blocked(
                key, str(getattr(error, "code", error)), getattr(error, "missing_codes", ())
            )
        submitted = await step.gate.submit(**scope)
        submission = str(submitted.status)
        if submission == _ALREADY_APPROVED:
            return _aligned(key, submitted.gate)
        if submission not in _SUBMITTED:
            return _blocked(key, submission)
        decided = await step.gate.decide(
            **scope, action=HumanGateAction.APPROVE, reason=ALIGNMENT_REASON
        )
        if str(decided.status) != _APPLIED:
            return _blocked(key, str(decided.issue or decided.status))
        return _aligned(key, decided.gate)


__all__ = [
    "ALIGNMENT_REASON",
    "FOLDER_STAGE_KEYS",
    "ITERATION_LIMIT_REACHED",
    "PROJECT_NOT_FOUND",
    "DesignAlignmentQueries",
    "DesignAlignmentView",
    "GateDecision",
    "GateSubmission",
    "SectionGate",
    "SectionOutcome",
    "SectionReads",
    "SectionRealignment",
    "SectionStep",
    "SectionUpdate",
    "SectionsAlignment",
    "SectionsAlignmentStatus",
    "SectionsFailure",
    "SectionsService",
    "SqlAlchemySectionReads",
    "TwinLearningQueries",
    "alignment_status",
    "design_facts",
    "design_has_mockup",
    "folder_facts",
    "requirements_facts",
    "user_twins_facts",
]
