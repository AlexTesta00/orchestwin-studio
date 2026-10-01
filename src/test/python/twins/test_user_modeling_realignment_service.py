from __future__ import annotations

import asyncio
from datetime import timedelta
from types import SimpleNamespace, TracebackType
from typing import ClassVar
from uuid import UUID

import pytest

from orchestwin.agents.team_gate import ProjectWorkflowReadiness
from orchestwin.api import twin_chat
from orchestwin.api.twin_chat import AskTwinRequest, TwinChatApplication, TwinChatResult
from orchestwin.api.twin_learning import TwinLearningApplication
from orchestwin.models.proposal_evidence import begin_model_generation
from orchestwin.projects.requirements_application import (
    RequirementsVersionAppendStatus,
    specification_matches_context,
)
from orchestwin.projects.requirements_realignment import (
    requirements_are_aligned,
    snapshot_reference,
    snapshot_twin_references,
)
from orchestwin.projects.requirements_realignment_service import (
    RequirementsAlignment,
    RequirementsRealignmentService,
)
from orchestwin.projects.requirements_specifications import RequirementsSpecificationVersion
from orchestwin.projects.twin_learning import (
    LearnedObservation,
    LearningSource,
    build_twin_learning,
)
from orchestwin.twins.application import (
    GovernedUserModelingContext,
    LocalUserModelingApplicationService,
    UserModelingApplicationIssueCode,
    UserModelingApplicationStatus,
    snapshot_matches_context,
)
from orchestwin.twins.conversations import TwinConversation, TwinConversationTurn
from orchestwin.twins.epistemics import ObservationValue
from orchestwin.twins.persistence.conversations import TwinConversationAppendStatus
from orchestwin.twins.persistence.repositories import VersionAppendStatus
from orchestwin.twins.realignment import UserModelingRealignment
from orchestwin.twins.realignment_service import (
    ALREADY_ALIGNED,
    BRIEF_APPROVAL_REQUIRED,
    PERSISTENCE_REJECTED,
    TEAM_APPROVAL_REQUIRED,
    USER_TWIN_REVISION_PENDING,
    USER_TWINS_NOT_FOUND,
    UserModelingAlignment,
    UserModelingRealignmentFailure,
    UserModelingRealignmentService,
)
from orchestwin.twins.revision_application import (
    LocalUserTwinProfileRevisionService,
    ProfileRevisionApplicationStatus,
    ProfileRevisionDecision,
)
from orchestwin.twins.revision_persistence import DiffPersistenceStatus
from orchestwin.twins.revisions import (
    UserTwinProfileDiff,
    UserTwinProfileDiffStatus,
    propose_user_twin_profile_diff,
)
from orchestwin.twins.user_modeling_gate import (
    user_modeling_artifact_reference,
    user_modeling_gate_is_currently_approved,
)
from orchestwin.twins.user_twins import (
    UserModelingSnapshotVersion,
    UserTwinField,
    UserTwinProfileVersion,
)
from orchestwin.workflow.gates import HumanGate, HumanGateType
from src.test.python.knowledge.knowledge_fixtures import approved_gate
from src.test.python.knowledge.test_twin_import import OWNER_ID
from src.test.python.projects.test_requirements_realignment import (
    requirements_context,
    requirements_version,
)
from src.test.python.twins.test_user_modeling_realignment import (
    AUDITOR,
    FIRST_TEAM,
    PROJECT_ID,
    REALIGNED_AT,
    REALIGNED_SNAPSHOT_ID,
    REALIGNED_TWIN_VERSION_IDS,
    RECEPTIONIST,
    SECOND_TEAM,
    brief_version,
    first_snapshot,
    governed_context,
    realign,
    reference_of,
    revised_snapshot,
)
from src.test.python.twins.test_user_twin_revisions import owner_replacement

STRANGER_ID = UUID("00000000-0000-4000-8000-00000000f000")
PENDING_DIFF_ID = UUID("00000000-0000-4000-8000-00000000e401")
REQUIREMENTS_REALIGNED_ID = UUID("00000000-0000-4000-8000-00000000e501")
NEW_IDS = (
    REALIGNED_TWIN_VERSION_IDS[RECEPTIONIST.twin_id],
    REALIGNED_TWIN_VERSION_IDS[AUDITOR.twin_id],
    REALIGNED_SNAPSHOT_ID,
)
READY = ProjectWorkflowReadiness.READY_FOR_MAIN_WORKFLOW


class Store:
    def __init__(self, snapshot: UserModelingSnapshotVersion | None) -> None:
        self.snapshots = [] if snapshot is None else [snapshot]
        self.twins = [] if snapshot is None else list(snapshot.snapshot.twin_versions)
        self.diffs: dict[UUID, UserTwinProfileDiff] = {}
        self.twin_refusal: VersionAppendStatus | None = None
        self.snapshot_refusal: VersionAppendStatus | None = None
        self.commits = 0

    @property
    def current(self) -> UserModelingSnapshotVersion | None:
        return self.snapshots[-1] if self.snapshots else None


class Snapshots:
    def __init__(self, unit: Unit) -> None:
        self.unit = unit

    async def current(self, *, project_id: UUID) -> UserModelingSnapshotVersion | None:
        return self.unit.store.current if self.unit.owns(project_id) else None

    async def append(self, version: UserModelingSnapshotVersion) -> VersionAppendStatus:
        status = self.unit.store.snapshot_refusal or VersionAppendStatus.APPENDED
        if status is VersionAppendStatus.APPENDED:
            self.unit.staged_snapshots.append(version)
        return status


class Twins:
    def __init__(self, unit: Unit) -> None:
        self.unit = unit

    async def append(self, version: UserTwinProfileVersion) -> VersionAppendStatus:
        status = self.unit.store.twin_refusal or VersionAppendStatus.APPENDED
        if status is VersionAppendStatus.APPENDED:
            self.unit.staged_twins.append(version)
        return status


class Diffs:
    def __init__(self, unit: Unit) -> None:
        self.unit = unit

    async def current_proposed(
        self, *, project_id: UUID, base_snapshot_version_id: UUID, twin_id: UUID
    ) -> UserTwinProfileDiff | None:
        if not self.unit.owns(project_id):
            return None
        return next(
            (
                diff
                for diff in self.unit.store.diffs.values()
                if diff.base_snapshot_version_id == base_snapshot_version_id
                and diff.twin_id == twin_id
                and diff.status is UserTwinProfileDiffStatus.PROPOSED
            ),
            None,
        )

    async def create(self, diff: UserTwinProfileDiff) -> DiffPersistenceStatus:
        self.unit.store.diffs[diff.id] = diff
        return DiffPersistenceStatus.CREATED

    async def get(self, *, project_id: UUID, diff_id: UUID) -> UserTwinProfileDiff | None:
        return self.unit.store.diffs.get(diff_id) if self.unit.owns(project_id) else None

    async def save_decision(self, diff: UserTwinProfileDiff) -> DiffPersistenceStatus:
        self.unit.store.diffs[diff.id] = diff
        return DiffPersistenceStatus.UPDATED


class Unit:
    def __init__(self, store: Store, owner_user_id: UUID) -> None:
        self.store = store
        self.owner_user_id = owner_user_id
        self.staged_twins: list[UserTwinProfileVersion] = []
        self.staged_snapshots: list[UserModelingSnapshotVersion] = []
        self.snapshots = Snapshots(self)
        self.twins = Twins(self)
        self.diffs = Diffs(self)

    def owns(self, project_id: UUID) -> bool:
        return self.owner_user_id == OWNER_ID and project_id == PROJECT_ID

    async def __aenter__(self) -> Unit:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.staged_twins = []
        self.staged_snapshots = []

    async def commit(self) -> None:
        self.store.twins.extend(self.staged_twins)
        self.store.snapshots.extend(self.staged_snapshots)
        self.staged_twins = []
        self.staged_snapshots = []
        self.store.commits += 1


class Governance:
    def __init__(self, context: GovernedUserModelingContext | None) -> None:
        self.context = context

    async def load_current(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> GovernedUserModelingContext | None:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None
        return self.context


class Team:
    def __init__(self, readiness: ProjectWorkflowReadiness) -> None:
        self.value = readiness

    async def readiness(self, *, project_id: UUID, owner_user_id: UUID) -> ProjectWorkflowReadiness:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return ProjectWorkflowReadiness.PROJECT_NOT_FOUND
        return self.value


class Identifiers:
    def __init__(self, values: tuple[UUID, ...]) -> None:
        self.values = list(values)

    def __call__(self) -> UUID:
        return self.values.pop(0)


class Harness:
    def __init__(
        self,
        *,
        snapshot: UserModelingSnapshotVersion | None,
        context: GovernedUserModelingContext | None,
        readiness: ProjectWorkflowReadiness = READY,
        injected: bool = True,
    ) -> None:
        self.store = Store(snapshot)
        self.before = (list(self.store.snapshots), list(self.store.twins))
        self.governance = Governance(context)
        self.team = Team(readiness)
        dependencies = {
            "governance": self.governance,
            "team_queries": self.team,
            "uow_factory": self.unit,
        }
        if injected:
            dependencies["clock"] = lambda: REALIGNED_AT
            dependencies["uuid_factory"] = Identifiers(NEW_IDS)
        self.service = UserModelingRealignmentService(**dependencies)

    def unit(self, *, owner_user_id: UUID) -> Unit:
        return Unit(self.store, owner_user_id)

    def status(self, owner_user_id: UUID = OWNER_ID) -> UserModelingAlignment:
        return asyncio.run(self.service.status(owner_user_id=owner_user_id, project_id=PROJECT_ID))

    def realign(self, owner_user_id: UUID = OWNER_ID) -> UserModelingRealignment:
        return asyncio.run(self.service.realign(owner_user_id=owner_user_id, project_id=PROJECT_ID))

    def refusal(self, owner_user_id: UUID = OWNER_ID) -> str:
        with pytest.raises(UserModelingRealignmentFailure) as raised:
            self.realign(owner_user_id)
        return raised.value.code

    def is_current(self, snapshot: UserModelingSnapshotVersion | None) -> bool:
        return asyncio.run(
            self.service.snapshot_context_is_current(
                owner_user_id=OWNER_ID, project_id=PROJECT_ID, snapshot=snapshot
            )
        )

    def nothing_written(self) -> bool:
        return (self.store.snapshots, self.store.twins) == self.before and self.store.commits == 0


def behind(**changes) -> Harness:
    values = {"snapshot": first_snapshot(), "context": governed_context(team=SECOND_TEAM)}
    values.update(changes)
    return Harness(**values)


def proposed_diff(base: UserModelingSnapshotVersion) -> UserTwinProfileDiff:
    result = propose_user_twin_profile_diff(
        base_snapshot_version=base,
        twin_id=RECEPTIONIST.twin_id,
        replacements={
            UserTwinField.GOALS: owner_replacement(
                UserTwinField.GOALS, ObservationValue.from_items(("Shorter queues",))
            )
        },
        diff_id=PENDING_DIFF_ID,
        created_by_user_id=OWNER_ID,
        created_at=REALIGNED_AT - timedelta(hours=1),
    )
    return result.diff


def pending(harness: Harness, base: UserModelingSnapshotVersion) -> Harness:
    diff = proposed_diff(base)
    harness.store.diffs[diff.id] = diff
    return harness


SCENARIOS = {
    "no-twins": (lambda: behind(snapshot=None), USER_TWINS_NOT_FOUND),
    "brief-not-approved": (
        lambda: behind(context=governed_context(team=SECOND_TEAM, brief_approved=False)),
        BRIEF_APPROVAL_REQUIRED,
    ),
    "brief-not-approved-for-the-team": (
        lambda: behind(readiness=ProjectWorkflowReadiness.BRIEF_APPROVAL_REQUIRED),
        BRIEF_APPROVAL_REQUIRED,
    ),
    "team-not-approved": (
        lambda: behind(
            context=governed_context(team=SECOND_TEAM, team_approved=False),
            readiness=ProjectWorkflowReadiness.TEAM_APPROVAL_REQUIRED,
        ),
        TEAM_APPROVAL_REQUIRED,
    ),
    "no-team": (
        lambda: behind(
            context=governed_context(team=None),
            readiness=ProjectWorkflowReadiness.TEAM_PROPOSAL_REQUIRED,
        ),
        TEAM_APPROVAL_REQUIRED,
    ),
    "team-of-an-earlier-brief": (
        lambda: behind(
            context=governed_context(brief=brief_version(2), team=SECOND_TEAM),
            readiness=ProjectWorkflowReadiness.TEAM_PROPOSAL_REQUIRED,
        ),
        TEAM_APPROVAL_REQUIRED,
    ),
    "earlier-catalog": (
        lambda: behind(context=governed_context(team=SECOND_TEAM, catalog_hash="e" * 64)),
        TEAM_APPROVAL_REQUIRED,
    ),
    "already-aligned": (lambda: behind(context=governed_context()), ALREADY_ALIGNED),
    "revision-pending": (lambda: pending(behind(), first_snapshot()), USER_TWIN_REVISION_PENDING),
}


def test_status_reports_twins_anchored_to_an_earlier_team_as_ready_to_re_anchor():
    harness = behind()

    assert harness.status() == UserModelingAlignment(
        aligned=False,
        issue=None,
        snapshot_version_number=1,
        brief_version_number=1,
        team_version_number=2,
    )
    assert harness.nothing_written()


def test_status_reports_twins_anchored_to_the_current_brief_and_team_as_aligned():
    assert behind(context=governed_context()).status() == UserModelingAlignment(
        aligned=True,
        issue=ALREADY_ALIGNED,
        snapshot_version_number=1,
        brief_version_number=1,
        team_version_number=1,
    )


@pytest.mark.parametrize("name", SCENARIOS)
def test_status_names_what_blocks_the_re_anchoring(name):
    build, code = SCENARIOS[name]

    alignment = build().status()

    assert alignment.issue == code
    assert alignment.aligned is (code == ALREADY_ALIGNED)


@pytest.mark.parametrize("name", SCENARIOS)
def test_realign_refuses_with_the_code_of_the_blocker_and_writes_nothing(name):
    build, code = SCENARIOS[name]
    harness = build()

    assert harness.refusal() == code
    assert harness.nothing_written()


def test_the_checks_follow_the_order_of_the_contract():
    nothing_ready = governed_context(team=SECOND_TEAM, brief_approved=False, team_approved=False)

    assert (
        behind(
            snapshot=None,
            context=nothing_ready,
            readiness=ProjectWorkflowReadiness.BRIEF_APPROVAL_REQUIRED,
        )
        .status()
        .issue
        == USER_TWINS_NOT_FOUND
    )
    assert (
        behind(context=nothing_ready, readiness=ProjectWorkflowReadiness.BRIEF_APPROVAL_REQUIRED)
        .status()
        .issue
        == BRIEF_APPROVAL_REQUIRED
    )
    assert (
        pending(
            behind(
                context=governed_context(team=SECOND_TEAM, team_approved=False),
                readiness=ProjectWorkflowReadiness.TEAM_APPROVAL_REQUIRED,
            ),
            first_snapshot(),
        )
        .status()
        .issue
        == TEAM_APPROVAL_REQUIRED
    )
    assert (
        pending(behind(context=governed_context()), first_snapshot()).status().issue
        == ALREADY_ALIGNED
    )


def test_the_alignment_of_a_project_without_twins_or_team_still_names_the_versions_it_has():
    assert behind(snapshot=None).status() == UserModelingAlignment(
        aligned=False,
        issue=USER_TWINS_NOT_FOUND,
        snapshot_version_number=None,
        brief_version_number=1,
        team_version_number=2,
    )
    assert behind(
        context=governed_context(team=None),
        readiness=ProjectWorkflowReadiness.TEAM_PROPOSAL_REQUIRED,
    ).status() == UserModelingAlignment(
        aligned=False,
        issue=TEAM_APPROVAL_REQUIRED,
        snapshot_version_number=1,
        brief_version_number=1,
        team_version_number=None,
    )


def test_another_owner_finds_no_twins_and_no_versions():
    harness = behind()

    assert harness.status(STRANGER_ID) == UserModelingAlignment(
        aligned=False,
        issue=USER_TWINS_NOT_FOUND,
        snapshot_version_number=None,
        brief_version_number=None,
        team_version_number=None,
    )
    assert harness.refusal(STRANGER_ID) == USER_TWINS_NOT_FOUND
    assert harness.nothing_written()


def test_a_revision_pending_on_an_older_snapshot_does_not_block_the_re_anchoring():
    harness = pending(behind(snapshot=revised_snapshot()), first_snapshot())

    assert harness.status().issue is None
    assert harness.realign().snapshot_version.version_number == 3


def test_realign_stores_new_twin_versions_and_a_snapshot_that_gate_three_has_not_approved():
    harness = behind()
    before = harness.store.current
    gate = approved_gate(
        before, HumanGateType.USER_MODELING, user_modeling_artifact_reference(before), 4000
    )

    realignment = harness.realign()

    assert realignment == realign(before, team=SECOND_TEAM)
    assert harness.store.snapshots == [before, realignment.snapshot_version]
    assert harness.store.twins == [*before.snapshot.twin_versions, *realignment.twin_versions]
    assert harness.store.commits == 1
    assert user_modeling_gate_is_currently_approved(gate, before)
    assert not user_modeling_gate_is_currently_approved(gate, realignment.snapshot_version)
    assert harness.status() == UserModelingAlignment(
        aligned=True,
        issue=ALREADY_ALIGNED,
        snapshot_version_number=2,
        brief_version_number=1,
        team_version_number=2,
    )
    assert harness.refusal() == ALREADY_ALIGNED
    assert harness.store.commits == 1


def test_twins_re_anchored_to_a_new_brief_keep_their_team_anchor_when_the_team_is_the_same():
    second_brief = brief_version(2)
    harness = behind(context=governed_context(brief=second_brief))

    realignment = harness.realign()

    snapshot = realignment.snapshot_version.snapshot
    assert snapshot.project_brief_reference == reference_of(second_brief)
    assert snapshot.agent_team_reference == FIRST_TEAM
    assert harness.status().issue == ALREADY_ALIGNED


@pytest.mark.parametrize(
    ("attribute", "status"),
    [
        ("twin_refusal", VersionAppendStatus.PROJECT_NOT_FOUND),
        ("twin_refusal", VersionAppendStatus.CONTEXT_NOT_FOUND),
        ("snapshot_refusal", VersionAppendStatus.PROJECT_NOT_FOUND),
        ("snapshot_refusal", VersionAppendStatus.CONTEXT_NOT_FOUND),
    ],
)
def test_realign_refuses_an_append_the_repository_rejects(attribute, status):
    harness = behind()
    setattr(harness.store, attribute, status)

    assert harness.refusal() == PERSISTENCE_REJECTED
    assert harness.nothing_written()


def test_without_injected_identity_and_clock_the_re_anchoring_uses_random_ids_and_utc_time():
    harness = behind(injected=False)

    realignment = harness.realign()

    identifiers = {
        realignment.snapshot_version.id,
        *(twin.id for twin in realignment.twin_versions),
    }
    assert len(identifiers) == 3
    assert identifiers.isdisjoint(NEW_IDS)
    assert realignment.snapshot_version.created_at.utcoffset().total_seconds() == 0


def test_twins_are_current_only_when_anchored_to_the_approved_brief_and_team():
    harness = behind()
    before = harness.store.current

    assert not harness.is_current(before)
    assert not harness.is_current(None)

    after = harness.realign().snapshot_version

    assert harness.is_current(after)
    harness.team.value = ProjectWorkflowReadiness.TEAM_PROPOSAL_REQUIRED
    assert not harness.is_current(after)


def commands(harness: Harness) -> LocalUserModelingApplicationService:
    return LocalUserModelingApplicationService(
        governance=harness.governance,
        proposals=object(),
        uow_factory=harness.unit,
    )


def test_after_a_re_anchoring_the_readiness_says_that_the_twins_follow_the_current_context():
    harness = behind()
    service = commands(harness)
    before = harness.store.current

    assert not asyncio.run(
        service.snapshot_context_is_current(
            owner_user_id=OWNER_ID, project_id=PROJECT_ID, snapshot=before
        )
    )

    after = harness.realign().snapshot_version

    assert asyncio.run(
        service.snapshot_context_is_current(
            owner_user_id=OWNER_ID, project_id=PROJECT_ID, snapshot=after
        )
    )


def test_after_a_re_anchoring_the_grounded_generation_answers_that_the_snapshot_exists():
    harness = behind()

    assert not snapshot_matches_context(harness.store.current, harness.governance.context)

    harness.realign()
    result = asyncio.run(
        commands(harness).generate_grounded_snapshot(owner_user_id=OWNER_ID, project_id=PROJECT_ID)
    )

    assert result.status is UserModelingApplicationStatus.REJECTED
    assert result.issue is UserModelingApplicationIssueCode.SNAPSHOT_ALREADY_EXISTS
    assert harness.store.commits == 1


def test_after_a_re_anchoring_the_owner_revises_a_twin_found_by_its_identity():
    harness = behind()
    realignment = harness.realign()
    revisions = LocalUserTwinProfileRevisionService(
        uow_factory=harness.unit,
        uuid_factory=Identifiers(tuple(UUID(int=0xE600 + index) for index in range(3))),
        clock=lambda: REALIGNED_AT + timedelta(hours=1),
    )
    replacement = owner_replacement(
        UserTwinField.GOALS, ObservationValue.from_items(("Shorter queues at the desk",))
    )

    async def scenario():
        proposed = await revisions.propose_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            twin_id=RECEPTIONIST.twin_id,
            replacements={UserTwinField.GOALS: replacement},
        )
        decided = await revisions.decide_revision(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            diff_id=proposed.diff.id,
            decision=ProfileRevisionDecision.APPROVE,
        )
        return proposed, decided

    proposed, decided = asyncio.run(scenario())

    assert proposed.status is ProfileRevisionApplicationStatus.CREATED
    assert proposed.diff.base_twin_version_id == realignment.twin_versions[0].id
    assert decided.status is ProfileRevisionApplicationStatus.APPLIED
    assert (decided.twin_version.twin_id, decided.twin_version.version_number) == (
        RECEPTIONIST.twin_id,
        3,
    )
    assert decided.twin_version.profile.observation_for(UserTwinField.GOALS) == replacement
    assert decided.twin_version.profile.agent_team_reference == SECOND_TEAM
    assert harness.store.current == decided.snapshot_version
    assert harness.status().issue == ALREADY_ALIGNED


def answering(value: object):
    async def answer(**scope: object) -> object:
        assert set(scope) == {"owner_user_id", "project_id"}
        return value

    return answer


def test_after_a_re_anchoring_the_twin_learning_finds_the_twins_and_what_they_learned():
    harness = behind()
    before = harness.store.current
    learned = LearnedObservation(
        twin_id=RECEPTIONIST.twin_id,
        number=1,
        statement="Guests ask for a late check-out at the desk.",
        source=LearningSource.OWNER,
        added_in_version=1,
        approved_at=REALIGNED_AT - timedelta(days=1),
    )

    realignment = harness.realign()
    current = realignment.snapshot_version
    runtime = SimpleNamespace(
        user_modeling_services=SimpleNamespace(
            queries=SimpleNamespace(current_snapshot=answering(current)),
            gates=SimpleNamespace(
                current_gate=answering(
                    approved_gate(
                        current,
                        HumanGateType.USER_MODELING,
                        user_modeling_artifact_reference(current),
                        4100,
                    )
                )
            ),
        )
    )
    twins = asyncio.run(
        TwinLearningApplication(runtime).approved_twins(
            owner_user_id=OWNER_ID, project_id=PROJECT_ID
        )
    )

    assert [twin.twin_id for twin in twins] == [
        twin.twin_id for twin in before.snapshot.twin_versions
    ]
    assert twins == realignment.twin_versions
    receptionist = twins[0]
    learning = build_twin_learning(
        twin_id=receptionist.twin_id,
        twin_name=receptionist.profile.name,
        profile_version_number=receptionist.version_number,
        records=(learned,),
    )
    assert learning.observations == (learned,)
    assert learning.label == "2.1"


class ChatTransaction:
    async def __aenter__(self) -> ChatTransaction:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class ChatSession:
    async def __aenter__(self) -> ChatSession:
        return self

    async def __aexit__(self, *_: object) -> None:
        return None

    def begin(self) -> ChatTransaction:
        return ChatTransaction()


class ChatTwins:
    store: ClassVar[Store] = Store(None)

    def __init__(self, session: object, *, owner_user_id: UUID) -> None:
        self.owner_user_id = owner_user_id

    async def current(self, *, project_id: UUID, twin_id: UUID) -> UserTwinProfileVersion | None:
        if self.owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None
        versions = [version for version in self.store.twins if version.twin_id == twin_id]
        return max(versions, key=lambda version: version.version_number, default=None)


class ChatConversations:
    recorded: ClassVar[list[TwinConversation]] = []

    def __init__(self, session: object, *, owner_user_id: UUID) -> None:
        self.owner_user_id = owner_user_id

    async def latest(self, *, project_id: UUID, twin_id: UUID) -> TwinConversation | None:
        return next((item for item in reversed(self.recorded) if item.twin_id == twin_id), None)

    async def create(self, conversation: TwinConversation) -> TwinConversationAppendStatus:
        self.recorded.append(conversation)
        return TwinConversationAppendStatus.APPENDED

    async def append_turn(self, turn: TwinConversationTurn) -> TwinConversationAppendStatus:
        index = next(
            place for place, item in enumerate(self.recorded) if item.id == turn.conversation_id
        )
        self.recorded[index] = self.recorded[index].with_turn(turn)
        return TwinConversationAppendStatus.APPENDED


class ChatBriefs:
    def __init__(self, session: object) -> None:
        self.session = session

    async def list_owned_versions(self, *, project_id: UUID, owner_user_id: UUID):
        return (brief_version(),)


class ChatLearning:
    def __init__(self, session: object, *, owner_user_id: UUID) -> None:
        self.owner_user_id = owner_user_id

    async def observations(self, project_id: UUID, twin_id: UUID) -> tuple[()]:
        return ()


class ChatEvidence:
    def __init__(self) -> None:
        self.kinds: list[str] = []

    async def begin(self, *, owner_user_id: UUID, project_id: UUID, request: object) -> None:
        self.kinds.append("BEGIN")

    async def append(
        self,
        *,
        generation_id: UUID,
        owner_user_id: UUID,
        project_id: UUID,
        kind: str,
        payload: dict,
        raw_body: bytes | None = None,
    ) -> None:
        self.kinds.append(kind)


class ChatGenerator:
    configuration = SimpleNamespace(max_output_tokens=4096)

    def __init__(self) -> None:
        self.contexts: list[dict[str, object]] = []

    async def generate(self, **kwargs: object) -> object:
        self.contexts.append(kwargs["context"])
        await begin_model_generation(
            SimpleNamespace(request_id=UUID(int=0xE700 + len(self.contexts)), content_hash="d" * 64)
        )
        return kwargs["output_type"].model_validate(
            {"reply": "I look for the booking before anything else.", "insights": []}
        )


def ask(chat: TwinChatApplication) -> TwinChatResult:
    return asyncio.run(
        chat.ask(
            owner_user_id=OWNER_ID,
            project_id=PROJECT_ID,
            twin_id=RECEPTIONIST.twin_id,
            body=AskTwinRequest(question="How do you check a guest in?", expected_turn_count=0),
        )
    )


def test_after_a_re_anchoring_the_twin_chat_finds_the_twin_by_its_identity(monkeypatch):
    harness = behind()
    monkeypatch.setattr(ChatTwins, "store", harness.store)
    monkeypatch.setattr(ChatConversations, "recorded", [])
    monkeypatch.setattr(twin_chat, "SqlAlchemyUserTwinVersionRepository", ChatTwins)
    monkeypatch.setattr(twin_chat, "SqlAlchemyTwinConversationRepository", ChatConversations)
    monkeypatch.setattr(twin_chat, "SqlAlchemyProjectBriefRepository", ChatBriefs)
    monkeypatch.setattr(twin_chat, "SqlAlchemyTwinLearningRepository", ChatLearning)
    generator = ChatGenerator()
    chat = TwinChatApplication(
        SimpleNamespace(
            database_runtime=SimpleNamespace(session_factory=ChatSession),
            real_model_runtime=SimpleNamespace(
                user_modeling=SimpleNamespace(proposal_port=SimpleNamespace(generator=generator))
            ),
            proposal_evidence_store=ChatEvidence(),
        )
    )

    first = ask(chat).conversation
    realignment = harness.realign()
    second = ask(chat).conversation

    receptionist = realignment.twin_versions[0]
    assert (first.twin_id, first.twin_version_number) == (RECEPTIONIST.twin_id, 1)
    assert (second.twin_id, second.twin_version_id, second.twin_version_number) == (
        RECEPTIONIST.twin_id,
        receptionist.id,
        2,
    )
    assert second.twin_name == first.twin_name == "Receptionist Twin"
    assert second.id != first.id
    assert len(second.turns) == 1
    assert ChatConversations.recorded == [first, second]
    context = generator.contexts[-1]["user_twin"]
    assert (context["twin_id"], context["version_number"]) == (str(RECEPTIONIST.twin_id), 2)
    assert context["profile"] == receptionist.profile.to_snapshot()
    assert (
        asyncio.run(
            chat.conversation(
                owner_user_id=OWNER_ID, project_id=PROJECT_ID, twin_id=RECEPTIONIST.twin_id
            )
        )
        == second
    )


class SnapshotQueries:
    def __init__(self, store: Store) -> None:
        self.store = store

    async def current_snapshot(
        self, *, owner_user_id: UUID, project_id: UUID
    ) -> UserModelingSnapshotVersion | None:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None
        return self.store.current


class GateQueries:
    def __init__(self, gate: HumanGate) -> None:
        self.gate = gate

    async def current_gate(self, *, project_id: UUID, owner_user_id: UUID) -> HumanGate | None:
        if owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None
        return self.gate


class RequirementsVersions:
    def __init__(self, unit: RequirementsUnit) -> None:
        self.unit = unit

    def _current(self, project_id: UUID) -> RequirementsSpecificationVersion | None:
        if self.unit.owner_user_id != OWNER_ID or project_id != PROJECT_ID:
            return None
        return self.unit.versions[-1]

    async def current(self, *, project_id: UUID) -> RequirementsSpecificationVersion | None:
        return self._current(project_id)

    async def get_current_owned_for_update(
        self, *, project_id: UUID, owner_user_id: UUID
    ) -> RequirementsSpecificationVersion | None:
        return self._current(project_id)

    async def append(
        self, version: RequirementsSpecificationVersion
    ) -> RequirementsVersionAppendStatus:
        self.unit.staged.append(version)
        return RequirementsVersionAppendStatus.APPENDED


class NoRequirementsDiffs:
    async def current_proposed(self, *, project_id: UUID, base_version_id: UUID) -> None:
        return None


class RequirementsUnit:
    def __init__(
        self, versions: list[RequirementsSpecificationVersion], owner_user_id: UUID
    ) -> None:
        self.versions = versions
        self.owner_user_id = owner_user_id
        self.staged: list[RequirementsSpecificationVersion] = []
        self.specifications = RequirementsVersions(self)
        self.diffs = NoRequirementsDiffs()

    async def __aenter__(self) -> RequirementsUnit:
        return self

    async def __aexit__(self, *_: object) -> None:
        self.staged = []

    async def commit(self) -> None:
        self.versions.extend(self.staged)
        self.staged = []


def test_a_new_team_reaches_the_twins_and_then_the_requirements_without_new_content():
    twins = behind()
    first = twins.store.current
    written = requirements_version(first)
    versions = [written]
    gates = GateQueries(
        approved_gate(
            first, HumanGateType.USER_MODELING, user_modeling_artifact_reference(first), 4000
        )
    )
    requirements = RequirementsRealignmentService(
        uow_factory=lambda *, owner_user_id: RequirementsUnit(versions, owner_user_id),
        user_modeling_queries=SnapshotQueries(twins.store),
        user_modeling_gates=gates,
        user_modeling_context=twins.service,
        clock=lambda: REALIGNED_AT + timedelta(minutes=5),
        uuid_factory=lambda: REQUIREMENTS_REALIGNED_ID,
    )
    scope = {"owner_user_id": OWNER_ID, "project_id": PROJECT_ID}

    assert asyncio.run(requirements.status(**scope)) == RequirementsAlignment(
        aligned=True,
        issue="USER_TWINS_APPROVAL_REQUIRED",
        requirements_version_number=3,
        snapshot_version_number=1,
        twins_approved=False,
    )

    current = twins.realign().snapshot_version
    gates.gate = approved_gate(
        current, HumanGateType.USER_MODELING, user_modeling_artifact_reference(current), 4100
    )

    assert twins.status().issue == ALREADY_ALIGNED
    assert asyncio.run(requirements.status(**scope)) == RequirementsAlignment(
        aligned=False,
        issue=None,
        requirements_version_number=3,
        snapshot_version_number=2,
        twins_approved=True,
    )

    version = asyncio.run(requirements.realign(**scope))

    specification = version.specification
    assert (version.id, version.version_number, version.based_on_version_number) == (
        REQUIREMENTS_REALIGNED_ID,
        4,
        3,
    )
    assert specification.user_modeling_reference == snapshot_reference(current)
    assert specification.user_twin_references == snapshot_twin_references(current)
    assert specification.agent_team_reference.artifact_id == SECOND_TEAM.artifact_id
    assert specification.project_brief_reference == written.specification.project_brief_reference
    assert [requirement.sources for requirement in specification.requirements] == [
        requirement.sources for requirement in written.specification.requirements
    ]
    assert requirements_are_aligned(specification, current)
    assert asyncio.run(requirements.status(**scope)).issue == "REQUIREMENTS_ALREADY_ALIGNED"
    change_context = requirements_context(
        current, brief=reference_of(brief_version()), team=SECOND_TEAM
    )
    assert not specification_matches_context(written.specification, change_context)
    assert specification_matches_context(specification, change_context)
