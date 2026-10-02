from __future__ import annotations

from dataclasses import replace

from orchestwin.agents.selection_rules import TeamRoleConstraintKind, determine_team_constraints
from orchestwin.models.team_proposals import (
    AgentTeamProposal,
    ProposedTeamMember,
    TeamProposalJustification,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
    deterministic_justification,
)
from orchestwin.projects.briefs import ProjectBrief, ProjectBriefVersion
from orchestwin.projects.domain import ProjectMode

PREPARE_AGAIN = "PREPARE_AGAIN"


class TeamRealignmentError(Exception):
    def __init__(self, code: str = PREPARE_AGAIN) -> None:
        super().__init__(code)
        self.code = code


def team_selection_can_realign(
    proposal: AgentTeamProposal, *, brief: ProjectBrief, project_mode: ProjectMode
) -> bool:
    constraints = determine_team_constraints(project_mode=project_mode, brief=brief)
    selected = frozenset(proposal.selected_agent_ids)
    return (
        proposal.project_mode is project_mode
        and not constraints.issues
        and frozenset(constraints.mandatory_agent_ids) <= selected
        and all(
            constraints.constraint_for(agent).kind
            not in {TeamRoleConstraintKind.IMPOSSIBLE, TeamRoleConstraintKind.CONFLICT}
            for agent in selected
        )
    )


def reanchored_team(
    proposal: AgentTeamProposal, *, brief: ProjectBriefVersion, project_mode: ProjectMode
) -> AgentTeamProposal:
    if proposal.project_id != brief.project_id or not team_selection_can_realign(
        proposal, brief=brief.brief, project_mode=project_mode
    ):
        raise TeamRealignmentError()
    constraints = determine_team_constraints(project_mode=project_mode, brief=brief.brief)
    members = []
    for member in proposal.members:
        constraint = constraints.constraint_for(member.agent_id)
        if constraint.kind is TeamRoleConstraintKind.MANDATORY:
            updated = ProposedTeamMember(
                agent_id=member.agent_id,
                source=TeamProposalMemberSource.DETERMINISTIC_MANDATORY,
                justifications=tuple(
                    deterministic_justification(reason) for reason in constraint.reasons
                ),
            )
        elif member.source is TeamProposalMemberSource.DETERMINISTIC_MANDATORY:
            updated = ProposedTeamMember(
                agent_id=member.agent_id,
                source=TeamProposalMemberSource.OWNER_ADDED,
                justifications=(
                    TeamProposalJustification(
                        kind=TeamProposalJustificationKind.OWNER_RATIONALE,
                        code="OWNER_CHOICE",
                        statement="Retained from the team previously approved by the owner.",
                    ),
                ),
            )
        else:
            updated = member
        members.append(updated)
    return replace(
        proposal,
        brief_version_id=brief.id,
        brief_version_number=brief.version_number,
        brief_content_hash=brief.content_hash,
        constraints=constraints,
        catalog_version=constraints.catalog_version,
        catalog_content_hash=constraints.catalog_content_hash,
        members=tuple(members),
    )


__all__ = ["PREPARE_AGAIN", "TeamRealignmentError", "reanchored_team", "team_selection_can_realign"]
