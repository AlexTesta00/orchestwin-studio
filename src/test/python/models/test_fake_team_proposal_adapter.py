"""Tests for the typed team-proposal port and fake adapter."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

import pytest

from orchestwin.agents.catalog import (
    AGENT_CATALOG_CONTENT_HASH,
    AGENT_CATALOG_VERSION,
    AgentIdentifier,
)
from orchestwin.agents.selection_rules import (
    TeamSelectionReasonCode,
    determine_team_constraints,
)
from orchestwin.models.fake_team_proposals import (
    FakeDeterministicTeamProposalAdapter,
)
from orchestwin.models.team_proposals import (
    ProposedTeamMember,
    TeamProposalGenerationStatus,
    TeamProposalJustification,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
    TeamProposalPort,
    TeamProposalRequest,
)
from orchestwin.projects.briefs import (
    BriefField,
    ProjectBriefVersion,
    create_project_brief,
)
from orchestwin.projects.domain import (
    ProjectMode,
)

PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
BRIEF_VERSION_ID = UUID("00000000-0000-4000-8000-000000000020")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
CREATED_AT = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)


def build_request(
    *,
    project_mode: ProjectMode = (ProjectMode.GREENFIELD_GENERATION),
    description: str = ("An accessible Vue web application with a browser dashboard."),
) -> TeamProposalRequest:
    """Create a deterministic proposal request."""
    provided_fields = {
        BriefField.NAME,
        BriefField.DESCRIPTION,
        BriefField.TECHNICAL_CONSTRAINTS,
        BriefField.FUNCTIONAL_REQUIREMENTS,
    }

    brief = create_project_brief(
        name="OrchesTwin fixture",
        description=description,
        technical_constraints=[
            "Vue frontend",
            "FastAPI backend",
            "PostgreSQL database",
            "WCAG 2.2 AA",
        ],
        functional_requirements=[
            "Users log in with a password.",
        ],
        unknown_fields=[field for field in BriefField if field not in provided_fields],
    )
    version = ProjectBriefVersion(
        id=BRIEF_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
    constraints = determine_team_constraints(
        project_mode=project_mode,
        brief=brief,
    )

    return TeamProposalRequest(
        project_mode=project_mode,
        brief_version=version,
        constraints=constraints,
    )


def build_conflicting_request() -> TeamProposalRequest:
    """Create a request with contradictory frontend signals."""
    provided_fields = {
        BriefField.NAME,
        BriefField.DESCRIPTION,
    }
    brief = create_project_brief(
        name="Contradictory project",
        description=("Use Vue for the frontend, but the final product must have no frontend."),
        unknown_fields=[field for field in BriefField if field not in provided_fields],
    )
    version = ProjectBriefVersion(
        id=BRIEF_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=CREATED_AT,
    )
    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )

    assert constraints.has_conflicts is True

    return TeamProposalRequest(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief_version=version,
        constraints=constraints,
    )


def test_fake_adapter_implements_typed_port() -> None:
    """Expose the fake through the provider-independent protocol."""
    adapter = FakeDeterministicTeamProposalAdapter()

    assert isinstance(
        adapter,
        TeamProposalPort,
    )


def test_request_rejects_project_mode_mismatch() -> None:
    """Keep the proposal request aligned with its constraints."""
    request = build_request()

    with pytest.raises(
        ValueError,
        match=("request mode must match the deterministic constraints"),
    ):
        TeamProposalRequest(
            project_mode=(ProjectMode.BROWNFIELD_ASSESSMENT),
            brief_version=(request.brief_version),
            constraints=(request.constraints),
        )


def test_fake_proposes_all_and_only_mandatory_roles() -> None:
    """Return a safe mandatory-only team in catalog order."""
    request = build_request()
    adapter = FakeDeterministicTeamProposalAdapter()

    result = asyncio.run(adapter.propose(request))

    assert result.status is (TeamProposalGenerationStatus.PROPOSED)
    assert result.issues == ()
    assert result.proposal is not None

    proposal = result.proposal

    assert proposal.selected_agent_ids == request.constraints.mandatory_agent_ids
    assert proposal.mandatory_agent_ids == request.constraints.mandatory_agent_ids
    assert proposal.suggested_agent_ids == ()

    assert not (set(proposal.selected_agent_ids) & set(request.constraints.impossible_agent_ids))


def test_fake_preserves_rule_justification_and_evidence() -> None:
    """Keep deterministic provenance for each selected role."""
    request = build_request()
    adapter = FakeDeterministicTeamProposalAdapter()

    result = asyncio.run(adapter.propose(request))

    assert result.proposal is not None

    frontend = result.proposal.member_for(AgentIdentifier.FRONTEND_ENGINEER)
    web_justification = next(
        justification
        for justification in frontend.justifications
        if (justification.code == TeamSelectionReasonCode.WEB_DELIVERY_SIGNAL.value)
    )

    assert frontend.source is (TeamProposalMemberSource.DETERMINISTIC_MANDATORY)
    assert web_justification.kind is (TeamProposalJustificationKind.DETERMINISTIC_RULE)
    assert BriefField.DESCRIPTION in web_justification.evidence_fields
    assert "vue" in web_justification.evidence_terms
    assert web_justification.statement is None


def test_suggested_member_requires_proposer_rationale() -> None:
    """Reserve optional selection for explicitly justified proposals."""
    with pytest.raises(
        ValueError,
        match=("proposer-suggested member requires a structured rationale"),
    ):
        ProposedTeamMember(
            agent_id=(AgentIdentifier.MOBILE_ENGINEER),
            source=(TeamProposalMemberSource.PROPOSER_SUGGESTED),
            justifications=(
                TeamProposalJustification(
                    kind=(TeamProposalJustificationKind.DETERMINISTIC_RULE),
                    code=(TeamSelectionReasonCode.MOBILE_DELIVERY_SIGNAL.value),
                ),
            ),
        )


def test_constraint_conflict_blocks_fake_proposal() -> None:
    """Return typed blocking issues instead of choosing silently."""
    request = build_conflicting_request()
    adapter = FakeDeterministicTeamProposalAdapter()

    result = asyncio.run(adapter.propose(request))

    assert result.status is (TeamProposalGenerationStatus.BLOCKED_BY_CONSTRAINTS)
    assert result.proposal is None
    assert result.issues == (request.constraints.issues)
    assert result.issues[0].agent_id is AgentIdentifier.FRONTEND_ENGINEER


def test_fake_proposal_is_reproducible_and_hashable() -> None:
    """Produce identical typed output for identical input."""
    request = build_request()
    adapter = FakeDeterministicTeamProposalAdapter()

    first = asyncio.run(adapter.propose(request))
    second = asyncio.run(adapter.propose(request))

    assert first == second
    assert first.proposal is not None
    assert second.proposal is not None

    first_proposal = first.proposal
    second_proposal = second.proposal

    assert first_proposal.to_snapshot() == second_proposal.to_snapshot()
    assert first_proposal.canonical_json() == second_proposal.canonical_json()
    assert first_proposal.content_hash == second_proposal.content_hash

    assert len(first_proposal.content_hash) == 64
    assert all(character in "0123456789abcdef" for character in first_proposal.content_hash)


def test_proposal_snapshot_preserves_audit_references() -> None:
    """Keep exact brief, catalog, constraint, and provider metadata."""
    request = build_request()
    adapter = FakeDeterministicTeamProposalAdapter()

    result = asyncio.run(adapter.propose(request))

    assert result.proposal is not None

    proposal = result.proposal
    snapshot = proposal.to_snapshot()
    decoded = json.loads(proposal.canonical_json())

    assert decoded == snapshot

    assert snapshot["project_id"] == str(PROJECT_ID)
    assert snapshot["brief_version"] == {
        "id": str(BRIEF_VERSION_ID),
        "version_number": 1,
        "content_hash": (request.brief_version.content_hash),
    }
    assert snapshot["catalog"] == {
        "version": (AGENT_CATALOG_VERSION),
        "content_hash": (AGENT_CATALOG_CONTENT_HASH),
    }
    assert snapshot["constraints_content_hash"] == (request.constraints.content_hash)
    assert snapshot["provider"] == {
        "kind": "FAKE_DETERMINISTIC",
        "provider_id": ("fake-deterministic-team-proposal"),
        "provider_version": 1,
    }
