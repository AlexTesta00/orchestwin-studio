from __future__ import annotations

from typing import Annotated, Final, Literal

from pydantic import Field

from orchestwin.agents.catalog import AgentIdentifier
from orchestwin.agents.selection_rules import (
    TeamRoleConstraintKind,
    TeamSelectionIssueCode,
    TeamSelectionReasonCode,
)
from orchestwin.knowledge.schema_models.base import (
    _BY_VALUE,
    CatalogReference,
    Sha256,
    Uuid,
    _BriefFieldName,
    _Record,
    _Version,
)
from orchestwin.models.team_proposals import (
    TEAM_PROPOSAL_SCHEMA_VERSION,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
    TeamProposalProviderKind,
)
from orchestwin.projects.domain import ProjectMode

_JUSTIFICATION_CODE_PATTERN: Final = r"^[A-Z][A-Z0-9_]{0,127}$"


class ProposalProvider(_Record):
    kind: Annotated[TeamProposalProviderKind, _BY_VALUE] = Field(
        description="Kind of adapter that produced the proposal."
    )
    provider_id: str = Field(description="Identifier of the adapter that produced the proposal.")
    provider_version: _Version = Field(description="Version of that adapter.")


class BriefVersionReference(_Record):
    id: Uuid = Field(description="Identifier of the approved project brief version.")
    version_number: _Version = Field(description="Version number of the project brief.")
    content_hash: Sha256 = Field(description="SHA-256 digest of that project brief version.")


class RuleEvidence(_Record):
    fields: list[_BriefFieldName] = Field(
        description="Brief fields whose text activated the rule, in brief order."
    )
    terms: list[str] = Field(
        description="Normalized terms found in those fields, in alphabetical order."
    )


class SelectionReason(_Record):
    code: Annotated[TeamSelectionReasonCode, _BY_VALUE] = Field(
        description="Deterministic selection rule that produced the constraint."
    )
    evidence: RuleEvidence = Field(
        description="Brief evidence that activated the rule, empty for rules that always apply."
    )


class RoleConstraint(_Record):
    agent_id: Annotated[AgentIdentifier, _BY_VALUE] = Field(
        description="Catalog agent the constraint applies to."
    )
    kind: Annotated[TeamRoleConstraintKind, _BY_VALUE] = Field(
        description="Whether the agent is mandatory, optional, impossible or in conflict."
    )
    owner_editable: bool = Field(description="True when the owner may add or remove the agent.")
    reasons: list[SelectionReason] = Field(
        description="Rules behind the constraint, empty for an optional agent."
    )


class SelectionIssue(_Record):
    code: Annotated[TeamSelectionIssueCode, _BY_VALUE] = Field(
        description="Kind of contradiction that the owner has to resolve."
    )
    agent_id: Annotated[AgentIdentifier, _BY_VALUE] = Field(
        description="Catalog agent affected by the contradiction."
    )


class TeamConstraints(_Record):
    catalog_version: _Version = Field(description="Version of the fixed agent catalog.")
    catalog_content_hash: Sha256 = Field(description="SHA-256 digest of the agent catalog.")
    project_mode: Annotated[ProjectMode, _BY_VALUE] = Field(
        description="Intake mode of the project the constraints were computed for."
    )
    role_constraints: list[RoleConstraint] = Field(
        description="One constraint for every catalog agent, in catalog order."
    )
    issues: list[SelectionIssue] = Field(
        description="Contradictions between brief signals, empty when there is none."
    )


class MemberJustification(_Record):
    kind: Annotated[TeamProposalJustificationKind, _BY_VALUE] = Field(
        description="Whether the justification is a deterministic rule or a written rationale."
    )
    code: str = Field(
        pattern=_JUSTIFICATION_CODE_PATTERN,
        description="Stable uppercase code of the justification.",
    )
    evidence_fields: list[_BriefFieldName] = Field(
        description="Brief fields that support the justification, in brief order."
    )
    evidence_terms: list[str] = Field(
        description="Normalized terms that support the justification, in alphabetical order."
    )
    statement: str | None = Field(
        description="Rationale written by the proposer or the owner, null for a rule."
    )


class TeamMember(_Record):
    agent_id: Annotated[AgentIdentifier, _BY_VALUE] = Field(
        description="Catalog agent selected for the team."
    )
    source: Annotated[TeamProposalMemberSource, _BY_VALUE] = Field(
        description="Whether a rule, the proposer or the owner put the agent in the team."
    )
    justifications: list[MemberJustification] = Field(
        description="Reasons for including the agent."
    )


class TeamProposalSnapshot(_Record):
    schema_version: Literal[TEAM_PROPOSAL_SCHEMA_VERSION] = Field(
        description="Version of the agent team proposal format."
    )
    provider: ProposalProvider = Field(description="Adapter that produced the proposal.")
    project_id: Uuid = Field(description="Project the team belongs to.")
    project_mode: Annotated[ProjectMode, _BY_VALUE] = Field(
        description="Intake mode of the project."
    )
    brief_version: BriefVersionReference = Field(
        description="Approved project brief version the proposal answers."
    )
    catalog: CatalogReference = Field(description="Agent catalog the members come from.")
    constraints: TeamConstraints = Field(
        description="Deterministic role constraints derived from the brief."
    )
    constraints_content_hash: Sha256 = Field(description="SHA-256 digest of the role constraints.")
    members: list[TeamMember] = Field(description="Selected agents, in catalog order.")
