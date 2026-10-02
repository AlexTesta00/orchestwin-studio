from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from orchestwin.artifacts.why_runtime import SqlAlchemyWhyQueryService
from orchestwin.knowledge.project_import_service import ProjectImportService
from orchestwin.persistence import create_database_runtime
from orchestwin.why import explain_why
from src.test.python.integration.test_postgresql_project_import import seed_users
from src.test.python.integration.test_proposal_evidence_postgres import database, run
from src.test.python.integration.test_research_evidence_import_postgres import (
    synthetic_evidence_archive,
)

__all__ = ["database"]
pytestmark = pytest.mark.integration


def test_why_reads_imported_exact_citations_and_rejects_a_different_owner(database):
    async def scenario():
        db = create_database_runtime(database)
        owner, stranger = uuid4(), uuid4()
        try:
            await seed_users(db, owner, stranger)
            archive, _, source = synthetic_evidence_archive()
            imported = await ProjectImportService(
                session_factory=db.session_factory,
                clock=lambda: datetime.now(UTC),
            ).import_archive(owner_user_id=owner, content=archive)
            query = SqlAlchemyWhyQueryService(db.session_factory)
            document = await query.current(owner_user_id=owner, project_id=imported.project.id)
            assert document["kind"] == "orchestwin.why"
            assert document["project_id"] == str(imported.project.id)
            expected = source["citations"][0]["citation"]
            claims = [
                node
                for node in document["nodes"]
                if node["kind"] == "USER_TWIN_CLAIM"
                and node["code"].endswith(":user_twin.goals")
                and node["citations"]
            ]
            assert len(claims) == 1
            citation = claims[0]["citations"][0]["citation"]
            for field in (
                "quote",
                "content_hash",
                "source_version",
                "start",
                "end",
                "start_line",
                "end_line",
            ):
                assert citation[field] == expected[field]
            answer = explain_why(document, claims[0]["key"])
            assert answer["summary"]["complete_to_evidence"]
            assert "SOURCE_TEXT_UNAVAILABLE" in answer["limits"]
            assert (
                await query.current(owner_user_id=stranger, project_id=imported.project.id) is None
            )
        finally:
            await db.dispose()

    run(scenario())
