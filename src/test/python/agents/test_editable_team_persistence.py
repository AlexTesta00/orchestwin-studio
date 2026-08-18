"""Tests for SQLAlchemy persistence of owner-edited teams."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from sqlalchemy.dialects import (
    postgresql,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from orchestwin.agents.catalog import (
    AgentIdentifier,
    all_agent_catalog_entries,
)
from orchestwin.agents.persistence.models import (
    TeamProposalVersionRecord,
)
from orchestwin.agents.persistence.team_gate import (
    SqlAlchemyEditableTeamProposalRepository,
    latest_owned_team_proposal_for_update_statement,
)
from orchestwin.agents.proposals import (
    TeamProposalRevisionKind,
    TeamProposalVersion,
)
from orchestwin.agents.selection_rules import (
    determine_team_constraints,
)
from orchestwin.agents.team_gate import (
    OwnerEditedProposalPersistenceStatus,
)
from orchestwin.models.fake_team_proposals import (
    FakeDeterministicTeamProposalAdapter,
)
from orchestwin.models.team_proposals import (
    ProposedTeamMember,
    TeamProposalJustification,
    TeamProposalJustificationKind,
    TeamProposalMemberSource,
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
from orchestwin.projects.persistence.models import (
    ProjectRecord,
)

OWNER_ID = UUID("00000000-0000-4000-8000-000000000001")
PROJECT_ID = UUID("00000000-0000-4000-8000-000000000010")
INITIAL_PROPOSAL_ID = UUID("00000000-0000-4000-8000-000000000020")
EDITED_PROPOSAL_ID = UUID("00000000-0000-4000-8000-000000000021")
BRIEF_VERSION_ID = UUID("00000000-0000-4000-8000-000000000030")
NOW = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)

_AGENT_CATALOG_ORDER = tuple(entry.agent_id for entry in all_agent_catalog_entries())


def ordered_members(
    *members: ProposedTeamMember,
) -> tuple[ProposedTeamMember, ...]:
    """Return fixture members in fixed-catalog order."""
    members_by_agent = {member.agent_id: member for member in members}

    if len(members_by_agent) != len(members):
        raise ValueError("team-proposal fixture contains duplicate agents")

    return tuple(
        members_by_agent[agent_id]
        for agent_id in _AGENT_CATALOG_ORDER
        if agent_id in members_by_agent
    )


async def build_versions():
    """Create a generated version and an owner-edited proposal."""
    provided = {
        BriefField.NAME,
        BriefField.DESCRIPTION,
        BriefField.TECHNICAL_CONSTRAINTS,
    }
    brief = create_project_brief(
        name="Persistence project",
        description=("A Vue web application with a FastAPI backend."),
        technical_constraints=[
            "Vue frontend",
            "FastAPI backend",
            "PostgreSQL database",
        ],
        unknown_fields=[field for field in BriefField if field not in provided],
    )
    brief_version = ProjectBriefVersion(
        id=BRIEF_VERSION_ID,
        project_id=PROJECT_ID,
        version_number=1,
        schema_version=(brief.SCHEMA_VERSION),
        brief=brief,
        content_hash=brief.content_hash,
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )
    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )
    generated = await FakeDeterministicTeamProposalAdapter().propose(
        TeamProposalRequest(
            project_mode=(ProjectMode.GREENFIELD_GENERATION),
            brief_version=brief_version,
            constraints=constraints,
        )
    )

    assert generated.proposal is not None

    initial = TeamProposalVersion(
        id=INITIAL_PROPOSAL_ID,
        project_id=PROJECT_ID,
        version_number=1,
        proposal=generated.proposal,
        revision_kind=(TeamProposalRevisionKind.PROPOSER_GENERATED),
        created_by_user_id=OWNER_ID,
        created_at=NOW,
    )
    mobile = ProposedTeamMember(
        agent_id=(AgentIdentifier.MOBILE_ENGINEER),
        source=(TeamProposalMemberSource.OWNER_ADDED),
        justifications=(
            TeamProposalJustification(
                kind=(TeamProposalJustificationKind.OWNER_RATIONALE),
                code=("OWNER_SELECTED_ROLE"),
                statement=("Add optional mobile expertise."),
            ),
        ),
    )
    edited = replace(
        initial.proposal,
        members=ordered_members(
            *initial.proposal.members,
            mobile,
        ),
    )

    return initial, edited


def record_from_version(
    version: TeamProposalVersion,
) -> TeamProposalVersionRecord:
    """Create one persisted record for the current version."""
    proposal = version.proposal

    return TeamProposalVersionRecord(
        id=version.id,
        project_id=version.project_id,
        version_number=(version.version_number),
        schema_version=(proposal.schema_version),
        revision_kind=(version.revision_kind.value),
        based_on_version_number=(version.based_on_version_number),
        brief_version_id=(proposal.brief_version_id),
        brief_version_number=(proposal.brief_version_number),
        brief_content_hash=(proposal.brief_content_hash),
        catalog_version=(proposal.catalog_version),
        catalog_content_hash=(proposal.catalog_content_hash),
        constraints_content_hash=(proposal.constraints.content_hash),
        provider_kind=(proposal.provider_kind.value),
        provider_id=proposal.provider_id,
        provider_version=(proposal.provider_version),
        content=proposal.to_snapshot(),
        content_hash=proposal.content_hash,
        created_by_user_id=(version.created_by_user_id),
        created_at=version.created_at,
    )


def compile_statement(
    statement: object,
) -> str:
    """Compile one statement using PostgreSQL syntax."""
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={
                "literal_binds": True,
            },
        )
    )


def test_locked_current_proposal_query_is_owner_scoped() -> None:
    """Lock the current proposal through project ownership."""
    sql = compile_statement(
        latest_owned_team_proposal_for_update_statement(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert "projects.id =" in sql
    assert "projects.owner_user_id =" in sql
    assert "projects.archived_at IS NULL" in sql
    assert "ORDER BY team_proposals.version_number DESC" in sql
    assert "FOR UPDATE" in sql


def test_repository_creates_owner_edited_version() -> None:
    """Persist version two with explicit lineage and provenance."""
    initial, edited = asyncio.run(build_versions())
    project = ProjectRecord(
        id=PROJECT_ID,
        owner_user_id=OWNER_ID,
        display_name="Persistence project",
        mode=(ProjectMode.GREENFIELD_GENERATION.value),
        current_brief_version=1,
        archived_at=None,
        created_at=NOW,
        updated_at=NOW,
    )
    current_record = record_from_version(initial)
    session = Mock(spec=AsyncSession)
    session.scalar = AsyncMock(
        side_effect=[
            project,
            current_record,
        ]
    )
    session.flush = AsyncMock()
    repository = SqlAlchemyEditableTeamProposalRepository(
        session,
        clock=lambda: NOW,
        uuid_factory=lambda: EDITED_PROPOSAL_ID,
    )

    result = asyncio.run(
        repository.create_owner_edited_owned(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            based_on=initial,
            proposal=edited,
        )
    )

    assert result.status is (OwnerEditedProposalPersistenceStatus.CREATED)
    assert result.version is not None
    assert result.version.version_number == 2
    assert result.version.based_on_version_number == 1
    assert result.version.revision_kind is (TeamProposalRevisionKind.OWNER_EDITED)

    session.add.assert_called_once()
    session.flush.assert_awaited_once()

    record = session.add.call_args.args[0]

    assert isinstance(
        record,
        TeamProposalVersionRecord,
    )
    assert record.id == (EDITED_PROPOSAL_ID)
    assert record.version_number == 2
    assert record.revision_kind == ("OWNER_EDITED")
    assert record.based_on_version_number == 1
    assert record.content == (edited.to_snapshot())
    assert record.content_hash == (edited.content_hash)


def test_owner_added_snapshot_round_trips() -> None:
    """Reconstruct owner provenance and rationale from JSONB."""
    from orchestwin.agents.persistence.repositories import (
        proposal_from_snapshot,
    )

    _, edited = asyncio.run(build_versions())

    reconstructed = proposal_from_snapshot(edited.to_snapshot())

    assert reconstructed == edited

    selected_agent_ids = set(reconstructed.selected_agent_ids)

    assert reconstructed.selected_agent_ids == tuple(
        agent_id for agent_id in _AGENT_CATALOG_ORDER if agent_id in selected_agent_ids
    )

    mobile = reconstructed.member_for(AgentIdentifier.MOBILE_ENGINEER)

    assert mobile.source is (TeamProposalMemberSource.OWNER_ADDED)
    assert mobile.justifications[0].kind is (TeamProposalJustificationKind.OWNER_RATIONALE)
