"""Deterministic fake adapter for typed agent-team proposals."""

from __future__ import annotations

from typing import ClassVar

from orchestwin.agents.selection_rules import (
    TeamRoleConstraintKind,
)
from orchestwin.models.team_proposals import (
    TEAM_PROPOSAL_SCHEMA_VERSION,
    AgentTeamProposal,
    ProposedTeamMember,
    TeamProposalGenerationResult,
    TeamProposalGenerationStatus,
    TeamProposalMemberSource,
    TeamProposalProviderKind,
    TeamProposalRequest,
    deterministic_justification,
)


class FakeDeterministicTeamProposalAdapter:
    """Propose all mandatory roles without network or model inference."""

    PROVIDER_ID: ClassVar[str] = "fake-deterministic-team-proposal"
    PROVIDER_VERSION: ClassVar[int] = 1

    async def propose(
        self,
        request: TeamProposalRequest,
    ) -> TeamProposalGenerationResult:
        """Return a reproducible mandatory-only team proposal."""
        constraints = request.constraints

        if constraints.has_conflicts:
            return TeamProposalGenerationResult(
                status=(TeamProposalGenerationStatus.BLOCKED_BY_CONSTRAINTS),
                issues=constraints.issues,
            )

        members = tuple(
            ProposedTeamMember(
                agent_id=constraint.agent_id,
                source=(TeamProposalMemberSource.DETERMINISTIC_MANDATORY),
                justifications=tuple(
                    deterministic_justification(reason) for reason in constraint.reasons
                ),
            )
            for constraint in constraints.role_constraints
            if (constraint.kind is TeamRoleConstraintKind.MANDATORY)
        )

        proposal = AgentTeamProposal(
            schema_version=(TEAM_PROPOSAL_SCHEMA_VERSION),
            provider_kind=(TeamProposalProviderKind.FAKE_DETERMINISTIC),
            provider_id=self.PROVIDER_ID,
            provider_version=(self.PROVIDER_VERSION),
            project_id=(request.brief_version.project_id),
            project_mode=(request.project_mode),
            brief_version_id=(request.brief_version.id),
            brief_version_number=(request.brief_version.version_number),
            brief_content_hash=(request.brief_version.content_hash),
            catalog_version=(constraints.catalog_version),
            catalog_content_hash=(constraints.catalog_content_hash),
            constraints=constraints,
            members=members,
        )

        return TeamProposalGenerationResult(
            status=(TeamProposalGenerationStatus.PROPOSED),
            proposal=proposal,
        )
