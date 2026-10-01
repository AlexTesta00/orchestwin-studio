from __future__ import annotations

import asyncio
import inspect
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID

import pytest

from orchestwin.artifacts.design_gate import DesignGateDecisionStatus, DesignGateSubmissionStatus
from orchestwin.knowledge.packages import KnowledgePackageVersion
from orchestwin.projects.design_realignment_service import (
    DesignAlignment,
    DesignRealignmentFailure,
)
from orchestwin.projects.progress import ArtifactVersion, GateState, ProjectStage
from orchestwin.projects.requirements_gate import (
    RequirementsGateDecisionStatus,
    RequirementsGateSubmissionStatus,
)
from orchestwin.projects.requirements_realignment_service import RequirementsRealignmentFailure
from orchestwin.projects.sections import (
    DesignFacts,
    FolderFacts,
    RequirementsFacts,
    SectionFacts,
    UserTwinsFacts,
)
from orchestwin.projects.sections_service import (
    ALIGNMENT_REASON,
    SectionOutcome,
    SectionsAlignmentStatus,
    SectionsFailure,
    SectionsService,
    SectionStep,
    SectionUpdate,
    alignment_status,
    design_facts,
    design_has_mockup,
    folder_facts,
    requirements_facts,
    user_twins_facts,
)
from orchestwin.twins.realignment_service import UserModelingRealignmentFailure
from orchestwin.twins.user_modeling_gate import (
    UserModelingGateDecisionStatus,
    UserModelingGateSubmissionStatus,
)
from orchestwin.workflow.gates import HumanGateIssueCode, HumanGateStatus
from src.test.python.artifacts import design_fixtures
from src.test.python.projects.test_requirements_realignment import first_snapshot
from src.test.python.projects.test_sections import (
    TWINS_2,
    aligned,
    artifact,
    design,
    requirements,
    team,
    twin,
    user_twins,
)

OWNER_ID = UUID("00000000-0000-4000-8000-0000000005a1")
STRANGER_ID = UUID("00000000-0000-4000-8000-0000000005a2")
PROJECT_ID = UUID("00000000-0000-4000-8000-0000000005b1")
UT = ProjectStage.USER_TWINS
RQ = ProjectStage.REQUIREMENTS
DS = ProjectStage.DESIGN
STATUSES = {
    UT: (UserModelingGateSubmissionStatus, UserModelingGateDecisionStatus),
    RQ: (RequirementsGateSubmissionStatus, RequirementsGateDecisionStatus),
    DS: (DesignGateSubmissionStatus, DesignGateDecisionStatus),
}
FAILURES = {
    UT: UserModelingRealignmentFailure,
    RQ: RequirementsRealignmentFailure,
    DS: DesignRealignmentFailure,
}
KINDS = {UT: "snapshot", RQ: "requirements", DS: "design"}
FIELDS = {UT: "user_twins", RQ: "requirements", DS: "design"}
NO_CODES = DesignAlignment(
    aligned=False,
    issue=None,
    design_version_number=None,
    grounded_requirements_version_number=None,
    requirements_version_number=None,
    missing_codes=(),
    uncovered_codes=(),
)


class World:
    def __init__(self, facts: SectionFacts) -> None:
        self.facts = facts
        self.initial = facts
        self.log: list[tuple[object, ...]] = []
        self.scopes: set[tuple[UUID, UUID]] = set()
        self.failures: dict[ProjectStage, Exception] = {}
        self.submissions: dict[ProjectStage, str] = {}
        self.decisions: dict[ProjectStage, tuple[str, HumanGateIssueCode | None]] = {}
        self.iterations: dict[ProjectStage, int] = {}
        self.statuses: dict[ProjectStage, HumanGateStatus] = {}
        self.learned = False
        self.alignment = NO_CODES

    def latest(self, key: ProjectStage):
        return getattr(self.facts, FIELDS[key])

    def realign(self, key: ProjectStage) -> None:
        facts = self.facts
        old = self.latest(key)
        version = artifact(KINDS[key], old.version.version_number + 1)
        if key is UT:
            new = UserTwinsFacts(
                version=version,
                approved=False,
                brief=facts.brief.version,
                team=facts.team.version,
                twins=frozenset(
                    twin(item.artifact_id, item.version_number + 1) for item in old.twins
                ),
            )
        elif key is RQ:
            snapshot = facts.user_twins
            new = RequirementsFacts(
                version=version,
                approved=False,
                brief=facts.brief.version,
                team=facts.team.version,
                user_modeling=snapshot.version,
                twins=snapshot.twins,
                cited_twin_ids=old.cited_twin_ids,
            )
        else:
            current = facts.requirements
            new = replace(
                old,
                version=version,
                approved=False,
                requirements=current.version,
                team=current.team,
                user_modeling=current.user_modeling,
                twins=current.twins,
            )
        self.facts = replace(facts, **{FIELDS[key]: new})

    def approve(self, key: ProjectStage) -> None:
        self.facts = replace(self.facts, **{FIELDS[key]: replace(self.latest(key), approved=True)})


class Reads:
    def __init__(self, world: World) -> None:
        self.world = world

    async def facts(self, *, owner_user_id: UUID, project_id: UUID) -> SectionFacts | None:
        self.world.log.append(("facts",))
        if (owner_user_id, project_id) != (OWNER_ID, PROJECT_ID):
            return None
        return self.world.facts


class Realignment:
    def __init__(self, world: World, key: ProjectStage) -> None:
        self.world = world
        self.key = key

    async def status(self, *, owner_user_id: UUID, project_id: UUID) -> DesignAlignment:
        self.world.scopes.add((owner_user_id, project_id))
        self.world.log.append(("status", self.key.value))
        return self.world.alignment

    async def realign(self, *, owner_user_id: UUID, project_id: UUID) -> object:
        self.world.scopes.add((owner_user_id, project_id))
        self.world.log.append(("realign", self.key.value))
        failure = self.world.failures.get(self.key)
        if failure is not None:
            raise failure
        self.world.realign(self.key)
        return object()


class Gate:
    def __init__(self, world: World, key: ProjectStage) -> None:
        self.world = world
        self.key = key
        self.submission, self.decision = STATUSES[key]

    def _gate(self) -> SimpleNamespace:
        return SimpleNamespace(
            artifact=SimpleNamespace(version=self.world.latest(self.key).version.version_number)
        )

    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID) -> SimpleNamespace:
        self.world.scopes.add((owner_user_id, project_id))
        self.world.log.append(("current_gate", self.key.value))
        return SimpleNamespace(
            status=self.world.statuses.get(self.key, HumanGateStatus.APPROVED),
            iteration=self.world.iterations.get(self.key, 1),
            max_iterations=3,
        )

    async def submit(self, *, project_id: UUID, owner_user_id: UUID) -> SimpleNamespace:
        self.world.scopes.add((owner_user_id, project_id))
        self.world.log.append(("submit", self.key.value))
        status = self.submission(self.world.submissions.get(self.key, "SUBMITTED"))
        return SimpleNamespace(status=status, gate=self._gate())

    async def decide(
        self, *, project_id: UUID, owner_user_id: UUID, action, reason: str | None = None
    ) -> SimpleNamespace:
        self.world.scopes.add((owner_user_id, project_id))
        self.world.log.append(("decide", self.key.value, action.value, reason))
        status, issue = self.world.decisions.get(self.key, ("APPLIED", None))
        if status == "APPLIED":
            self.world.approve(self.key)
        return SimpleNamespace(status=self.decision(status), gate=self._gate(), issue=issue)


class Learning:
    def __init__(self, world: World) -> None:
        self.world = world

    async def learned(self, *, owner_user_id: UUID, project_id: UUID) -> bool:
        self.world.scopes.add((owner_user_id, project_id))
        self.world.log.append(("learned",))
        return self.world.learned


def service(world: World) -> SectionsService:
    design_realignment = Realignment(world, DS)
    return SectionsService(
        reads=Reads(world),
        user_twins=SectionStep(
            realignment=Realignment(world, UT), gate=Gate(world, UT), failure=FAILURES[UT]
        ),
        requirements=SectionStep(
            realignment=Realignment(world, RQ), gate=Gate(world, RQ), failure=FAILURES[RQ]
        ),
        design=SectionStep(
            realignment=design_realignment, gate=Gate(world, DS), failure=FAILURES[DS]
        ),
        design_alignment=design_realignment,
        twin_learning=Learning(world),
    )


def current(world: World, owner_user_id: UUID = OWNER_ID):
    return asyncio.run(service(world).current(owner_user_id=owner_user_id, project_id=PROJECT_ID))


def align(world: World, owner_user_id: UUID = OWNER_ID):
    return asyncio.run(service(world).align(owner_user_id=owner_user_id, project_id=PROJECT_ID))


def gesture(key: ProjectStage) -> list[tuple[object, ...]]:
    return [
        ("current_gate", key.value),
        ("realign", key.value),
        ("submit", key.value),
        ("decide", key.value, "APPROVE", ALIGNMENT_REASON),
    ]


def states(sections) -> dict[str, tuple[str, int | None]]:
    return {
        section.key.value: (section.state.value, section.version_number)
        for section in sections.sections
    }


def test_the_sections_are_read_once_and_completed_with_learning_and_design_codes():
    world = World(aligned())
    world.learned = True
    world.alignment = replace(NO_CODES, uncovered_codes=("REQ-009",))

    sections = current(world)

    assert sections.to_snapshot()["sections"][2:5] == [
        {
            "key": "USER_TWINS",
            "state": "UPDATE_AVAILABLE",
            "version_number": 1,
            "reasons": ["TWINS_LEARNED"],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "REQUIREMENTS",
            "state": "FINE",
            "version_number": 1,
            "reasons": [],
            "blocked": None,
            "codes": [],
        },
        {
            "key": "DESIGN",
            "state": "UPDATE_AVAILABLE",
            "version_number": 1,
            "reasons": ["REQUIREMENTS_NOT_COVERED"],
            "blocked": None,
            "codes": ["REQ-009"],
        },
    ]
    assert world.log == [("facts",), ("learned",), ("status", "DESIGN")]
    assert world.scopes == {(OWNER_ID, PROJECT_ID)}


def test_nothing_more_is_asked_when_no_section_can_use_it():
    waiting = World(aligned(team=team(2, approved=False)))
    without_design = World(aligned(design=None))

    sections = current(waiting)

    assert states(sections)["USER_TWINS"] == ("TO_UPDATE", 1)
    assert sections.section(DS).blocked.value == "UPSTREAM_NOT_READY"
    assert waiting.log == [("facts",)]
    assert states(current(without_design))["DESIGN"] == ("NOT_STARTED", None)
    assert without_design.log == [("facts",), ("learned",)]


def test_the_codes_of_the_design_realignment_block_a_design_behind():
    world = World(aligned(requirements=requirements(2)))
    world.alignment = replace(
        NO_CODES, missing_codes=("REQ-002",), uncovered_codes=("REQ-003", "REQ-004")
    )

    sections = current(world)
    design_section = sections.section(DS)

    assert (design_section.state.value, design_section.blocked.value) == (
        "TO_UPDATE",
        "REQUIREMENT_NO_LONGER_AVAILABLE",
    )
    assert design_section.codes == ("REQ-002",)
    assert sections.alignment.available is False
    assert sections.alignment.uncovered_codes == ()


def test_a_project_of_another_owner_is_not_found():
    world = World(aligned(team=team(2)))

    for call in (current, align):
        with pytest.raises(SectionsFailure) as raised:
            call(world, STRANGER_ID)
        assert raised.value.code == "PROJECT_NOT_FOUND"
    assert world.log == [("facts",), ("facts",)]


def test_the_gesture_updates_the_design_alone_and_approves_it():
    world = World(aligned(requirements=requirements(2)))

    result = align(world)

    assert result.results == (
        SectionUpdate(key=DS, outcome=SectionOutcome.ALIGNED, version_number=2),
    )
    assert result.status is SectionsAlignmentStatus.ALIGNED
    assert world.log == [
        ("facts",),
        ("status", "DESIGN"),
        *gesture(DS),
        ("facts",),
        ("learned",),
        ("status", "DESIGN"),
    ]
    assert states(result.sections)["DESIGN"] == ("FINE", 2)
    assert world.facts.design.requirements == artifact("requirements", 2)


def test_the_gesture_updates_requirements_then_design():
    world = World(aligned(team=team(2), user_twins=user_twins(2, on_team=2, twins=TWINS_2)))

    result = align(world)

    assert [(item.key, item.outcome, item.version_number) for item in result.results] == [
        (RQ, SectionOutcome.ALIGNED, 2),
        (DS, SectionOutcome.ALIGNED, 2),
    ]
    assert result.status is SectionsAlignmentStatus.ALIGNED
    assert world.log == [
        ("facts",),
        ("status", "DESIGN"),
        *gesture(RQ),
        *gesture(DS),
        ("facts",),
        ("learned",),
        ("status", "DESIGN"),
    ]
    assert states(result.sections) == {
        "BRIEF": ("FINE", 1),
        "TEAM": ("FINE", 2),
        "USER_TWINS": ("FINE", 2),
        "REQUIREMENTS": ("FINE", 2),
        "DESIGN": ("FINE", 2),
        "PACKAGE": ("TO_UPDATE", 5),
    }


def test_the_gesture_updates_the_three_sections_in_order_and_never_the_team_or_the_folder():
    world = World(aligned(team=team(2)))
    before = world.facts

    result = align(world)

    assert [(item.key, item.outcome, item.version_number) for item in result.results] == [
        (UT, SectionOutcome.ALIGNED, 2),
        (RQ, SectionOutcome.ALIGNED, 2),
        (DS, SectionOutcome.ALIGNED, 2),
    ]
    assert result.status is SectionsAlignmentStatus.ALIGNED
    assert world.log == [
        ("facts",),
        ("status", "DESIGN"),
        *gesture(UT),
        *gesture(RQ),
        *gesture(DS),
        ("facts",),
        ("learned",),
        ("status", "DESIGN"),
    ]
    assert (world.facts.brief, world.facts.team, world.facts.folder) == (
        before.brief,
        before.team,
        before.folder,
    )
    assert {key: state for key, (state, _) in states(result.sections).items()} == {
        "BRIEF": "FINE",
        "TEAM": "FINE",
        "USER_TWINS": "FINE",
        "REQUIREMENTS": "FINE",
        "DESIGN": "FINE",
        "PACKAGE": "TO_UPDATE",
    }
    assert result.sections.alignment.sections == ()
    assert world.scopes == {(OWNER_ID, PROJECT_ID)}


def test_the_service_has_no_way_to_change_the_team_or_publish_the_folder():
    assert set(inspect.signature(SectionsService).parameters) == {
        "reads",
        "user_twins",
        "requirements",
        "design",
        "design_alignment",
        "twin_learning",
    }


def test_a_refusal_in_the_middle_keeps_what_was_updated_and_stops():
    world = World(aligned(team=team(2)))
    world.failures[RQ] = RequirementsRealignmentFailure("REQUIREMENTS_REVISION_PENDING")

    result = align(world)

    assert result.results == (
        SectionUpdate(key=UT, outcome=SectionOutcome.ALIGNED, version_number=2),
        SectionUpdate(key=RQ, outcome=SectionOutcome.BLOCKED, issue="REVISION_PENDING"),
        SectionUpdate(key=DS, outcome=SectionOutcome.SKIPPED),
    )
    assert result.status is SectionsAlignmentStatus.PARTIAL
    assert ("realign", "DESIGN") not in world.log
    assert states(result.sections)["USER_TWINS"] == ("FINE", 2)
    assert states(result.sections)["REQUIREMENTS"] == ("TO_UPDATE", 1)


def test_a_section_blocked_before_the_gesture_is_not_tried():
    world = World(aligned(team=team(2), user_twins=user_twins(revision_pending=True)))

    result = align(world)

    assert result.results == (
        SectionUpdate(key=UT, outcome=SectionOutcome.BLOCKED, issue="REVISION_PENDING"),
        SectionUpdate(key=RQ, outcome=SectionOutcome.SKIPPED),
        SectionUpdate(key=DS, outcome=SectionOutcome.SKIPPED),
    )
    assert result.status is SectionsAlignmentStatus.NOTHING_TO_ALIGN
    assert world.log == [("facts",), ("facts",)]
    assert world.facts == world.initial


def test_a_design_blocked_by_missing_requirements_names_the_codes():
    world = World(aligned(requirements=requirements(2)))
    world.alignment = replace(NO_CODES, missing_codes=("REQ-001",))

    result = align(world)

    assert result.results == (
        SectionUpdate(
            key=DS,
            outcome=SectionOutcome.BLOCKED,
            issue="REQUIREMENT_NO_LONGER_AVAILABLE",
            codes=("REQ-001",),
        ),
    )
    assert result.status is SectionsAlignmentStatus.NOTHING_TO_ALIGN
    assert ("realign", "DESIGN") not in world.log


@pytest.mark.parametrize(
    ("failure", "issue", "codes"),
    [
        (UserModelingRealignmentFailure("TEAM_APPROVAL_REQUIRED"), "UPSTREAM_NOT_READY", ()),
        (UserModelingRealignmentFailure("USER_TWIN_REVISION_PENDING"), "REVISION_PENDING", ()),
        (UserModelingRealignmentFailure("PERSISTENCE_REJECTED"), "PERSISTENCE_REJECTED", ()),
    ],
)
def test_a_refusal_of_the_first_section_leaves_nothing_done(failure, issue, codes):
    world = World(aligned(team=team(2)))
    world.failures[UT] = failure

    result = align(world)

    assert result.results[0] == SectionUpdate(
        key=UT, outcome=SectionOutcome.BLOCKED, issue=issue, codes=codes
    )
    assert [item.outcome for item in result.results[1:]] == [SectionOutcome.SKIPPED] * 2
    assert result.status is SectionsAlignmentStatus.NOTHING_TO_ALIGN
    assert ("submit", "USER_TWINS") not in world.log


def test_the_missing_codes_of_a_refused_design_realignment_are_kept():
    world = World(aligned(requirements=requirements(2)))
    world.failures[DS] = DesignRealignmentFailure(
        "REQUIREMENT_NO_LONGER_AVAILABLE", missing_codes=("REQ-002", "AC-004")
    )

    result = align(world)

    assert result.results == (
        SectionUpdate(
            key=DS,
            outcome=SectionOutcome.BLOCKED,
            issue="REQUIREMENT_NO_LONGER_AVAILABLE",
            codes=("REQ-002", "AC-004"),
        ),
    )


def test_a_gate_that_refuses_the_submission_ends_the_gesture():
    world = World(aligned(team=team(2)))
    world.submissions[UT] = "GATE_BLOCKED"

    result = align(world)

    assert result.results[0] == SectionUpdate(
        key=UT, outcome=SectionOutcome.BLOCKED, issue="GATE_BLOCKED"
    )
    assert result.status is SectionsAlignmentStatus.NOTHING_TO_ALIGN
    assert ("decide", "USER_TWINS", "APPROVE", ALIGNMENT_REASON) not in world.log
    assert states(result.sections)["USER_TWINS"] == ("IN_PROGRESS", 2)


def test_a_gate_that_refuses_the_approval_ends_the_gesture_with_its_issue():
    world = World(aligned(team=team(2)))
    world.decisions[RQ] = ("REJECTED", HumanGateIssueCode.INVALID_TRANSITION)

    result = align(world)

    assert [(item.key, item.outcome, item.issue) for item in result.results] == [
        (UT, SectionOutcome.ALIGNED, None),
        (RQ, SectionOutcome.BLOCKED, "INVALID_TRANSITION"),
        (DS, SectionOutcome.SKIPPED, None),
    ]
    assert result.status is SectionsAlignmentStatus.PARTIAL


def test_a_decision_refused_without_an_issue_reports_its_status():
    world = World(aligned(requirements=requirements(2)))
    world.decisions[DS] = ("ARTIFACT_STALE", None)

    result = align(world)

    assert result.results[0].issue == "ARTIFACT_STALE"


def test_an_approval_already_given_counts_as_updated():
    world = World(aligned(requirements=requirements(2)))
    world.submissions[DS] = "ALREADY_APPROVED"

    result = align(world)

    assert result.results == (
        SectionUpdate(key=DS, outcome=SectionOutcome.ALIGNED, version_number=2),
    )
    assert ("decide", "DESIGN", "APPROVE", ALIGNMENT_REASON) not in world.log


@pytest.mark.parametrize(
    ("status", "iteration"),
    [(HumanGateStatus.APPROVED, 3), (HumanGateStatus.REJECTED, 2)],
)
def test_a_gate_that_can_take_one_more_version_lets_the_gesture_update_the_section(
    status, iteration
):
    world = World(aligned(requirements=requirements(2)))
    world.statuses[DS] = status
    world.iterations[DS] = iteration

    result = align(world)

    assert result.results == (
        SectionUpdate(key=DS, outcome=SectionOutcome.ALIGNED, version_number=2),
    )
    assert result.status is SectionsAlignmentStatus.ALIGNED
    assert world.log == [
        ("facts",),
        ("status", "DESIGN"),
        *gesture(DS),
        ("facts",),
        ("learned",),
        ("status", "DESIGN"),
    ]
    assert world.facts.design.requirements == artifact("requirements", 2)


@pytest.mark.parametrize("status", [HumanGateStatus.REJECTED, HumanGateStatus.PAUSED_NEEDS_HUMAN])
def test_a_gate_not_approved_at_its_last_iteration_is_left_untouched(status):
    world = World(aligned(requirements=requirements(2)))
    world.statuses[DS] = status
    world.iterations[DS] = 3

    result = align(world)

    assert result.results == (
        SectionUpdate(key=DS, outcome=SectionOutcome.BLOCKED, issue="ITERATION_LIMIT_REACHED"),
    )
    assert result.status is SectionsAlignmentStatus.NOTHING_TO_ALIGN
    assert ("realign", "DESIGN") not in world.log
    assert world.facts == world.initial


def test_nothing_is_tried_when_every_section_is_up_to_date():
    world = World(aligned())

    result = align(world)

    assert result.results == ()
    assert result.status is SectionsAlignmentStatus.NOTHING_TO_ALIGN
    assert all(entry[0] in {"facts", "status", "learned"} for entry in world.log)


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ((), "NOTHING_TO_ALIGN"),
        (("BLOCKED", "SKIPPED"), "NOTHING_TO_ALIGN"),
        (("ALIGNED",), "ALIGNED"),
        (("ALIGNED", "ALIGNED", "ALIGNED"), "ALIGNED"),
        (("ALIGNED", "BLOCKED", "SKIPPED"), "PARTIAL"),
    ],
)
def test_the_status_of_the_gesture(outcomes, expected):
    results = [SectionUpdate(key=UT, outcome=SectionOutcome(outcome)) for outcome in outcomes]

    assert alignment_status(results).value == expected


def gate_for(version) -> GateState:
    return GateState(
        status=HumanGateStatus.APPROVED,
        artifact=ArtifactVersion(
            artifact_id=version.id,
            version_number=version.version_number,
            content_hash=version.content_hash,
        ),
    )


def test_the_twins_facts_come_from_the_snapshot_and_its_references():
    snapshot = first_snapshot()
    facts = user_twins_facts(snapshot, gate=gate_for(snapshot), revision_pending=True)

    assert facts.version == ArtifactVersion(snapshot.id, 1, snapshot.content_hash)
    assert facts.approved is True
    assert facts.brief.artifact_id == snapshot.snapshot.project_brief_reference.artifact_id
    assert facts.team.version_number == snapshot.snapshot.agent_team_reference.version_number
    assert facts.twin_ids == {version.twin_id for version in snapshot.snapshot.twin_versions}
    assert facts.revision_pending is True
    assert user_twins_facts(snapshot, gate=None).approved is False


def test_the_requirements_facts_come_from_the_context_of_the_specification():
    version = design_fixtures.requirements_version()
    specification = version.specification
    facts = requirements_facts(version, gate=gate_for(version))

    assert facts.approved is True
    assert facts.brief.artifact_id == specification.project_brief_reference.artifact_id
    assert facts.team.content_hash == specification.agent_team_reference.content_hash
    assert facts.user_modeling.version_number == 1
    assert facts.twins == frozenset({ArtifactVersion(design_fixtures.TWIN_ID, 2, "a" * 64)})
    assert facts.cited_twin_ids == frozenset({design_fixtures.TWIN_ID})
    stale = GateState(status=HumanGateStatus.STALE, artifact=gate_for(version).artifact)
    assert requirements_facts(version, gate=stale).approved is False


def test_the_design_facts_come_from_the_grounding_and_the_chosen_mockup():
    version = design_fixtures.design_version()
    grounding = version.package.grounding
    facts = design_facts(version, gate=gate_for(version), reviewed=True)
    unselected = design_fixtures.design_version(
        package=design_fixtures.design_package(selected=False)
    )

    assert isinstance(facts, DesignFacts)
    assert facts.requirements == ArtifactVersion(
        grounding.requirements_reference.artifact_id,
        grounding.requirements_reference.version_number,
        grounding.requirements_reference.content_hash,
    )
    assert facts.team.artifact_id == grounding.agent_team_reference.artifact_id
    assert facts.twin_ids == frozenset({design_fixtures.TWIN_ID})
    assert (facts.has_mockup, facts.reviewed, facts.approved) == (True, True, True)
    assert design_has_mockup(unselected) is False
    assert design_facts(unselected, gate=None).has_mockup is False


def test_the_folder_facts_are_the_stages_the_published_folder_holds():
    brief, team_version = artifact("brief", 2), artifact("team", 1)
    manifest = {
        "stages": {
            "brief": {
                "version_id": str(brief.artifact_id),
                "version_number": 2,
                "content_hash": brief.content_hash,
            },
            "team": {
                "version_id": str(team_version.artifact_id),
                "version_number": 1,
                "content_hash": team_version.content_hash,
            },
            "twins": {"version_id": "not-a-uuid", "version_number": 1, "content_hash": "a"},
            "requirements": {"version_number": True, "content_hash": "b"},
            "design": "missing",
        }
    }
    published = KnowledgePackageVersion(
        id=UUID("00000000-0000-4000-8000-0000000005c1"),
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        version_number=7,
        schema_version=3,
        content_hash="c" * 64,
        archive_hash="d" * 64,
        file_name="orchestwin.zip",
        file_count=3,
        archive_size=10,
        manifest=manifest,
        created_at=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
    )

    assert folder_facts(published) == FolderFacts(
        version_number=7,
        stages={ProjectStage.BRIEF: brief, ProjectStage.TEAM: team_version},
    )
    assert folder_facts(replace(published, manifest={"package": {}})) == FolderFacts(
        version_number=7
    )


def test_a_design_with_a_prototype_waits_for_a_review_of_its_own_version():
    world = World(aligned(design=design(has_mockup=True)))

    assert current(world).section(DS).reasons[0].value == "EVALUATION_MISSING"
