"""Typed provider-independent contracts for agent-team proposals."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final, Protocol, runtime_checkable
from uuid import UUID

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
    all_agent_catalog_entries,
    catalog_entry,
)
from orchestwin.agents.selection_rules import (
    DeterministicTeamConstraints,
    TeamRoleConstraintKind,
    TeamSelectionIssue,
    TeamSelectionReason,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
)
from orchestwin.projects.domain import (
    ProjectMode,
)

TEAM_PROPOSAL_SCHEMA_VERSION: Final = 1
MAX_PROPOSAL_JUSTIFICATION_LENGTH: Final = 2000
MAX_PROPOSAL_PROVIDER_ID_LENGTH: Final = 128

_BRIEF_FIELD_ORDER: Final = tuple(BriefField)
_AGENT_CATALOG_ORDER: Final = tuple(entry.agent_id for entry in all_agent_catalog_entries())


def _is_sha256_digest(
    value: str,
) -> bool:
    """Return whether a value is a lowercase SHA-256 digest."""
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _ordered_fields(
    fields: tuple[BriefField, ...],
) -> tuple[BriefField, ...]:
    """Return fields in stable Project Brief declaration order."""
    unique_fields = set(fields)

    return tuple(field for field in _BRIEF_FIELD_ORDER if field in unique_fields)


def _agent_position(
    agent_id: AgentIdentifier,
) -> int:
    """Return the stable position of an agent in the fixed catalog."""
    return _AGENT_CATALOG_ORDER.index(agent_id)


class TeamProposalProviderKind(StrEnum):
    """Categories of adapters that can produce a team proposal."""

    FAKE_DETERMINISTIC = "FAKE_DETERMINISTIC"
    MODEL_ADAPTER = "MODEL_ADAPTER"


class TeamProposalMemberSource(StrEnum):
    """Origin of one selected member in a proposal."""

    DETERMINISTIC_MANDATORY = "DETERMINISTIC_MANDATORY"
    PROPOSER_SUGGESTED = "PROPOSER_SUGGESTED"


class TeamProposalJustificationKind(StrEnum):
    """Kinds of structured justification attached to a member."""

    DETERMINISTIC_RULE = "DETERMINISTIC_RULE"
    PROPOSER_RATIONALE = "PROPOSER_RATIONALE"


class TeamProposalGenerationStatus(StrEnum):
    """Stable outcomes of requesting a team proposal."""

    PROPOSED = "PROPOSED"
    BLOCKED_BY_CONSTRAINTS = "BLOCKED_BY_CONSTRAINTS"


@dataclass(frozen=True, slots=True)
class TeamProposalJustification:
    """One typed justification for including an agent."""

    kind: TeamProposalJustificationKind
    code: str
    evidence_fields: tuple[
        BriefField,
        ...,
    ] = ()
    evidence_terms: tuple[
        str,
        ...,
    ] = ()
    statement: str | None = None

    def __post_init__(self) -> None:
        """Protect code, evidence, and rationale invariants."""
        if (
            re.fullmatch(
                r"[A-Z][A-Z0-9_]{0,127}",
                self.code,
            )
            is None
        ):
            raise ValueError(
                "team-proposal justification code must be a stable uppercase identifier"
            )

        if self.evidence_fields != _ordered_fields(self.evidence_fields):
            raise ValueError(
                "team-proposal evidence fields must be unique and use Project Brief order"
            )

        normalized_terms = tuple(
            sorted(
                {
                    normalized
                    for term in self.evidence_terms
                    if (normalized := " ".join(term.split()).casefold())
                }
            )
        )

        if self.evidence_terms != normalized_terms:
            raise ValueError("team-proposal evidence terms must be normalized, unique, and ordered")

        if self.kind is TeamProposalJustificationKind.DETERMINISTIC_RULE:
            if self.statement is not None:
                raise ValueError(
                    "deterministic justifications must not contain free-text rationale"
                )

            return

        if self.statement is None:
            raise ValueError("proposer rationale is required for a suggested role")

        normalized_statement = " ".join(self.statement.split())

        if not normalized_statement or normalized_statement != self.statement:
            raise ValueError("team-proposal rationale must be normalized")

        if len(self.statement) > MAX_PROPOSAL_JUSTIFICATION_LENGTH:
            raise ValueError("team-proposal rationale exceeds maximum length")


@dataclass(frozen=True, slots=True)
class ProposedTeamMember:
    """One fixed-catalog agent selected in a team proposal."""

    agent_id: AgentIdentifier
    source: TeamProposalMemberSource
    justifications: tuple[
        TeamProposalJustification,
        ...,
    ]

    def __post_init__(self) -> None:
        """Protect catalog membership and source invariants."""
        catalog_entry(self.agent_id)

        if not self.justifications:
            raise ValueError("a proposed team member requires justification")

        if len(self.justifications) != len(set(self.justifications)):
            raise ValueError("proposed team-member justifications must be unique")

        if self.source is TeamProposalMemberSource.DETERMINISTIC_MANDATORY:
            if any(
                justification.kind is not TeamProposalJustificationKind.DETERMINISTIC_RULE
                for justification in self.justifications
            ):
                raise ValueError("mandatory members require only deterministic justifications")

            return

        if not any(
            justification.kind is TeamProposalJustificationKind.PROPOSER_RATIONALE
            for justification in self.justifications
        ):
            raise ValueError("a proposer-suggested member requires a structured rationale")


@dataclass(frozen=True, slots=True)
class TeamProposalRequest:
    """Typed context supplied to a team-proposal adapter."""

    project_mode: ProjectMode
    brief_version: ProjectBriefVersion
    constraints: DeterministicTeamConstraints

    def __post_init__(self) -> None:
        """Protect request alignment with deterministic constraints."""
        if self.constraints.project_mode is not self.project_mode:
            raise ValueError("team-proposal request mode must match the deterministic constraints")

        if (
            self.constraints.catalog_version != AGENT_CATALOG_VERSION
            or self.constraints.catalog_content_hash != AGENT_CATALOG_CONTENT_HASH
        ):
            raise ValueError("team-proposal request must use the current agent catalog")


@dataclass(frozen=True, slots=True)
class AgentTeamProposal:
    """Immutable provider output for one Project Brief version."""

    schema_version: int
    provider_kind: TeamProposalProviderKind
    provider_id: str
    provider_version: int
    project_id: UUID
    project_mode: ProjectMode
    brief_version_id: UUID
    brief_version_number: int
    brief_content_hash: str
    catalog_version: int
    catalog_content_hash: str
    constraints: DeterministicTeamConstraints = field(repr=False)
    members: tuple[
        ProposedTeamMember,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        """Protect provenance, coverage, ordering, and role constraints."""
        if self.schema_version != TEAM_PROPOSAL_SCHEMA_VERSION:
            raise ValueError("team proposal must use the current schema version")

        normalized_provider_id = self.provider_id.strip()

        if not normalized_provider_id or normalized_provider_id != self.provider_id:
            raise ValueError("team-proposal provider ID must be normalized")

        if len(self.provider_id) > MAX_PROPOSAL_PROVIDER_ID_LENGTH:
            raise ValueError("team-proposal provider ID exceeds maximum length")

        if self.provider_version < 1:
            raise ValueError("team-proposal provider version must be positive")

        if self.brief_version_number < 1:
            raise ValueError("team-proposal brief version must be positive")

        if not _is_sha256_digest(self.brief_content_hash):
            raise ValueError("team-proposal brief hash must be a lowercase SHA-256 digest")

        if self.project_mode is not self.constraints.project_mode:
            raise ValueError("team proposal mode must match its constraints")

        if (
            self.catalog_version != self.constraints.catalog_version
            or self.catalog_content_hash != self.constraints.catalog_content_hash
        ):
            raise ValueError(
                "team proposal catalog metadata must match its deterministic constraints"
            )

        if (
            self.catalog_version != AGENT_CATALOG_VERSION
            or self.catalog_content_hash != AGENT_CATALOG_CONTENT_HASH
        ):
            raise ValueError("team proposal must use the current fixed catalog")

        member_ids = tuple(member.agent_id for member in self.members)

        if len(member_ids) != len(set(member_ids)):
            raise ValueError("team proposal must not contain duplicate agents")

        expected_member_order = tuple(
            sorted(
                self.members,
                key=lambda member: _agent_position(member.agent_id),
            )
        )

        if self.members != expected_member_order:
            raise ValueError("team proposal members must use fixed-catalog order")

        missing_mandatory = tuple(
            agent_id
            for agent_id in self.constraints.mandatory_agent_ids
            if agent_id not in member_ids
        )

        if missing_mandatory:
            raise ValueError("team proposal must contain every mandatory agent")

        for member in self.members:
            constraint = self.constraints.constraint_for(member.agent_id)

            if constraint.kind in {
                TeamRoleConstraintKind.IMPOSSIBLE,
                TeamRoleConstraintKind.CONFLICT,
            }:
                raise ValueError("team proposal cannot include an impossible or conflicting agent")

            if constraint.kind is TeamRoleConstraintKind.MANDATORY:
                if member.source is not TeamProposalMemberSource.DETERMINISTIC_MANDATORY:
                    raise ValueError("mandatory roles must preserve their deterministic source")

                expected_justifications = tuple(
                    deterministic_justification(reason) for reason in constraint.reasons
                )

                if member.justifications != expected_justifications:
                    raise ValueError(
                        "mandatory role justifications must match the deterministic constraints"
                    )

                continue

            if member.source is not TeamProposalMemberSource.PROPOSER_SUGGESTED:
                raise ValueError("optional roles must be marked as proposer-suggested")

    @property
    def selected_agent_ids(
        self,
    ) -> tuple[AgentIdentifier, ...]:
        """Return selected agents in fixed-catalog order."""
        return tuple(member.agent_id for member in self.members)

    @property
    def mandatory_agent_ids(
        self,
    ) -> tuple[AgentIdentifier, ...]:
        """Return members required by deterministic constraints."""
        return tuple(
            member.agent_id
            for member in self.members
            if (member.source is TeamProposalMemberSource.DETERMINISTIC_MANDATORY)
        )

    @property
    def suggested_agent_ids(
        self,
    ) -> tuple[AgentIdentifier, ...]:
        """Return optional roles selected by the proposal adapter."""
        return tuple(
            member.agent_id
            for member in self.members
            if (member.source is TeamProposalMemberSource.PROPOSER_SUGGESTED)
        )

    def member_for(
        self,
        agent_id: AgentIdentifier,
    ) -> ProposedTeamMember:
        """Return one selected member by stable agent identifier."""
        for member in self.members:
            if member.agent_id is agent_id:
                return member

        raise KeyError(agent_id)

    def to_snapshot(
        self,
    ) -> dict[str, object]:
        """Return a deterministic JSON-serializable proposal snapshot."""
        return {
            "schema_version": self.schema_version,
            "provider": {
                "kind": self.provider_kind.value,
                "provider_id": self.provider_id,
                "provider_version": (self.provider_version),
            },
            "project_id": str(self.project_id),
            "project_mode": (self.project_mode.value),
            "brief_version": {
                "id": str(self.brief_version_id),
                "version_number": (self.brief_version_number),
                "content_hash": (self.brief_content_hash),
            },
            "catalog": {
                "version": self.catalog_version,
                "content_hash": (self.catalog_content_hash),
            },
            "constraints": (self.constraints.to_snapshot()),
            "constraints_content_hash": (self.constraints.content_hash),
            "members": [
                {
                    "agent_id": (member.agent_id.value),
                    "source": (member.source.value),
                    "justifications": [
                        {
                            "kind": (justification.kind.value),
                            "code": (justification.code),
                            "evidence_fields": [
                                field.value for field in justification.evidence_fields
                            ],
                            "evidence_terms": list(justification.evidence_terms),
                            "statement": (justification.statement),
                        }
                        for justification in member.justifications
                    ],
                }
                for member in self.members
            ],
        }

    def canonical_json(
        self,
    ) -> str:
        """Serialize the proposal with deterministic ordering."""
        return json.dumps(
            self.to_snapshot(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(
                ",",
                ":",
            ),
        )

    @property
    def content_hash(
        self,
    ) -> str:
        """Return the SHA-256 hash of the complete proposal."""
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class TeamProposalGenerationResult:
    """Typed result returned by a team-proposal adapter."""

    status: TeamProposalGenerationStatus
    proposal: AgentTeamProposal | None = None
    issues: tuple[
        TeamSelectionIssue,
        ...,
    ] = ()

    def __post_init__(self) -> None:
        """Protect proposed and blocked result shapes."""
        if self.status is TeamProposalGenerationStatus.PROPOSED:
            if self.proposal is None or self.issues:
                raise ValueError("a proposed result requires only a proposal")

            return

        if self.proposal is not None or not self.issues:
            raise ValueError(
                "a blocked proposal result requires constraint issues without a proposal"
            )


@runtime_checkable
class TeamProposalPort(Protocol):
    """Provider-independent asynchronous team-proposal boundary."""

    async def propose(
        self,
        request: TeamProposalRequest,
    ) -> TeamProposalGenerationResult:
        """Produce a typed team proposal or a blocked result."""


def deterministic_justification(
    reason: TeamSelectionReason,
) -> TeamProposalJustification:
    """Convert a deterministic rule reason into proposal justification."""
    return TeamProposalJustification(
        kind=(TeamProposalJustificationKind.DETERMINISTIC_RULE),
        code=reason.code.value,
        evidence_fields=(reason.evidence.fields),
        evidence_terms=(reason.evidence.terms),
    )
