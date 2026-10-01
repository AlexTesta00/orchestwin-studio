from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final
from uuid import UUID

from orchestwin.projects.progress import ArtifactVersion, ProjectStage


class SectionState(StrEnum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    FINE = "FINE"
    UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
    TO_UPDATE = "TO_UPDATE"


class SectionReason(StrEnum):
    BRIEF_CHANGED = "BRIEF_CHANGED"
    PERSPECTIVES_CHANGED = "PERSPECTIVES_CHANGED"
    ARCHETYPES_CHANGED = "ARCHETYPES_CHANGED"
    USER_TWINS_CHANGED = "USER_TWINS_CHANGED"
    REQUIREMENTS_CHANGED = "REQUIREMENTS_CHANGED"
    FOLDER_BEHIND = "FOLDER_BEHIND"
    TWINS_LEARNED = "TWINS_LEARNED"
    REQUIREMENTS_NOT_COVERED = "REQUIREMENTS_NOT_COVERED"
    EVALUATION_MISSING = "EVALUATION_MISSING"


class SectionBlock(StrEnum):
    REQUIREMENT_NO_LONGER_AVAILABLE = "REQUIREMENT_NO_LONGER_AVAILABLE"
    TWIN_SET_CHANGED = "TWIN_SET_CHANGED"
    TWIN_NO_LONGER_AVAILABLE = "TWIN_NO_LONGER_AVAILABLE"
    REVISION_PENDING = "REVISION_PENDING"
    UPSTREAM_NOT_READY = "UPSTREAM_NOT_READY"
    PREPARE_AGAIN = "PREPARE_AGAIN"
    PREPARE_TWINS = "PREPARE_TWINS"


ALIGNABLE_SECTIONS: Final = (
    ProjectStage.TEAM,
    ProjectStage.USER_TWINS,
    ProjectStage.REQUIREMENTS,
    ProjectStage.DESIGN,
)
FOLDER_STAGES: Final = (
    ProjectStage.BRIEF,
    ProjectStage.TEAM,
    ProjectStage.USER_TWINS,
    ProjectStage.REQUIREMENTS,
    ProjectStage.DESIGN,
)
_NOT_READY: Final = frozenset({SectionState.NOT_STARTED, SectionState.IN_PROGRESS})


@dataclass(frozen=True, slots=True)
class BriefFacts:
    version: ArtifactVersion
    approved: bool


@dataclass(frozen=True, slots=True)
class TeamFacts:
    version: ArtifactVersion
    approved: bool
    brief: ArtifactVersion
    alignable: bool = False


@dataclass(frozen=True, slots=True)
class UserTwinsFacts:
    version: ArtifactVersion
    approved: bool
    brief: ArtifactVersion
    team: ArtifactVersion
    twins: frozenset[ArtifactVersion] = frozenset()
    revision_pending: bool = False
    learned: bool = False
    archetypes_current: bool = True

    @property
    def twin_ids(self) -> frozenset[UUID]:
        return frozenset(twin.artifact_id for twin in self.twins)


@dataclass(frozen=True, slots=True)
class RequirementsFacts:
    version: ArtifactVersion
    approved: bool
    brief: ArtifactVersion
    team: ArtifactVersion
    user_modeling: ArtifactVersion
    twins: frozenset[ArtifactVersion] = frozenset()
    cited_twin_ids: frozenset[UUID] = frozenset()
    revision_pending: bool = False

    @property
    def twin_ids(self) -> frozenset[UUID]:
        return frozenset(twin.artifact_id for twin in self.twins)


@dataclass(frozen=True, slots=True)
class DesignFacts:
    version: ArtifactVersion
    approved: bool
    requirements: ArtifactVersion
    team: ArtifactVersion
    user_modeling: ArtifactVersion
    twins: frozenset[ArtifactVersion] = frozenset()
    revision_pending: bool = False
    missing_codes: tuple[str, ...] = ()
    uncovered_codes: tuple[str, ...] = ()
    has_mockup: bool = False
    reviewed: bool = False

    @property
    def twin_ids(self) -> frozenset[UUID]:
        return frozenset(twin.artifact_id for twin in self.twins)


@dataclass(frozen=True, slots=True)
class FolderFacts:
    version_number: int
    stages: Mapping[ProjectStage, ArtifactVersion] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SectionFacts:
    brief: BriefFacts | None = None
    team: TeamFacts | None = None
    user_twins: UserTwinsFacts | None = None
    requirements: RequirementsFacts | None = None
    design: DesignFacts | None = None
    folder: FolderFacts | None = None
    design_approved_once: bool = False


@dataclass(frozen=True, slots=True)
class Section:
    key: ProjectStage
    state: SectionState
    version_number: int | None = None
    reasons: tuple[SectionReason, ...] = ()
    blocked: SectionBlock | None = None
    codes: tuple[str, ...] = ()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "key": self.key.value,
            "state": self.state.value,
            "version_number": self.version_number,
            "reasons": [reason.value for reason in self.reasons],
            "blocked": None if self.blocked is None else self.blocked.value,
            "codes": list(self.codes),
        }


@dataclass(frozen=True, slots=True)
class SectionAlignment:
    available: bool = False
    sections: tuple[ProjectStage, ...] = ()
    uncovered_codes: tuple[str, ...] = ()

    def to_snapshot(self) -> dict[str, object]:
        return {
            "available": self.available,
            "sections": [key.value for key in self.sections],
            "uncovered_codes": list(self.uncovered_codes),
        }


@dataclass(frozen=True, slots=True)
class ProjectSections:
    first_pass_complete: bool
    sections: tuple[Section, ...]
    alignment: SectionAlignment

    def section(self, key: ProjectStage) -> Section:
        return next(section for section in self.sections if section.key is key)

    def to_snapshot(self) -> dict[str, object]:
        return {
            "first_pass_complete": self.first_pass_complete,
            "sections": [section.to_snapshot() for section in self.sections],
            "alignment": self.alignment.to_snapshot(),
        }


_Obstacle = tuple[SectionBlock, tuple[str, ...]]
_Stage = BriefFacts | TeamFacts | UserTwinsFacts | RequirementsFacts | DesignFacts


def _ordered(reasons: Iterable[SectionReason]) -> tuple[SectionReason, ...]:
    wanted = frozenset(reasons)
    return tuple(reason for reason in SectionReason if reason in wanted)


def _ready(upstream: Iterable[Section]) -> bool:
    return all(
        section.state not in _NOT_READY
        and not (section.state is SectionState.TO_UPDATE and section.blocked is not None)
        for section in upstream
    )


def _blocked(upstream: tuple[Section, ...], obstacles: Iterable[_Obstacle]) -> _Obstacle | None:
    if not _ready(upstream):
        return SectionBlock.UPSTREAM_NOT_READY, ()
    return next(iter(obstacles), None)


def _section(
    key: ProjectStage,
    version: ArtifactVersion | None,
    *,
    approved: bool,
    upstream: tuple[Section, ...] = (),
    behind: Iterable[SectionReason] = (),
    obstacles: Iterable[_Obstacle] = (),
    offered: Iterable[SectionReason] = (),
    offered_codes: tuple[str, ...] = (),
) -> Section:
    if version is None:
        return Section(key=key, state=SectionState.NOT_STARTED)
    number = version.version_number
    if not approved:
        return Section(key=key, state=SectionState.IN_PROGRESS, version_number=number)
    reasons = _ordered(behind)
    if reasons:
        blocked = _blocked(upstream, obstacles)
        return Section(
            key=key,
            state=SectionState.TO_UPDATE,
            version_number=number,
            reasons=reasons,
            blocked=None if blocked is None else blocked[0],
            codes=() if blocked is None else blocked[1],
        )
    available = _ordered(offered)
    if available:
        return Section(
            key=key,
            state=SectionState.UPDATE_AVAILABLE,
            version_number=number,
            reasons=available,
            codes=offered_codes if SectionReason.REQUIREMENTS_NOT_COVERED in available else (),
        )
    return Section(key=key, state=SectionState.FINE, version_number=number)


def _version(facts: _Stage | None) -> ArtifactVersion | None:
    return None if facts is None else facts.version


def _behind(section: Section) -> bool:
    return section.state is SectionState.TO_UPDATE


def _brief_section(facts: SectionFacts) -> Section:
    brief = facts.brief
    return _section(
        ProjectStage.BRIEF,
        _version(brief),
        approved=brief is not None and brief.approved,
    )


def _team_section(facts: SectionFacts, brief: Section) -> Section:
    team = facts.team
    if team is None:
        return _section(ProjectStage.TEAM, None, approved=False)
    return _section(
        ProjectStage.TEAM,
        team.version,
        approved=team.approved,
        upstream=(brief,),
        behind=(SectionReason.BRIEF_CHANGED,) if team.brief != _version(facts.brief) else (),
        obstacles=() if team.alignable else ((SectionBlock.PREPARE_AGAIN, ()),),
    )


def _user_twins_section(facts: SectionFacts, brief: Section, team: Section) -> Section:
    twins = facts.user_twins
    if twins is None:
        return _section(ProjectStage.USER_TWINS, None, approved=False)
    behind = []
    if twins.brief != _version(facts.brief):
        behind.append(SectionReason.BRIEF_CHANGED)
    if twins.team != _version(facts.team) or _behind(team):
        behind.append(SectionReason.PERSPECTIVES_CHANGED)
    if not twins.archetypes_current:
        behind.append(SectionReason.ARCHETYPES_CHANGED)
    obstacles = []
    if not twins.archetypes_current:
        obstacles.append((SectionBlock.PREPARE_TWINS, ()))
    if twins.revision_pending:
        obstacles.append((SectionBlock.REVISION_PENDING, ()))
    return _section(
        ProjectStage.USER_TWINS,
        twins.version,
        approved=twins.approved,
        upstream=(brief, team),
        behind=behind,
        obstacles=obstacles,
        offered=(SectionReason.TWINS_LEARNED,) if twins.learned else (),
    )


def _requirements_obstacles(facts: SectionFacts) -> list[_Obstacle]:
    requirements = facts.requirements
    twins = facts.user_twins
    obstacles: list[_Obstacle] = []
    if requirements is None:
        return obstacles
    if twins is not None and not requirements.cited_twin_ids <= twins.twin_ids:
        obstacles.append((SectionBlock.TWIN_NO_LONGER_AVAILABLE, ()))
    if requirements.revision_pending:
        obstacles.append((SectionBlock.REVISION_PENDING, ()))
    return obstacles


def _requirements_section(facts: SectionFacts, upstream: tuple[Section, ...]) -> Section:
    requirements = facts.requirements
    if requirements is None:
        return _section(ProjectStage.REQUIREMENTS, None, approved=False)
    _, team, twins = upstream
    snapshot = facts.user_twins
    behind = []
    if requirements.brief != _version(facts.brief):
        behind.append(SectionReason.BRIEF_CHANGED)
    if requirements.team != _version(facts.team) or _behind(team):
        behind.append(SectionReason.PERSPECTIVES_CHANGED)
    if (
        snapshot is None
        or requirements.user_modeling != snapshot.version
        or requirements.twins != snapshot.twins
        or _behind(twins)
    ):
        behind.append(SectionReason.USER_TWINS_CHANGED)
    return _section(
        ProjectStage.REQUIREMENTS,
        requirements.version,
        approved=requirements.approved,
        upstream=upstream,
        behind=behind,
        obstacles=_requirements_obstacles(facts),
    )


def _design_obstacles(facts: SectionFacts) -> list[_Obstacle]:
    design = facts.design
    requirements = facts.requirements
    obstacles: list[_Obstacle] = []
    if design is None:
        return obstacles
    if design.missing_codes:
        obstacles.append((SectionBlock.REQUIREMENT_NO_LONGER_AVAILABLE, design.missing_codes))
    if requirements is not None and design.twin_ids != requirements.twin_ids:
        obstacles.append((SectionBlock.TWIN_SET_CHANGED, ()))
    if design.revision_pending:
        obstacles.append((SectionBlock.REVISION_PENDING, ()))
    return obstacles


def _design_section(facts: SectionFacts, upstream: tuple[Section, ...]) -> Section:
    design = facts.design
    if design is None:
        return _section(ProjectStage.DESIGN, None, approved=False)
    requirements = facts.requirements
    behind = []
    if requirements is None or design.requirements != requirements.version or _behind(upstream[-1]):
        behind.append(SectionReason.REQUIREMENTS_CHANGED)
    if requirements is not None and (
        design.user_modeling != requirements.user_modeling or design.twins != requirements.twins
    ):
        behind.append(SectionReason.USER_TWINS_CHANGED)
    if requirements is not None and design.team != requirements.team:
        behind.append(SectionReason.PERSPECTIVES_CHANGED)
    offered = []
    if design.uncovered_codes:
        offered.append(SectionReason.REQUIREMENTS_NOT_COVERED)
    if design.has_mockup and not design.reviewed:
        offered.append(SectionReason.EVALUATION_MISSING)
    return _section(
        ProjectStage.DESIGN,
        design.version,
        approved=design.approved,
        upstream=upstream,
        behind=behind,
        obstacles=_design_obstacles(facts),
        offered=offered,
        offered_codes=design.uncovered_codes,
    )


def _approved_chain(facts: SectionFacts) -> tuple[tuple[ProjectStage, ArtifactVersion], ...]:
    chain: list[tuple[ProjectStage, ArtifactVersion]] = []
    for key, stage in zip(
        FOLDER_STAGES,
        (facts.brief, facts.team, facts.user_twins, facts.requirements, facts.design),
        strict=True,
    ):
        if stage is None or not stage.approved:
            break
        chain.append((key, stage.version))
    return tuple(chain)


def _package_section(facts: SectionFacts, upstream: tuple[Section, ...]) -> Section:
    folder = facts.folder
    if folder is None:
        return Section(key=ProjectStage.PACKAGE, state=SectionState.NOT_STARTED)
    if dict(folder.stages) == dict(_approved_chain(facts)) and not any(
        section.state is SectionState.TO_UPDATE for section in upstream
    ):
        return Section(
            key=ProjectStage.PACKAGE,
            state=SectionState.FINE,
            version_number=folder.version_number,
        )
    waiting = any(
        section.state is SectionState.IN_PROGRESS
        or (section.state is SectionState.TO_UPDATE and section.blocked is not None)
        for section in upstream
    )
    return Section(
        key=ProjectStage.PACKAGE,
        state=SectionState.TO_UPDATE,
        version_number=folder.version_number,
        reasons=(SectionReason.FOLDER_BEHIND,),
        blocked=SectionBlock.UPSTREAM_NOT_READY if waiting else None,
    )


def _alignment(sections: tuple[Section, ...], facts: SectionFacts) -> SectionAlignment:
    behind = tuple(
        section
        for section in sections
        if section.key in ALIGNABLE_SECTIONS and section.state is SectionState.TO_UPDATE
    )
    available = bool(behind) and behind[0].blocked is None
    design = next((section for section in behind if section.key is ProjectStage.DESIGN), None)
    uncovered = (
        facts.design.uncovered_codes
        if available and design is not None and design.blocked is None and facts.design is not None
        else ()
    )
    return SectionAlignment(
        available=available,
        sections=tuple(section.key for section in behind),
        uncovered_codes=uncovered,
    )


def project_sections(facts: SectionFacts) -> ProjectSections:
    brief = _brief_section(facts)
    team = _team_section(facts, brief)
    twins = _user_twins_section(facts, brief, team)
    requirements = _requirements_section(facts, (brief, team, twins))
    design = _design_section(facts, (brief, team, twins, requirements))
    upstream = (brief, team, twins, requirements, design)
    sections = (*upstream, _package_section(facts, upstream))
    return ProjectSections(
        first_pass_complete=facts.design_approved_once
        or (facts.design is not None and facts.design.approved),
        sections=sections,
        alignment=_alignment(sections, facts),
    )


__all__ = [
    "ALIGNABLE_SECTIONS",
    "FOLDER_STAGES",
    "BriefFacts",
    "DesignFacts",
    "FolderFacts",
    "ProjectSections",
    "RequirementsFacts",
    "Section",
    "SectionAlignment",
    "SectionBlock",
    "SectionFacts",
    "SectionReason",
    "SectionState",
    "TeamFacts",
    "UserTwinsFacts",
    "project_sections",
]
