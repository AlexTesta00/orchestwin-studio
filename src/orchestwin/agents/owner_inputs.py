from __future__ import annotations

from collections.abc import Iterable

from orchestwin.agents.catalog import AgentIdentifier, all_agent_catalog_entries
from orchestwin.agents.proposals import (
    LocalTeamProposalApplicationService,
    TeamProposalApplicationResult,
    TeamProposalApplicationStatus,
    TeamProposalUnitOfWorkFactory,
    TeamProposalVersionCreationStatus,
    TeamSelectionContext,
)
from orchestwin.agents.selection_rules import TeamRoleConstraintKind, determine_team_constraints
from orchestwin.agents.team_gate import OwnerAgentRationale
from orchestwin.models.team_proposals import (
    TEAM_PROPOSAL_SCHEMA_VERSION,
    AgentTeamProposal,
    ProposedTeamMember,
    TeamProposalJustification,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
    TeamProposalProviderKind,
    deterministic_justification,
)


class OwnerTeamInputError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def owner_team_proposal(
    context: TeamSelectionContext,
    selected_agent_ids: Iterable[AgentIdentifier],
    owner_rationales: Iterable[OwnerAgentRationale] = (),
) -> AgentTeamProposal:
    if context.brief_version is None:
        raise OwnerTeamInputError("BRIEF_NOT_FOUND")
    selected = tuple(selected_agent_ids)
    rationales = tuple(owner_rationales)
    if len(selected) != len(set(selected)):
        raise OwnerTeamInputError("DUPLICATE_AGENT")
    rationale_ids = tuple(value.agent_id for value in rationales)
    if len(rationale_ids) != len(set(rationale_ids)):
        raise OwnerTeamInputError("DUPLICATE_RATIONALE")
    constraints = determine_team_constraints(
        project_mode=context.project_mode, brief=context.brief_version.brief
    )
    if not set(constraints.mandatory_agent_ids).issubset(selected):
        raise OwnerTeamInputError("MANDATORY_AGENT_MISSING")
    reasons = {value.agent_id: value.statement for value in rationales}
    members = []
    for entry in all_agent_catalog_entries():
        if entry.agent_id not in selected:
            continue
        constraint = constraints.constraint_for(entry.agent_id)
        if constraint.kind is TeamRoleConstraintKind.IMPOSSIBLE:
            raise OwnerTeamInputError("AGENT_NOT_SELECTABLE")
        if constraint.kind is TeamRoleConstraintKind.MANDATORY:
            if entry.agent_id in reasons:
                raise OwnerTeamInputError("UNUSED_RATIONALE")
            member = ProposedTeamMember(
                agent_id=entry.agent_id,
                source=TeamProposalMemberSource.DETERMINISTIC_MANDATORY,
                justifications=tuple(
                    deterministic_justification(reason) for reason in constraint.reasons
                ),
            )
        else:
            statement = reasons.pop(entry.agent_id, None)
            if statement is None:
                raise OwnerTeamInputError("RATIONALE_REQUIRED")
            member = ProposedTeamMember(
                agent_id=entry.agent_id,
                source=TeamProposalMemberSource.OWNER_ADDED,
                justifications=(
                    TeamProposalJustification(
                        kind=TeamProposalJustificationKind.OWNER_RATIONALE,
                        code="OWNER_PROVIDED_ROLE",
                        statement=statement,
                    ),
                ),
            )
        members.append(member)
    if reasons:
        raise OwnerTeamInputError("UNUSED_RATIONALE")
    if len(members) != len(selected):
        raise OwnerTeamInputError("AGENT_NOT_SELECTABLE")
    brief = context.brief_version
    return AgentTeamProposal(
        schema_version=TEAM_PROPOSAL_SCHEMA_VERSION,
        provider_kind=TeamProposalProviderKind.FAKE_DETERMINISTIC,
        provider_id="owner-input",
        provider_version=1,
        project_id=context.project_id,
        project_mode=context.project_mode,
        brief_version_id=brief.id,
        brief_version_number=brief.version_number,
        brief_content_hash=brief.content_hash,
        catalog_version=constraints.catalog_version,
        catalog_content_hash=constraints.catalog_content_hash,
        constraints=constraints,
        members=tuple(members),
    )


class OwnerTeamInputService:
    def __init__(self, *, unit_of_work_factory: TeamProposalUnitOfWorkFactory) -> None:
        self._unit_of_work_factory = unit_of_work_factory

    async def create(
        self, *, project_id, owner_user_id, selected_agent_ids, owner_rationales=()
    ) -> TeamProposalApplicationResult:
        async with self._unit_of_work_factory() as unit:
            context = await unit.contexts.get_current_owned_for_update(
                project_id=project_id, owner_user_id=owner_user_id
            )
            failure = LocalTeamProposalApplicationService._precondition_result(context)
            if failure is not None:
                return failure
            if context is None:
                raise RuntimeError("ready team context is missing")
            if (
                await unit.proposals.get_current_owned(
                    project_id=project_id, owner_user_id=owner_user_id
                )
                is not None
            ):
                raise OwnerTeamInputError("TEAM_PROPOSAL_ALREADY_EXISTS")
            proposal = owner_team_proposal(context, selected_agent_ids, owner_rationales)
            persisted = await unit.proposals.create_owner_provided_owned(
                project_id=project_id, owner_user_id=owner_user_id, proposal=proposal
            )
            if persisted.status is TeamProposalVersionCreationStatus.PROJECT_NOT_FOUND:
                return TeamProposalApplicationResult(
                    status=TeamProposalApplicationStatus.CONTEXT_CHANGED
                )
            return TeamProposalApplicationResult(
                status=TeamProposalApplicationStatus.CREATED,
                version=persisted.version,
                issues=proposal.constraints.issues,
            )
