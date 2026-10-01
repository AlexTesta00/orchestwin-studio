"""Tests for immutable team-proposal persistence."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
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

from orchestwin.agents.catalog import (
    AgentIdentifier,
)
from orchestwin.agents.persistence.models import (
    TeamProposalVersionRecord,
)
from orchestwin.agents.persistence.repositories import (
    SqlAlchemyTeamProposalVersionRepository,
    latest_owned_team_proposal_statement,
    proposal_from_snapshot,
    team_proposal_record_to_domain,
)
from orchestwin.agents.perspectives import (
    perspective_views,
)
from orchestwin.agents.proposals import (
    TeamProposalVersionCreationStatus,
)
from orchestwin.agents.selection_rules import (
    determine_team_constraints,
)
from orchestwin.knowledge.stage_documents import (
    team_version_from_document,
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
CONTRADICTION = "Una app con database ma senza backend."
GOLDEN_TEAM = (
    Path(__file__).resolve().parents[1] / "knowledge" / "data" / "guest_list" / "team.json"
)


def build_proposal(
    description: str = "A Vue web application with a FastAPI backend.",
):
    """Create one deterministic fake proposal."""
    provided_fields = {
        BriefField.NAME,
        BriefField.DESCRIPTION,
        BriefField.TECHNICAL_CONSTRAINTS,
    }
    brief = create_project_brief(
        name="Persistence project",
        description=description,
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


def test_contradiction_snapshot_round_trips_with_its_issue() -> None:
    proposal = build_proposal(CONTRADICTION)
    snapshot = proposal.to_snapshot()
    backend = next(
        constraint
        for constraint in snapshot["constraints"]["role_constraints"]
        if constraint["agent_id"] == "BACKEND_ENGINEER"
    )

    reconstructed = proposal_from_snapshot(snapshot)

    assert snapshot["constraints"]["issues"] == [
        {"code": "CONTRADICTORY_ROLE_SIGNALS", "agent_id": "BACKEND_ENGINEER"}
    ]
    assert (backend["kind"], backend["owner_editable"]) == ("CONFLICT", True)
    assert reconstructed == proposal
    assert reconstructed.constraints.issues == proposal.constraints.issues
    assert reconstructed.content_hash == proposal.content_hash
    assert AgentIdentifier.BACKEND_ENGINEER not in reconstructed.selected_agent_ids


def test_repository_stores_a_proposal_with_its_constraint_issue() -> None:
    proposal = build_proposal(CONTRADICTION)
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
    session.scalar = AsyncMock(side_effect=[project, None])
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
    assert result.version.proposal.constraints.issues == proposal.constraints.issues

    record = session.add.call_args.args[0]

    assert record.content == proposal.to_snapshot()
    assert record.constraints_content_hash == proposal.constraints.content_hash
    assert team_proposal_record_to_domain(record).proposal == proposal


def test_stored_issues_must_name_exactly_the_contested_roles() -> None:
    contested = build_proposal(CONTRADICTION).to_snapshot()
    without_issue = deepcopy(contested)
    without_issue["constraints"]["issues"] = []
    other_agent = deepcopy(contested)
    other_agent["constraints"]["issues"][0]["agent_id"] = "MOBILE_ENGINEER"
    unknown_code = deepcopy(contested)
    unknown_code["constraints"]["issues"][0]["code"] = "SOMETHING_ELSE"
    old_flag = deepcopy(contested)

    for constraint in old_flag["constraints"]["role_constraints"]:
        if constraint["kind"] == "CONFLICT":
            constraint["owner_editable"] = False

    invented = build_proposal().to_snapshot()
    invented["constraints"]["issues"] = deepcopy(contested["constraints"]["issues"])

    for snapshot in (without_issue, other_agent, unknown_code, old_flag, invented):
        with pytest.raises(ValueError):
            proposal_from_snapshot(snapshot)


def test_a_proposal_stored_before_this_sprint_still_reads_and_keeps_its_hash() -> None:
    document = json.loads(GOLDEN_TEAM.read_text(encoding="utf-8"))
    version = team_version_from_document(document)
    proposal = proposal_from_snapshot(document["proposal"])
    views = {
        view.key.value: view.to_snapshot()
        for view in perspective_views(proposal.constraints, proposal.selected_agent_ids)
    }

    assert proposal == version.proposal
    assert proposal.to_snapshot() == document["proposal"]
    assert version.content_hash == document["content_hash"]
    assert proposal.content_hash == (
        "a33b4badb0a16f53683c7bce63f2dbfe517bec709eadf734ccd7dc6a5114f884"
    )
    assert proposal.constraints.content_hash == document["proposal"]["constraints_content_hash"]
    assert proposal.constraints.issues == ()
    assert views["UX"]["requested"] == {
        "fields": ["technical_constraints"],
        "terms": ["applicazione web"],
    }
    assert (views["ACCESSIBILITY"]["standing"], views["ACCESSIBILITY"]["applied"]) == (
        "ALWAYS",
        False,
    )
    assert views["SOFTWARE_ENGINEERING"]["aspects"][1] == {
        "key": "SERVICES",
        "agent_id": "BACKEND_ENGINEER",
        "standing": "EXCLUDED",
        "applied": False,
        "editable": False,
        "requested": {"fields": [], "terms": []},
        "excluded": {"fields": ["technical_constraints"], "terms": ["nessun backend"]},
    }
    assert (views["SECURITY"]["standing"], views["SECURITY"]["applied"]) == ("OPTIONAL", False)


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
