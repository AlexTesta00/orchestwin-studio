import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from orchestwin.agents.owner_inputs import (
    OwnerTeamInputError,
    OwnerTeamInputService,
    owner_team_proposal,
)
from orchestwin.agents.proposals import (
    TeamProposalApplicationStatus,
    TeamProposalRevisionKind,
    TeamProposalVersion,
    TeamProposalVersionCreationResult,
    TeamProposalVersionCreationStatus,
)
from orchestwin.agents.selection_rules import determine_team_constraints
from orchestwin.agents.team_gate import OwnerAgentRationale, agent_team_artifact_reference
from orchestwin.models.team_proposals import TeamProposalMemberSource
from src.test.python.agents.test_team_proposal_application import (
    NOW,
    OWNER_ID,
    PROJECT_ID,
    InMemoryTeamProposalUnitOfWork,
    InMemoryTeamSelectionContextRepository,
    approved_gate,
    complete_brief_version,
    selection_context,
)


def supplied_context():
    brief = complete_brief_version()
    return selection_context(version=brief, gate=approved_gate(brief))


def selection(context):
    constraints = determine_team_constraints(
        project_mode=context.project_mode, brief=context.brief_version.brief
    )
    optional = constraints.optional_agent_ids[0]
    return (
        (*constraints.mandatory_agent_ids, optional),
        (OwnerAgentRationale(optional, "Review the supplied design from this perspective."),),
    )


def test_owner_team_preserves_constraints_and_exact_gate_reference_without_model():
    context = supplied_context()
    selected, rationales = selection(context)
    proposal = owner_team_proposal(context, reversed(selected), rationales)
    assert proposal.provider_id == "owner-input"
    assert proposal.owner_added_agent_ids == (rationales[0].agent_id,)
    assert not proposal.suggested_agent_ids
    assert all(
        member.source is TeamProposalMemberSource.DETERMINISTIC_MANDATORY
        for member in proposal.members
        if member.agent_id in proposal.mandatory_agent_ids
    )
    version = TeamProposalVersion(
        id=PROJECT_ID,
        project_id=PROJECT_ID,
        version_number=1,
        proposal=proposal,
        revision_kind=TeamProposalRevisionKind.OWNER_PROVIDED,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )
    gate_reference = agent_team_artifact_reference(version)
    assert gate_reference.artifact_id == version.id
    assert gate_reference.content_hash == proposal.content_hash
    with pytest.raises(ValueError):
        replace(version, version_number=2, based_on_version_number=1)


@pytest.mark.parametrize("case", ("duplicate", "mandatory", "rationale", "unused"))
def test_owner_team_rejects_invalid_membership_before_persistence(case):
    context = supplied_context()
    selected, rationales = selection(context)
    if case == "duplicate":
        selected = (*selected, selected[0])
        expected = "DUPLICATE_AGENT"
    elif case == "mandatory":
        selected = (rationales[0].agent_id,)
        expected = "MANDATORY_AGENT_MISSING"
    elif case == "rationale":
        rationales = ()
        expected = "RATIONALE_REQUIRED"
    else:
        rationales = (*rationales, OwnerAgentRationale(selected[0], "Unneeded."))
        expected = "UNUSED_RATIONALE"
    with pytest.raises(OwnerTeamInputError, match=expected):
        owner_team_proposal(context, selected, rationales)


def test_owner_team_service_requires_gate_and_initial_history():
    context = supplied_context()
    contexts = InMemoryTeamSelectionContextRepository()
    contexts.set_context(context)
    selected, rationales = selection(context)
    proposal = owner_team_proposal(context, selected, rationales)
    version = TeamProposalVersion(
        id=PROJECT_ID,
        project_id=PROJECT_ID,
        version_number=1,
        proposal=proposal,
        revision_kind=TeamProposalRevisionKind.OWNER_PROVIDED,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )
    repository = AsyncMock()
    repository.get_current_owned.return_value = None
    repository.create_owner_provided_owned.return_value = TeamProposalVersionCreationResult(
        status=TeamProposalVersionCreationStatus.CREATED, version=version
    )
    service = OwnerTeamInputService(
        unit_of_work_factory=lambda: InMemoryTeamProposalUnitOfWork(contexts, repository)
    )
    command = dict(
        project_id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        selected_agent_ids=selected,
        owner_rationales=rationales,
    )
    result = asyncio.run(service.create(**command))
    assert result.status is TeamProposalApplicationStatus.CREATED
    repository.create_generated_owned.assert_not_called()
    repository.get_current_owned.return_value = version
    with pytest.raises(OwnerTeamInputError, match="TEAM_PROPOSAL_ALREADY_EXISTS"):
        asyncio.run(service.create(**command))
    contexts.set_context(replace(context, brief_gate=None))
    result = asyncio.run(service.create(**command))
    assert result.status is TeamProposalApplicationStatus.BRIEF_NOT_APPROVED
    assert repository.create_owner_provided_owned.await_count == 1
