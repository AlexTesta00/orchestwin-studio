"""Tests for immutable team-proposal persistence."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import AsyncMock, Mock
from uuid import UUID

from alembic import command
from alembic.script import (
    ScriptDirectory,
)
from sqlalchemy.dialects import (
    postgresql,
)
from sqlalchemy.ext.asyncio import (
    AsyncSession,
)

from orchestwin.agents.persistence.models import (
    TeamProposalVersionRecord,
)
from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamProposalVersionRepository,
    latest_owned_team_proposal_statement,
    proposal_from_snapshot,
)
from orchestwin.agents.proposals import (
    TeamProposalVersionCreationStatus,
)
from orchestwin.agents.selection_rules import (
    determine_team_constraints,
)
from orchestwin.models.fake_team_proposals import (
    FakeDeterministicTeamProposalAdapter,
)
from orchestwin.models.team_proposals import (
    TeamProposalRequest,
)
from orchestwin.persistence.migrate import (
    create_alembic_config,
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
PROPOSAL_ID = UUID("00000000-0000-4000-8000-000000000020")
BRIEF_VERSION_ID = UUID("00000000-0000-4000-8000-000000000030")
NOW = datetime(
    2026,
    8,
    12,
    12,
    0,
    tzinfo=UTC,
)
TEST_DATABASE_URL = (
    "postgresql+psycopg://user:database-secret-must-not-leak-8472@localhost:5432/orchestwin"
)


def build_proposal():
    """Create one deterministic fake proposal."""
    provided_fields = {
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
        created_at=NOW,
    )
    constraints = determine_team_constraints(
        project_mode=(ProjectMode.GREENFIELD_GENERATION),
        brief=brief,
    )
    result = asyncio.run(
        FakeDeterministicTeamProposalAdapter().propose(
            TeamProposalRequest(
                project_mode=(ProjectMode.GREENFIELD_GENERATION),
                brief_version=version,
                constraints=constraints,
            )
        )
    )

    assert result.proposal is not None

    return result.proposal


def compile_statement(
    statement: object,
) -> str:
    """Compile a statement using PostgreSQL syntax."""
    return str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={
                "literal_binds": True,
            },
        )
    )


def test_latest_proposal_query_is_owner_scoped() -> None:
    """Prevent proposal lookup through project ID alone."""
    sql = compile_statement(
        latest_owned_team_proposal_statement(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
        )
    )

    assert "projects.id =" in sql
    assert "projects.owner_user_id =" in sql
    assert "projects.archived_at IS NULL" in sql
    assert "ORDER BY team_proposals.version_number DESC" in sql


def test_proposal_snapshot_round_trips_to_domain() -> None:
    """Reconstruct the complete proposal and its constraints."""
    proposal = build_proposal()

    reconstructed = proposal_from_snapshot(proposal.to_snapshot())

    assert reconstructed == proposal
    assert reconstructed.content_hash == proposal.content_hash


def test_repository_creates_first_immutable_version() -> None:
    """Persist proposal version one with complete audit metadata."""
    proposal = build_proposal()
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
    session = Mock(spec=AsyncSession)
    session.scalar = AsyncMock(
        side_effect=[
            project,
            None,
        ]
    )
    session.flush = AsyncMock()
    repository = SqlAlchemyTeamProposalVersionRepository(
        session,
        clock=lambda: NOW,
        uuid_factory=lambda: PROPOSAL_ID,
    )

    result = asyncio.run(
        repository.create_generated_owned(
            project_id=PROJECT_ID,
            owner_user_id=OWNER_ID,
            proposal=proposal,
        )
    )

    assert result.status is (TeamProposalVersionCreationStatus.CREATED)
    assert result.version is not None
    assert result.version.version_number == 1

    session.add.assert_called_once()
    session.flush.assert_awaited_once()

    record = session.add.call_args.args[0]

    assert isinstance(
        record,
        TeamProposalVersionRecord,
    )
    assert record.id == PROPOSAL_ID
    assert record.content == (proposal.to_snapshot())
    assert record.content_hash == (proposal.content_hash)
    assert record.revision_kind == ("PROPOSER_GENERATED")
    assert record.based_on_version_number is None


def test_migration_creates_immutable_team_proposals() -> None:
    """Render the team-proposal table and mutation trigger."""
    output = StringIO()
    configuration = create_alembic_config(
        TEST_DATABASE_URL,
        output_buffer=output,
    )

    command.upgrade(
        configuration,
        "head",
        sql=True,
    )

    generated_sql = output.getvalue()

    assert "CREATE TABLE team_proposals" in generated_sql
    assert "trg_team_proposals_immutable" in generated_sql
    assert "reject_team_proposal_mutation" in generated_sql
    assert "BEFORE UPDATE OR DELETE" in generated_sql
    assert "0008_versioned_team_proposals" in generated_sql
    assert "database-secret-must-not-leak-8472" not in generated_sql


def test_team_proposal_revision_follows_gate_persistence() -> None:
    """Attach proposal persistence to Gate 1 persistence."""
    scripts = ScriptDirectory.from_config(create_alembic_config(TEST_DATABASE_URL))
    revision = scripts.get_revision("0008_versioned_team_proposals")

    assert revision is not None
    assert revision.down_revision == ("0007_project_brief_human_gates")
    assert len(scripts.get_heads()) == 1
