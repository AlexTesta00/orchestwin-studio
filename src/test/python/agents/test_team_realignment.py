from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.agents.perspectives import perspective_views
from orchestwin.agents.proposals import TeamProposalRevisionKind, TeamProposalVersion
from orchestwin.agents.realignment import (
    TeamRealignmentError,
    reanchored_team,
    team_selection_can_realign,
)
from orchestwin.agents.realignment_service import TeamRealignmentFailure, TeamRealignmentService
from orchestwin.projects.briefs import ProjectBriefVersion, create_project_brief
from orchestwin.projects.domain import ProjectMode
from orchestwin.workflow.gates import HumanGateStatus
from src.test.python.agents.test_team_proposal_persistence import (
    NOW,
    OWNER_ID,
    PROJECT_ID,
    build_proposal,
)

MODE = ProjectMode.GREENFIELD_GENERATION
PROPOSAL_ID = UUID(int=3001)
NEXT_ID = UUID(int=3002)


def changed_brief(description="A Vue web application with a FastAPI backend and clearer forms."):
    brief = create_project_brief(
        name="Persistence project",
        description=description,
        technical_constraints=["Vue frontend", "FastAPI backend", "PostgreSQL database"],
    )
    return ProjectBriefVersion(
        id=UUID(int=3010),
        project_id=PROJECT_ID,
        version_number=2,
        schema_version=brief.SCHEMA_VERSION,
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )


def version():
    return TeamProposalVersion(
        id=PROPOSAL_ID,
        project_id=PROJECT_ID,
        version_number=1,
        proposal=build_proposal(),
        revision_kind=TeamProposalRevisionKind.PROPOSER_GENERATED,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )


def test_reanchoring_keeps_the_selected_roster_and_perspectives_with_new_brief_refs():
    current = version()
    brief = changed_brief()
    before = current.proposal
    after = reanchored_team(before, brief=brief, project_mode=MODE)
    assert after.selected_agent_ids == before.selected_agent_ids

    def perspectives(proposal):
        return [
            (view.key, view.applied, [(aspect.key, aspect.applied) for aspect in view.aspects])
            for view in perspective_views(proposal.constraints, proposal.selected_agent_ids)
        ]

    assert perspectives(after) == perspectives(before)
    assert (after.brief_version_id, after.brief_version_number, after.brief_content_hash) == (
        brief.id,
        2,
        brief.content_hash,
    )
    assert before.brief_version_number == 1


def test_a_new_mandatory_mobile_role_requires_an_owner_choice_instead_of_silent_addition():
    current = version()
    brief = changed_brief(
        "A Vue web application with a FastAPI backend and a mobile app for iOS and Android."
    )
    assert AgentIdentifier.MOBILE_ENGINEER not in current.proposal.selected_agent_ids
    assert not team_selection_can_realign(current.proposal, brief=brief.brief, project_mode=MODE)
    with pytest.raises(TeamRealignmentError) as raised:
        reanchored_team(current.proposal, brief=brief, project_mode=MODE)
    assert raised.value.code == "PREPARE_AGAIN"


class Unit:
    def __init__(self, world, owner_user_id):
        self.world = world
        self.owner = owner_user_id
        self.contexts = self
        self.proposals = self
        self.gates = self
        self.pending = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        self.pending = None
        self.world.exits.append(args[0])

    async def get_current_owned(self, *, owner_user_id, project_id):
        if (owner_user_id, project_id) != (OWNER_ID, PROJECT_ID):
            return None
        return self.world.context

    async def get_current_owned_for_update(self, **scope):
        self.world.locks += 1
        return await self.get_current_owned(**scope)

    async def current(self, **scope):
        return self.world.current if await self.get_current_owned(**scope) else None

    async def get_latest_owned_for_update(self, **scope):
        return self.world.gate

    async def append(self, new):
        if self.world.error:
            raise self.world.error
        self.pending = new
        return self.world.accept

    async def commit(self):
        self.world.versions.append(self.pending)
        self.world.current = self.pending


class World:
    def __init__(self, *, brief=None):
        self.current = version()
        self.versions = [self.current]
        self.context = SimpleNamespace(
            brief_is_approved=True,
            brief_version=brief or changed_brief(),
            project_mode=MODE,
        )
        self.gate = SimpleNamespace(
            status=HumanGateStatus.APPROVED,
            artifact=SimpleNamespace(
                artifact_id=self.current.id, version=1, content_hash=self.current.content_hash
            ),
        )
        self.accept = True
        self.error = None
        self.locks = 0
        self.exits = []
        self.service = TeamRealignmentService(
            uow_factory=lambda *, owner_user_id: Unit(self, owner_user_id),
            clock=lambda: NOW,
            uuid_factory=lambda: NEXT_ID,
        )

    def realign(self, owner=OWNER_ID):
        return asyncio.run(self.service.realign(owner_user_id=owner, project_id=PROJECT_ID))


def test_the_service_appends_legal_lineage_and_does_not_approve_the_new_team():
    world = World()
    previous = world.current
    new = world.realign()
    assert new.id == NEXT_ID
    assert new.version_number == 2 and new.based_on_version_number == 1
    assert new.revision_kind is TeamProposalRevisionKind.OWNER_EDITED
    assert new.proposal.selected_agent_ids == previous.proposal.selected_agent_ids
    assert world.versions == [previous, new] and world.locks == 1
    assert world.gate.artifact.artifact_id == previous.id
    assert (
        asyncio.run(world.service.status(owner_user_id=OWNER_ID, project_id=PROJECT_ID)).issue
        == "TEAM_APPROVAL_REQUIRED"
    )


@pytest.mark.parametrize(
    "issue",
    [
        "TEAM_NOT_FOUND",
        "BRIEF_APPROVAL_REQUIRED",
        "TEAM_APPROVAL_REQUIRED",
        "PREPARE_AGAIN",
        "PERSISTENCE_REJECTED",
    ],
)
def test_the_service_refuses_missing_scope_pending_human_choice_and_invalid_selection(issue):
    world = World()
    owner = OWNER_ID
    if issue == "TEAM_NOT_FOUND":
        owner = UUID(int=999)
    elif issue == "BRIEF_APPROVAL_REQUIRED":
        world.context.brief_is_approved = False
    elif issue == "TEAM_APPROVAL_REQUIRED":
        world.gate.status = HumanGateStatus.PENDING_APPROVAL
    elif issue == "PREPARE_AGAIN":
        world.context.brief_version = changed_brief(
            "Vue web application, FastAPI backend and a mobile app for iOS and Android."
        )
    else:
        world.accept = False
    with pytest.raises(TeamRealignmentFailure) as raised:
        world.realign(owner)
    assert raised.value.code == issue
    assert len(world.versions) == 1


def test_sql_failure_rolls_back_and_is_a_controlled_persistence_conflict():
    world = World()
    world.error = IntegrityError("insert", {}, ValueError("private database detail"))
    with pytest.raises(TeamRealignmentFailure) as raised:
        world.realign()
    assert raised.value.code == "PERSISTENCE_REJECTED"
    assert len(world.versions) == 1
    assert world.exits == [IntegrityError]
