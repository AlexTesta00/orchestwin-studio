from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from sqlalchemy.dialects import postgresql

from orchestwin.projects import sections_service as readers
from orchestwin.projects.persistence.progress import overview_statement, project_overview
from orchestwin.projects.progress import CURRENT_CATALOG, ProjectNextAction
from src.test.python.agents.test_team_realignment import MODE, changed_brief, version
from src.test.python.api.test_sections_api import SECTIONS, client
from src.test.python.projects.test_project_progress import BRIEF, TEAM, TWINS, columns, row
from src.test.python.projects.test_sections import aligned
from src.test.python.projects.test_sections_service import World, service
from src.test.python.twins.test_user_modeling_realignment import first_snapshot


def pending_row():
    snapshot = first_snapshot().snapshot
    timestamp = datetime(2026, 10, 1, tzinfo=UTC)
    return row(
        **columns("brief", BRIEF),
        **columns("brief_gate", BRIEF),
        brief_gate_status="APPROVED",
        **(columns("team", TEAM) | {"team_version": 2}),
        **columns("team_brief", BRIEF),
        team_catalog_version=CURRENT_CATALOG.version,
        team_catalog_hash=CURRENT_CATALOG.content_hash,
        **(columns("team_gate", TEAM) | {"team_gate_version": 2}),
        team_gate_status="APPROVED",
        **columns("twins", TWINS),
        **columns("twins_brief", BRIEF),
        **columns("twins_team", TEAM),
        twins_catalog_version=CURRENT_CATALOG.version,
        twins_catalog_hash=CURRENT_CATALOG.content_hash,
        **columns("twins_gate", TWINS),
        twins_gate_status="APPROVED",
        brief_content=changed_brief().brief.to_snapshot(),
        team_content=version().proposal.to_snapshot(),
        twins_snapshot=snapshot.to_snapshot(),
        archetype_versions=[item.to_snapshot() for item in snapshot.persona_versions],
        twins_revision_pending=True,
        project_id=BRIEF.artifact_id,
        project_owner_user_id=BRIEF.artifact_id,
        project_display_name="Pending on a historical base",
        project_mode=MODE.value,
        project_current_brief_version=1,
        project_archived_at=None,
        project_created_at=timestamp,
        project_updated_at=timestamp,
    )


def test_the_batched_read_checks_pending_twins_for_the_project_and_other_diffs_for_the_base():
    sql = str(
        overview_statement(owner_user_id=BRIEF.artifact_id).compile(dialect=postgresql.dialect())
    )
    assert "user_twin_profile_diffs.base_snapshot_version_id =" not in sql
    assert "requirements_specification_diffs.base_version_id =" in sql
    assert "design_package_diffs.base_version_id =" in sql


def test_the_project_list_and_sections_get_keep_the_global_pending_flag_from_the_batched_row(
    monkeypatch,
):
    values = pending_row()
    overview = project_overview(values)
    available = project_overview(values | {"twins_revision_pending": False})
    assert overview.progress.next_action is ProjectNextAction.CONFIRM_TWINS
    assert available.progress.next_action is ProjectNextAction.UPDATE_SECTIONS
    mappings = Mock()
    mappings.first.return_value = values
    result = Mock()
    result.mappings.return_value = mappings
    session = AsyncMock()
    session.execute.return_value = result
    session.__aenter__.return_value = session
    monkeypatch.setattr(
        readers,
        "SqlAlchemyKnowledgePackageRepository",
        lambda *args, **kwargs: SimpleNamespace(latest=AsyncMock(return_value=None)),
    )
    monkeypatch.setattr(readers, "_design_approved_once", AsyncMock(return_value=False))
    old_reader = AsyncMock(
        side_effect=AssertionError(
            "the old base-specific reader must not override the batched facts"
        )
    )
    monkeypatch.setattr(readers.SqlAlchemySectionReads, "_user_twins", old_reader)
    commands = service(World(aligned()))
    commands._reads = readers.SqlAlchemySectionReads(lambda: session)
    answer = client(commands).get(SECTIONS)
    assert answer.status_code == 200
    body = answer.json()
    twins = next(item for item in body["sections"] if item["key"] == "USER_TWINS")
    assert twins["blocked"] == "REVISION_PENDING"
    assert body["alignment"]["available"] is False
    old_reader.assert_not_awaited()
    session.execute.assert_awaited_once()
